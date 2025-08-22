# main.py - 超高速スタートアップ版（Cloud Run Startup Probe対応）

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
    title="RAG API",
    description="AI Chat API with RAG functionality - Ultra Fast Startup",
    version="1.0.0"
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
            "startup_mode": "fast_boot"
        }
    
    # 基本的なアプリケーション健全性チェック（RAG無関係）
    return {
        "status": "healthy",
        "uptime": uptime,
        "timestamp": datetime.now().isoformat(),
        "rag_initialized": is_initialized,
        "rag_initialization_in_progress": initialization_in_progress,
        "service": "rag-api",
        "version": "1.0.0",
        "fast_startup": True
    }

@app.get("/")
async def root():
    """ルートエンドポイント（超軽量）"""
    return {
        "message": "RAG API is running with ultra-fast startup",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "rag_status": "initialized" if is_initialized else "initializing",
        "uptime": time.time() - startup_time,
        "fast_startup_enabled": DISABLE_RAG_INIT
    }

# 統一されたキャッシュシステム
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
            logger.info(f"⚡ Cache HIT for: {query[:30]}...")
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
            "query_original": query[:100]
        }
        self.access_times[key] = time.time()
        logger.info(f"💾 Cache SET for: {query[:30]}...")
   
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

# 完全遅延RAG初期化（起動時は実行しない）
async def initialize_rag_system_if_needed():
    """RAGシステムの完全遅延初期化（必要時のみ実行）"""
    global vectorstore, rag_chain_template, llm_instance, is_initialized, initialization_in_progress
    
    if DISABLE_RAG_INIT:
        logger.info("🚫 RAG initialization disabled for fast startup")
        return False
    
    async with initialization_lock:
        if is_initialized or initialization_in_progress:
            return is_initialized
        
        initialization_in_progress = True
        logger.info("🚀 Starting on-demand RAG system initialization...")
        
        try:
            # 軽量ベクトルストアのみ読み込み
            logger.info("Loading minimal vectorstore...")
            loop = asyncio.get_event_loop()
            
            def load_minimal_vectorstore():
                try:
                    from rag.fast_rag_chain import create_minimal_vectorstore_ultra_fast
                    return create_minimal_vectorstore_ultra_fast()
                except Exception as e:
                    logger.error(f"Minimal vectorstore load error: {e}")
                    return None
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = loop.run_in_executor(executor, load_minimal_vectorstore)
                try:
                    vectorstore = await asyncio.wait_for(future, timeout=15)
                    if vectorstore:
                        logger.info("✅ Minimal vectorstore loaded")
                    else:
                        logger.warning("⚠️ Failed to load minimal vectorstore")
                except asyncio.TimeoutError:
                    logger.error("⏰ Vectorstore loading timeout")
                    vectorstore = None
            
            # 高速RAGチェーンの作成
            if vectorstore:
                logger.info("Creating fast RAG chain...")
                try:
                    from rag.fast_rag_chain import get_ultra_fast_rag_chain
                    rag_chain_template = get_ultra_fast_rag_chain(vectorstore)
                    logger.info("✅ Fast RAG chain created")
                except Exception as e:
                    logger.error(f"Fast RAG chain creation error: {e}")
                    rag_chain_template = None
            
            # LLMは最低限のみ
            try:
                from llm.llm_runner import load_llm
                llm_instance, _, _ = load_llm()
                logger.info("✅ LLM loaded")
            except Exception as e:
                logger.error(f"LLM load error: {e}")
                llm_instance = None
            
            is_initialized = True
            logger.info("🎉 On-demand RAG system initialization completed")
            return True
            
        except Exception as e:
            logger.error(f"❌ On-demand RAG system initialization failed: {e}")
            return False
        
        finally:
            initialization_in_progress = False

