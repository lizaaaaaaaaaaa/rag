# api/routers/chat_unified.py - 統合チャットルーター（高速版＋RAG統合）

import logging
import os
import asyncio
import time
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, List
import concurrent.futures
from uuid import uuid4
import traceback
import re

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from fastapi.responses import JSONResponse, StreamingResponse

# 共通ユーティリティのインポート
from utils.web_search import GoogleSearcher as WebSearcher
from utils.langsmith_tracer import RAGTracer

# ハルシネーション対策統合機能
try:
    from integration.anti_hallucination_integration import enhance_web_chat_response
    ANTI_HALLUCINATION_AVAILABLE = True
except ImportError:
    ANTI_HALLUCINATION_AVAILABLE = False

# LangSmithトレース（条件付き）
try:
    from langsmith import traceable
except ImportError:
    def traceable(name=None, **kwargs):
        def decorator(func):
            return func
        return decorator

logger = logging.getLogger(__name__)
router = APIRouter()

# ============================================================================
# 統合キャッシュシステム（Web/LINE分離＋高速アクセス）
# ============================================================================
class UnifiedCacheSystem:
    def __init__(self, max_size: int = 1000):
        # プラットフォーム分離キャッシュ
        self.web_cache: Dict[str, Dict[str, Any]] = {}
        self.line_cache: Dict[str, Dict[str, Any]] = {}
        self.rag_cache: Dict[str, Dict[str, Any]] = {}  # RAG専用キャッシュ
        self.access_times: Dict[str, float] = {}
        self.max_size = max_size
        
        # 統計情報
        self.stats = {
            "web_hits": 0, "web_misses": 0,
            "line_hits": 0, "line_misses": 0,
            "rag_hits": 0, "rag_misses": 0,
            "total_requests": 0
        }

    def _generate_key(self, query: str, platform: str, cache_type: str = "general") -> str:
        """統合キー生成"""
        normalized = f"{platform}:{cache_type}:{query.lower().strip()[:200]}"
        return hashlib.md5(normalized.encode()).hexdigest()

    def get(self, query: str, platform: str = "web", cache_type: str = "general") -> Optional[Dict[str, Any]]:
        """統合キャッシュ取得"""
        key = self._generate_key(query, platform, cache_type)
        
        # キャッシュ選択
        if cache_type == "rag":
            cache_dict = self.rag_cache
            stat_prefix = "rag"
        elif platform == "line":
            cache_dict = self.line_cache  
            stat_prefix = "line"
        else:
            cache_dict = self.web_cache
            stat_prefix = "web"
        
        self.stats["total_requests"] += 1
        
        if key in cache_dict:
            self.access_times[key] = time.time()
            self.stats[f"{stat_prefix}_hits"] += 1
            logger.info(f"⚡ {stat_prefix.upper()} Cache HIT: {query[:30]}...")
            return cache_dict[key]
        
        self.stats[f"{stat_prefix}_misses"] += 1
        return None

    def set(self, query: str, response: Dict[str, Any], platform: str = "web", cache_type: str = "general") -> None:
        """統合キャッシュ保存"""
        if self._total_cache_size() >= self.max_size:
            self._evict_oldest()

        key = self._generate_key(query, platform, cache_type)
        
        # キャッシュ選択
        if cache_type == "rag":
            cache_dict = self.rag_cache
        elif platform == "line":
            cache_dict = self.line_cache
        else:
            cache_dict = self.web_cache
        
        cache_dict[key] = {
            "answer": response.get("answer", ""),
            "sources": response.get("sources", []),
            "timestamp": time.time(),
            "query_original": query[:100],
            "platform": platform,
            "cache_type": cache_type,
            "source": response.get("source", "unknown"),
            "meta": response.get("meta", {})
        }
        self.access_times[key] = time.time()

    def _total_cache_size(self) -> int:
        return len(self.web_cache) + len(self.line_cache) + len(self.rag_cache)

    def _evict_oldest(self) -> None:
        """最古エントリ削除"""
        if self.access_times:
            oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
            # 全キャッシュから削除
            self.web_cache.pop(oldest_key, None)
            self.line_cache.pop(oldest_key, None) 
            self.rag_cache.pop(oldest_key, None)
            del self.access_times[oldest_key]

    def clear_all(self) -> Dict[str, int]:
        """全キャッシュクリア"""
        old_sizes = {
            "web": len(self.web_cache),
            "line": len(self.line_cache), 
            "rag": len(self.rag_cache)
        }
        
        self.web_cache.clear()
        self.line_cache.clear()
        self.rag_cache.clear()
        self.access_times.clear()
        
        # 統計リセット
        for key in self.stats:
            if key != "total_requests":
                self.stats[key] = 0
        
        return old_sizes

    def get_stats(self) -> Dict[str, Any]:
        """統合統計取得"""
        total = self.stats["total_requests"]
        
        return {
            "cache_sizes": {
                "web": len(self.web_cache),
                "line": len(self.line_cache),
                "rag": len(self.rag_cache),
                "total": self._total_cache_size()
            },
            "max_size": self.max_size,
            "hit_rates": {
                "web": (self.stats["web_hits"] / (self.stats["web_hits"] + self.stats["web_misses"]) * 100) if (self.stats["web_hits"] + self.stats["web_misses"]) > 0 else 0,
                "line": (self.stats["line_hits"] / (self.stats["line_hits"] + self.stats["line_misses"]) * 100) if (self.stats["line_hits"] + self.stats["line_misses"]) > 0 else 0,
                "rag": (self.stats["rag_hits"] / (self.stats["rag_hits"] + self.stats["rag_misses"]) * 100) if (self.stats["rag_hits"] + self.stats["rag_misses"]) > 0 else 0,
                "overall": (sum([self.stats["web_hits"], self.stats["line_hits"], self.stats["rag_hits"]]) / total * 100) if total > 0 else 0
            },
            "raw_stats": self.stats
        }

