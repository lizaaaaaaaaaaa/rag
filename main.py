# main.py - RAG API メインアプリケーション（修正版）

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
    description="AI Chat API with RAG functionality",
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

# 統一されたキャッシュシステム
class UnifiedFastCache:
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

# RAG初期化関数
async def initialize_rag_system():
    """RAGシステムの初期化"""
    global vectorstore, rag_chain_template, llm_instance, is_initialized
    
    async with initialization_lock:
        if is_initialized:
            return
        
        logger.info("🚀 Initializing RAG system...")
        
        try:
            # 1. ベクトルストアの読み込み
            from rag.ingested_text import load_vectorstore
            vectorstore = load_vectorstore()
            logger.info("✅ Vectorstore loaded")
            
            # 2. LLMの初期化
            from llm.llm_runner import load_llm
            llm_instance, _, _ = load_llm()
            logger.info("✅ LLM loaded")
            
            # 3. RAGチェーンの作成
            from rag.ingested_text import get_rag_chain
            rag_chain_template = get_rag_chain(vectorstore, return_source=True)
            logger.info("✅ RAG chain created")
            
            is_initialized = True
            logger.info("🎉 RAG system initialization completed")
            
        except Exception as e:
            logger.error(f"❌ RAG system initialization failed: {e}")
            logger.error(traceback.format_exc())
            
            # フォールバック: 最小限のシステム
            try:
                from rag.fast_rag_chain import load_ultra_fast_vectorstore, get_ultra_fast_rag_chain
                vectorstore = load_ultra_fast_vectorstore()
                rag_chain_template = get_ultra_fast_rag_chain(vectorstore)
                logger.info("✅ Fallback RAG system initialized")
                is_initialized = True
            except Exception as fallback_error:
                logger.error(f"❌ Fallback initialization also failed: {fallback_error}")

# 応答生成クラス（RAG統合版）
class RAGIntegratedResponseGenerator:
    def __init__(self):
        self.cache = UnifiedFastCache(max_size=500)
        self.response_templates = self._load_unified_templates()
       
    def _load_unified_templates(self) -> Dict[str, str]:
        return {
            "坪単価": "坪単価についてご案内いたします。標準仕様では約70〜85万円/坪が目安となりますが、お客様のご希望される仕様によって変動いたします。詳細なお見積りをご提供いたしますので、お気軽にお問い合わせください。",
            "標準仕様": "標準仕様についてご説明いたします。耐震等級3の長期優良住宅を基準とし、高品質な住まいをご提供するため、様々な設備や性能を標準装備としております。詳細は展示場でご確認いただけます。",
            "断熱性能": "断熱性能については、高品質な断熱材を使用し、快適な住環境を実現しています。ZEH基準に対応した省エネ性能で、一年中快適にお過ごしいただけます。詳細は展示場でご確認いただけます。",
            "耐震性能": "耐震性能については、耐震等級3を標準とし、地震に強い安心・安全な住まいをご提供しています。構造計算に基づいた確かな技術で建築いたします。",
            "資料請求": "資料請求を承ります。お名前、ご住所、お電話番号をお教えいただければ、詳しい資料をお送りいたします。3営業日以内にお送りいたします。",
            "見学予約": "展示場見学を承ります。ご希望の日時をお聞かせください。スタッフが丁寧にご案内いたします。最新の住宅仕様をご確認いただけます。",
        }
   
    async def generate_rag_response(self, query: str, user: str) -> Dict[str, Any]:
        """RAG統合レスポンス生成"""
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
            
            # 2. テンプレート即座マッチング
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
            
            # 3. RAG処理（メイン処理）
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
            
            # 4. フォールバック
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
        """RAGチェーンでの処理"""
        global rag_chain_template
        
        if not rag_chain_template:
            logger.warning("RAG chain not initialized")
            return None
        
        try:
            # タイムアウト付きでRAG処理
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
                    rag_result = await asyncio.wait_for(future, timeout=8.0)
                    if rag_result and len(rag_result.strip()) > 10:
                        logger.info(f"✅ RAG success: {len(rag_result)} chars")
                        return rag_result
                    else:
                        logger.warning("RAG returned empty or short result")
                        return None
                except asyncio.TimeoutError:
                    logger.warning("⏰ RAG processing timeout (8s)")
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
rag_generator = RAGIntegratedResponseGenerator()

