import logging
import os
import asyncio
import time
import hashlib
import re
from datetime import datetime
from typing import Dict, Any, Optional, List
import concurrent.futures
from uuid import uuid4
import traceback

from fastapi import APIRouter, Request
from pydantic import BaseModel
from fastapi.responses import JSONResponse

# 共通ユーティリティのインポート
from utils.web_search import should_use_web_search, is_richmenu_pressed
from utils.langsmith_tracer import RAGTracer

# ハルシネーション対策統合機能（デフォルト無効）
try:
    from integration.anti_hallucination_integration import should_skip_anti_hallucination
    ANTI_HALLUCINATION_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("✅ Anti-hallucination integration available (default OFF)")
except ImportError as e:
    ANTI_HALLUCINATION_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning(f"⚠️ Anti-hallucination integration not available: {e}")
    
    def should_skip_anti_hallucination(query: str) -> bool:
        return True  # デフォルトでスキップ

try:
    from langsmith import traceable
except ImportError:
    def traceable(name=None, **kwargs):
        def decorator(func):
            return func
        return decorator

router = APIRouter()
history_logs: List[Dict] = []

# 環境変数から設定を読み込み（デフォルトは高速化優先）
ENABLE_WEB_SEARCH = os.environ.get("ENABLE_WEB_SEARCH", "false").lower() == "true"
ENABLE_ANTI_HALLUCINATION = os.environ.get("ENABLE_ANTI_HALLUCINATION", "false").lower() == "true"
TEMPLATE_PRIORITY = os.environ.get("TEMPLATE_PRIORITY", "false").lower() == "true"
ENABLE_RAG_AVOIDANCE = os.environ.get("ENABLE_RAG_AVOIDANCE", "false").lower() == "true"
OPTIMIZED_SEARCH_K = int(os.environ.get("OPTIMIZED_SEARCH_K", "4"))
OPTIMIZED_RAG_TIMEOUT = float(os.environ.get("OPTIMIZED_RAG_TIMEOUT", "8"))
RERANK_TOPN = int(os.environ.get("RERANK_TOPN", "3"))

