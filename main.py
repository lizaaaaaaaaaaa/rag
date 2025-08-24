# main.py - 超高速版（RAG完全無効化・プラットフォーム分離対応）

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
    title="RAG API - Ultra Fast Edition (Platform Separated)",
    description="AI Chat API with Ultra Fast Startup & Separated Web/LINE Bot",
    version="2.1.0"
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# グローバル変数（RAGコンポーネント完全無効化）
vectorstore = None
rag_chain_template = None
llm_instance = None
initialization_lock = asyncio.Lock()
is_initialized = False
initialization_in_progress = False

# 起動時刻を記録
startup_time = time.time()

# RAG初期化を完全無効化（Cloud Run起動超高速化）
DISABLE_RAG_INIT = True  # 強制的にTrue
FORCE_TEMPLATE_MODE = True  # テンプレートモード強制有効

# ==============================================================================
# プラットフォーム分離対応キャッシュシステム
# ==============================================================================
class PlatformSeparatedCache:
    def __init__(self, max_size: int = 1000):
        # プラットフォーム別キャッシュ
        self.web_cache: Dict[str, Dict] = {}
        self.line_cache: Dict[str, Dict] = {}
        self.access_times: Dict[str, float] = {}
        self.max_size = max_size
        self.stats = {"web_hits": 0, "web_misses": 0, "line_hits": 0, "line_misses": 0}
   
    def _generate_key(self, query: str, platform: str) -> str:
        normalized = f"{platform}:{query.lower().strip()[:200]}"
        return hashlib.md5(normalized.encode()).hexdigest()
   
    def get(self, query: str, platform: str = "web") -> Optional[Dict]:
        key = self._generate_key(query, platform)
        cache = self.web_cache if platform == "web" else self.line_cache
        
        if key in cache:
            self.access_times[key] = time.time()
            self.stats[f"{platform}_hits"] += 1
            logger.info(f"⚡ {platform.upper()} Cache HIT for: {query[:30]}...")
            return cache[key]
        
        self.stats[f"{platform}_misses"] += 1
        return None
   
    def set(self, query: str, response: Dict, platform: str = "web"):
        if len(self.web_cache) + len(self.line_cache) >= self.max_size:
            self._evict_oldest()
       
        key = self._generate_key(query, platform)
        cache = self.web_cache if platform == "web" else self.line_cache
        
        cache[key] = {
            "answer": response.get("answer", ""),
            "timestamp": time.time(),
            "query_original": query[:100],
            "source": response.get("source", "unknown"),
            "platform": platform
        }
        self.access_times[key] = time.time()
        logger.info(f"💾 {platform.upper()} Cache SET for: {query[:30]}...")
   
    def _evict_oldest(self):
        if self.access_times:
            oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
            # どちらのキャッシュにあるかチェック
            if oldest_key in self.web_cache:
                del self.web_cache[oldest_key]
            elif oldest_key in self.line_cache:
                del self.line_cache[oldest_key]
            del self.access_times[oldest_key]
   
    def get_stats(self) -> Dict:
        total_web = self.stats["web_hits"] + self.stats["web_misses"]
        total_line = self.stats["line_hits"] + self.stats["line_misses"]
        
        return {
            "web_cache_size": len(self.web_cache),
            "line_cache_size": len(self.line_cache),
            "total_size": len(self.web_cache) + len(self.line_cache),
            "max_size": self.max_size,
            "web_stats": {
                "hits": self.stats["web_hits"],
                "misses": self.stats["web_misses"],
                "hit_rate": self.stats["web_hits"] / total_web if total_web > 0 else 0
            },
            "line_stats": {
                "hits": self.stats["line_hits"],
                "misses": self.stats["line_misses"],
                "hit_rate": self.stats["line_hits"] / total_line if total_line > 0 else 0
            }
        }

