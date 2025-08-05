import os
import sys
import traceback
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from api.routers import upload, chat, google_oauth, healthz, line_bot, liff_auth
from api.routers import upload, chat, google_oauth, healthz, line_bot, liff_auth, line_login

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# 環境変数読み込み
if os.getenv("ENV") != "production":
    from dotenv import load_dotenv
    load_dotenv(".env")
    logger.info(">>> Loaded .env for local development")
else:
    logger.info(">>> Running in production mode")

# 環境変数デバッグログ
logger.info("==== Environment Variables ====")
logger.info("ENV: %s", os.environ.get("ENV"))
logger.info("OPENAI_API_KEY: %s****", (os.environ.get("OPENAI_API_KEY") or "")[:10])
logger.info("GCS_BUCKET_NAME: %s", os.environ.get("GCS_BUCKET_NAME"))
logger.info("LINE_CHANNEL_ACCESS_TOKEN: %s****", (os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or "")[:10])
logger.info("LINE_CHANNEL_SECRET: %s****", (os.environ.get("LINE_CHANNEL_SECRET") or "")[:10])
logger.info("LANGSMITH_API_KEY: %s****", (os.environ.get("LANGSMITH_API_KEY") or "")[:10])
logger.info("LANGCHAIN_TRACING_V2: %s", os.environ.get("LANGCHAIN_TRACING_V2"))
logger.info("=================================")

# FastAPI初期化
app = FastAPI(
    title="RAG FastAPI Backend with LINE Bot",
    description="RAG + LLM連携API (Cloud Run対応) + LINE Messaging API",
    version="1.0.0"
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://leafy-kitsune-eb4566.netlify.app",
        "https://preview.studio.site",
        "https://*.studio.site",
        "http://localhost:3000",
        "http://localhost:8501",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600
)

# セキュリティヘッダー
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' https:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
        "style-src 'self' 'unsafe-inline' https:;"
    )
    return response

# グローバル変数
vectorstore = None
rag_chain_template = None
llm_instance = None