# ============================================================================
# 🚀 高速テンプレートシステム（リッチメニュー対応）
# ============================================================================
class FastTemplateSystem:
    """高速テンプレートシステム（リッチメニュー固定応答対応）"""
    
    def __init__(self):
        self.templates = self._load_templates()
        self.richmenu_templates = self._load_richmenu_templates()
        
    def _load_richmenu_templates(self) -> Dict[str, str]:
        """リッチメニュー固定応答テンプレート"""
        return {
            "🤖 AI相談": """🤖 AI住まい相談を開始します！
キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 **例えば**
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？

何でもお聞きください😊

※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",

            "🌐 AI住まいサイト": """🌐 AI住まいサイトのご案内
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

            "📋 資料請求": """📋ありがとうございます！こちらからご覧いただけます。

〔資料タイトル〕（PDF）：〔URL〕

よろしければ簡単アンケート（任意）：
・ご計画時期：今すぐ / 3–6か月 / 1年以内 / 未定
・連絡方法（任意）：このLINE / メール / 連絡不要

※必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",

            "📍 展示場来場": """📍 展示場のご来場予約につきましては、下記URLより必要事項のご入力をお願い申し上げます。

【https://preview.studio.site/live/EjOQljz1WJ/reservation 】

スタッフ一同、心よりお待ちしております！""",

            "💰 資金計画": """💬 AI資金診断のご案内
本診断は匿名でご利用いただけます。ご回答内容は保存いたしません。算出される金額は試算（概算）であり、目安としてご確認ください。

お手数ですが、以下の5点をご入力ください。
・年収（概算可）
・毎月のご希望返済額
・住宅ローンのご希望借入期間
・ご家族構成（例：大人2名・お子さま1名）
・その他の大きなご負担（例：自動車ローン 等）

未入力の項目があっても進められます。ご入力後、概算結果をご提示いたします。""",

            "💬 チャット相談": """💬 スタッフとのご相談

【対応時間】
営業時間：9:00-18:00

📱 ご相談方法：
・このLINEでの直接相談
・お電話での相談
・展示場での対面相談

営業時間内でしたら迅速にお返事します。
お気軽にお声かけください！"""
        }
    
    def _load_templates(self) -> Dict[str, str]:
        """Web用基本テンプレート（簡潔版）"""
        return {
            "坪単価": "坪単価は約70〜85万円（標準仕様）です。仕様により変動いたしますので、詳細なお見積りをご提供いたします。",
            "価格": "建物本体価格は坪単価×延床面積が基本です。付帯工事費や諸費用を含めた総額をご提案いたします。",
            "標準仕様": "耐震等級3、長期優良住宅基準の高性能住宅です。詳しい仕様書は展示場でご確認いただけます。",
            "断熱": "断熱等級4以上、UA値0.6以下の高断熱仕様です。夏涼しく冬暖かい快適な住環境を実現します。",
            "耐震": "耐震等級3（最高等級）を標準採用。建築基準法の1.5倍の耐震強度で安心・安全な住まいです。"
        }
    
    def find_richmenu_template(self, query: str) -> Optional[str]:
        """リッチメニューテンプレート検索"""
        query_stripped = query.strip()
        
        # 完全一致チェック
        for key, template in self.richmenu_templates.items():
            if query_stripped == key or query_stripped == key.replace("🤖 ", "").replace("🌐 ", "").replace("📋 ", "").replace("📍 ", "").replace("💰 ", "").replace("💬 ", ""):
                logger.info(f"🎯 Richmenu template hit: {key}")
                return template
        
        # キーワードマッチング
        richmenu_keywords = {
            "AI相談": "🤖 AI相談",
            "AI住まいサイト": "🌐 AI住まいサイト",
            "資料請求": "📋 資料請求",
            "展示場来場": "📍 展示場来場",
            "展示場来場　予約": "📍 展示場来場",
            "資金計画": "💰 資金計画",
            "チャット相談": "💬 チャット相談"
        }
        
        for keyword, template_key in richmenu_keywords.items():
            if keyword in query_stripped:
                logger.info(f"🎯 Richmenu keyword match: {keyword}")
                return self.richmenu_templates[template_key]
        
        return None
    
    def find_template(self, query: str, platform: str) -> Optional[str]:
        """テンプレート検索（プラットフォーム別）"""
        # リッチメニューチェック（LINE優先）
        if platform == "line":
            richmenu_template = self.find_richmenu_template(query)
            if richmenu_template:
                return richmenu_template
        
        # 基本テンプレートチェック
        query_lower = query.lower().strip()
        for key, template in self.templates.items():
            if key in query_lower:
                return template
        
        return None

# ============================================================================
# 🚀 超高速キャッシュシステム
# ============================================================================
class UltraFastCache:
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.access_times: Dict[str, float] = {}
        self.hits = 0
        self.misses = 0
    
    def _generate_key(self, query: str, platform: str) -> str:
        """キー生成（正規化）"""
        normalized = query.lower().strip()
        normalized = re.sub(r'[？?！!。、\s]+', '', normalized)
        key_str = f"{platform}:{normalized[:50]}"
        return hashlib.md5(key_str.encode()).hexdigest()[:12]
    
    def get(self, query: str, platform: str) -> Optional[Dict[str, Any]]:
        """キャッシュ取得"""
        key = self._generate_key(query, platform)
        
        if key in self.cache:
            self.access_times[key] = time.time()
            self.hits += 1
            return self.cache[key]
        
        self.misses += 1
        return None
    
    def set(self, query: str, response: Dict[str, Any], platform: str) -> None:
        """キャッシュ保存"""
        if len(self.cache) >= self.max_size:
            # LRU削除
            oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
            del self.cache[oldest_key]
            del self.access_times[oldest_key]
        
        key = self._generate_key(query, platform)
        self.cache[key] = response
        self.access_times[key] = time.time()

# ============================================================================
# 🚀 統合応答生成システム（最適化版）
# ============================================================================
class OptimizedResponseGenerator:
    def __init__(self):
        self.cache = UltraFastCache()
        self.templates = FastTemplateSystem()
        self.tracer = RAGTracer()
        
        self.stats = {
            "total_requests": 0,
            "template_responses": 0,
            "rag_responses": 0,
            "cache_responses": 0,
            "richmenu_responses": 0,
            "errors": 0
        }
    
    def _should_use_rag(self, query: str, platform: str) -> bool:
        """RAG使用判定（RAG優先）"""
        # 環境変数でRAG回避が有効な場合
        if ENABLE_RAG_AVOIDANCE:
            return False
        
        # リッチメニュー押下はRAG不要
        if is_richmenu_pressed(query):
            return False
        
        # テンプレート優先が無効（デフォルト）ならRAG使用
        if not TEMPLATE_PRIORITY:
            # 短すぎる質問以外はRAG使用
            return len(query) > 10
        
        # テンプレートが存在する場合はRAG不要
        if self.templates.find_template(query, platform):
            return False
        
        return True
    
    async def generate_response(self, query: str, platform: str = "web", 
                               user: str = "unknown", mode: str = "auto") -> Dict[str, Any]:
        """統合応答生成（高速化・RAG優先）"""
        start_time = time.time()
        self.stats["total_requests"] += 1
        
        try:
            # 1. リッチメニューチェック（最優先）
            if is_richmenu_pressed(query):
                template_response = self.templates.find_richmenu_template(query)
                if template_response:
                    self.stats["richmenu_responses"] += 1
                    return {
                        "answer": template_response,
                        "sources": [],
                        "processing_time": time.time() - start_time,
                        "source": "richmenu_template",
                        "platform": platform,
                        "status": "ok"
                    }
            
            # 2. キャッシュチェック
            cached = self.cache.get(query, platform)
            if cached:
                self.stats["cache_responses"] += 1
                return {
                    **cached,
                    "processing_time": time.time() - start_time,
                    "source": "cache"
                }
            
            # 3. RAG判定（優先）
            if mode == "rag" or (mode == "auto" and self._should_use_rag(query, platform)):
                rag_response = await self._generate_rag_response(query, platform, user, start_time)
                if rag_response["answer"]:
                    self.cache.set(query, rag_response, platform)
                    return rag_response
            
            # 4. テンプレート応答
            template = self.templates.find_template(query, platform)
            if template:
                self.stats["template_responses"] += 1
                response = {
                    "answer": template,
                    "sources": [],
                    "processing_time": time.time() - start_time,
                    "source": "template",
                    "platform": platform,
                    "status": "ok"
                }
                self.cache.set(query, response, platform)
                return response
            
            # 5. フォールバック
            return self._generate_fallback_response(query, platform, start_time)
            
        except Exception as e:
            logger.error(f"Response generation error: {e}")
            self.stats["errors"] += 1
            return self._generate_error_response(query, platform, start_time)
    
    async def _generate_rag_response(self, query: str, platform: str, user: str, start_time: float) -> Dict[str, Any]:
        """RAG応答生成（高速化）"""
        try:
            # RAGコンポーネント取得
            globals_dict = self._get_app_globals()
            vectorstore = globals_dict.get('vectorstore')
            rag_chain = globals_dict.get('rag_chain_template')
            
            if not vectorstore or not rag_chain:
                logger.warning("RAG components not available")
                return self._generate_fallback_response(query, platform, start_time)
            
            # RAG実行（タイムアウト付き）
            try:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(rag_chain.invoke, {"query": query})
                    result = future.result(timeout=OPTIMIZED_RAG_TIMEOUT)
                    
                    answer = result.get("result", "")
                    if not answer:
                        return self._generate_fallback_response(query, platform, start_time)
                    
                    self.stats["rag_responses"] += 1
                    
                    return {
                        "answer": answer,
                        "sources": [{"content": "社内データベース"}],
                        "processing_time": time.time() - start_time,
                        "source": "rag",
                        "platform": platform,
                        "status": "ok"
                    }
                    
            except concurrent.futures.TimeoutError:
                logger.warning(f"RAG timeout for query: {query}")
                return self._generate_fallback_response(query, platform, start_time)
                
        except Exception as e:
            logger.error(f"RAG generation error: {e}")
            return self._generate_fallback_response(query, platform, start_time)
    
    def _generate_fallback_response(self, query: str, platform: str, start_time: float) -> Dict[str, Any]:
        """フォールバック応答"""
        q_lower = query.lower()
        
        # キーワードベース応答
        if "坪単価" in q_lower or "価格" in q_lower:
            answer = "坪単価は約70〜85万円（標準仕様）です。詳細なお見積りをご提供いたします。"
        elif "仕様" in q_lower or "設備" in q_lower:
            answer = "耐震等級3の長期優良住宅基準です。詳しくは展示場でご確認ください。"
        elif "断熱" in q_lower or "性能" in q_lower:
            answer = "高断熱・高気密仕様で快適な住環境を実現します。"
        else:
            answer = "住まいづくりに関するご質問にお答えいたします。詳しくは展示場でご相談ください。"
        
        return {
            "answer": answer,
            "sources": [],
            "processing_time": time.time() - start_time,
            "source": "fallback",
            "platform": platform,
            "status": "ok"
        }
    
    def _generate_error_response(self, query: str, platform: str, start_time: float) -> Dict[str, Any]:
        """エラー応答"""
        return {
            "answer": "申し訳ございません。一時的なエラーが発生しました。もう一度お試しください。",
            "sources": [],
            "processing_time": time.time() - start_time,
            "source": "error",
            "platform": platform,
            "status": "error"
        }
    
    def _get_app_globals(self) -> Dict[str, Any]:
        """アプリのグローバル変数を取得"""
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
        """パフォーマンス統計"""
        total = self.stats["total_requests"]
        cache_hit_rate = (self.stats["cache_responses"] / total * 100) if total > 0 else 0
        
        return {
            "total_requests": total,
            "response_distribution": {
                "template": self.stats["template_responses"],
                "rag": self.stats["rag_responses"],
                "cache": self.stats["cache_responses"],
                "richmenu": self.stats["richmenu_responses"]
            },
            "cache_performance": {
                "hits": self.cache.hits,
                "misses": self.cache.misses,
                "hit_rate": cache_hit_rate
            },
            "errors": self.stats["errors"],
            "optimization_settings": {
                "web_search": ENABLE_WEB_SEARCH,
                "anti_hallucination": ENABLE_ANTI_HALLUCINATION,
                "template_priority": TEMPLATE_PRIORITY,
                "rag_avoidance": ENABLE_RAG_AVOIDANCE,
                "search_k": OPTIMIZED_SEARCH_K,
                "rag_timeout": OPTIMIZED_RAG_TIMEOUT,
                "rerank_topn": RERANK_TOPN
            }
        }

# グローバルインスタンス
unified_generator = OptimizedResponseGenerator()
optimized_generator = unified_generator  # 互換性維持

# リクエストモデル
class ChatRequest(BaseModel):
    question: str
    username: str | None = None
    platform: str | None = "web"
    mode: str | None = "auto"

# メインエンドポイント
@router.post("/", summary="統合チャットエンドポイント")
async def chat_endpoint(req: ChatRequest):
    """統合チャットエンドポイント（高速化・RAG優先）"""
    
    overall_start = time.time()
    platform = req.platform or "web"
    username = req.username or f"{platform}-user"
    mode = req.mode or "auto"
    
    logger.info(f"🌟 Chat ({platform}): {req.question[:50]}...")
    
    try:
        response = await unified_generator.generate_response(
            req.question, platform, username, mode
        )
        
        total_time = time.time() - overall_start
        
        logger.info(
            f"✅ Response: {total_time:.3f}s, "
            f"source={response.get('source')}, "
            f"length={len(response['answer'])}"
        )
        
        return {
            "answer": response["answer"],
            "sources": response.get("sources", []),
            "status": "ok",
            "performance": {
                "total_time": total_time,
                "source": response.get("source"),
                "platform": platform
            }
        }
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        logger.error(traceback.format_exc())
        
        return JSONResponse(
            status_code=200,
            content={
                "answer": "申し訳ございません。エラーが発生しました。",
                "sources": [],
                "status": "error",
                "performance": {
                    "total_time": time.time() - overall_start,
                    "platform": platform
                }
            }
        )

# 統計エンドポイント
@router.get("/stats", summary="パフォーマンス統計")
def get_stats():
    """パフォーマンス統計取得"""
    return unified_generator.get_performance_stats()

@router.post("/clear-cache", summary="キャッシュクリア")
def clear_cache():
    """キャッシュクリア"""
    old_size = len(unified_generator.cache.cache)
    unified_generator.cache = UltraFastCache()
    
    return {
        "status": "cache_cleared",
        "cleared_entries": old_size,
        "timestamp": datetime.now().isoformat()
    }
