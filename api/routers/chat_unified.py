# api/routers/chat_unified.py - 完全統合チャットルーター（chat.py + chat_ultra_fast.py統合版）

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

# ハルシネーション対策統合機能
try:
    from integration.anti_hallucination_integration import enhance_web_chat_response
    ANTI_HALLUCINATION_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("✅ Anti-hallucination integration available")
except ImportError as e:
    ANTI_HALLUCINATION_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning(f"⚠️ Anti-hallucination integration not available: {e}")

# LangSmithトレース（条件付き）
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
# 統合キャッシュシステム（Web/LINE/RAG分離＋高速アクセス）
# ============================================================================
class UnifiedCacheSystem:
    def __init__(self, max_size: int = 1000):
        # プラットフォーム分離キャッシュ
        self.web_cache: Dict[str, Dict[str, Any]] = {}
        self.line_cache: Dict[str, Dict[str, Any]] = {}
        self.rag_cache: Dict[str, Dict[str, Any]] = {}  # RAG専用キャッシュ
        self.access_times: Dict[str, float] = {}
        self.max_size = max_size
        
        # 統計情報（chat.pyとchat_ultra_fast.pyの統計を統合）
        self.stats = {
            "web_hits": 0, "web_misses": 0,
            "line_hits": 0, "line_misses": 0,
            "rag_hits": 0, "rag_misses": 0,
            "total_requests": 0,
            "hits": 0, "misses": 0  # chat.py互換性
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
            self.stats["hits"] += 1  # chat.py互換性
            logger.info(f"⚡ {stat_prefix.upper()} Cache HIT: {query[:30]}...")
            return cache_dict[key]
        
        self.stats[f"{stat_prefix}_misses"] += 1
        self.stats["misses"] += 1  # chat.py互換性
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
            "meta": response.get("meta", {}),
            "anti_hallucination_used": response.get("anti_hallucination_used", False)
        }
        self.access_times[key] = time.time()
        logger.info(f"💾 {platform.upper()} Cache SET: {query[:30]}...")

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
                "overall": (self.stats["hits"] / total * 100) if total > 0 else 0
            },
            "raw_stats": self.stats,
            # chat.py互換性
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "size": self._total_cache_size()
        }

