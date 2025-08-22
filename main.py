# main.py - 超高速LINE Bot統合版

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

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI アプリケーションインスタンス
app = FastAPI(
    title="RAG API - Ultra Fast Edition",
    description="AI Chat API with Ultra Fast Startup & LINE Bot",
    version="2.0.0"
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# グローバル変数でRAGコンポーネントを管理
vectorstore = None
rag_chain_template = None
llm_instance = None
initialization_lock = asyncio.Lock()
is_initialized = False
initialization_in_progress = False

# 起動時刻を記録
startup_time = time.time()

# RAG初期化を無効化するフラグ（Cloud Run起動高速化）
DISABLE_RAG_INIT = os.getenv("DISABLE_RAG_INIT", "false").lower() == "true"

# 超軽量ヘルスチェック（RAG初期化を一切待たない）
@app.get("/healthz")
async def health_check():
    """超軽量ヘルスチェック（Cloud Run Startup Probe対応）"""
    uptime = time.time() - startup_time
    
    # 起動から10秒以内なら問答無用でOK（スタートアップ対策）
    if uptime < 10:
        return {
            "status": "healthy",
            "uptime": uptime,
            "timestamp": datetime.now().isoformat(),
            "message": "Application is ready for traffic",
            "startup_mode": "ultra_fast_boot"
        }
    
    # 基本的なアプリケーション健全性チェック（RAG無関係）
    return {
        "status": "healthy",
        "uptime": uptime,
        "timestamp": datetime.now().isoformat(),
        "rag_initialized": is_initialized,
        "rag_initialization_in_progress": initialization_in_progress,
        "service": "rag-api-ultra-fast",
        "version": "2.0.0",
        "fast_startup": True,
        "line_bot_configured": check_line_bot_config(),
        "ultra_fast_enabled": True
    }

def check_line_bot_config():
    """LINE Bot 設定チェック"""
    try:
        token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
        secret = os.getenv("LINE_CHANNEL_SECRET")
        return bool(token and secret)
    except:
        return False

@app.get("/")
async def root():
    """ルートエンドポイント（超軽量）"""
    return {
        "message": "RAG API Ultra Fast Edition is running",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
        "rag_status": "initialized" if is_initialized else "lazy_loading",
        "uptime": time.time() - startup_time,
        "ultra_fast_startup": DISABLE_RAG_INIT,
        "line_bot_status": "ultra_fast_configured" if check_line_bot_config() else "not_configured",
        "features": [
            "Ultra Fast Startup",
            "Template-based Responses", 
            "Smart Caching",
            "LINE Bot Ultra Fast",
            "Lazy RAG Loading"
        ]
    }

# ==============================================================================
# 超高速キャッシュシステム（Web版）
# ==============================================================================
class UltraFastCache:
    def __init__(self, max_size: int = 1000):
        self.cache: Dict[str, Dict] = {}
        self.access_times: Dict[str, float] = {}
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
   
    def _generate_key(self, query: str) -> str:
        normalized = query.lower().strip()[:200]
        return hashlib.md5(normalized.encode()).hexdigest()
   
    def get(self, query: str) -> Optional[Dict]:
        key = self._generate_key(query)
        if key in self.cache:
            self.access_times[key] = time.time()
            self.hits += 1
            logger.info(f"⚡ Web Cache HIT for: {query[:30]}...")
            return self.cache[key]
        self.misses += 1
        return None
   
    def set(self, query: str, response: Dict):
        if len(self.cache) >= self.max_size:
            self._evict_oldest()
       
        key = self._generate_key(query)
        self.cache[key] = {
            "answer": response.get("answer", ""),
            "timestamp": time.time(),
            "query_original": query[:100],
            "source": response.get("source", "unknown")
        }
        self.access_times[key] = time.time()
        logger.info(f"💾 Web Cache SET for: {query[:30]}...")
   
    def _evict_oldest(self):
        if self.access_times:
            oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
            del self.cache[oldest_key]
            del self.access_times[oldest_key]
   
    def get_stats(self) -> Dict:
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": hit_rate,
            "total_requests": total
        }