# ============================================================================
# 統合テンプレートシステム（Web/LINE最適化）
# ============================================================================
class UnifiedTemplateSystem:
    def __init__(self):
        self.web_templates = self._load_web_templates()
        self.line_templates = self._load_line_templates()
        self.template_hits = {"web": 0, "line": 0}

    def _load_web_templates(self) -> Dict[str, str]:
        """Web専用テンプレート"""
        return {
            "坪単価": """坪単価についてご案内いたします。

当社の坪単価目安：
・標準仕様：約70～85万円/坪  
・高性能仕様：約85～100万円/坪

含まれる内容：
・耐震等級3の構造
・長期優良住宅対応
・高断熱・高気密仕様  
・標準設備一式

お客様のご希望される仕様によって変動いたします。詳細なお見積りをご提供いたしますので、お気軽にお問い合わせください。""",

            "標準仕様": """標準仕様についてご説明いたします。

構造・性能：
・耐震等級3（最高等級）
・長期優良住宅認定対応
・省エネ等級4以上
・高断熱・高気密仕様

設備仕様：
・システムキッチン
・ユニットバス
・洗面化粧台
・トイレ（温水洗浄便座付）

より詳しい仕様書については、資料請求または展示場見学でご確認いただけます。""",

            "補助金": """住宅購入時の補助金・支援制度についてご案内いたします。

主な補助金制度：

ZEH補助金：
・高性能住宅への補助
・省エネ基準を満たす住宅が対象
・補助額：定額55万円～（条件により異なる）

こどもエコすまい支援事業：
・子育て世帯・若年夫婦世帯への支援
・最大100万円の補助金
・省エネ性能に応じて補助額が変動

住宅ローン減税：
・所得税の控除制度
・13年間の減税メリット
・年間最大35万円の控除（条件により異なる）

地域独自の補助金：
・自治体による支援制度
・地域により内容が異なります

※制度は年度ごとに変更される可能性があります。最新情報については公式サイトでご確認いただくか、スタッフまでお問い合わせください。""",

            "AI相談": """AI住まい相談へようこそ！

住まいづくりに関するご質問をお気軽にどうぞ！

よくあるご質問：
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？
・補助金について教えて

何でもお聞きください。"""
        }

    def _load_line_templates(self) -> Dict[str, str]:
        """LINE専用テンプレート（絵文字・短文・親しみやすい）"""
        return {
            # リッチメニュー対応
            "AI相談": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 **例えば**
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？

何でもお聞きください😊""",

            "資料請求": """📋 ありがとうございます！こちらからご覧いただけます。

〔資料タイトル〕（PDF）：〔URL〕

よろしければ簡単アンケート（任意）：
・ご計画時期：今すぐ / 3–6か月 / 1年以内 / 未定
・連絡方法（任意）：このLINE / メール / 連絡不要

※プライバシーポリシーをご確認ください。""",

            "坪単価": """💰 坪単価についてご案内いたします

🏠 **当社の坪単価目安**
・標準仕様：約70～85万円/坪
・高性能仕様：約85～100万円/坪

✨ **含まれる内容**
・耐震等級3の構造
・長期優良住宅対応
・高断熱・高気密仕様
・標準設備一式

お客様のご要望により変動いたします。
詳細なお見積りをご希望でしたら、お気軽にお問い合わせください😊""",

            "補助金": """💰 住宅購入時の補助金制度についてご案内します

**主な補助金制度**

🏠 **ZEH補助金**
高性能住宅への補助
定額55万円～

🌱 **こどもエコすまい支援事業**
子育て世帯への支援
最大100万円

🏦 **住宅ローン減税**
所得税の控除制度
13年間の減税メリット

📋 **地域独自の補助金**
自治体による支援
地域により異なります

※制度は年度ごとに変更される可能性があります。
最新情報はスタッフまでお問い合わせください😊"""
        }

    def match_template(self, query: str, platform: str) -> Optional[str]:
        """プラットフォーム別テンプレートマッチング"""
        templates = self.line_templates if platform == "line" else self.web_templates
        query_lower = query.lower()

        # キーワードマッピング  
        keyword_mapping = {
            "AI相談": ["🤖 ai相談", "ai相談"],
            "資料請求": ["📋 資料請求", "資料請求"],
            "坪単価": ["坪単価", "坪たんか", "価格", "値段", "費用", "コスト", "いくら", "金額"],
            "標準仕様": ["標準仕様", "仕様", "設備", "標準", "基本", "スタンダード"],
            "補助金": ["補助金", "助成金", "支援金", "補助制度", "支援制度", "zeh補助", "こどもエコ"],
        }

        for template_key, keywords in keyword_mapping.items():
            if any(keyword in query_lower for keyword in keywords):
                self.template_hits[platform] += 1
                logger.info(f"🎯 {platform.upper()} Template match: {template_key}")
                return templates.get(template_key)

        return None

    def get_stats(self) -> Dict[str, Any]:
        return {
            "template_counts": {
                "web": len(self.web_templates),
                "line": len(self.line_templates)
            },
            "template_hits": self.template_hits
        }

# ============================================================================
# 統合応答生成システム（高速版＋RAG統合）
# ============================================================================
class UnifiedResponseGenerator:
    def __init__(self):
        self.cache = UnifiedCacheSystem(max_size=1000)
        self.templates = UnifiedTemplateSystem()
        self.tracer = RAGTracer()
        self.performance_metrics = {
            "total_requests": 0,
            "template_responses": 0,
            "rag_responses": 0,  
            "cache_responses": 0,
            "anti_hallucination_used": 0
        }

    async def generate_response(self, query: str, platform: str = "web", 
                              user: str = "unknown", mode: str = "auto") -> Dict[str, Any]:
        """統合応答生成"""
        start_time = time.time()
        self.performance_metrics["total_requests"] += 1

        try:
            # 1. キャッシュチェック（プラットフォーム・モード別）
            cache_type = "rag" if mode == "rag" else "general"
            cached_response = self.cache.get(query, platform, cache_type)
            
            if cached_response:
                self.performance_metrics["cache_responses"] += 1
                complete_cached = self._ensure_completeness(cached_response["answer"], platform, query)
                
                return {
                    "answer": complete_cached,
                    "sources": cached_response.get("sources", []),
                    "processing_time": time.time() - start_time,
                    "source": "cache",
                    "platform": platform,
                    "status": "ok",
                    "sentence_complete": complete_cached.endswith(('。', '！', '？', '.', '!', '?'))
                }

            # 2. モード別処理分岐
            if mode == "template" or (mode == "auto" and self._should_use_template(query)):
                response = await self._generate_template_response(query, platform, user, start_time)
            elif mode == "rag" or (mode == "auto" and self._should_use_rag(query)):
                response = await self._generate_rag_response(query, platform, user, start_time)
            else:
                response = await self._generate_template_response(query, platform, user, start_time)

            # 3. 応答の完全性チェック
            response["answer"] = self._ensure_completeness(response["answer"], platform, query)
            response["sentence_complete"] = response["answer"].endswith(('。', '！', '？', '.', '!', '?'))

            # 4. キャッシュ保存
            cache_type = "rag" if response.get("source", "").startswith("rag") else "general"
            self.cache.set(query, response, platform, cache_type)

            return response

        except Exception as e:
            logger.error(f"Unified response generation error: {e}")
            return self._generate_error_response(query, platform, start_time)

    async def _generate_template_response(self, query: str, platform: str, user: str, start_time: float) -> Dict[str, Any]:
        """テンプレート応答生成"""
        template_response = self.templates.match_template(query, platform)
        
        if template_response:
            self.performance_metrics["template_responses"] += 1
            
            # ハルシネーション対策適用
            if ANTI_HALLUCINATION_AVAILABLE:
                try:
                    enhanced_result = await enhance_web_chat_response(
                        query=query,
                        original_response=template_response,
                        user_context={"username": user, "platform": platform}
                    )
                    
                    self.performance_metrics["anti_hallucination_used"] += 1
                    
                    return {
                        "answer": enhanced_result.get("answer", template_response),
                        "sources": enhanced_result.get("sources", []),
                        "processing_time": time.time() - start_time,
                        "source": "template_enhanced",
                        "platform": platform,
                        "status": "ok",
                        "anti_hallucination_used": True,
                        "verification": enhanced_result.get("verification_note")
                    }
                    
                except Exception as e:
                    logger.warning(f"Template enhancement error: {e}")
                    
            return {
                "answer": template_response,
                "sources": [],
                "processing_time": time.time() - start_time,
                "source": "template",
                "platform": platform,
                "status": "ok",
                "anti_hallucination_used": False
            }
        
        # フォールバック
        return self._generate_fallback_response(query, platform, start_time)

    async def _generate_rag_response(self, query: str, platform: str, user: str, start_time: float) -> Dict[str, Any]:
        """RAG応答生成"""
        try:
            # アプリのグローバル変数取得
            globals_dict = self._get_app_globals()
            vectorstore = globals_dict.get('vectorstore')
            rag_chain_template = globals_dict.get('rag_chain_template')
            
            if not vectorstore or not rag_chain_template:
                logger.warning("RAG components not available, falling back to template")
                return await self._generate_template_response(query, platform, user, start_time)
            
            # ベクトル検索
            docs = vectorstore.similarity_search(query, k=3)
            self.tracer.trace_retrieval(query, docs)
            
            # RAG生成
            if hasattr(rag_chain_template, 'invoke'):
                result = rag_chain_template.invoke({"query": query})
            else:
                result = rag_chain_template({"query": query})
            
            raw_answer = result.get("result", "")
            cleaned_answer = self._clean_rag_response(raw_answer)
            
            # 生成トレース
            context = "\n".join([getattr(doc, "page_content", "") for doc in docs])
            self.tracer.trace_generation(query, context, cleaned_answer)
            
            self.performance_metrics["rag_responses"] += 1
            
            # ハルシネーション対策
            if ANTI_HALLUCINATION_AVAILABLE and len(cleaned_answer) > 10:
                try:
                    enhanced_result = await enhance_web_chat_response(
                        query=query,
                        original_response=cleaned_answer,
                        user_context={"username": user, "platform": platform}
                    )
                    
                    self.performance_metrics["anti_hallucination_used"] += 1
                    
                    return {
                        "answer": enhanced_result.get("answer", cleaned_answer),
                        "sources": [{"content": getattr(doc, "page_content", "")[:200] + "..."} for doc in docs[:2]],
                        "processing_time": time.time() - start_time,
                        "source": "rag_enhanced",
                        "platform": platform,
                        "status": "ok",
                        "anti_hallucination_used": True,
                        "verification": enhanced_result.get("verification_note")
                    }
                    
                except Exception as e:
                    logger.warning(f"RAG enhancement error: {e}")
            
            return {
                "answer": cleaned_answer,
                "sources": [{"content": getattr(doc, "page_content", "")[:200] + "..."} for doc in docs[:2]],
                "processing_time": time.time() - start_time,
                "source": "rag",
                "platform": platform,
                "status": "ok",
                "anti_hallucination_used": False
            }
            
        except Exception as e:
            logger.error(f"RAG generation error: {e}")
            return await self._generate_template_response(query, platform, user, start_time)

    def _should_use_template(self, query: str) -> bool:
        """テンプレート使用判定"""
        template_keywords = [
            "ai相談", "資料請求", "展示場", "見学", "予約", 
            "坪単価", "価格", "費用", "標準仕様", "補助金"
        ]
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in template_keywords) or len(query) <= 15

    def _should_use_rag(self, query: str) -> bool:
        """RAG使用判定"""
        rag_keywords = [
            "詳しく", "具体的", "教えて", "説明", "について", 
            "どのような", "どうやって", "なぜ", "理由"
        ]
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in rag_keywords) and len(query) > 10

    def _clean_rag_response(self, raw_response: str) -> str:
        """RAG応答クリーンアップ（chat.pyから移植）"""
        if not raw_response or len(raw_response.strip()) < 3:
            return "申し訳ございません。お尋ねの内容について詳細な情報が見つかりませんでした。"

        cleaned = raw_response

        # 構造化・出典表記などの除去
        structure_patterns = [
            r"関連文書が見つかりました[:：]?\s*",
            r"関連情報が見つかりました[:：]?\s*",
            r"\d+\.\s*【質問】[^】]*】\s*",
            r"【回答】\s*",
            r"【質問】\s*",
            r"出典[:：]\s*[^\n]*",
            r"/tmp/tmp[a-zA-Z0-9_]*\.pdf",
            r"\([pP]\d+\)",
            r"^\d+\.\s*",
            r"【[^】]*】",
        ]
        
        for pattern in structure_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)

        # 重複行の排除と最適化
        lines = [line.strip() for line in cleaned.split('\n') if line.strip()]
        if lines:
            result = max(lines, key=len)
            result = re.sub(r'\s+', ' ', result).strip()
            if len(result) < 10:
                result = "申し訳ございません。お尋ねの内容について、詳細な情報をお答えできませんでした。"
            return result
        
        return "申し訳ございません。お尋ねの内容について、より詳しい情報をご提供するため、直接お問い合わせいただければと思います。"

    def _ensure_completeness(self, text: str, platform: str, query: str) -> str:
        """文章完全性チェック（chat_ultra_fast.pyから統合）"""
        if not text or len(text.strip()) < 5:
            return self._generate_platform_fallback(query, platform)
        
        text = text.strip()
        
        if not text.endswith(('。', '！', '？', '.', '!', '?')):
            # プラットフォーム別補完
            completion_patterns = {
                'や': '関連する準備を進めましょう✨' if platform == "line" else '関連する準備を進めることをお勧めします。',
                '重要': 'です😊詳しくはお気軽にご相談ください。' if platform == "line" else 'です。詳しくはお気軽にご相談ください。',
                '必要': 'です。',
                'について': 'は詳しくご案内します💡' if platform == "line" else 'は詳細をご案内いたします。',
                '、': '。',
            }
            
            # パターンマッチングで補完
            for pattern, completion in completion_patterns.items():
                if text.endswith(pattern):
                    if pattern == '、':
                        text = text[:-1] + completion
                    else:
                        text += completion
                    break
            else:
                if text.endswith(('ます', 'です')):
                    text += '。'
                elif text.endswith(('た', 'る')):
                    text += '。'
                elif text.endswith(('は', 'が')):
                    text += '重要なポイントです。'
                else:
                    if len(text) > 50:
                        text += '。'
                    elif len(text) > 25:
                        suffix = '。詳しくはお問い合わせください😊' if platform == "line" else '。詳細はお問い合わせください。'
                        text += suffix
                    else:
                        text = self._generate_platform_fallback(query, platform)
        
        return text

    def _generate_fallback_response(self, query: str, platform: str, start_time: float) -> Dict[str, Any]:
        """フォールバック応答生成"""
        fallback_answer = self._generate_platform_fallback(query, platform)
        
        return {
            "answer": fallback_answer,
            "sources": [],
            "processing_time": time.time() - start_time,
            "source": "fallback",
            "platform": platform,
            "status": "ok",
            "anti_hallucination_used": False
        }

    def _generate_error_response(self, query: str, platform: str, start_time: float) -> Dict[str, Any]:
        """エラー応答生成"""
        error_answer = self._generate_platform_fallback(query, platform)
        
        return {
            "answer": error_answer,
            "sources": [],
            "processing_time": time.time() - start_time,
            "source": "error",
            "platform": platform,
            "status": "error",
            "anti_hallucination_used": False
        }

    def _generate_platform_fallback(self, query: str, platform: str) -> str:
        """プラットフォーム別フォールバック"""
        q_lower = query.lower()
        
        if platform == "line":
            if any(keyword in q_lower for keyword in ["家を建てる", "マイホーム", "新築"]):
                return """🏗️ 家づくりについてお答えいたします

家づくりは人生で最も大きな買い物の一つです✨

**まずはこちらから始めませんか？**
1️⃣ 資料請求で情報収集
2️⃣ 展示場見学で実際の住まいを体感
3️⃣ 資金計画で予算を明確化

お客様のご希望をお聞かせいただければ、最適なプランをご提案いたします😊"""
            else:
                return """ご質問ありがとうございます✨

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

**よくあるご質問**
💰 坪単価や費用について
🏠 住宅性能や仕様について
📋 資料請求・展示場見学

具体的にお聞かせいただければ、詳しくご案内いたします😊"""
        else:
            if any(keyword in q_lower for keyword in ["家を建てる", "マイホーム", "新築"]):
                return """家づくりについてお答えいたします。

家づくりは人生で最も大きな買い物の一つです。まずは情報収集から始めませんか？

・資料請求で詳しい情報を入手
・展示場見学で実際の住まいを体感
・資金計画で予算を明確化

お客様のご希望をお聞かせいただければ、最適なプランをご提案いたします。"""
            else:
                return """お尋ねの内容について詳しくご案内いたします。

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

・坪単価や費用について
・住宅性能や仕様について  
・資料請求・展示場見学について
・資金計画・住宅ローンについて
・補助金制度について

具体的にお聞かせいただければ、詳しくご案内いたします。"""

    def _get_app_globals(self) -> Dict[str, Any]:
        """アプリグローバル変数取得"""
        try:
            import main
            return {
                'vectorstore': getattr(main, 'vectorstore', None),
                'rag_chain_template': getattr(main, 'rag_chain_template', None),
                'llm_instance': getattr(main, 'llm_instance', None)
            }
        except ImportError:
            return {}

    def get_performance_stats(self) -> Dict[str, Any]:
        """パフォーマンス統計取得"""
        cache_stats = self.cache.get_stats()
        template_stats = self.templates.get_stats()
        
        total = self.performance_metrics["total_requests"]
        
        return {
            "unified_performance": {
                "total_requests": total,
                "template_rate": (self.performance_metrics["template_responses"] / total * 100) if total > 0 else 0,
                "rag_rate": (self.performance_metrics["rag_responses"] / total * 100) if total > 0 else 0,
                "cache_rate": (self.performance_metrics["cache_responses"] / total * 100) if total > 0 else 0,
                "anti_hallucination_rate": (self.performance_metrics["anti_hallucination_used"] / total * 100) if total > 0 else 0
            },
            "cache_performance": cache_stats,
            "template_performance": template_stats,
            "features": [
                "統合キャッシュシステム（Web/LINE/RAG分離）",
                "プラットフォーム最適化テンプレート",  
                "RAG処理統合",
                "ハルシネーション対策強化",
                "文章完全性自動補完",
                "パフォーマンス最適化"
            ]
        }

# ============================================================================
# グローバルインスタンス
# ============================================================================
unified_generator = UnifiedResponseGenerator()
history_logs: List[Dict] = []

# ============================================================================
# リクエストモデル
# ============================================================================
class UnifiedChatRequest(BaseModel):
    question: str
    username: str | None = None
    platform: str | None = "web"
    mode: str | None = "auto"  # auto, template, rag

# ============================================================================
# メインエンドポイント
# ============================================================================
@router.post("/", summary="統合チャットエンドポイント（高速版＋RAG統合）")
async def unified_chat_endpoint(req: UnifiedChatRequest, request: Request):
    """統合チャットエンドポイント"""
    
    overall_start = time.time()
    platform = req.platform or "web"
    username = req.username or f"{platform}-user"
    mode = req.mode or "auto"
    
    logger.info(f"🌟 Unified Chat ({platform}, {mode}): {req.question[:50]}...")

    try:
        # 統合応答生成
        response = await unified_generator.generate_response(
            req.question, platform, username, mode
        )

        total_time = time.time() - overall_start

        # ログ保存
        log_entry = {
            "id": str(uuid4()),
            "question": req.question,
            "username": username,
            "answer": response["answer"],
            "platform": platform,
            "mode": mode,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sources": response.get("sources", []),
            "performance": {
                "total_time": total_time,
                "processing_time": response.get("processing_time", 0),
                "source": response.get("source")
            }
        }
        history_logs.append(log_entry)

        logger.info(
            f"✅ Unified response ({platform}): {total_time:.3f}s, "
            f"source={response.get('source')}, "
            f"length={len(response['answer'])}, "
            f"complete={response.get('sentence_complete', False)}"
        )

        return {
            "answer": response["answer"],
            "sources": response.get("sources", []),
            "status": response.get("status", "ok"),
            "performance": {
                "total_time": total_time,
                "processing_time": response.get("processing_time", 0),
                "source": response.get("source"),
                "platform": platform,
                "mode": mode,
                "sentence_complete": response.get("sentence_complete", False),
                "unified_system": True,
                "anti_hallucination_used": response.get("anti_hallucination_used", False)
            },
            "enhanced_info": {
                "verification": response.get("verification"),
                "anti_hallucination_used": response.get("anti_hallucination_used", False)
            } if ANTI_HALLUCINATION_AVAILABLE else {}
        }

    except Exception as e:
        total_time = time.time() - overall_start
        error_id = str(uuid4())[:8]

        logger.error(f"❌ Unified chat error [{error_id}]: {e}")
        logger.error(traceback.format_exc())

        fallback_answer = unified_generator._generate_platform_fallback(req.question, platform)
        complete_fallback = unified_generator._ensure_completeness(fallback_answer, platform, req.question)

        return JSONResponse(
            status_code=200,
            content={
                "answer": complete_fallback,
                "sources": [],
                "status": "error",
                "error_id": error_id,
                "performance": {
                    "total_time": total_time,
                    "platform": platform,
                    "mode": mode,
                    "sentence_complete": complete_fallback.endswith(('。', '！', '？', '.', '!', '?')),
                    "unified_system": True
                },
                "enhanced_info": {}
            }
        )

@router.post("", include_in_schema=False)
async def unified_chat_endpoint_slashless(req: UnifiedChatRequest, request: Request):
    return await unified_chat_endpoint(req, request)

# ============================================================================
# 管理エンドポイント
# ============================================================================
@router.get("/performance-stats", summary="統合パフォーマンス統計")
def get_unified_performance_stats():
    """統合パフォーマンス統計取得"""
    stats = unified_generator.get_performance_stats()
    
    return {
        "unified_chat_system": stats,
        "system_features": [
            "🔄 統合キャッシュシステム（Web/LINE/RAG分離）",
            "⚡ プラットフォーム最適化テンプレート",
            "🤖 RAG処理統合（vectorstore + LLM）",
            "🛡️ ハルシネーション対策強化",
            "✅ 文章完全性自動補完",
            "📊 詳細パフォーマンス計測",
            "🚀 モード別処理分岐（auto/template/rag）"
        ],
        "target_performance": {
            "template_response": "< 0.5s",
            "rag_response": "< 3.0s", 
            "cache_hit_rate": "> 70%",
            "sentence_completion_rate": "> 95%"
        },
        "integration_status": {
            "chat_py_features_integrated": True,
            "chat_ultra_fast_features_integrated": True,
            "anti_hallucination_available": ANTI_HALLUCINATION_AVAILABLE,
            "rag_components_available": True
        },
        "timestamp": datetime.now().isoformat()
    }

@router.post("/clear-cache", summary="統合キャッシュクリア")
def clear_unified_cache():
    """統合キャッシュクリア"""
    old_sizes = unified_generator.cache.clear_all()
    
    return {
        "status": "unified_cache_cleared",
        "cleared_caches": old_sizes,
        "platforms_cleared": ["web", "line", "rag"],
        "timestamp": datetime.now().isoformat()
    }

@router.get("/history", summary="チャット履歴取得")
def get_unified_history():
    return {"logs": history_logs, "count": len(history_logs)}

@router.get("/export/csv", summary="履歴CSVエクスポート")
def export_unified_csv():
    import csv
    import io
    
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(["id", "question", "username", "answer", "platform", "mode", "timestamp", "source"])
    
    for log in history_logs:
        writer.writerow([
            log.get("id", ""),
            log.get("question", ""),
            log.get("username", ""),
            log.get("answer", "")[:200] + "..." if len(log.get("answer", "")) > 200 else log.get("answer", ""),
            log.get("platform", ""),
            log.get("mode", ""),
            log.get("timestamp", ""),
            log.get("performance", {}).get("source", "")
        ])
    
    si.seek(0)
    return StreamingResponse(
        si,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=unified_chat_history.csv"}
    )

@router.get("/templates", summary="テンプレート一覧")
def get_unified_templates():
    """統合テンプレート一覧"""
    template_stats = unified_generator.templates.get_stats()
    
    return {
        "templates": {
            "web": list(unified_generator.templates.web_templates.keys()),
            "line": list(unified_generator.templates.line_templates.keys())
        },
        "template_stats": template_stats,
        "features": [
            "プラットフォーム別最適化",
            "リッチメニュー対応",
            "絵文字・短文（LINE用）",
            "詳細説明（Web用）"
        ],
        "timestamp": datetime.now().isoformat()
    }