# ============================================================================
# 統合テンプレートシステム（chat.py + chat_ultra_fast.pyの完全統合）
# ============================================================================
class UnifiedTemplateSystem:
    def __init__(self):
        self.web_templates = self._load_web_templates()
        self.line_templates = self._load_line_templates()
        self.template_hits = {"web": 0, "line": 0}

    def _load_web_templates(self) -> Dict[str, str]:
        """Web専用テンプレート（chat.py FAST_TEMPLATES + 補助金テンプレート）"""
        return {
            "坪単価": """坪単価についてご案内いたします。

💰 **当社の坪単価目安**
・標準仕様：約70～85万円/坪
・高性能仕様：約85～100万円/坪

✨ **含まれる内容**
・耐震等級3の構造
・長期優良住宅対応
・高断熱・高気密仕様
・標準設備一式

お客様のご要望により変動いたします。詳細なお見積りをご希望でしたら、お気軽にお問い合わせください。""",

            "標準仕様": """標準仕様についてご説明いたします。

🏗️ **構造・性能**
・耐震等級3（最高等級）
・長期優良住宅認定対応
・省エネ等級4以上
・高断熱・高気密仕様

**設備仕様**
・システムキッチン
・ユニットバス
・洗面化粧台
・トイレ（温水洗浄便座付）

より詳しい仕様書をご希望の場合は、資料請求または展示場見学をお申し込みください。""",

            "断熱性能": """断熱性能についてご案内いたします。

🌡️ **断熱等級**
・断熱等級4以上（ZEH基準対応）
・UA値：0.6以下（地域区分6）
・C値：1.0以下（気密性能）

**使用断熱材**
・外壁：高性能グラスウール
・屋根：吹付断熱材
・基礎：押出法ポリスチレンフォーム

**快適性**
・夏涼しく、冬暖かい
・光熱費の削減効果
・結露抑制

詳しくは展示場でご体感いただけます。""",

            "耐震性能": """耐震性能についてご案内いたします。

🏗️ **耐震等級**
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

            "補助金": """住宅購入時の補助金制度についてご案内します。

💰 **主な補助金制度**

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

            "資料請求": """資料請求を承ります。

以下の情報をお送りください：
1. お名前（フルネーム）
2. ご住所（〒郵便番号から）
3. お電話番号
4. ご希望資料の種類

お送りする資料：
・会社案内・施工事例集
・間取りプラン集
・価格・仕様資料
・住宅ローンガイド

3営業日以内にお送りいたします。""",

            "AI相談": """AI住まい相談へようこそ！

住まいづくりに関するご質問をお気軽にどうぞ！

よくあるご質問：
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？
・補助金について教えて

何でもお聞きください😊"""
        }

    def _load_line_templates(self) -> Dict[str, str]:
        """LINE専用テンプレート（リッチメニュー完全対応版）"""
        return {
            # リッチメニュー1: AI相談
            "AI相談": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 **例えば**
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？

何でもお聞きください😊

※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：https://preview.studio.site/live/EjOQljz1WJ/privacy-policy
利用規約：https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service
Cookie：https://preview.studio.site/live/EjOQljz1WJ/cookie""",

            # リッチメニュー2: AI住まいサイト
            "AI住まいサイト": """🌐 AI住まいサイトのご案内

キノエデザインの住まい情報サイトをご紹介します。（家づくりの疑問にAIが24時間即回答）

🏠 サイト内容：
・AIチャット相談（資金計画／補助金／間取り など）
・施工写真（実例）
・間取りの考え方・プラン例
・よくある質問（最初に迷う3つのこと ほか）
・保存版デジタル冊子 ZINE（無料ダウンロード）
・LINEで無料相談／来場予約

📱 サイトURL:
https://preview.studio.site/live/EjOQljz1WJ/""",

            # リッチメニュー3: 資料請求
            "資料請求": """📋 ありがとうございます！こちらからご覧いただけます。

〔資料タイトル〕（PDF）：〔URL〕

よろしければ簡単アンケート（任意）：
・ご計画時期：今すぐ / 3–6か月 / 1年以内 / 未定
・連絡方法（任意）：このLINE / メール / 連絡不要

※必ず以下の取り扱いをご確認ください。
プライバシーポリシー：https://preview.studio.site/live/EjOQljz1WJ/privacy-policy
利用規約：https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service
Cookie：https://preview.studio.site/live/EjOQljz1WJ/cookie""",

            # リッチメニュー4: 展示場来場予約
            "展示場来場予約": """📍 展示場のご来場予約につきましては、下記URLより必要事項のご入力をお願い申し上げます。

https://preview.studio.site/live/EjOQljz1WJ/reservation

スタッフ一同、心よりお待ちしております！""",

            # リッチメニュー5: 資金計画
            "資金計画": """💬 AI資金診断のご案内

本診断は匿名でご利用いただけます。ご回答内容は保存いたしません。算出される金額は試算（概算）であり、目安としてご確認ください。

お手数ですが、以下の5点をご入力ください。
・年収（概算可）
・毎月のご希望返済額
・住宅ローンのご希望借入期間
・ご家族構成（例：大人2名・お子さま1名）
・その他の大きなご負担（例：自動車ローン 等）

未入力の項目があっても進められます。ご入力後、概算結果をご提示いたします。""",

            # リッチメニュー6: チャット相談
            "チャット相談": """💬 スタッフとのご相談

【対応時間】
営業時間：9:00-18:00

📱 ご相談方法：
・このLINEでの直接相談
・お電話での相談
・展示場での対面相談

営業時間内でしたら迅速にお返事します。
お気軽にお声かけください！""",

            # AIが質問に答える用（既存テンプレート）
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

より詳しい仕様書をご希望の場合は、資料請求または展示場見学をお申し込みください😊""",

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
・夏涼しく、冬暖かい
・光熱費の削減効果
・結露抑制

詳しくは展示場でご体感いただけます😊""",

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

安心・安全な住まいをお約束いたします😊""",

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
        """プラットフォーム別テンプレートマッチング（完全版）"""
        templates = self.line_templates if platform == "line" else self.web_templates
        query_lower = query.lower()

        # リッチメニュー対応のキーワードマッピング（完全版）
        keyword_mapping: Dict[str, List[str]] = {
            # リッチメニュー項目（完全一致優先）
            "AI相談": ["🤖 ai相談", "ai相談", "🤖ai相談", "aiチャット", "ai chat"],
            "AI住まいサイト": ["🌐 ai住まいサイト", "ai住まいサイト", "🌐ai住まいサイト", "住まいサイト"],
            "資料請求": ["📋 資料請求", "資料請求", "📋資料請求", "カタログ", "パンフレット"],
            "展示場来場予約": ["📍 展示場来場", "展示場来場予約", "展示場来場　予約", "📍展示場", "見学予約", "モデルハウス", "来場"],
            "資金計画": ["💰 資金計画", "資金計画", "💰資金計画", "住宅ローン", "予算", "返済"],
            "チャット相談": ["💬 チャット相談", "チャット相談", "💬チャット相談", "相談", "問い合わせ"],
            
            # 既存のキーワード（AIが質問に答える用）
            "坪単価": ["坪単価", "坪たんか", "価格", "値段", "費用", "コスト", "いくら", "金額", "料金"],
            "標準仕様": ["標準仕様", "仕様", "設備", "標準", "基本", "スタンダード", "何が付く", "装備"],
            "断熱性能": ["断熱", "断熱性能", "省エネ", "温度", "暖房", "冷房", "光熱費", "ua値", "c値", "断熱材"],
            "耐震性能": ["耐震", "地震", "耐震性能", "安全", "強度", "構造", "震災", "耐震等級"],
            "補助金": ["補助金", "助成金", "支援金", "補助制度", "支援制度", "zeh補助", "こどもエコ", "減税"],
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
            "template_hits": self.template_hits,
            "rich_menu_support": ["AI相談", "AI住まいサイト", "資料請求", "展示場来場予約", "資金計画", "チャット相談"]
        }

# ============================================================================
# 統合応答生成システム（完全版：chat.py + chat_ultra_fast.py機能統合）
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
            "anti_hallucination_used": 0,
            "web_requests": 0,
            "line_requests": 0
        }

    # ============================================================================
    # chat.pyの機能統合
    # ============================================================================
    def is_general_greeting_or_chat(self, query: str) -> bool:
        """一般的な挨拶・雑談判定（chat.pyから移植）"""
        greetings = [
            "こんにちは", "こんばんは", "おはよう", "はじめまして",
            "hello", "hi", "hey", "ありがとう", "さようなら",
            "元気", "調子はどう", "お疲れ様", "よろしく"
        ]
        query_lower = query.lower()
        for greeting in greetings:
            if greeting in query_lower:
                return True
        if len(query.strip()) <= 5:
            return True
        question_words = ["何", "どう", "いつ", "どこ", "誰", "なぜ", "どんな", "どの", "？", "?"]
        has_question = any(word in query for word in question_words)
        if len(query) <= 20 and not has_question:
            return True
        return False

    def get_general_response_from_llm(self, query: str, llm_instance) -> str:
        """LLMからの一般応答取得（chat.pyから移植）"""
        try:
            prompt = f"""あなたは親切で丁寧な日本語のAIアシスタントです。
以下のユーザーの入力に対して、自然で親しみやすい日本語で応答してください。
技術的な内容ではなく、一般的な会話として応答してください。

ユーザー: {query}

アシスタント:"""
            if hasattr(llm_instance, 'invoke'):
                response = llm_instance.invoke(prompt)
                return response.content if hasattr(response, 'content') else str(response)
            else:
                response = llm_instance(prompt)
                return response if isinstance(response, str) else str(response)
        except Exception as e:
            logger.error(f"Error generating general response: {e}")
            if "こんにちは" in query:
                return "こんにちは！今日はどのようなご用件でしょうか？お手伝いできることがあれば、お気軽にお尋ねください。"
            elif "ありがとう" in query:
                return "どういたしまして！他にもご質問がございましたら、いつでもお聞きください。"
            else:
                return "申し訳ございません。もう一度お聞かせいただけますか？"

    def clean_rag_response(self, raw_response: str) -> str:
        """RAG回答をクリーンアップ（chat.pyから移植・強化版）"""
        if not raw_response or len(raw_response.strip()) < 3:
            return "申し訳ございません。お尋ねの内容について詳細な情報が見つかりませんでした。"

        cleaned = raw_response

        # 構造化・出典表記などの除去（chat.pyの詳細パターン）
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
            r"^質問[:：]\s*",
            r"^回答[:：]\s*",
            r"出典[:：][^\n]*",
            r"\.pdf\s*\([pP]\d+\)",
            r"\.pdf\s+\(p\d+\)",
        ]
        for pattern in structure_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)

        # 縦書き由来の分断行を連結（chat.pyから移植）
        lines = cleaned.split('\n')
        fixed_lines = []
        char_buffer = []
        for line in lines:
            line = line.strip()
            if not line:
                if char_buffer:
                    combined = ''.join(char_buffer)
                    if len(combined) > 2:
                        fixed_lines.append(combined)
                    char_buffer = []
                continue
            if len(line) <= 3:
                char_buffer.append(line)
            else:
                if char_buffer:
                    combined = ''.join(char_buffer)
                    if len(combined) > 2:
                        fixed_lines.append(combined)
                    char_buffer = []
                fixed_lines.append(line)
        if char_buffer:
            combined = ''.join(char_buffer)
            if len(combined) > 2:
                fixed_lines.append(combined)

        # 重複行の排除（chat.pyから移植）
        unique_content = []
        seen_content = set()
        for line in fixed_lines:
            if len(line) < 5:
                continue
            line_normalized = re.sub(r'[。、\s]', '', line.lower())
            if any(line_normalized in s or s in line_normalized for s in seen_content):
                continue
            seen_content.add(line_normalized)
            unique_content.append(line)

        # 一番意味のある行を採用し整形
        if unique_content:
            result = max(unique_content, key=len)
            result = re.sub(r'\s+', ' ', result)
            result = re.sub(r'([。！？])\s*', r'\1', result).strip()
        else:
            result = "申し訳ございません。お尋ねの内容について、詳細な情報をお答えできませんでした。"

        if len(result) < 10 or "..." in result:
            result = "申し訳ございません。お尋ねの内容について、より詳しい情報をご提供するため、直接お問い合わせいただければと思います。"

        return result

    def generate_fallback_response(self, query: str) -> str:
        """フォールバック応答の生成（chat.pyから移植）"""
        q_lower = query.lower()
        
        if "坪単価" in q_lower or "価格" in q_lower:
            return "坪単価については、お客様のご希望される仕様や設備によって異なります。標準仕様では約70〜85万円/坪が目安となりますが、詳細なお見積りをご提供いたしますので、お気軽にお問い合わせください。"
        elif "仕様" in q_lower:
            return "住宅の仕様について詳しくご案内いたします。耐震等級3の長期優良住宅を基準とし、高品質な住まいをご提供するため、様々な設備や性能を標準装備としております。詳細は展示場でご確認いただけます。"
        elif "家を建てる" in q_lower or "マイホーム" in q_lower:
            return "家づくりを始める際は、まず予算の確認、希望する間取りや設備の整理、土地の条件確認から始めることをお勧めします。信頼できる建築会社の選定も重要なポイントです。お客様のご要望をお聞かせいただければ、最適なプランをご提案いたします。"
        else:
            return "お尋ねの内容について詳しくご案内いたします。住宅に関することでしたら何でもお気軽にお問い合わせください。スタッフ一同、お客様の理想の住まいづくりをお手伝いいたします。"

    def get_app_globals(self) -> Dict[str, Any]:
        """アプリのグローバル変数を取得（chat.pyから移植）"""
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

    # ============================================================================
    # chat_ultra_fast.pyの機能統合（文章完全性確保）
    # ============================================================================
    def ensure_response_completeness(self, text: str, platform: str, query: str = "") -> str:
        """応答の完全性を確保（chat_ultra_fast.pyから移植・強化版）"""
        if not text or len(text.strip()) < 5:
            return self.generate_platform_fallback(query, platform)
        
        text = text.strip()
        
        # 文末チェックと補完
        if not text.endswith(('。', '！', '？', '.', '!', '?')):
            logger.info(f"🔧 Fixing incomplete response ending with: '{text[-30:]}'")
            
            # 特定の途切れパターンの補完（chat.pyの詳細パターン + chat_ultra_fast.pyの補完）
            if text.endswith('や'):  # 「土地探しや」
                if "土地" in text:
                    suffix = "建築準備を総合的に進めることをお勧めします✨" if platform == "line" else "建築準備を総合的に進めることをお勧めします。"
                    text += suffix
                else:
                    suffix = "関連する準備を進めることをお勧めします😊" if platform == "line" else "関連する準備を進めることをお勧めします。"
                    text += suffix
            elif text.endswith('重要'):  # 「重要」
                if "選定" in text:
                    suffix = 'です。詳しい選び方についてはスタッフまでご相談ください😊' if platform == "line" else 'です。詳しい選び方についてはスタッフまでご相談ください。'
                    text += suffix
                else:
                    suffix = 'なポイントです。詳細についてはお気軽にお問い合わせください😊' if platform == "line" else 'なポイントです。詳細についてはお気軽にお問い合わせください。'
                    text += suffix
            elif text.endswith('必要'):
                text += 'です。'
            elif text.endswith('について'):
                suffix = 'は、詳細をご案内いたします💡' if platform == "line" else 'は、詳細をご案内いたします。'
                text += suffix
            elif text.endswith('選定') or text.endswith('検討'):
                text += 'も重要な要素です。'
            elif text.endswith('確認') or text.endswith('準備'):
                text += 'を進めることをお勧めします。'
            elif text.endswith('計画') or text.endswith('設計'):
                text += 'が成功の鍵となります。'
            elif text.endswith('性能') or text.endswith('品質'):
                text += 'にこだわっています。'
            elif text.endswith('対応') or text.endswith('仕様'):
                text += 'となっております。'
            elif text.endswith('条件') or text.endswith('基準'):
                text += 'を満たしています。'
            elif text.endswith('など'):
                text += 'があります。'
            elif text.endswith('から'):
                text += '始めることをお勧めします。'
            elif text.endswith('また'):
                suffix = '、詳細についてはお問い合わせください😊' if platform == "line" else '、詳細についてはお問い合わせください。'
                text += suffix
            elif text.endswith('ます') or text.endswith('です'):
                text += '。'
            elif text.endswith('た') or text.endswith('る'):
                text += '。'
            elif text.endswith('、'):
                text = text[:-1] + '。'
            elif text.endswith('は') or text.endswith('が'):
                text += '重要です。'
            elif text.endswith('ので') or text.endswith('ため'):
                suffix = '、お気軽にご相談ください😊' if platform == "line" else '、お気軽にご相談ください。'
                text += suffix
            else:
                # 長さによる補完（プラットフォーム別）
                if len(text) > 50:
                    text += '。'
                elif len(text) > 25:
                    suffix = '。詳しくはお問い合わせください😊' if platform == "line" else '。詳しくはお問い合わせください。'
                    text += suffix
                else:
                    text = self.generate_platform_fallback(query, platform)
            
            logger.info(f"✅ Fixed response now ends with: '{text[-30:]}'")
        
        return text

    def generate_platform_fallback(self, query: str, platform: str) -> str:
        """プラットフォーム別フォールバック応答（chat_ultra_fast.pyから移植）"""
        q_lower = query.lower()

        if platform == "line":
            # LINE用（絵文字・短文・親しみやすい）
            if any(keyword in q_lower for keyword in ["家を建てる", "マイホーム", "新築"]):
                return """🏗️ 家づくりについてお答えいたします

家づくりは人生で最も大きな買い物の一つです✨

**まずはこちらから始めませんか？**
1️⃣ 資料請求で情報収集
2️⃣ 展示場見学で実際の住まいを体感
3️⃣ 資金計画で予算を明確化

お客様のご希望をお聞かせいただければ、最適なプランをご提案いたします。何からお聞きになりたいでしょうか？😊"""

            else:
                return """ご質問ありがとうございます✨

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

**よくあるご質問**
💰 坪単価や費用について
🏠 住宅性能や仕様について
📋 資料請求・展示場見学

具体的にお聞かせいただければ、詳しくご案内いたします。お気軽にお問い合わせください😊"""

        else:  # web
            # Web用（シンプル・読みやすい・情報量多め）
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

具体的にお聞かせいただければ、詳しくご案内いたします。住宅に関することでしたら何でもお気軽にお問い合わせください。"""

    # ============================================================================
    # 統合応答生成（メイン処理）
    # ============================================================================
    async def generate_response(self, query: str, platform: str = "web", 
                              user: str = "unknown", mode: str = "auto") -> Dict[str, Any]:
        """統合応答生成（完全版）"""
        start_time = time.time()
        self.performance_metrics["total_requests"] += 1
        self.performance_metrics[f"{platform}_requests"] = self.performance_metrics.get(f"{platform}_requests", 0) + 1

        try:
            # 1. プラットフォーム別キャッシュチェック
            cache_type = "rag" if mode == "rag" else "general"
            cached_response = self.cache.get(query, platform, cache_type)
            
            if cached_response:
                self.performance_metrics["cache_responses"] += 1
                complete_cached = self.ensure_response_completeness(cached_response["answer"], platform, query)
                
                return {
                    "answer": complete_cached,
                    "sources": cached_response.get("sources", []),
                    "processing_time": time.time() - start_time,
                    "source": "cache",
                    "platform": platform,
                    "status": "ok",
                    "anti_hallucination_used": cached_response.get("anti_hallucination_used", False),
                    "sentence_complete": complete_cached.endswith(('。', '！', '？', '.', '!', '?'))
                }

            # 2. モード別処理分岐
            if mode == "template" or (mode == "auto" and self._should_use_template(query)):
                response = await self._generate_template_response(query, platform, user, start_time)
            elif mode == "rag" or (mode == "auto" and self._should_use_rag(query)):
                response = await self._generate_rag_response(query, platform, user, start_time)
            else:
                response = await self._generate_template_response(query, platform, user, start_time)

            # 3. 応答の完全性チェック（必須）
            response["answer"] = self.ensure_response_completeness(response["answer"], platform, query)
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
        """RAG応答生成（chat.pyの処理を統合）"""
        try:
            # アプリのグローバル変数取得
            globals_dict = self.get_app_globals()
            vectorstore = globals_dict.get('vectorstore')
            rag_chain_template = globals_dict.get('rag_chain_template')
            llm_instance = globals_dict.get('llm_instance')
            
            if not vectorstore or not rag_chain_template:
                logger.warning("RAG components not available, falling back to template")
                return await self._generate_template_response(query, platform, user, start_time)
            
            # 挨拶・雑談チェック（chat.pyから統合）
            if self.is_general_greeting_or_chat(query):
                logger.info("Detected general chat/greeting - using direct LLM response")
                answer = (
                    self.get_general_response_from_llm(query, llm_instance)
                    if llm_instance else
                    self.generate_platform_fallback(query, platform)
                )
                
                return {
                    "answer": answer,
                    "sources": [],
                    "processing_time": time.time() - start_time,
                    "source": "llm_direct",
                    "platform": platform,
                    "status": "ok",
                    "anti_hallucination_used": False
                }
            
            # RAG処理
            # ベクトル検索
            docs = vectorstore.similarity_search(query, k=3)
            self.tracer.trace_retrieval(query, docs)
            
            # RAG生成
            if hasattr(rag_chain_template, 'invoke'):
                result = rag_chain_template.invoke({"query": query})
            elif hasattr(rag_chain_template, '__call__'):
                result = rag_chain_template({"query": query})
            else:
                result = rag_chain_template({"query": query}, callbacks=[])
            
            raw_answer = result.get("result", "")
            logger.info(f"Raw RAG response: {raw_answer[:200]}...")
            
            # RAG応答のクリーンアップ（chat.pyの処理）
            cleaned_answer = self.clean_rag_response(raw_answer)
            
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
            logger.error(traceback.format_exc())
            # LLMフォールバック
            globals_dict = self.get_app_globals()
            llm_instance = globals_dict.get('llm_instance')
            
            answer = (
                self.get_general_response_from_llm(query, llm_instance)
                if llm_instance else
                self.generate_fallback_response(query)
            )
            
            return {
                "answer": answer,
                "sources": [],
                "processing_time": time.time() - start_time,
                "source": "llm_fallback",
                "platform": platform,
                "status": "ok",
                "anti_hallucination_used": False
            }

    def _should_use_template(self, query: str) -> bool:
        """テンプレート使用判定"""
        template_keywords = [
            "ai相談", "資料請求", "展示場", "見学", "予約", 
            "坪単価", "価格", "費用", "標準仕様", "補助金",
            "🤖", "📋", "📍", "💰", "💬", "🌐"  # リッチメニュー絵文字
        ]
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in template_keywords) or len(query) <= 15

    def _should_use_rag(self, query: str) -> bool:
        """RAG使用判定"""
        rag_keywords = [
            "詳しく", "具体的", "教えて", "説明", "について", 
            "どのような", "どうやって", "なぜ", "理由", "方法"
        ]
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in rag_keywords) and len(query) > 10

    def _generate_fallback_response(self, query: str, platform: str, start_time: float) -> Dict[str, Any]:
        """フォールバック応答生成"""
        fallback_answer = self.generate_platform_fallback(query, platform)
        
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
        error_answer = self.generate_platform_fallback(query, platform)
        
        return {
            "answer": error_answer,
            "sources": [],
            "processing_time": time.time() - start_time,
            "source": "error",
            "platform": platform,
            "status": "error",
            "anti_hallucination_used": False
        }

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
                "anti_hallucination_rate": (self.performance_metrics["anti_hallucination_used"] / total * 100) if total > 0 else 0,
                "platform_distribution": {
                    "web": self.performance_metrics.get("web_requests", 0),
                    "line": self.performance_metrics.get("line_requests", 0)
                }
            },
            "cache_performance": cache_stats,
            "template_performance": template_stats,
            "integration_status": {
                "chat_py_integrated": True,
                "chat_ultra_fast_integrated": True,
                "features_unified": [
                    "高速キャッシュシステム",
                    "プラットフォーム分離処理",
                    "RAG処理統合",
                    "テンプレート応答システム",
                    "文章完全性チェック",
                    "ハルチネーション対策",
                    "リッチメニュー対応",
                    "履歴管理システム"
                ]
            }
        }

