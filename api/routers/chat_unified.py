# api/routers/chat_unified.py - 高速化版（RAG呼び出し最小化）

import logging
import os
import asyncio
import time
import hashlib
import csv
import io
import re
from datetime import datetime
from typing import Dict, Any, Optional, List
import concurrent.futures
from uuid import uuid4
import traceback

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from fastapi.responses import JSONResponse, StreamingResponse

# 共通ユーティリティのインポート
from utils.web_search import GoogleSearcher as WebSearcher
from utils.langsmith_tracer import RAGTracer

# ハルシネーション対策統合機能（条件厳格化）
try:
    from integration.anti_hallucination_integration import enhance_web_chat_response
    ANTI_HALLUCINATION_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("✅ Anti-hallucination integration available (optimized)")
except ImportError as e:
    ANTI_HALLUCINATION_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning(f"⚠️ Anti-hallucination integration not available: {e}")

try:
    from langsmith import traceable
except ImportError:
    def traceable(name=None, **kwargs):
        def decorator(func):
            return func
        return decorator

router = APIRouter()
history_logs: List[Dict] = []

# ============================================================================
# 🚀 高速化キャッシュシステム（ヒット率向上・期限管理）
# ============================================================================
class OptimizedCacheSystem:
    def __init__(self, max_size: int = 2000):  # 🔧 拡大：1000→2000
        # プラットフォーム分離キャッシュ
        self.web_cache: Dict[str, Dict[str, Any]] = {}
        self.line_cache: Dict[str, Dict[str, Any]] = {}
        self.rag_cache: Dict[str, Dict[str, Any]] = {}
        self.access_times: Dict[str, float] = {}
        self.max_size = max_size
        self.cache_expire_time = 3600  # 🔧 1時間キャッシュ
        
        # 統計情報強化
        self.stats = {
            "web_hits": 0, "web_misses": 0,
            "line_hits": 0, "line_misses": 0,
            "rag_hits": 0, "rag_misses": 0,
            "total_requests": 0,
            "hits": 0, "misses": 0,
            "expired_entries": 0  # 🔧 期限切れ統計
        }

    def _generate_key(self, query: str, platform: str, cache_type: str = "general") -> str:
        """高速化キー生成（正規化強化）"""
        # 🚀 クエリ正規化強化
        normalized = query.lower().strip()
        normalized = re.sub(r'[？?！!。、\s]+', '', normalized)  # ノイズ除去
        normalized = normalized.replace("について", "").replace("教えて", "")
        
        key_str = f"{platform}:{cache_type}:{normalized[:80]}"
        return hashlib.md5(key_str.encode()).hexdigest()[:12]

    def get(self, query: str, platform: str = "web", cache_type: str = "general") -> Optional[Dict[str, Any]]:
        """高速化キャッシュ取得（期限チェック付き）"""
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
        current_time = time.time()
        
        if key in cache_dict:
            cache_entry = cache_dict[key]
            # 🚀 期限チェック
            if current_time - cache_entry.get("timestamp", 0) < self.cache_expire_time:
                self.access_times[key] = current_time
                self.stats[f"{stat_prefix}_hits"] += 1
                self.stats["hits"] += 1
                logger.debug(f"⚡ {stat_prefix.upper()} Cache HIT: {query[:25]}...")
                return cache_entry
            else:
                # 期限切れエントリ削除
                del cache_dict[key]
                self.access_times.pop(key, None)
                self.stats["expired_entries"] += 1
                logger.debug(f"🗑️ Expired cache entry removed: {query[:25]}...")
        
        self.stats[f"{stat_prefix}_misses"] += 1
        self.stats["misses"] += 1
        return None

    def set(self, query: str, response: Dict[str, Any], platform: str = "web", cache_type: str = "general") -> None:
        """高速化キャッシュ保存（タイムスタンプ付き）"""
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
            "timestamp": time.time(),  # 🚀 タイムスタンプ追加
            "query_original": query[:50],
            "platform": platform,
            "cache_type": cache_type,
            "source": response.get("source", "unknown"),
            "meta": response.get("meta", {}),
            "anti_hallucination_used": response.get("anti_hallucination_used", False)
        }
        self.access_times[key] = time.time()
        logger.debug(f"💾 {platform.upper()} Cache SET: {query[:25]}...")

    def _total_cache_size(self) -> int:
        return len(self.web_cache) + len(self.line_cache) + len(self.rag_cache)

    def _evict_oldest(self) -> None:
        """LRU方式で最古エントリ削除"""
        if self.access_times:
            oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
            # 全キャッシュから削除
            self.web_cache.pop(oldest_key, None)
            self.line_cache.pop(oldest_key, None) 
            self.rag_cache.pop(oldest_key, None)
            del self.access_times[oldest_key]

    def clear_expired(self) -> int:
        """🚀 期限切れエントリの一括削除"""
        current_time = time.time()
        expired_keys = []
        
        for cache_dict in [self.web_cache, self.line_cache, self.rag_cache]:
            for key, entry in list(cache_dict.items()):
                if current_time - entry.get("timestamp", 0) >= self.cache_expire_time:
                    expired_keys.append(key)
        
        for key in expired_keys:
            self.web_cache.pop(key, None)
            self.line_cache.pop(key, None)
            self.rag_cache.pop(key, None)
            self.access_times.pop(key, None)
        
        if expired_keys:
            logger.info(f"🧹 Cleared {len(expired_keys)} expired cache entries")
        
        return len(expired_keys)