# ==============================================================================
# プラットフォーム分離応答生成クラス
# ==============================================================================
class PlatformSeparatedResponseGenerator:
    def __init__(self):
        self.cache = PlatformSeparatedCache(max_size=500)
        self.web_templates = self._load_web_templates()
        self.line_templates = self._load_line_templates()
        self.performance_metrics = {"web_requests": 0, "line_requests": 0, "template_hits": 0, "fallback_hits": 0}
       
    def _load_web_templates(self) -> Dict[str, str]:
        """Web専用テンプレート"""
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

            "AI相談": """🤖 AI住まい相談へようこそ！

住まいづくりに関するご質問をお気軽にどうぞ！

よくあるご質問：
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？

何でもお聞きください😊""",

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

3営業日以内にお送りいたします。お気軽にお問い合わせください。"""
        }
   
    def _load_line_templates(self) -> Dict[str, str]:
        """LINE専用テンプレート"""
        return {
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
詳細なお見積りをご希望でしたら、お気軽にお問い合わせください。""",

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

より詳しい仕様書をご希望の場合は、資料請求または展示場見学をお申し込みください。""",

            "AI相談": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 **例えば：**
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？

何でもお聞きください😊""",

            "資料請求": """📋 資料請求を承ります

**必要情報をお送りください**
1️⃣ お名前（フルネーム）
2️⃣ ご住所（〒郵便番号から）
3️⃣ お電話番号
4️⃣ ご希望資料の種類

**お送りする資料**
・会社案内・施工事例集
・間取りプラン集
・価格・仕様資料
・住宅ローンガイド

3営業日以内にお送りいたします！"""
        }
   
    async def generate_platform_response(self, query: str, platform: str = "web", user: str = "unknown") -> Dict[str, Any]:
        """プラットフォーム分離応答生成"""
        start_time = time.time()
        self.performance_metrics[f"{platform}_requests"] += 1
        
        try:
            # 1. プラットフォーム別キャッシュチェック
            cached_response = self.cache.get(query, platform)
            if cached_response:
                return {
                    "answer": cached_response["answer"],
                    "processing_time": time.time() - start_time,
                    "source": "cache",
                    "platform": platform,
                    "status": "ok"
                }
            
            # 2. プラットフォーム別テンプレートマッチング
            templates = self.web_templates if platform == "web" else self.line_templates
            template_response = self._match_template(query, templates)
            
            if template_response:
                self.performance_metrics["template_hits"] += 1
                result = {
                    "answer": template_response,
                    "processing_time": time.time() - start_time,
                    "source": "template",
                    "platform": platform,
                    "status": "ok"
                }
                self.cache.set(query, result, platform)
                return result
            
            # 3. プラットフォーム別フォールバック
            self.performance_metrics["fallback_hits"] += 1
            fallback_response = self._generate_platform_fallback(query, platform)
            result = {
                "answer": fallback_response,
                "processing_time": time.time() - start_time,
                "source": "fallback",
                "platform": platform,
                "status": "ok"
            }
            self.cache.set(query, result, platform)
            return result
            
        except Exception as e:
            logger.error(f"Platform response generation error: {e}")
            return {
                "answer": self._generate_platform_fallback(query, platform),
                "processing_time": time.time() - start_time,
                "source": "error",
                "platform": platform,
                "status": "error"
            }
   
    def _match_template(self, query: str, templates: Dict[str, str]) -> Optional[str]:
        """テンプレートマッチング"""
        query_lower = query.lower()
        
        keyword_mapping = {
            "坪単価": ["坪単価", "価格", "費用", "コスト", "いくら", "金額", "料金"],
            "標準仕様": ["標準仕様", "仕様", "設備", "標準", "基本", "何が付く"],
            "断熱性能": ["断熱", "省エネ", "温度", "暖房", "冷房", "光熱費"],
            "耐震性能": ["耐震", "地震", "安全", "強度", "構造"],
            "資料請求": ["資料", "パンフレット", "カタログ", "送って"],
            "AI相談": ["ai相談", "相談", "質問", "聞きたい", "教えて"],
        }
        
        for template_key, keywords in keyword_mapping.items():
            if any(keyword in query_lower for keyword in keywords):
                logger.info(f"🎯 Template match: {template_key}")
                return templates.get(template_key)
        
        return None
   
    def _generate_platform_fallback(self, query: str, platform: str) -> str:
        """プラットフォーム別フォールバック"""
        q_lower = query.lower()
        
        if platform == "line":
            if "坪単価" in q_lower or "価格" in q_lower:
                return "💰 坪単価についてご案内いたします。お客様のご希望される仕様によって異なりますので、詳細なお見積りをご提供いたします。お気軽にお問い合わせください。"
            elif "仕様" in q_lower:
                return "🏗️ 住宅の仕様について詳しくご案内いたします。展示場でご確認いただくか、お気軽にお問い合わせください。"
            else:
                return "ご質問ありがとうございます✨\n\n住まいづくりについて、どのようなことをお知りになりたいでしょうか？\n\nお気軽にお聞かせください😊"
        else:  # web
            if "坪単価" in q_lower or "価格" in q_lower:
                return "坪単価についてご案内いたします。お客様のご希望される仕様によって異なりますので、詳細なお見積りをご提供いたします。お気軽にお問い合わせください。"
            elif "仕様" in q_lower:
                return "住宅の仕様について詳しくご案内いたします。展示場でご確認いただくか、お気軽にお問い合わせください。"
            else:
                return "お尋ねの内容について詳しくご案内いたします。住宅に関することでしたら何でもお気軽にお問い合わせください。"