@app.on_event("startup")
async def load_models_on_startup():
    """システム起動時のモデル読み込み"""
    global vectorstore, rag_chain_template, llm_instance

    logger.info("=== System Startup: Loading Models ===")
    
    # LangSmith設定確認
    langsmith_enabled = os.environ.get("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    logger.info(f"LangSmith tracing: {'enabled' if langsmith_enabled else 'disabled'}")

    # 1. LLMの読み込み
    try:
        from llm.llm_runner import load_llm
        llm, tokenizer, max_tokens = load_llm()
        llm_instance = llm
        logger.info(f"✅ LLM loaded: {type(llm).__name__}")
        
        # LLMテスト
        try:
            test_response = llm.invoke("Hello") if hasattr(llm, "invoke") else llm("Hello")
            logger.info("✅ LLM test successful")
        except Exception as e:
            logger.warning(f"LLM test warning (non-critical): {e}")
            
    except Exception as e:
        logger.error(f"❌ LLM load failed: {e}")
        logger.error(traceback.format_exc())
        llm_instance = None

    # 2. ベクトルストアの読み込み
    try:
        from rag.ingested_text import load_vectorstore
        vectorstore = load_vectorstore()
        logger.info("✅ Vectorstore loaded successfully")
    except Exception as e:
        logger.warning(f"⚠️ Vectorstore load failed: {e}")
        vectorstore = None

    # 3. RAGチェーンの構築
    if vectorstore:
        try:
            if llm_instance:
                from rag.ingested_text import get_rag_chain
                rag_chain_template = get_rag_chain(vectorstore=vectorstore, return_source=True)
                logger.info("✅ RAG chain created with LLM")
            else:
                # LLMなしの検索専用チェーン
                class SimpleSearchChain:
                    def __init__(self, vectorstore):
                        self.vectorstore = vectorstore
                        self.retriever = vectorstore.as_retriever()
                        self.callbacks = []

                    def invoke(self, inputs):
                        query = inputs.get("query", "")
                        docs = self.retriever.get_relevant_documents(query)
                        
                        if docs:
                            result = "関連文書が見つかりました:\n\n"
                            for i, doc in enumerate(docs[:3], 1):
                                result += f"{i}. {doc.page_content[:200]}...\n"
                                result += f"   出典: {doc.metadata.get('source', '不明')} "
                                result += f"(p{doc.metadata.get('page', '?')})\n\n"
                        else:
                            result = "関連する文書が見つかりませんでした。"
                        
                        return {"result": result, "source_documents": docs[:3]}

                rag_chain_template = SimpleSearchChain(vectorstore)
                logger.info("✅ Search-only chain created")
        except Exception as e:
            logger.error(f"❌ RAG chain creation failed: {e}")
            logger.error(traceback.format_exc())
            rag_chain_template = None

    # 起動完了ログ
    logger.info("=== Startup Complete ===")
    logger.info(f"  LLM: {'✅ Loaded' if llm_instance else '❌ Not loaded'}")
    logger.info(f"  VectorStore: {'✅ Loaded' if vectorstore else '❌ Not loaded'}")
    logger.info(f"  RAG Chain: {'✅ Created' if rag_chain_template else '❌ Not created'}")
    logger.info(f"  LINE Bot: {'✅ Configured' if os.environ.get('LINE_CHANNEL_ACCESS_TOKEN') else '❌ Not configured'}")
    logger.info("========================")

# ルーター登録
from api.routers import upload, chat, google_oauth, healthz, line_bot

app.include_router(upload.router, prefix="/upload", tags=["upload"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(google_oauth.router, tags=["auth"])
app.include_router(healthz.router, prefix="", tags=["healthz"])
app.include_router(line_bot.router, tags=["line"])
app.include_router(liff_auth.router, tags=["liff"])
app.include_router(line_login.router, tags=["line-login"])

# 静的ファイル
pdf_dir = os.path.join("rag", "vectorstore", "pdfs")
if os.path.isdir(pdf_dir):
    app.mount("/pdfs", StaticFiles(directory=pdf_dir), name="pdfs")

# ルートエンドポイント
@app.get("/")
def read_root():
    """ルートエンドポイント"""
    return {
        "message": "RAG FastAPI Backend with LINE Bot",
        "version": "1.0.0",
        "status": {
            "llm": llm_instance is not None,
            "vectorstore": vectorstore is not None,
            "rag_chain": rag_chain_template is not None,
            "line_bot": bool(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
        }
    }

@app.get("/status")
def get_status():
    """システムステータス確認"""
    return {
        "llm_loaded": llm_instance is not None,
        "vectorstore_loaded": vectorstore is not None,
        "rag_chain_loaded": rag_chain_template is not None,
        "openai_api_key_set": bool(os.environ.get("OPENAI_API_KEY")),
        "gcs_bucket": os.environ.get("GCS_BUCKET_NAME", "Not set"),
        "line_bot_configured": bool(
            os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") and 
            os.environ.get("LINE_CHANNEL_SECRET")
        ),
        "langsmith_enabled": os.environ.get("LANGCHAIN_TRACING_V2") == "true"
    }

# デバッグエンドポイント
@app.get("/debug/env")
def debug_env():
    """環境変数デバッグ情報"""
    return {
        "environment": os.environ.get("ENV"),
        "openai_api_key_set": bool(os.environ.get("OPENAI_API_KEY")),
        "gcs_bucket": os.environ.get("GCS_BUCKET_NAME"),
        "line_channel_access_token_set": bool(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")),
        "line_channel_secret_set": bool(os.environ.get("LINE_CHANNEL_SECRET")),
        "langsmith_api_key_set": bool(os.environ.get("LANGSMITH_API_KEY")),
        "langchain_tracing": os.environ.get("LANGCHAIN_TRACING_V2"),
        "langchain_project": os.environ.get("LANGCHAIN_PROJECT"),
        "total_env_vars": len(os.environ)
    }

@app.get("/debug/langsmith-test")
def test_langsmith():
    """LangSmith接続テスト"""
    try:
        langsmith_key = os.environ.get("LANGSMITH_API_KEY")
        tracing_enabled = os.environ.get("LANGCHAIN_TRACING_V2")
        
        if not langsmith_key:
            return {"status": "error", "message": "LANGSMITH_API_KEY not found"}
        
        if tracing_enabled != "true":
            return {
                "status": "error", 
                "message": f"LANGCHAIN_TRACING_V2 is '{tracing_enabled}', should be 'true'"
            }
        
        from langsmith import Client
        client = Client(api_key=langsmith_key)
        
        return {
            "status": "success",
            "client_created": True,
            "project": os.environ.get("LANGCHAIN_PROJECT"),
            "key_prefix": langsmith_key[:10] + "...",
            "tracing_enabled": tracing_enabled
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/debug/liff")
def debug_liff():
    """LIFF設定のデバッグ情報"""
    return {
        "line_login_channel_id": bool(os.environ.get("LINE_LOGIN_CHANNEL_ID")),
        "line_login_channel_secret": bool(os.environ.get("LINE_LOGIN_CHANNEL_SECRET")),
        "liff_app_id": os.environ.get("LIFF_APP_ID"),
        "jwt_secret_set": bool(os.environ.get("JWT_SECRET")),
        "api_url": os.environ.get("API_URL")
    }    

@app.get("/debug/line-login")
def debug_line_login():
    """LINEログイン設定のデバッグ情報"""
    return {
        "line_login_channel_id": bool(os.environ.get("LINE_LOGIN_CHANNEL_ID")),
        "line_login_channel_secret": bool(os.environ.get("LINE_LOGIN_CHANNEL_SECRET")),
        "jwt_secret_set": bool(os.environ.get("JWT_SECRET")),
        "callback_url": f"{os.environ.get('API_URL')}/line-login/callback",
        "auth_url": f"{os.environ.get('API_URL')}/line-login/auth",
        "frontend_url": os.environ.get("FRONTEND_URL"),
    }

# CORS preflight handling
@app.options("/{path:path}")
async def handle_options(path: str):
    """CORS preflight requests"""
    return JSONResponse(
        content={"message": "OK"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)