# ============================================================================
# 🚀 拡張テンプレートシステム（RAG回避強化）
# ============================================================================
class OptimizedTemplateSystem:
    def __init__(self):
        self.web_templates = self._load_enhanced_web_templates()
        self.line_templates = self._load_enhanced_line_templates()
        self.template_hits = {"web": 0, "line": 0}
        
        # 🚀 高速マッチング用のキーワードセット
        self.fast_keywords = self._build_fast_keyword_map()

    def _build_fast_keyword_map(self) -> Dict[str, str]:
        """🚀 高速キーワードマッチング用マップ構築"""
        keyword_map = {}
        
        # 基本キーワード
        basic_keywords = {
            "坪単価": ["坪単価", "坪たんか", "価格", "値段", "費用", "金額", "いくら"],
            "標準仕様": ["標準仕様", "仕様", "標準", "設備", "何が付く", "装備"],
            "断熱性能": ["断熱", "断熱性能", "省エネ", "ZEH", "UA値", "C値"],
            "耐震性能": ["耐震", "地震", "耐震性能", "安全", "強度", "構造"],
            "補助金": ["補助金", "助成金", "支援金", "zeh補助", "減税"],
            "資料請求": ["資料請求", "資料", "カタログ", "パンフレット"],
            "展示場": ["展示場", "見学", "モデルハウス", "来場"]
        }
        
        # リッチメニュー対応
        rich_menu = {
            "AI相談": ["ai相談", "🤖", "aiチャット"],
            "AI住まいサイト": ["ai住まいサイト", "🌐", "サイト"],
            "資金計画": ["資金計画", "💰", "ローン計算"],
            "チャット相談": ["チャット相談", "💬", "相談"]
        }
        
        # マップ構築
        for template_key, keywords in {**basic_keywords, **rich_menu}.items():
            for keyword in keywords:
                keyword_map[keyword.lower()] = template_key
        
        return keyword_map

    def _load_enhanced_web_templates(self) -> Dict[str, str]:
        """Web専用強化テンプレート（高速回答用）"""
        return {
            "坪単価": """💰 坪単価についてご案内いたします

**当社の坪単価目安**
・標準仕様：約70～85万円/坪
・高性能仕様：約85～100万円/坪

**含まれる内容**
・耐震等級3の構造
・長期優良住宅対応
・高断熱・高気密仕様
・標準設備一式

お客様のご要望により変動いたします。詳細なお見積りは展示場またはお問い合わせにてご相談ください。""",

            "標準仕様": """🏗️ 標準仕様についてご説明いたします

**構造・性能**
・耐震等級3（最高等級）
・長期優良住宅認定対応
・省エネ等級4以上
・高断熱・高気密仕様

**設備仕様**
・システムキッチン
・ユニットバス
・洗面化粧台
・トイレ（温水洗浄便座付）

より詳しい仕様書は資料請求または展示場見学でご確認いただけます。""",

            "断熱性能": """🌡️ 断熱性能についてご案内いたします

**断熱等級**
・断熱等級4以上（ZEH基準対応）
・UA値：0.6以下（地域区分6）
・C値：1.0以下（気密性能）

**使用断熱材**
・外壁：高性能グラスウール
・屋根：吹付断熱材
・基礎：押出法ポリスチレンフォーム

**快適性**
・夏涼しく、冬暖かい住環境
・光熱費の削減効果
・結露抑制で健康的

詳しくは展示場でご体感いただけます。""",

            "耐震性能": """🏗️ 耐震性能についてご案内いたします

**耐震等級**
・耐震等級3（最高等級）を標準採用
・建築基準法の1.5倍の耐震強度
・許容応力度計算による構造計算

**構造材**
・構造用集成材使用
・金物工法による強固な接合
・ベタ基礎による堅固な基礎

**保証**
・構造躯体20年保証
・地盤保証20年
・瑕疵担保責任保険対応

安心・安全な住まいをお約束いたします。""",

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

※制度は年度ごとに変更される可能性があります。最新情報はスタッフまでお問い合わせください。""",

            "資料請求": """📋 資料請求を承ります

**お送りする資料**
・会社案内・施工事例集
・間取りプラン集
・価格・仕様資料
・住宅ローンガイド

**必要情報**
1. お名前（フルネーム）
2. ご住所（〒郵便番号から）
3. お電話番号
4. ご希望資料の種類

3営業日以内にお送りいたします。お気軽にお申し付けください。""",

            "展示場": """📍 展示場見学についてご案内いたします

**見学内容**
・最新の住宅仕様をご確認
・実際の住み心地を体感
・詳細な打ち合わせ可能

**ご予約方法**
・お電話でのご予約
・Web予約フォーム
・このチャットでのご相談

**営業時間**
平日・土日祝：9:00-18:00
定休日：水曜日

スタッフ一同、心よりお待ちしております。""",

            "AI相談": """🤖 AI住まい相談へようこそ！

住まいづくりに関するご質問をお気軽にどうぞ！

**よくあるご質問**
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？
・補助金について教えて

何でもお聞きください😊"""
        }

    def _load_enhanced_line_templates(self) -> Dict[str, str]:
        """LINE専用強化テンプレート（短文・絵文字対応）"""
        return {
            # 基本テンプレート（短縮版）
            "坪単価": """💰 坪単価についてご案内

🏠 **目安**
・標準仕様：約70～85万円/坪
・高性能仕様：約85～100万円/坪

✨ **含まれる内容**
・耐震等級3の構造
・長期優良住宅対応
・高断熱・高気密仕様
・標準設備一式

詳細なお見積りは展示場でご相談ください😊""",

            "標準仕様": """🏗️ 標準仕様について

**構造・性能**
・耐震等級3（最高等級）
・長期優良住宅認定対応
・省エネ等級4以上
・高断熱・高気密仕様

**設備**
・システムキッチン
・ユニットバス
・洗面化粧台
・温水洗浄便座付トイレ

詳しくは展示場見学をご利用ください😊""",

            "断熱性能": """🌡️ 断熱性能について

**等級**
・断熱等級4以上（ZEH対応）
・UA値：0.6以下
・C値：1.0以下

**効果**
・夏涼しく、冬暖かい
・光熱費削減
・結露抑制

展示場で体感できます✨""",

            # リッチメニュー対応（完全版）
            "AI相談": """🤖 AI住まい相談開始！

住まいに関するご質問をお気軽にどうぞ！

💡 **例えば**
・坪単価について
・標準仕様は？
・性能について
・補助金情報

何でもお聞きください😊""",

            "AI住まいサイト": """🌐 AI住まいサイト

家づくりの疑問にAIが24時間即回答

🏠 **内容**
・AIチャット相談
・施工事例
・間取りプラン例
・よくある質問
・デジタル冊子

📱 https://preview.studio.site/live/EjOQljz1WJ/""",

            "資料請求": """📋 資料請求承ります

お名前、ご住所、お電話番号をお教えください。

**お送りする資料**
・会社案内・施工事例
・間取りプラン集
・価格・仕様資料

3営業日以内にお送りします😊""",

            "展示場": """📍 展示場見学予約

https://preview.studio.site/live/EjOQljz1WJ/reservation

**営業時間**
9:00-18:00（水曜定休）

スタッフ一同お待ちしております！""",

            "資金計画": """💰 資金計画診断

年収、返済希望額、借入期間、家族構成、その他負担をお教えください。

概算結果をご提示いたします。

※匿名利用可・回答内容非保存""",

            "チャット相談": """💬 スタッフとのご相談

**対応時間**
営業時間：9:00-18:00

**相談方法**
・このLINEで直接相談
・お電話での相談
・展示場での対面相談

お気軽にお声かけください！"""
        }

    def fast_template_match(self, query: str, platform: str) -> Optional[str]:
        """🚀 高速テンプレートマッチング（O(1)検索）"""
        templates = self.line_templates if platform == "line" else self.web_templates
        query_lower = query.lower().strip()
        
        # 🚀 完全一致チェック（最優先）
        if query_lower in self.fast_keywords:
            template_key = self.fast_keywords[query_lower]
            if template_key in templates:
                self.template_hits[platform] += 1
                logger.info(f"⚡ Fast template match: {template_key}")
                return templates[template_key]
        
        # 🚀 部分一致チェック（高頻度キーワードのみ）
        high_priority_keywords = [
            ("坪単価", "坪単価"), ("価格", "坪単価"), ("費用", "坪単価"),
            ("標準仕様", "標準仕様"), ("仕様", "標準仕様"),
            ("断熱", "断熱性能"), ("性能", "断熱性能"),
            ("耐震", "耐震性能"), ("地震", "耐震性能"),
            ("補助金", "補助金"), ("助成金", "補助金"),
            ("資料", "資料請求"), ("展示", "展示場"),
            ("ai相談", "AI相談"), ("🤖", "AI相談"),
            ("ai住まい", "AI住まいサイト"), ("🌐", "AI住まいサイト"),
            ("資金計画", "資金計画"), ("💰", "資金計画"),
            ("チャット相談", "チャット相談"), ("💬", "チャット相談")
        ]
        
        for keyword, template_key in high_priority_keywords:
            if keyword in query_lower and template_key in templates:
                self.template_hits[platform] += 1
                logger.info(f"⚡ Keyword template match: {template_key}")
                return templates[template_key]
        
        return None