# ==============================================================================
# 超高速応答生成クラス（Web版）
# ==============================================================================
class UltraFastResponseGenerator:
    def __init__(self):
        self.cache = UltraFastCache(max_size=500)
        self.response_templates = self._load_unified_templates()
        self.performance_metrics = {"requests": 0, "cache_hits": 0, "template_hits": 0, "fallback_hits": 0}
       
    def _load_unified_templates(self) -> Dict[str, str]:
        """Web版とLINE版統一テンプレート"""
        return {
            "坪単価": """坪単価についてご案内いたします。

当社の坪単価目安：
・標準仕様：約70〜85万円/坪
・高性能仕様：約85〜100万円/坪

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

            "断熱性能": """断熱性能についてご案内いたします。

断熱等級：
・断熱等級4以上（ZEH基準対応）
・UA値：0.6以下（地域区分6）
・C値：1.0以下（気密性能）

使用断熱材：
・外壁：高性能グラスウール
・屋根：吹付断熱材
・基礎：押出法ポリスチレンフォーム

快適性：
・夏涼しく、冬暖かい
・光熱費の削減効果
・結露抑制

詳しくは展示場でご体感いただけます。""",

            "耐震性能": """耐震性能についてご案内いたします。

耐震等級：
・耐震等級3（最高等級）を標準採用
・建築基準法の1.5倍の耐震強度
・許容応力度計算による構造計算

構造材：
・構造用集成材使用
・金物工法による強固な接合
・ベタ基礎による堅固な基礎

保証：
・構造躯体20年保証
・地盤保証20年
・瑕疵担保責任保険対応

安心・安全な住まいをお約束いたします。""",

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

3営業日以内にお送いいたします。""",

            "見学予約": """展示場見学を承ります。

以下をお聞かせください：
・ご希望日時（第1・第2希望）
・お名前・お電話番号
・参加人数（大人・お子様）
・ご質問・ご要望

見学時間：約90分
展示場：最新の住宅仕様をご確認

スタッフ一同、心よりお待ちしております。""",

            "AI相談": """AI住まい相談へようこそ！

住まいづくりに関するご質問をお気軽にどうぞ。

よくあるご質問：
・坪単価について
・標準仕様について
・断熱性能について
・耐震性能について
・資料請求について
・展示場見学について

何でもお聞きください。""",

            "資金計画": """資金計画についてサポートいたします。

ご相談内容：
・住宅ローンの種類・金利比較
・月々の返済計画
・頭金・諸費用の計算
・住宅ローン控除について

お聞かせください：
・ご年収・自己資金
・ご希望借入額・返済期間
・家族構成・将来計画

最適なプランをご提案いたします。""",
        }
   
    async def generate_ultra_fast_response(self, query: str, user: str) -> Dict[str, Any]:
        """超高速レスポンス生成（Web版）"""
        start_time = time.time()
        self.performance_metrics["requests"] += 1
        
        try:
            # 1. キャッシュチェック（最優先）
            cached_response = self.cache.get(query)
            if cached_response:
                self.performance_metrics["cache_hits"] += 1
                return {
                    "answer": cached_response["answer"],
                    "processing_time": time.time() - start_time,
                    "source": "cache",
                    "status": "ok"
                }
            
            # 2. テンプレート即座マッチング
            template_response = self._match_unified_template(query)
            if template_response:
                self.performance_metrics["template_hits"] += 1
                result = {
                    "answer": template_response,
                    "processing_time": time.time() - start_time,
                    "source": "template",
                    "status": "ok"
                }
                self.cache.set(query, result)
                return result
            
            # 3. 統一フォールバック
            self.performance_metrics["fallback_hits"] += 1
            fallback_response = self._generate_unified_fallback(query)
            result = {
                "answer": fallback_response,
                "processing_time": time.time() - start_time,
                "source": "fallback",
                "status": "ok"
            }
            self.cache.set(query, result)
            return result
            
        except Exception as e:
            logger.error(f"Ultra fast response generation error: {e}")
            return {
                "answer": self._generate_unified_fallback(query),
                "processing_time": time.time() - start_time,
                "source": "error",
                "status": "error"
            }
   
    def _match_unified_template(self, query: str) -> Optional[str]:
        """統一テンプレートマッチング（強化版）"""
        query_lower = query.lower()
        
        # より包括的なキーワードマッピング
        keyword_mapping = {
            "坪単価": ["坪単価", "坪たんか", "価格", "費用", "コスト", "いくら", "金額", "料金", "建築費"],
            "標準仕様": ["標準仕様", "仕様", "設備", "標準", "基本", "スタンダード", "何が付く", "装備"],
            "断熱性能": ["断熱", "断熱性能", "省エネ", "温度", "暖房", "冷房", "光熱費", "ua値", "c値"],
            "耐震性能": ["耐震", "地震", "耐震性能", "耐震等級", "安全", "強度", "構造", "震災"],
            "資料請求": ["資料", "パンフレット", "カタログ", "資料請求", "パンフ", "送って", "郵送"],
            "見学予約": ["見学", "展示場", "予約", "モデルハウス", "見に行く", "見たい", "体験"],
            "AI相談": ["ai相談", "相談", "質問", "聞きたい", "教えて", "知りたい"],
            "資金計画": ["資金計画", "資金", "ローン", "住宅ローン", "お金", "支払い", "返済"],
        }
        
        for template_key, keywords in keyword_mapping.items():
            if any(keyword in query_lower for keyword in keywords):
                logger.info(f"🎯 Web Template match: {template_key}")
                return self.response_templates.get(template_key)
        
        return None
   
    def _generate_unified_fallback(self, query: str) -> str:
        """統一フォールバック応答"""
        q_lower = query.lower()
        
        if any(word in q_lower for word in ["家を建てる", "マイホーム", "新築", "建て方"]):
            return """家づくりについてお答えいたします。

家づくりは人生で最も大きな買い物の一つです。まずは情報収集から始めませんか？

・資料請求で詳しい情報を入手
・展示場見学で実際の住まいを体感
・資金計画で予算を明確化

お客様のご希望をお聞かせいただければ、最適なプランをご提案いたします。"""

        elif any(word in q_lower for word in ["補助金", "助成金", "支援", "制度"]):
            return """住宅購入時の補助金制度についてご案内します。

主な補助金制度：
・ZEH補助金：高性能住宅への補助
・こどもエコすまい支援事業：子育て世帯への支援
・住宅ローン減税：所得税の控除制度
・地域独自の補助金：自治体による支援

※制度は年度ごとに変更される可能性があります。最新情報については公式サイトでご確認いただくか、スタッフまでお問い合わせください。"""

        elif "坪単価" in q_lower or "価格" in q_lower:
            return "坪単価についてご案内いたします。お客様のご希望される仕様によって異なりますので、詳細なお見積りをご提供いたします。お気軽にお問い合わせください。"
        elif "仕様" in q_lower:
            return "住宅の仕様について詳しくご案内いたします。展示場でご確認いただくか、お気軽にお問い合わせください。"
        elif "性能" in q_lower:
            return "住宅性能について詳しくご説明いたします。耐震性能、断熱性能など、お客様のご要望に合わせてご案内いたします。"
        elif "資料" in q_lower:
            return "資料請求を承ります。お名前、ご住所、お電話番号をお教えいただければ、詳しい資料をお送りいたします。"
        else:
            return "お尋ねの内容について詳しくご案内いたします。住宅に関することでしたら何でもお気軽にお問い合わせください。"