# ヘルスチェックエンドポイント
@app.get("/healthz")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "rag-api",
        "rag_initialized": is_initialized
    }

@app.get("/")
async def root():
    return {
        "message": "RAG API is running",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "rag_status": "initialized" if is_initialized else "initializing"
    }

# メインチャットエンドポイント
@app.post("/chat")
@app.post("/chat/")
async def chat_endpoint(req: ChatRequest, request: Request):
    """RAG統合チャットエンドポイント"""
    
    overall_start = time.time()
    logger.info(f"🚀 RAG processing: {req.question[:50]}...")
    
    # RAGシステム初期化確認
    if not is_initialized:
        await initialize_rag_system()
    
    try:
        # RAG統合応答生成
        response = await rag_generator.generate_rag_response(
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
                "rag_enabled": True
            }
        }
        
    except Exception as e:
        total_time = time.time() - overall_start
        error_id = str(uuid4())[:8]
        
        logger.error(f"❌ Chat error [{error_id}]: {e}")
        logger.error(traceback.format_exc())
        
        fallback_answer = rag_generator._generate_unified_fallback(req.question if hasattr(req, 'question') else "")
        
        return JSONResponse(
            status_code=200,
            content={
                "answer": fallback_answer,
                "sources": [],
                "status": "fallback",
                "error_id": error_id,
                "performance": {
                    "total_time": total_time,
                    "rag_enabled": False
                }
            }
        )

# LINEボット関連ルーター追加
@app.on_event("startup")
async def startup_event():
    """アプリケーション起動時の処理"""
    logger.info("🚀 Starting RAG API application...")
    
    # RAGシステムの初期化
    await initialize_rag_system()
    
    # LINEボットルーターの追加
    try:
        from api.routers.line_bot_fixed import router as line_router
        app.include_router(line_router, prefix="/line", tags=["line"])
        logger.info("✅ LINE bot router added")
    except Exception as e:
        logger.error(f"❌ Failed to add LINE bot router: {e}")
    
    # その他のルーターも追加
    try:
        # アップロード機能
        from api.routers.upload import router as upload_router
        app.include_router(upload_router, prefix="/upload", tags=["upload"])
        logger.info("✅ Upload router added")
    except Exception as e:
        logger.error(f"❌ Failed to add upload router: {e}")

# システム状態エンドポイント
@app.get("/system-status")
async def get_system_status():
    """システム状態取得"""
    return {
        "rag_initialized": is_initialized,
        "vectorstore_loaded": vectorstore is not None,
        "rag_chain_loaded": rag_chain_template is not None,
        "llm_loaded": llm_instance is not None,
        "cache_stats": rag_generator.cache.get_stats(),
        "timestamp": datetime.now().isoformat()
    }

# パフォーマンス統計
@app.get("/performance-stats")
def get_performance_stats():
    cache_stats = rag_generator.cache.get_stats()
    
    return {
        "cache_performance": cache_stats,
        "response_templates": len(rag_generator.response_templates),
        "rag_features": [
            "ベクトルストア検索",
            "LLM回答生成", 
            "テンプレート即座応答",
            "統一フォールバック",
            "キャッシュシステム"
        ],
        "target_metrics": {
            "response_time": "< 3.0s",
            "cache_hit_rate": "> 50%",
            "rag_success_rate": "> 80%"
        },
        "timestamp": datetime.now().isoformat()
    }

# キャッシュクリア
@app.post("/clear-cache")
def clear_cache():
    old_stats = rag_generator.cache.get_stats()
    rag_generator.cache = UnifiedFastCache(max_size=500)
    
    return {
        "status": "cache_cleared",
        "previous_stats": old_stats,
        "new_cache_size": 0,
        "timestamp": datetime.now().isoformat()
    }

# RAGシステム再初期化
@app.post("/reinitialize-rag")
async def reinitialize_rag():
    """RAGシステムの再初期化"""
    global is_initialized
    is_initialized = False
    
    await initialize_rag_system()
    
    return {
        "status": "reinitialized",
        "rag_initialized": is_initialized,
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