# ============================================================================
# 🚀 最適化統合応答生成システム（RAG呼び出し最小化）
# ============================================================================
class OptimizedResponseGenerator:
    def __init__(self):
        self.cache = OptimizedCacheSystem(max_size=2000)
        self.templates = OptimizedTemplateSystem()
        self.tracer = RAGTracer()
        
        # 🚀 パフォーマンス統計強化
        self.performance_metrics = {
            "total_requests": 0,
            "template_responses": 0,
            "rag_responses": 0,  
            "cache_responses": 0,
            "anti_hallucination_used": 0,
            "rag_avoided": 0,  # 🔧 RAG回避数
            "avg_response_time": 0.0,
            "template_hit_rate": 0.0,
            "cache_hit_rate": 0.0
        }

    def _should_use_template_optimized(self, query: str) -> bool:
        """🚀 最適化テンプレート使用判定（RAG回避強化）"""
        query_lower = query.lower().strip()
        
        # 🚀 高優先度キーワード（テンプレート必須）
        template_priority_keywords = [
            "坪単価", "価格", "費用", "金額", "いくら",
            "標準仕様", "仕様", "設備", "標準",
            "断熱", "性能", "ZEH", "省エネ",
            "耐震", "地震", "安全", "構造",
            "補助金", "助成金", "支援金", "減税",
            "資料請求", "資料", "カタログ",
            "展示場", "見学", "モデルハウス",
            "ai相談", "🤖", "aiチャット",
            "ai住まいサイト", "🌐", "サイト",
            "資金計画", "💰", "ローン",
            "チャット相談", "💬", "相談"
        ]
        
        # 短いクエリは必ずテンプレート
        if len(query) <= 15:
            return True
        
        # 高優先度キーワードが含まれる場合はテンプレート
        if any(keyword in query_lower for keyword in template_priority_keywords):
            return True
        
        # 絵文字が含まれる場合（LINEリッチメニュー）
        if any(emoji in query for emoji in ["🤖", "🌐", "📋", "📍", "💰", "💬"]):
            return True
        
        # 挨拶・定型文
        greeting_patterns = [
            "こんにちは", "こんばんは", "おはよう", "はじめまして",
            "ありがとう", "助かり", "よろしく", "お疲れ様"
        ]
        if any(pattern in query_lower for pattern in greeting_patterns):
            return True
        
        return False

    def _should_use_rag_strict(self, query: str) -> bool:
        """🚀 厳格なRAG使用判定（不要な呼び出しを削減）"""
        query_lower = query.lower().strip()
        
        # 🚀 RAG不要なパターン（明確に除外）
        template_only_patterns = [
            "坪単価", "価格", "標準仕様", "仕様", "断熱", "耐震",
            "資料請求", "展示場", "見学", "ai相談", "資金計画",
            "補助金", "助成金", "支援金"
        ]
        
        if any(pattern in query_lower for pattern in template_only_patterns):
            self.performance_metrics["rag_avoided"] += 1
            logger.info(f"🚫 RAG avoided (template pattern): {query[:30]}...")
            return False
        
        # 短いクエリはRAG不要
        if len(query) <= 20:
            self.performance_metrics["rag_avoided"] += 1
            return False
        
        # 🚀 RAG必要な明確なパターン
        rag_required_patterns = [
            "詳しく教えて", "具体的に", "どのように", "なぜ", "理由",
            "メリット", "デメリット", "比較", "違い", "選び方",
            "注意点", "ポイント", "流れ", "手順", "プロセス"
        ]
        
        # かつ十分な長さがある場合のみRAG実行
        has_rag_pattern = any(pattern in query_lower for pattern in rag_required_patterns)
        is_complex_query = len(query) > 30
        has_question_words = any(word in query_lower for word in ["？", "?", "どう", "どの", "いつ", "どこ"])
        
        if has_rag_pattern and is_complex_query and has_question_words:
            return True
        
        # デフォルトはRAG回避
        self.performance_metrics["rag_avoided"] += 1
        logger.info(f"🚫 RAG avoided (strict filter): {query[:30]}...")
        return False

    def _should_use_anti_hallucination_strict(self, query: str) -> bool:
        """🚀 厳格なハルチネーション対策判定（過剰適用防止）"""
        if not ANTI_HALLUCINATION_AVAILABLE:
            return False
        
        query_lower = query.lower()
        
        # 🚀 厳格なキーワードチェック（補助金・最新情報のみ）
        strict_subsidy_keywords = [
            "zeh補助金", "こどもエコすまい", "住宅ローン控除", "住宅ローン減税",
            "2024年度補助金", "2025年度補助金", "最新の補助金制度",
            "令和6年度", "令和7年度"
        ]
        
        current_info_keywords = [
            "最新の", "現在の", "今年の", "2024年", "2025年", "令和6", "令和7"
        ]
        
        # 補助金と最新情報の両方が明確に含まれる場合のみ
        has_subsidy = any(keyword in query_lower for keyword in strict_subsidy_keywords)
        has_current = any(keyword in query_lower for keyword in current_info_keywords)
        
        return has_subsidy or (has_current and "補助" in query_lower)

    async def generate_response(self, query: str, platform: str = "web", 
                              user: str = "unknown", mode: str = "auto") -> Dict[str, Any]:
        """🚀 最適化統合応答生成（高速化版）"""
        start_time = time.time()
        self.performance_metrics["total_requests"] += 1

        try:
            # 🚀 1. 期限切れキャッシュクリーンアップ（定期）
            if self.performance_metrics["total_requests"] % 100 == 0:
                self.cache.clear_expired()

            # 🚀 2. キャッシュチェック（最優先）
            cache_type = "rag" if mode == "rag" else "general"
            cached_response = self.cache.get(query, platform, cache_type)
            
            if cached_response:
                self.performance_metrics["cache_responses"] += 1
                return {
                    "answer": cached_response["answer"],
                    "sources": cached_response.get("sources", []),
                    "processing_time": time.time() - start_time,
                    "source": "cache",
                    "platform": platform,
                    "status": "ok",
                    "optimization": "cache_hit",
                    "anti_hallucination_used": cached_response.get("anti_hallucination_used", False)
                }

            # 🚀 3. テンプレート判定（RAG回避優先）
            if mode == "template" or (mode == "auto" and self._should_use_template_optimized(query)):
                template_response = self.templates.fast_template_match(query, platform)
                
                if template_response:
                    self.performance_metrics["template_responses"] += 1
                    
                    # ハルチネーション対策（厳格条件のみ）
                    final_response = template_response
                    anti_hallucination_used = False
                    
                    if self._should_use_anti_hallucination_strict(query):
                        try:
                            enhanced_result = await enhance_web_chat_response(
                                query=query,
                                original_response=template_response,
                                user_context={"username": user, "platform": platform}
                            )
                            final_response = enhanced_result.get("answer", template_response)
                            anti_hallucination_used = True
                            self.performance_metrics["anti_hallucination_used"] += 1
                        except Exception as e:
                            logger.warning(f"Template enhancement failed: {e}")
                    
                    response = {
                        "answer": final_response,
                        "sources": [],
                        "processing_time": time.time() - start_time,
                        "source": "template_optimized",
                        "platform": platform,
                        "status": "ok",
                        "optimization": "template_fast_match",
                        "anti_hallucination_used": anti_hallucination_used
                    }
                    
                    # キャッシュ保存
                    self.cache.set(query, response, platform, "template")
                    return response

            # 🚀 4. RAG判定（厳格フィルタ）
            if mode == "rag" or (mode == "auto" and self._should_use_rag_strict(query)):
                return await self._generate_rag_response_optimized(query, platform, user, start_time)

            # 🚀 5. フォールバック（高速）
            return await self._generate_fast_fallback_response(query, platform, start_time)

        except Exception as e:
            logger.error(f"Optimized response generation error: {e}")
            return self._generate_error_response(query, platform, start_time)

    async def _generate_rag_response_optimized(self, query: str, platform: str, user: str, start_time: float) -> Dict[str, Any]:
        """🚀 最適化RAG応答生成"""
        try:
            # アプリのグローバル変数取得
            globals_dict = self.get_app_globals()
            vectorstore = globals_dict.get('vectorstore')
            rag_chain_template = globals_dict.get('rag_chain_template')
            
            if not vectorstore or not rag_chain_template:
                logger.warning("RAG components not available, using fast fallback")
                return await self._generate_fast_fallback_response(query, platform, start_time)
            
            # 🚀 RAG処理（タイムアウト短縮）
            try:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(self._execute_rag_sync, rag_chain_template, query)
                    result = future.result(timeout=6)  # 🔧 短縮：8→6秒
                    
                    raw_answer = result.get("result", "")
                    if not raw_answer or len(raw_answer.strip()) < 10:
                        return await self._generate_fast_fallback_response(query, platform, start_time)
                    
                    self.performance_metrics["rag_responses"] += 1
                    
                    # ハルチネーション対策（厳格条件）
                    final_answer = raw_answer
                    anti_hallucination_used = False
                    
                    if ANTI_HALLUCINATION_AVAILABLE and self._should_use_anti_hallucination_strict(query):
                        try:
                            enhanced_result = await enhance_web_chat_response(
                                query=query,
                                original_response=raw_answer,
                                user_context={"username": user, "platform": platform}
                            )
                            final_answer = enhanced_result.get("answer", raw_answer)
                            anti_hallucination_used = True
                            self.performance_metrics["anti_hallucination_used"] += 1
                        except Exception as e:
                            logger.warning(f"RAG enhancement failed: {e}")
                    
                    response = {
                        "answer": final_answer,
                        "sources": [{"content": "社内データベース"}],
                        "processing_time": time.time() - start_time,
                        "source": "rag_optimized",
                        "platform": platform,
                        "status": "ok",
                        "optimization": "rag_timeout_reduced",
                        "anti_hallucination_used": anti_hallucination_used
                    }
                    
                    # キャッシュ保存
                    self.cache.set(query, response, platform, "rag")
                    return response
                    
            except concurrent.futures.TimeoutError:
                logger.warning("⏰ RAG timeout, using fast fallback")
                return await self._generate_fast_fallback_response(query, platform, start_time)
            
        except Exception as e:
            logger.error(f"RAG generation error: {e}")
            return await self._generate_fast_fallback_response(query, platform, start_time)

    def _execute_rag_sync(self, rag_chain, query: str):
        """同期RAG実行"""
        return rag_chain.invoke({"query": query})

    async def _generate_fast_fallback_response(self, query: str, platform: str, start_time: float) -> Dict[str, Any]:
        """🚀 高速フォールバック応答"""
        # テンプレートマッチを再試行
        fallback_template = self.templates.fast_template_match(query, platform)
        
        if fallback_template:
            answer = fallback_template
        else:
            # 最小限のキーワードベース応答
            q_lower = query.lower()
            if any(kw in q_lower for kw in ["坪単価", "価格", "費用"]):
                answer = "坪単価は約70〜85万円/坪です。詳細はお問い合わせください。"
            elif any(kw in q_lower for kw in ["住宅", "家", "建築"]):
                answer = "住まいづくりについてお答えいたします。具体的なご質問があればお聞かせください。"
            else:
                answer = "お尋ねの件についてお答えいたします。詳しくはお気軽にお問い合わせください。"
        
        response = {
            "answer": answer,
            "sources": [],
            "processing_time": time.time() - start_time,
            "source": "fast_fallback",
            "platform": platform,
            "status": "ok",
            "optimization": "keyword_based_fallback",
            "anti_hallucination_used": False
        }
        
        # キャッシュ保存
        self.cache.set(query, response, platform, "fallback")
        return response

    def _generate_error_response(self, query: str, platform: str, start_time: float) -> Dict[str, Any]:
        """エラー応答生成"""
        return {
            "answer": "申し訳ございません。一時的にエラーが発生しました。しばらく後に再度お試しください。",
            "sources": [],
            "processing_time": time.time() - start_time,
            "source": "error",
            "platform": platform,
            "status": "error",
            "optimization": "error_fallback",
            "anti_hallucination_used": False
        }

    def get_app_globals(self) -> Dict[str, Any]:
        """アプリのグローバル変数を取得"""
        try:
            import main
            return {
                'vectorstore': getattr(main, 'vectorstore', None),
                'rag_chain_template': getattr(main, 'rag_chain_template', None),
                'llm_instance': getattr(main, 'llm_instance', None)
            }
        except ImportError:
            logger.warning("Main module not available")
            return {}

    def get_performance_stats(self) -> Dict[str, Any]:
        """🚀 最適化パフォーマンス統計取得"""
        total = self.performance_metrics["total_requests"]
        cache_stats = self.cache.get_stats()
        
        # 統計計算
        template_hit_rate = (self.performance_metrics["template_responses"] / total * 100) if total > 0 else 0
        rag_avoidance_rate = (self.performance_metrics["rag_avoided"] / total * 100) if total > 0 else 0
        
        return {
            "optimization_performance": {
                "total_requests": total,
                "template_hit_rate": template_hit_rate,
                "rag_avoidance_rate": rag_avoidance_rate,
                "cache_hit_rate": cache_stats["hit_rates"]["overall"],
                "anti_hallucination_usage": (self.performance_metrics["anti_hallucination_used"] / total * 100) if total > 0 else 0,
                "avg_response_time": self.performance_metrics.get("avg_response_time", 0.0)
            },
            "response_distribution": {
                "template": self.performance_metrics["template_responses"],
                "rag": self.performance_metrics["rag_responses"],
                "cache": self.performance_metrics["cache_responses"],
                "rag_avoided": self.performance_metrics["rag_avoided"]
            },
            "cache_performance": cache_stats,
            "optimizations_applied": [
                "🚀 Extended cache size (2000 entries)",
                "⚡ Fast keyword matching (O(1))",
                "🚫 Strict RAG filtering",
                "🎯 Enhanced template coverage",
                "⏰ Reduced timeouts (6s RAG)",
                "🧹 Automatic cache expiration (1h)",
                "🛡️ Strict anti-hallucination conditions"
            ]
        }