# ==============================================================================
# リクエストモデル
# ==============================================================================
class ChatRequest(BaseModel):
    question: str
    username: str | None = None

# グローバルインスタンス
ultra_fast_generator = UltraFastResponseGenerator()

# ==============================================================================
# メインチャットエンドポイント（超高速版）
# ==============================================================================
@app.post("/chat")
@app.post("/chat/")
async def ultra_fast_chat_endpoint(req: ChatRequest, request: Request):
    """超高速チャットエンドポイント（完全RAG非依存）"""
    
    overall_start = time.time()
    logger.info(f"🚀 Ultra Fast Chat: {req.question[:50]}...")
    
    try:
        # 超高速応答生成（RAG完全スキップ）
        response = await ultra_fast_generator.generate_ultra_fast_response(
            req.question,
            req.username or "web-user-ultra"
        )
        
        total_time = time.time() - overall_start
        
        logger.info(f"✅ Ultra Fast Response: {total_time:.3f}s, "
                   f"source={response.get('source')}, "
                   f"length={len(response.get('answer', ''))}")
        
        return {
            "answer": response["answer"],
            "sources": [],  # 出典情報は非表示
            "status": response["status"],
            "performance": {
                "total_time": total_time,
                "processing_time": response.get("processing_time", 0),
                "source": response.get("source"),
                "rag_enabled": False,  # RAG完全無効
                "ultra_fast_startup": True,
                "template_based": response.get("source") == "template",
                "cache_hit": response.get("source") == "cache"
            }
        }
        
    except Exception as e:
        total_time = time.time() - overall_start
        error_id = str(uuid4())[:8]
        
        logger.error(f"❌ Ultra Fast Chat error [{error_id}]: {e}")
        
        fallback_answer = ultra_fast_generator._generate_unified_fallback(req.question if hasattr(req, 'question') else "")
        
        return JSONResponse(
            status_code=200,
            content={
                "answer": fallback_answer,
                "sources": [],
                "status": "fallback",
                "error_id": error_id,
                "performance": {
                    "total_time": total_time,
                    "ultra_fast_enabled": True,
                    "rag_enabled": False
                }
            }
        )