# 応答生成クラス（RAG非依存）
class UltraFastResponseGenerator:
    def __init__(self):
        self.cache = UltraFastCache(max_size=500)
        self.response_templates = self._load_unified_templates()
       
    def _load_unified_templates(self) -> Dict[str, str]:
        return {
            "坪単価": "坪単価についてご案内いたします。標準仕様では約70〜85万円/坪が目安となりますが、お客様のご希望される仕様によって変動いたします。詳細なお見積りをご提供いたしますので、お気軽にお問い合わせください。",
            "標準仕様": "標準仕様についてご説明いたします。耐震等級3の長期優良住宅を基準とし、高品質な住まいをご提供するため、様々な設備や性能を標準装備としております。詳細は展示場でご確認いただけます。",
            "断熱性能": "断熱性能については、高品質な断熱材を使用し、快適な住環境を実現しています。ZEH基準に対応した省エネ性能で、一年中快適にお過ごしいただけます。詳細は展示場でご確認いただけます。",
            "耐震性能": "耐震性能については、耐震等級3を標準とし、地震に強い安心・安全な住まいをご提供しています。構造計算に基づいた確かな技術で建築いたします。",
            "資料請求": "資料請求を承ります。お名前、ご住所、お電話番号をお教えいただければ、詳しい資料をお送りいたします。3営業日以内にお送りいたします。",
            "見学予約": "展示場見学を承ります。ご希望の日時をお聞かせください。スタッフが丁寧にご案内いたします。最新の住宅仕様をご確認いただけます。",
            "AI相談": "🤖 AI住まい相談を開始します！住まいに関するご質問をお気軽にどうぞ。坪単価、標準仕様、性能、資料請求など何でもお聞きください😊",
            "AI住まいサイト": "🌐 住まい情報サイトをご案内します。詳しくはこちら→ https://kinoe-design.com",
            "資金計画": "💰 資金計画についてご相談承ります。住宅ローンや支援制度など、お気軽にお問い合わせください。",
            "チャット相談": "💬 スタッフとのご相談を承ります。住まいづくりに関することなら何でもお気軽にお聞かせください。",
        }
   
    async def generate_ultra_fast_response(self, query: str, user: str) -> Dict[str, Any]:
        """超高速レスポンス生成（RAG非依存）"""
        start_time = time.time()
        
        try:
            # 1. キャッシュチェック
            cached_response = self.cache.get(query)
            if cached_response:
                return {
                    "answer": cached_response["answer"],
                    "processing_time": time.time() - start_time,
                    "source": "cache",
                    "status": "ok"
                }
            
            # 2. テンプレート即座マッチング（RAG不要）
            template_response = self._match_unified_template(query)
            if template_response:
                result = {
                    "answer": template_response,
                    "processing_time": time.time() - start_time,
                    "source": "template",
                    "status": "ok"
                }
                self.cache.set(query, result)
                return result
            
            # 3. オンデマンドRAG処理（初回アクセス時のみ初期化）
            if not DISABLE_RAG_INIT:
                rag_available = await initialize_rag_system_if_needed()
                if rag_available and rag_chain_template:
                    rag_response = await self._process_with_rag(query)
                    if rag_response:
                        result = {
                            "answer": rag_response,
                            "processing_time": time.time() - start_time,
                            "source": "rag",
                            "status": "ok"
                        }
                        self.cache.set(query, result)
                        return result
            
            # 4. 統一フォールバック（RAG不要）
            fallback_response = self._generate_unified_fallback(query)
            result = {
                "answer": fallback_response,
                "processing_time": time.time() - start_time,
                "source": "fallback",
                "status": "ok"
            }
            return result
            
        except Exception as e:
            logger.error(f"Response generation error: {e}")
            return {
                "answer": self._generate_unified_fallback(query),
                "processing_time": time.time() - start_time,
                "source": "error",
                "status": "error"
            }
    
    async def _process_with_rag(self, query: str) -> Optional[str]:
        """RAGチェーンでの処理（超軽量版）"""
        global rag_chain_template
        
        if not rag_chain_template:
            return None
        
        try:
            def run_rag():
                try:
                    result = rag_chain_template.invoke({"query": query})
                    return result.get("result", "")
                except Exception as e:
                    logger.error(f"RAG processing error: {e}")
                    return None
            
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = loop.run_in_executor(executor, run_rag)
                try:
                    rag_result = await asyncio.wait_for(future, timeout=3.0)  # 3秒に短縮
                    if rag_result and len(rag_result.strip()) > 10:
                        logger.info(f"✅ RAG success: {len(rag_result)} chars")
                        return rag_result
                    else:
                        return None
                except asyncio.TimeoutError:
                    logger.warning("⏰ RAG processing timeout (3s)")
                    return None
                    
        except Exception as e:
            logger.error(f"RAG processing error: {e}")
            return None
   
    def _match_unified_template(self, query: str) -> Optional[str]:
        query_lower = query.lower()
        keyword_mapping = {
            "坪単価": ["坪単価", "価格", "費用", "コスト", "いくら", "金額"],
            "標準仕様": ["標準仕様", "仕様", "設備", "標準", "基本"],
            "断熱性能": ["断熱", "断熱性能", "省エネ", "温度", "暖房", "冷房"],
            "耐震性能": ["耐震", "地震", "耐震性能", "耐震等級", "安全"],
            "資料請求": ["資料", "パンフレット", "カタログ", "資料請求"],
            "見学予約": ["見学", "展示場", "予約", "見に行く", "見たい"],
            "AI相談": ["ai相談", "AI相談", "ai住まい", "相談"],
            "AI住まいサイト": ["ai住まいサイト", "サイト", "ホームページ"],
            "資金計画": ["資金計画", "資金", "ローン", "お金"],
            "チャット相談": ["チャット相談", "チャット", "スタッフ"],
        }
        
        for template_key, keywords in keyword_mapping.items():
            if any(keyword in query_lower for keyword in keywords):
                logger.info(f"🎯 Template match: {template_key}")
                return self.response_templates.get(template_key)
        
        return None
   
    def _generate_unified_fallback(self, query: str) -> str:
        if "坪単価" in query or "価格" in query:
            return "坪単価についてご案内いたします。お客様のご希望される仕様によって異なりますので、詳細なお見積りをご提供いたします。お気軽にお問い合わせください。"
        elif "仕様" in query:
            return "住宅の仕様について詳しくご案内いたします。展示場でご確認いただくか、お気軽にお問い合わせください。"
        elif "性能" in query:
            return "住宅性能について詳しくご説明いたします。耐震性能、断熱性能など、お客様のご要望に合わせてご案内いたします。"
        elif "資料" in query:
            return "資料請求を承ります。お名前、ご住所、お電話番号をお教えいただければ、詳しい資料をお送りいたします。"
        else:
            return "お尋ねの内容について詳しくご案内いたします。住宅に関することでしたら何でもお気軽にお問い合わせください。"