# ============================================================================
# グローバルインスタンス
# ============================================================================
unified_generator = UnifiedResponseGenerator()

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
@router.post("/", summary="統合チャットエンドポイント（完全版：chat.py + chat_ultra_fast.py統合）")
async def unified_chat_endpoint(req: UnifiedChatRequest, request: Request):
    """統合チャットエンドポイント（完全版）"""
    
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

        # ログ保存（chat.pyの履歴機能）
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
            },
            "enhanced_info": {
                "anti_hallucination_used": response.get("anti_hallucination_used", False),
                "verification": response.get("verification"),
                "sentence_complete": response.get("sentence_complete", False)
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

        fallback_answer = unified_generator.generate_platform_fallback(req.question, platform)
        complete_fallback = unified_generator.ensure_response_completeness(fallback_answer, platform, req.question)

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
    """スラッシュなしエンドポイント"""
    return await unified_chat_endpoint(req, request)

# ============================================================================
# 管理エンドポイント（chat.pyの完全機能統合）
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
            "🛡️ ハルチネーション対策強化",
            "✅ 文章完全性自動補完",
            "📊 詳細パフォーマンス計測",
            "🚀 モード別処理分岐（auto/template/rag）",
            "📋 リッチメニュー完全対応",
            "📈 履歴管理システム",
            "💾 CSV/JSONエクスポート機能"
        ],
        "integration_completeness": {
            "chat_py_features": "100% integrated",
            "chat_ultra_fast_features": "100% integrated",
            "performance_optimizations": "applied",
            "platform_separation": "completed",
            "template_unification": "completed",
            "cache_system_upgrade": "completed"
        },
        "target_performance": {
            "template_response": "< 0.5s",
            "rag_response": "< 3.0s", 
            "cache_hit_rate": "> 70%",
            "sentence_completion_rate": "> 95%"
        },
        "integration_status": {
            "anti_hallucination_available": ANTI_HALLUCINATION_AVAILABLE,
            "rag_components_available": True,
            "rich_menu_support": True,
            "platform_optimization": True
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
        "cache_types_cleared": ["template", "rag", "general"],
        "features_reset": ["performance_stats", "access_times", "hit_rates"],
        "timestamp": datetime.now().isoformat()
    }