# ============================================================================
# グローバルインスタンス
# ============================================================================
optimized_generator = OptimizedResponseGenerator()

# ============================================================================
# リクエストモデル
# ============================================================================
class OptimizedChatRequest(BaseModel):
    question: str
    username: str | None = None
    platform: str | None = "web"
    mode: str | None = "auto"  # auto, template, rag

# ============================================================================
# メインエンドポイント（最適化版）
# ============================================================================
@router.post("/", summary="最適化統合チャットエンドポイント（高速化版）")
async def optimized_chat_endpoint(req: OptimizedChatRequest, request: Request):
    """最適化統合チャットエンドポイント（高速化版）"""
    
    overall_start = time.time()
    platform = req.platform or "web"
    username = req.username or f"{platform}-user"
    mode = req.mode or "auto"
    
    logger.info(f"🚀 Optimized Chat ({platform}, {mode}): {req.question[:50]}...")

    try:
        # 最適化応答生成
        response = await optimized_generator.generate_response(
            req.question, platform, username, mode
        )

        total_time = time.time() - overall_start
        
        # パフォーマンス統計更新
        optimized_generator.performance_metrics["avg_response_time"] = (
            (optimized_generator.performance_metrics["avg_response_time"] * 
             (optimized_generator.performance_metrics["total_requests"] - 1) + total_time) / 
            optimized_generator.performance_metrics["total_requests"]
        )

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
                "source": response.get("source"),
                "optimization": response.get("optimization")
            },
            "optimization_info": {
                "anti_hallucination_used": response.get("anti_hallucination_used", False),
                "rag_avoided": response.get("source", "").startswith("template"),
                "cache_hit": response.get("source") == "cache"
            }
        }
        history_logs.append(log_entry)

        logger.info(
            f"✅ Optimized response: {total_time:.3f}s, "
            f"source={response.get('source')}, "
            f"opt={response.get('optimization')}, "
            f"length={len(response['answer'])}"
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
                "optimization": response.get("optimization"),
                "speed_optimized": True,
                "anti_hallucination_used": response.get("anti_hallucination_used", False)
            }
        }

    except Exception as e:
        total_time = time.time() - overall_start
        error_id = str(uuid4())[:8]

        logger.error(f"❌ Optimized chat error [{error_id}]: {e}")
        logger.error(traceback.format_exc())

        return JSONResponse(
            status_code=200,
            content={
                "answer": "申し訳ございません。一時的にエラーが発生しました。しばらく後に再度お試しください。",
                "sources": [],
                "status": "error",
                "error_id": error_id,
                "performance": {
                    "total_time": total_time,
                    "platform": platform,
                    "mode": mode,
                    "optimization": "error_fallback",
                    "speed_optimized": True
                }
            }
        )

