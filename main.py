# main.py - 最適化版（ルーティング分離 + 文章途切れ対策 + 高速化）

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
    title="RAG API - Optimized Edition with Route Separation",
    description="High-Performance AI Chat API with Smart Routing and Anti-Truncation",
    version="4.0.0"
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# グローバル変数（RAG機能）
vectorstore = None
rag_chain_template = None
llm_instance = None
initialization_lock = asyncio.Lock()
is_initialized = False

# 起動時刻を記録
startup_time = time.time()

# 設定フラグ
ENABLE_RAG_INITIALIZATION = True  # RAG機能を有効化
ENABLE_SMART_ROUTING = True  # スマートルーティング有効化
ENABLE_FAST_ROUTES = True  # 高速ルート有効化
ENABLE_SENTENCE_COMPLETION = True  # 文章完全性チェック有効化

# ==============================================================================
# スマートルーティングシステム
# ==============================================================================
class SmartRouter:
    """用途別ルート振り分けシステム"""
    
    def __init__(self):
        self.routing_stats = {
            "fast_route_count": 0,
            "rag_route_count": 0, 
            "template_route_count": 0,
            "total_requests": 0
        }
        
        # 高速ルート対象キーワード（テンプレート対応可能）
        self.fast_keywords = [
            "AI相談", "資料請求", "展示場", "見学", "予約", "チャット相談",
            "AI住まいサイト", "サイト", "ホームページ", "資金計画", "ローン",
            "こんにちは", "はじめまして", "よろしく", "ありがとう"
        ]
        
        # RAG処理が必要なキーワード（高度な回答が必要）
        self.rag_keywords = [
            "坪単価", "価格", "費用", "金額", "コスト", "値段",
            "仕様", "標準", "設備", "グレード", "オプション",
            "断熱", "性能", "省エネ", "ZEH", "UA値", "C値",
            "耐震", "地震", "安全", "構造", "基礎", "工法",
            "補助金", "助成金", "支援金", "制度", "控除",
            "建ぺい率", "容積率", "法規", "規制", "基準"
        ]
    
    def determine_route(self, query: str, platform: str = "web") -> str:
        """クエリに基づく最適ルート決定"""
        self.routing_stats["total_requests"] += 1
        query_lower = query.lower()
        
        # 1. 高速ルート判定（テンプレート対応可能）
        if any(keyword in query_lower for keyword in self.fast_keywords):
            self.routing_stats["fast_route_count"] += 1
            return "fast"
        
        # 2. RAGルート判定（専門知識が必要）
        if any(keyword in query_lower for keyword in self.rag_keywords):
            self.routing_stats["rag_route_count"] += 1
            return "rag"
        
        # 3. 質問の複雑さで判定
        question_indicators = ["？", "?", "教えて", "知りたい", "どう", "なぜ", "どこ", "いつ"]
        if any(indicator in query for indicator in question_indicators):
            # 複雑な質問はRAGへ
            if len(query) > 20:
                self.routing_stats["rag_route_count"] += 1
                return "rag"
            else:
                self.routing_stats["fast_route_count"] += 1
                return "fast"
        
        # 4. デフォルト：短い文章は高速、長い文章はRAG
        if len(query) <= 15:
            self.routing_stats["template_route_count"] += 1
            return "template"
        else:
            self.routing_stats["rag_route_count"] += 1
            return "rag"
    
    def get_stats(self) -> Dict[str, Any]:
        """ルーティング統計取得"""
        total = self.routing_stats["total_requests"]
        
        return {
            "total_requests": total,
            "fast_route_percentage": (self.routing_stats["fast_route_count"] / total * 100) if total > 0 else 0,
            "rag_route_percentage": (self.routing_stats["rag_route_count"] / total * 100) if total > 0 else 0,
            "template_route_percentage": (self.routing_stats["template_route_count"] / total * 100) if total > 0 else 0,
            "routing_efficiency": {
                "fast_routes": self.routing_stats["fast_route_count"],
                "rag_routes": self.routing_stats["rag_route_count"],
                "template_routes": self.routing_stats["template_route_count"]
            }
        }