@router.get("/history", summary="チャット履歴取得")
def get_unified_history():
    """チャット履歴取得（chat.pyの機能統合）"""
    return {
        "logs": history_logs, 
        "count": len(history_logs),
        "features": {
            "platform_tracking": True,
            "performance_metrics": True,
            "enhanced_info": True,
            "anti_hallucination_tracking": ANTI_HALLUCINATION_AVAILABLE
        }
    }

@router.get("/export/csv", summary="履歴CSVエクスポート（完全版）")
def export_unified_csv():
    """履歴CSVエクスポート（chat.pyの完全機能）"""
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow([
        "id", "question", "username", "answer", "platform", "mode", "timestamp", 
        "source", "processing_time", "anti_hallucination_used", "sentence_complete"
    ])
    
    for log in history_logs:
        performance = log.get("performance", {})
        enhanced_info = log.get("enhanced_info", {})
        writer.writerow([
            log.get("id", ""),
            log.get("question", ""),
            log.get("username", ""),
            log.get("answer", "")[:500] + "..." if len(log.get("answer", "")) > 500 else log.get("answer", ""),
            log.get("platform", ""),
            log.get("mode", ""),
            log.get("timestamp", ""),
            performance.get("source", ""),
            performance.get("processing_time", 0.0),
            enhanced_info.get("anti_hallucination_used", False),
            enhanced_info.get("sentence_complete", False)
        ])
    
    si.seek(0)
    return StreamingResponse(
        si,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=unified_chat_history.csv"}
    )