# ==============================================================================
# 超高速版専用エンドポイント
# ==============================================================================
@app.post("/chat-ultra-fast")
@app.post("/chat-ultra-fast/")
async def dedicated_ultra_fast_endpoint(req: ChatRequest, request: Request):
    """専用超高速エンドポイント（フォールバック用）"""
    return await ultra_fast_chat_endpoint(req, request)

# ==============================================================================
# アプリケーション起動時の処理（超高速版）
# ==============================================================================
@app.on_event("startup")
async def startup_event():
    """アプリケーション起動時の処理（超高速版）"""
    logger.info("🚀 Starting RAG API Ultra Fast Edition...")
    
    # 超高速LINE Bot ルーターの追加
    try:
        from api.routers.line_bot_ultra_fast import router as ultra_line_router
        app.include_router(ultra_line_router, prefix="/line", tags=["line-ultra-fast"])
        logger.info("✅ Ultra Fast LINE Bot router added with prefix /line")
        
        # LINE Bot 設定確認
        token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
        secret = os.getenv("LINE_CHANNEL_SECRET")
        
        if token and secret:
            logger.info("✅ Ultra Fast LINE Bot credentials found")
        else:
            logger.warning("⚠️ LINE Bot credentials not found")
            
    except Exception as e:
        logger.error(f"❌ Failed to add Ultra Fast LINE Bot router: {e}")
        logger.error(traceback.format_exc())
    
    # 通常のLINE Botルーター（フォールバック用）
    try:
        from api.routers.line_bot_fixed import router as line_router
        app.include_router(line_router, prefix="/line-fallback", tags=["line-fallback"])
        logger.info("✅ Fallback LINE Bot router added with prefix /line-fallback")
    except Exception as e:
        logger.warning(f"⚠️ Fallback LINE Bot router not added: {e}")
    
    # その他のルーター
    try:
        from api.routers.upload import router as upload_router
        app.include_router(upload_router, prefix="/upload", tags=["upload"])
        logger.info("✅ Upload router added")
    except Exception as e:
        logger.warning(f"⚠️ Upload router not added: {e}")
    
    # LINE プロキシルーター（オプション）
    try:
        from api.routers.line_proxy import router as proxy_router
        app.include_router(proxy_router, prefix="/line-proxy", tags=["line-proxy"])
        logger.info("✅ LINE Proxy router added")
    except Exception as e:
        logger.warning(f"⚠️ LINE Proxy router not added: {e}")
    
    # RAG初期化は完全にスキップ（超高速起動）
    if DISABLE_RAG_INIT:
        logger.info("🚫 RAG initialization completely disabled for ultra-fast startup")
        logger.info("💡 Template-based responses and caching will handle all queries")
    else:
        logger.info("🔄 RAG initialization available on-demand")
    
    logger.info("🎉 Ultra Fast Application startup completed successfully")
    logger.info(f"⚡ Startup time: {time.time() - startup_time:.2f} seconds")