# リクエストモデル
class ChatRequest(BaseModel):
    question: str
    username: str | None = None

# グローバルインスタンス
ultra_fast_generator = UltraFastResponseGenerator()

# メインチャットエンドポイント
@app.post("/chat")
@app.post("/chat/")
async def chat_endpoint(req: ChatRequest, request: Request):
    """超高速チャットエンドポイント（RAG非依存起動）"""
    
    overall_start = time.time()
    logger.info(f"🚀 Chat request: {req.question[:50]}...")
    
    try:
        # 超高速応答生成（起動時RAG初期化不要）
        response = await ultra_fast_generator.generate_ultra_fast_response(
            req.question,
            req.username or "web-user"
        )
        
        total_time = time.time() - overall_start
        
        logger.info(f"✅ Response: {total_time:.3f}s, "
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
                "rag_enabled": is_initialized,
                "fast_startup": True
            }
        }
        
    except Exception as e:
        total_time = time.time() - overall_start
        error_id = str(uuid4())[:8]
        
        logger.error(f"❌ Chat error [{error_id}]: {e}")
        
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
                    "rag_enabled": False,
                    "fast_startup": True
                }
            }
        )

# アプリケーション起動時の処理（超高速版）
@app.on_event("startup")
async def startup_event():
    """アプリケーション起動時の処理（超高速起動）"""
    logger.info("🚀 Starting RAG API application (Ultra Fast Startup Mode)...")
    
    # LINE Botルーターの追加（即座実行）
    try:
        from api.routers.line_bot_fixed import router as line_router
        app.include_router(line_router, prefix="/line", tags=["line"])
        logger.info("✅ LINE bot router added with prefix /line")
    except Exception as e:
        logger.error(f"❌ Failed to add LINE bot router: {e}")
    
    # その他のルーターも追加
    try:
        from api.routers.upload import router as upload_router
        app.include_router(upload_router, prefix="/upload", tags=["upload"])
        logger.info("✅ Upload router added")
    except Exception as e:
        logger.error(f"❌ Failed to add upload router: {e}")
    
    # RAG初期化は完全にスキップ（超高速起動）
    if DISABLE_RAG_INIT:
        logger.info("🚫 RAG initialization skipped for ultra-fast startup")
    else:
        logger.info("🔄 RAG initialization will be done on-demand")
    
    logger.info("✅ Ultra-fast application startup completed")