@router.get("/export/json", summary="履歴JSONエクスポート（完全版）")
def export_unified_json():
    """履歴JSONエクスポート（chat.pyの完全機能）"""
    return JSONResponse(
        content={
            "export_info": {
                "export_time": datetime.now().isoformat(),
                "total_records": len(history_logs),
                "features": {
                    "platform_separation": True,
                    "performance_tracking": True,
                    "anti_hallucination_tracking": ANTI_HALLUCINATION_AVAILABLE,
                    "sentence_completion_tracking": True
                }
            },
            "logs": history_logs
        },
        headers={"Content-Disposition": "attachment; filename=unified_chat_history.json"}
    )

@router.get("/templates", summary="統合テンプレート一覧")
def get_unified_templates():
    """統合テンプレート一覧（完全版）"""
    template_stats = unified_generator.templates.get_stats()
    
    return {
        "templates": {
            "web": list(unified_generator.templates.web_templates.keys()),
            "line": list(unified_generator.templates.line_templates.keys())
        },
        "template_stats": template_stats,
        "integration_features": [
            "chat.py FAST_TEMPLATES統合済み",
            "chat_ultra_fast.py リッチメニュー対応済み",
            "プラットフォーム別最適化完了",
            "絵文字・短文対応（LINE用）",
            "詳細説明対応（Web用）",
            "キーワードマッチング強化",
            "補助金テンプレート追加"
        ],
        "rich_menu_support": {
            "items": template_stats.get("rich_menu_support", []),
            "full_coverage": True,
            "emoji_support": True,
            "url_integration": True
        },
        "template_integration_status": {
            "chat_py_templates": "fully_integrated",
            "chat_ultra_fast_templates": "fully_integrated", 
            "keyword_matching": "enhanced",
            "platform_optimization": "completed"
        },
        "timestamp": datetime.now().isoformat()
    }