# ==============================================================================
# リクエストモデル
# ==============================================================================
class ChatRequest(BaseModel):
    question: str
    username: str | None = None

# グローバルインスタンス
platform_generator = PlatformSeparatedResponseGenerator()

# ==============================================================================
# メインチャットエンドポイント（Web専用・超高速版）
# ==============================================================================
@app.post("/chat")
@app.post("/chat/")
async def web_chat_endpoint(req: ChatRequest, request: Request):
    """Web専用超高速チャットエンドポイント（RAG完全無効）"""
    
    overall_start = time.time()
    logger.info(f"🌐 Web Chat: {req.question[:50]}...")
    
    try:
        # Web専用応答生成
        response = await platform_generator.generate_platform_response(
            req.question,
            platform="web",
            user=req.username or "web-user"
        )
        
        total_time = time.time() - overall_start
        
        logger.info(f"✅ Web Response: {total_time:.3f}s, "
                   f"source={response.get('source')}, "
                   f"length={len(response.get('answer', ''))}")
        
        return {
            "answer": response["answer"],
            "sources": [],
            "status": response["status"],
            "performance": {
                "total_time": total_time,
                "processing_time": response.get("processing_time", 0),
                "source": response.get("source"),
                "platform": "web",
                "rag_enabled": False,
                "template_based": response.get("source") == "template"
            }
        }
        
    except Exception as e:
        total_time = time.time() - overall_start
        error_id = str(uuid4())[:8]
        
        logger.error(f"❌ Web Chat error [{error_id}]: {e}")
        
        fallback_answer = platform_generator._generate_platform_fallback(
            req.question if hasattr(req, 'question') else "", "web"
        )
        
        return JSONResponse(
            status_code=200,
            content={
                "answer": fallback_answer,
                "sources": [],
                "status": "fallback",
                "error_id": error_id,
                "performance": {
                    "total_time": total_time,
                    "platform": "web",
                    "rag_enabled": False
                }
            }
        )

# ==============================================================================
# 超軽量ヘルスチェック
# ==============================================================================
@app.get("/healthz")
async def health_check():
    """超軽量ヘルスチェック（Cloud Run Startup Probe対応）"""
    uptime = time.time() - startup_time
    
    return {
        "status": "healthy",
        "uptime": uptime,
        "timestamp": datetime.now().isoformat(),
        "message": "Platform Separated Ultra Fast API",
        "startup_mode": "ultra_fast_platform_separated",
        "rag_disabled": True,
        "template_mode": FORCE_TEMPLATE_MODE
    }