# ==============================================================================
# システム状態・監視エンドポイント
# ==============================================================================
@app.get("/system-status")
async def get_system_status():
    """システム状態取得（超高速版）"""
    web_stats = ultra_fast_generator.cache.get_stats()
    perf_metrics = ultra_fast_generator.performance_metrics
    
    return {
        "rag_system": {
            "initialized": is_initialized,
            "initialization_in_progress": initialization_in_progress,
            "vectorstore_loaded": vectorstore is not None,
            "rag_chain_loaded": rag_chain_template is not None,
            "llm_loaded": llm_instance is not None,
        },
        "ultra_fast_system": {
            "enabled": True,
            "web_cache_stats": web_stats,
            "performance_metrics": perf_metrics,
            "template_count": len(ultra_fast_generator.response_templates),
        },
        "uptime": time.time() - startup_time,
        "ultra_fast_startup_enabled": DISABLE_RAG_INIT,
        "line_bot_configured": check_line_bot_config(),
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/performance-stats")
def get_performance_stats():
    """パフォーマンス統計（超高速版）"""
    web_cache_stats = ultra_fast_generator.cache.get_stats()
    web_perf_metrics = ultra_fast_generator.performance_metrics
    
    # 効率性計算
    total_requests = web_perf_metrics["requests"]
    fast_response_rate = 0
    if total_requests > 0:
        fast_responses = web_perf_metrics["cache_hits"] + web_perf_metrics["template_hits"]
        fast_response_rate = (fast_responses / total_requests) * 100
    
    return {
        "web_performance": {
            "cache_stats": web_cache_stats,
            "performance_metrics": web_perf_metrics,
            "fast_response_rate": fast_response_rate
        },
        "system_features": [
            "Ultra Fast Startup (< 10s)",
            "Template-based Instant Responses",
            "Smart Caching System",
            "LINE Bot Ultra Fast Processing",
            "Zero RAG Dependency for Speed",
            "Intelligent Fallback Responses"
        ],
        "performance_targets": {
            "startup_time": "< 10s",
            "template_response_time": "< 100ms",
            "cache_response_time": "< 50ms",
            "cache_hit_rate": "> 60%",
            "fast_response_rate": "> 90%"
        },
        "uptime": time.time() - startup_time,
        "ultra_fast_enabled": True,
        "rag_dependency": "None (for speed optimization)",
        "line_bot_status": "ultra_fast_configured" if check_line_bot_config() else "not_configured",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/ultra-debug")
async def ultra_debug_info():
    """超高速版デバッグ情報"""
    return {
        "system_info": {
            "version": "2.0.0",
            "startup_mode": "ultra_fast",
            "rag_disabled": DISABLE_RAG_INIT,
            "uptime": time.time() - startup_time,
        },
        "web_chat": {
            "endpoint": "/chat",
            "fallback_endpoint": "/chat-ultra-fast",
            "cache_enabled": True,
            "template_count": len(ultra_fast_generator.response_templates),
            "cache_stats": ultra_fast_generator.cache.get_stats(),
        },
        "line_bot": {
            "primary_endpoint": "/line/webhook",
            "fallback_endpoint": "/line-fallback/webhook",
            "credentials_configured": check_line_bot_config(),
            "ultra_fast_enabled": True,
        },
        "performance": {
            "target_response_time": "< 1000ms",
            "template_response_time": "< 100ms", 
            "cache_response_time": "< 50ms",
            "startup_target": "< 10s",
        },
        "recommendations": [
            "ウェブチャットは /chat エンドポイントを使用",
            "LINE Botは /line/webhook で超高速処理",
            "Cloud Run環境変数 DISABLE_RAG_INIT=true を設定済み",
            "テンプレート応答で90%以上のクエリをカバー"
        ],
        "timestamp": datetime.now().isoformat()
    }

# キャッシュクリアエンドポイント
@app.post("/clear-cache")
def clear_all_caches():
    """全キャッシュクリア"""
    old_web_stats = ultra_fast_generator.cache.get_stats()
    
    # Webキャッシュクリア
    ultra_fast_generator.cache = UltraFastCache(max_size=500)
    
    return {
        "status": "all_caches_cleared",
        "previous_web_stats": old_web_stats,
        "new_cache_size": 0,
        "ultra_fast_enabled": True,
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)