# システム状態エンドポイント
@app.get("/system-status")
async def get_system_status():
    """システム状態取得"""
    return {
        "rag_initialized": is_initialized,
        "rag_initialization_in_progress": initialization_in_progress,
        "vectorstore_loaded": vectorstore is not None,
        "rag_chain_loaded": rag_chain_template is not None,
        "llm_loaded": llm_instance is not None,
        "cache_stats": ultra_fast_generator.cache.get_stats(),
        "uptime": time.time() - startup_time,
        "fast_startup_enabled": DISABLE_RAG_INIT,
        "timestamp": datetime.now().isoformat()
    }

# LINE Bot専用デバッグエンドポイント
@app.get("/line-debug")
async def line_debug_endpoint():
    """LINE Bot専用デバッグ情報"""
    try:
        # LINE Bot関連の環境変数確認
        line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
        line_secret = os.getenv("LINE_CHANNEL_SECRET", "")
        
        return {
            "line_bot_status": {
                "access_token_set": bool(line_token),
                "access_token_length": len(line_token) if line_token else 0,
                "channel_secret_set": bool(line_secret),
                "channel_secret_length": len(line_secret) if line_secret else 0,
                "token_preview": line_token[:10] + "..." if len(line_token) > 10 else "None",
            },
            "endpoints": {
                "webhook": "/line/webhook",
                "debug": "/line/debug-ultimate",
                "test": "/line/test-credentials"
            },
            "templates": {
                "available_templates": list(ultra_fast_generator.response_templates.keys()),
                "template_count": len(ultra_fast_generator.response_templates)
            },
            "system": {
                "uptime": time.time() - startup_time,
                "fast_startup": DISABLE_RAG_INIT,
                "timestamp": datetime.now().isoformat()
            }
        }
    except Exception as e:
        return {
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# パフォーマンス統計
@app.get("/performance-stats")
def get_performance_stats():
    cache_stats = ultra_fast_generator.cache.get_stats()
    
    return {
        "cache_performance": cache_stats,
        "response_templates": len(ultra_fast_generator.response_templates),
        "rag_features": [
            "超高速起動",
            "テンプレート即座応答",
            "オンデマンドRAG初期化",
            "統一フォールバック",
            "キャッシュシステム"
        ],
        "target_metrics": {
            "startup_time": "< 10s",
            "response_time": "< 1.0s (template), < 3.0s (RAG)",
            "cache_hit_rate": "> 50%"
        },
        "uptime": time.time() - startup_time,
        "fast_startup": DISABLE_RAG_INIT,
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)