@app.get("/")
async def root():
    """ルートエンドポイント"""
    return {
        "message": "RAG API Ultra Fast Edition - Platform Separated",
        "version": "2.1.0",
        "timestamp": datetime.now().isoformat(),
        "platforms": {
            "web": "Template-based responses optimized for web",
            "line": "LINE-specific formatted responses"
        },
        "rag_status": "completely_disabled_for_speed",
        "uptime": time.time() - startup_time,
        "features": [
            "Platform Separated Responses",
            "Ultra Fast Startup (< 5s)",
            "Template-based Instant Responses", 
            "Smart Caching System",
            "Zero RAG Dependency"
        ]
    }

# ==============================================================================
# システム状態・監視エンドポイント
# ==============================================================================
@app.get("/system-status")
async def get_system_status():
    """システム状態取得"""
    cache_stats = platform_generator.cache.get_stats()
    perf_metrics = platform_generator.performance_metrics
    
    return {
        "platform_separation": {
            "enabled": True,
            "web_templates": len(platform_generator.web_templates),
            "line_templates": len(platform_generator.line_templates),
            "cache_stats": cache_stats,
        },
        "performance_metrics": perf_metrics,
        "uptime": time.time() - startup_time,
        "rag_completely_disabled": True,
        "force_template_mode": FORCE_TEMPLATE_MODE,
        "version": "2.1.0",
        "timestamp": datetime.now().isoformat()
    }

# ==============================================================================
# アプリケーション起動時の処理
# ==============================================================================
@app.on_event("startup")
async def startup_event():
    """アプリケーション起動時の処理（プラットフォーム分離対応）"""
    logger.info("🚀 Starting Platform Separated Ultra Fast API...")
    
    # LINE専用ルーター（reply失効対策付き）
    try:
        from api.routers.line_bot_ultra_fast import router as ultra_line_router
        app.include_router(ultra_line_router, prefix="/line", tags=["line-ultra-fast"])
        logger.info("✅ LINE Ultra Fast router added with prefix /line")
        
        # LINE Bot 設定確認
        token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
        secret = os.getenv("LINE_CHANNEL_SECRET")
        
        if token and secret:
            logger.info("✅ LINE Bot credentials found")
        else:
            logger.warning("⚠️ LINE Bot credentials not found")
            
    except Exception as e:
        logger.error(f"❌ Failed to add LINE router: {e}")
        
        # フォールバック：修正版LINEルーター
        try:
            from api.routers.line_bot_fixed import router as line_fallback_router
            app.include_router(line_fallback_router, prefix="/line-fallback", tags=["line-fallback"])
            logger.info("✅ LINE Fallback router added")
        except Exception as fallback_error:
            logger.error(f"❌ Fallback LINE router also failed: {fallback_error}")
    
    # その他のルーター（オプション）
    try:
        from api.routers.upload import router as upload_router
        app.include_router(upload_router, prefix="/upload", tags=["upload"])
        logger.info("✅ Upload router added")
    except Exception as e:
        logger.warning(f"⚠️ Upload router not added: {e}")
    
    # 重要：RAG関連ルーターは一切追加しない（超高速化のため）
    logger.info("🚫 RAG-related routers completely disabled for ultra-fast performance")
    logger.info("🔄 Template-based responses will handle all queries")
    
    logger.info("🎉 Platform Separated Ultra Fast startup completed")
    logger.info(f"⚡ Startup time: {time.time() - startup_time:.2f} seconds")

@app.post("/clear-cache")
def clear_all_caches():
    """プラットフォーム分離キャッシュクリア"""
    old_stats = platform_generator.cache.get_stats()
    
    # 分離キャッシュクリア
    platform_generator.cache = PlatformSeparatedCache(max_size=500)
    
    return {
        "status": "platform_separated_caches_cleared",
        "previous_stats": old_stats,
        "platforms_cleared": ["web", "line"],
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)