# グローバルルーター
smart_router = SmartRouter()

# ==============================================================================
# 文章完全性保証システム（メイン統合版）
# ==============================================================================
def ensure_response_completeness(text: str, query: str = "", platform: str = "web") -> str:
    """文章完全性保証（統合版）"""
    if not text or len(text.strip()) < 5:
        return generate_platform_fallback(query, platform)
    
    text = text.strip()
    
    # 文末チェックと補完
    if not text.endswith(('。', '！', '？', '.', '!', '?')):
        logger.info(f"🔧 Fixing incomplete response: '{text[-30:]}'")
        
        # 包括的な途切れパターン対応
        completion_patterns = {
            'や': '関連する準備を進めることをお勧めします。',
            '重要': 'です。詳しくはお気軽にご相談ください。',
            '必要': 'です。',
            'について': 'は詳細をご案内いたします。',
            '選定': 'も重要な工程です。',
            '検討': 'が必要です。',
            '確認': 'を進めることをお勧めします。',
            '準備': 'を行うことが大切です。',
            '計画': 'が成功の鍵となります。',
            '設計': 'を慎重に行います。',
            '性能': 'にこだわっています。',
            '品質': 'を重視しています。',
            '対応': 'しています。',
            '仕様': 'となっております。',
            '条件': 'を満たしています。',
            '基準': 'に適合しています。',
            'など': 'があります。詳細はお問い合わせください。',
            'から': '、ご検討ください。',
            'して': 'います。',
            'また': '、詳細についてはお問い合わせください。',
            '、': '。',  # カンマで終わる場合
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
            # パターンにマッチしない場合
            if text.endswith(('ます', 'です')):
                text += '。'
            elif text.endswith(('た', 'る', 'し')):
                text += '。'
            elif text.endswith(('は', 'が')):
                text += '重要なポイントです。'
            elif text.endswith(('ので', 'ため')):
                text += '、お気軽にご相談ください。'
            else:
                # 長さによる補完
                if len(text) > 50:
                    text += '。'
                elif len(text) > 25:
                    text += '。詳細はお問い合わせください。'
                else:
                    text = generate_platform_fallback(query, platform)
        
        logger.info(f"✅ Fixed response: '{text[-30:]}'")
    
    return text

def generate_platform_fallback(query: str, platform: str) -> str:
    """プラットフォーム別フォールバック応答"""
    fallback_templates = {
        "坪単価": "坪単価については、お客様のご要望や仕様によって異なりますので、詳細なお見積りをご提供いたします。",
        "仕様": "住宅の仕様について詳しくご案内いたします。お客様のご要望に合わせて最適な仕様をご提案いたします。",
        "資料": "資料請求を承ります。お名前、ご住所、お電話番号をお教えいただければ、詳しい資料をお送りいたします。",
        "土地": "土地探しから建築まで、トータルでサポートいたします。お客様のご希望条件をお聞かせください。"
    }
    
    # クエリに応じたテンプレート選択
    for keyword, template in fallback_templates.items():
        if keyword in query:
            return template
    
    # デフォルトフォールバック
    if platform == "line":
        return """ご質問ありがとうございます✨

お尋ねの内容について、より詳しい情報をご提供するため、スタッフまでお問い合わせください。

お気軽にご連絡ください😊"""
    else:
        return "お尋ねの内容について詳しくご案内いたします。住宅に関することでしたら何でもお気軽にお問い合わせください。"

# ==============================================================================
# RAGコンポーネント初期化
# ==============================================================================
async def initialize_rag_components():
    """RAGコンポーネントの初期化"""
    global vectorstore, rag_chain_template, llm_instance, is_initialized
    
    if is_initialized:
        return
    
    async with initialization_lock:
        if is_initialized:
            return
            
        logger.info("🚀 Initializing optimized RAG components...")
        
        try:
            # LLMインスタンス（文章完全性対応版）
            from llm.llm_runner import load_llm
            llm_instance = load_llm()[0]
            
            # ベクトルストア読み込み
            try:
                from rag.fast_rag_chain import load_ultra_fast_vectorstore, get_ultra_fast_rag_chain
                vectorstore = load_ultra_fast_vectorstore()
                rag_chain_template = get_ultra_fast_rag_chain(vectorstore)
                logger.info("✅ Using ultra fast RAG chain")
            except Exception as e:
                logger.warning(f"Ultra fast RAG chain failed, using fallback: {e}")
                # フォールバック処理
                pass
            
            is_initialized = True
            logger.info("✅ Optimized RAG components initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ RAG initialization failed: {e}")
            is_initialized = False

# ==============================================================================
# リクエストモデル
# ==============================================================================
class OptimizedChatRequest(BaseModel):
    question: str
    username: str | None = None
    platform: str | None = "web"
    route_preference: str | None = None  # "fast", "rag", "auto"

# ==============================================================================
# エンドポイント（最適化版）
# ==============================================================================
@app.post("/chat")
@app.post("/chat/")
async def optimized_chat_endpoint(req: OptimizedChatRequest, request: Request):
    """最適化チャットエンドポイント（スマートルーティング + 文章完全性保証）"""
    
    overall_start = time.time()
    platform = req.platform or "web"
    username = req.username or f"{platform}-user"
    
    logger.info(f"🌐 Optimized Chat ({platform}): {req.question[:50]}...")
    
    try:
        # 1. スマートルーティング
        if req.route_preference and req.route_preference in ["fast", "rag"]:
            selected_route = req.route_preference
            logger.info(f"🎯 User-specified route: {selected_route}")
        else:
            selected_route = smart_router.determine_route(req.question, platform)
            logger.info(f"🧠 Smart-selected route: {selected_route}")
        
        # 2. ルート別処理
        if selected_route == "fast" and ENABLE_FAST_ROUTES:
            # 高速ルート（テンプレート + 軽量処理）
            response = await process_fast_route(req.question, platform, username)
            
        elif selected_route == "rag":
            # RAGルート（高品質回答）
            response = await process_rag_route(req.question, platform, username)
            
        else:
            # テンプレートルート（即座応答）
            response = await process_template_route(req.question, platform, username)
        
        total_time = time.time() - overall_start
        
        # 3. 文章完全性チェック（統合）
        if ENABLE_SENTENCE_COMPLETION:
            response["answer"] = ensure_response_completeness(
                response["answer"], req.question, platform
            )
            response["sentence_complete"] = response["answer"].endswith(('。', '！', '？', '.', '!', '?'))
        
        logger.info(f"✅ Optimized Response ({platform}): {total_time:.3f}s, "
                   f"route={selected_route}, "
                   f"length={len(response['answer'])}, "
                   f"complete={response.get('sentence_complete', False)}")
        
        return {
            "answer": response["answer"],
            "sources": response.get("sources", []),
            "status": response.get("status", "ok"),
            "performance": {
                "total_time": total_time,
                "selected_route": selected_route,
                "platform": platform,
                "sentence_complete": response.get("sentence_complete", False),
                "smart_routing_enabled": ENABLE_SMART_ROUTING,
                "processing_method": response.get("method", "unknown")
            }
        }
        
    except Exception as e:
        total_time = time.time() - overall_start
        error_id = str(uuid4())[:8]
        
        logger.error(f"❌ Optimized chat error [{error_id}]: {e}")
        logger.error(traceback.format_exc())
        
        # エラー時も文章完全性保証
        fallback_answer = generate_platform_fallback(req.question, platform)
        complete_fallback = ensure_response_completeness(fallback_answer, req.question, platform)
        
        return JSONResponse(
            status_code=200,
            content={
                "answer": complete_fallback,
                "sources": [],
                "status": "fallback",
                "error_id": error_id,
                "performance": {
                    "total_time": total_time,
                    "selected_route": "error",
                    "platform": platform,
                    "sentence_complete": complete_fallback.endswith(('。', '！', '？', '.', '!', '?'))
                }
            }
        )

async def process_fast_route(query: str, platform: str, username: str) -> Dict[str, Any]:
    """高速ルート処理"""
    try:
        if platform == "line":
            # LINE用高速処理
            from api.routers.line_bot_template_fast import template_responder
            result = template_responder.get_instant_response(query, username)
            
            return {
                "answer": result["response"],
                "sources": [],
                "status": "ok",
                "method": "line_template_fast"
            }
        else:
            # Web用高速処理
            from api.routers.chat_ultra_fast import separated_generator
            result = await separated_generator.generate_separated_response(query, platform, username)
            
            return {
                "answer": result["answer"],
                "sources": [],
                "status": result.get("status", "ok"),
                "method": "web_ultra_fast"
            }
            
    except Exception as e:
        logger.error(f"Fast route error: {e}")
        return {
            "answer": generate_platform_fallback(query, platform),
            "sources": [],
            "status": "fallback",
            "method": "fast_fallback"
        }

async def process_rag_route(query: str, platform: str, username: str) -> Dict[str, Any]:
    """RAGルート処理"""
    try:
        # RAG初期化確認
        if not is_initialized and ENABLE_RAG_INITIALIZATION:
            await initialize_rag_components()
        
        if rag_chain_template:
            # RAG処理実行
            result = rag_chain_template.invoke({"query": query})
            rag_answer = result.get("result", "")
            
            if rag_answer and len(rag_answer.strip()) > 10:
                return {
                    "answer": rag_answer,
                    "sources": [],
                    "status": "ok",
                    "method": "rag_processing"
                }
        
        # RAG失敗時のフォールバック
        return {
            "answer": generate_platform_fallback(query, platform),
            "sources": [],
            "status": "fallback",
            "method": "rag_fallback"
        }
        
    except Exception as e:
        logger.error(f"RAG route error: {e}")
        return {
            "answer": generate_platform_fallback(query, platform),
            "sources": [],
            "status": "fallback",
            "method": "rag_error_fallback"
        }

async def process_template_route(query: str, platform: str, username: str) -> Dict[str, Any]:
    """テンプレートルート処理"""
    return {
        "answer": generate_platform_fallback(query, platform),
        "sources": [],
        "status": "ok",
        "method": "template_direct"
    }

# ==============================================================================
# ヘルスチェック・システム状態
# ==============================================================================
@app.get("/healthz")
async def health_check():
    """最適化ヘルスチェック"""
    uptime = time.time() - startup_time
    routing_stats = smart_router.get_stats()
    
    return {
        "status": "healthy",
        "uptime": uptime,
        "timestamp": datetime.now().isoformat(),
        "version": "4.0.0-optimized",
        "message": "Optimized RAG API with Smart Routing and Sentence Completion",
        "features": {
            "smart_routing": ENABLE_SMART_ROUTING,
            "fast_routes": ENABLE_FAST_ROUTES,
            "sentence_completion": ENABLE_SENTENCE_COMPLETION,
            "rag_initialization": ENABLE_RAG_INITIALIZATION
        },
        "routing_stats": routing_stats,
        "rag_status": {
            "initialized": is_initialized,
            "vectorstore_ready": vectorstore is not None,
            "llm_ready": llm_instance is not None
        }
    }

@app.get("/")
async def root():
    """ルートエンドポイント"""
    routing_stats = smart_router.get_stats()
    
    return {
        "message": "Optimized RAG API with Smart Routing",
        "version": "4.0.0",
        "timestamp": datetime.now().isoformat(),
        "features": [
            "Smart Route Selection (Fast/RAG/Template)",
            "Sentence Completion Guarantee", 
            "Platform-Optimized Processing",
            "LLM/OpenAI API Independence (Fast Routes)",
            "High-Performance Caching",
            "Error Recovery with Completeness"
        ],
        "routing_efficiency": routing_stats,
        "uptime": time.time() - startup_time
    }

@app.get("/system-status")
async def get_system_status():
    """最適化システム状態"""
    routing_stats = smart_router.get_stats()
    
    return {
        "optimization_features": {
            "smart_routing": ENABLE_SMART_ROUTING,
            "fast_routes": ENABLE_FAST_ROUTES,
            "sentence_completion": ENABLE_SENTENCE_COMPLETION,
            "rag_initialization": ENABLE_RAG_INITIALIZATION
        },
        "routing_performance": routing_stats,
        "system_health": {
            "rag_initialized": is_initialized,
            "vectorstore_ready": vectorstore is not None,
            "llm_ready": llm_instance is not None
        },
        "completion_patterns": 20,
        "supported_platforms": ["web", "line"],
        "version": "4.0.0-optimized",
        "timestamp": datetime.now().isoformat()
    }

# ==============================================================================
# 管理エンドポイント
# ==============================================================================
@app.post("/routing/reset-stats")
async def reset_routing_stats():
    """ルーティング統計リセット"""
    old_stats = smart_router.get_stats()
    smart_router.routing_stats = {
        "fast_route_count": 0,
        "rag_route_count": 0,
        "template_route_count": 0,
        "total_requests": 0
    }
    
    return {
        "status": "routing_stats_reset",
        "previous_stats": old_stats,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/routing/test/{query}")
async def test_routing(query: str, platform: str = "web"):
    """ルーティングテスト"""
    selected_route = smart_router.determine_route(query, platform)
    
    return {
        "query": query,
        "platform": platform,
        "selected_route": selected_route,
        "routing_logic": {
            "fast_keywords_matched": any(kw in query.lower() for kw in smart_router.fast_keywords),
            "rag_keywords_matched": any(kw in query.lower() for kw in smart_router.rag_keywords),
            "query_length": len(query)
        },
        "timestamp": datetime.now().isoformat()
    }

# ==============================================================================
# 起動時処理
# ==============================================================================
@app.on_event("startup")
async def startup_event():
    """最適化起動処理"""
    logger.info("🚀 Starting Optimized RAG API with Smart Routing...")
    
    # RAG初期化（バックグラウンド）
    if ENABLE_RAG_INITIALIZATION:
        asyncio.create_task(initialize_rag_components())
    
    # ルーター追加（最適化順序）
    
    # 1. 最高速度テンプレート専用LINE Bot（最優先）
    try:
        from api.routers.line_bot_template_fast import router as line_template_fast_router
        app.include_router(line_template_fast_router, prefix="/line-template-fast", tags=["line-template-fast"])
        logger.info("✅ LINE Template Fast router added (HIGHEST PRIORITY)")
    except Exception as e:
        logger.error(f"❌ Failed to add LINE Template Fast router: {e}")
    
    # 2. 高速チャット
    try:
        from api.routers.chat_ultra_fast import router as chat_ultra_fast_router
        app.include_router(chat_ultra_fast_router, prefix="/chat-ultra-fast", tags=["chat-ultra-fast"])
        logger.info("✅ Chat Ultra Fast router added")
    except Exception as e:
        logger.warning(f"⚠️ Failed to add Chat Ultra Fast router: {e}")
    
    # 3. その他のルーター
    try:
        from api.routers.upload import router as upload_router
        app.include_router(upload_router, prefix="/upload", tags=["upload"])
        logger.info("✅ Upload router added")
    except Exception as e:
        logger.warning(f"⚠️ Upload router not added: {e}")
    
    logger.info("🎉 Optimized RAG API startup completed")
    logger.info(f"⚡ Startup time: {time.time() - startup_time:.2f} seconds")
    logger.info(f"🎯 Smart Routing: {'Enabled' if ENABLE_SMART_ROUTING else 'Disabled'}")
    logger.info(f"🔧 Sentence Completion: {'Enabled' if ENABLE_SENTENCE_COMPLETION else 'Disabled'}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)