# ============================================================================
# 管理エンドポイント（最適化版）
# ============================================================================
@router.get("/optimization-stats", summary="最適化統計取得")
def get_optimization_stats():
    """最適化統計取得"""
    stats = optimized_generator.get_performance_stats()
    
    return {
        "optimization_results": stats,
        "speed_improvements": {
            "template_response_time": "< 0.3s (target)",
            "rag_response_time": "< 6s (reduced from 8s)",
            "cache_hit_response": "< 0.1s",
            "rag_avoidance_rate": f"{stats['optimization_performance']['rag_avoidance_rate']:.1f}%",
            "template_hit_rate": f"{stats['optimization_performance']['template_hit_rate']:.1f}%"
        },
        "optimizations_summary": [
            f"🚫 RAG Avoidance: {stats['response_distribution']['rag_avoided']} requests",
            f"⚡ Template Fast Match: {stats['response_distribution']['template']} requests",
            f"💾 Cache Hits: {stats['response_distribution']['cache']} requests",
            f"🤖 RAG Usage: {stats['response_distribution']['rag']} requests",
            f"🛡️ Anti-hallucination: {stats['optimization_performance']['anti_hallucination_usage']:.1f}% usage"
        ],
        "timestamp": datetime.now().isoformat()
    }

@router.post("/clear-optimized-cache", summary="最適化キャッシュクリア")
def clear_optimized_cache():
    """最適化キャッシュクリア"""
    old_sizes = optimized_generator.cache.clear_all()
    
    return {
        "status": "optimized_cache_cleared",
        "cleared_caches": old_sizes,
        "optimization_features": [
            "Extended cache size (2000)",
            "Cache expiration (1h)",
            "Fast keyword matching",
            "RAG avoidance filtering",
            "Template prioritization"
        ],
        "timestamp": datetime.now().isoformat()
    }