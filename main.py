import os
import sys
import traceback
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# .env 読み込み（ローカルのみ）
if os.getenv("ENV") != "production":
    from dotenv import load_dotenv
    load_dotenv(".env")
    logger.info(">>> Loaded .env for local development")
else:
    logger.info(">>> Running in production mode")

# 環境変数ログ（LangSmith含む）
logger.info("==== DEBUG: ENV = %s", os.environ.get("ENV"))
logger.info("==== DEBUG: OPENAI_API_KEY = %s****", (os.environ.get("OPENAI_API_KEY") or "")[:10])
logger.info("==== DEBUG: GCS_BUCKET_NAME = %s", os.environ.get("GCS_BUCKET_NAME"))
logger.info("==== DEBUG: LINE_CHANNEL_ACCESS_TOKEN = %s****", (os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or "")[:10])
logger.info("==== DEBUG: LINE_CHANNEL_SECRET = %s****", (os.environ.get("LINE_CHANNEL_SECRET") or "")[:10])
logger.info("==== DEBUG: LANGSMITH_API_KEY = %s****", (os.environ.get("LANGSMITH_API_KEY") or "")[:10])
logger.info("==== DEBUG: LANGCHAIN_TRACING_V2 = %s", os.environ.get("LANGCHAIN_TRACING_V2"))
logger.info("==== DEBUG: LANGCHAIN_PROJECT = %s", os.environ.get("LANGCHAIN_PROJECT"))

# FastAPI 初期化
app = FastAPI(
    title="RAG FastAPI Backend with LINE Bot + LangSmith",
    description="RAG + LLM 連携 API (Cloud Run対応) + LINE Messaging API + LangSmith",
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

# CSPヘッダー
@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'self' https:; script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; style-src 'self' 'unsafe-inline' https:;"
    return response

# グローバル変数
vectorstore = None
rag_chain_template = None
llm_instance = None

@app.on_event("startup")
async def load_models_on_startup():
    global vectorstore, rag_chain_template, llm_instance

    logger.info("=== startup: begin loading models ===")
    logger.info(f"LANGCHAIN_TRACING_V2: {os.environ.get('LANGCHAIN_TRACING_V2', 'not set')}")
    logger.info(f"DISABLE_LANGSMITH: {os.environ.get('DISABLE_LANGSMITH', 'not set')}")

    # LLMロード
    try:
        from llm.llm_runner import load_llm
        llm, tokenizer, max_tokens = load_llm()
        llm_instance = llm
        logger.info(f"✅ LLM loaded successfully: {type(llm).__name__}")
        try:
            result = llm.invoke("Hello") if hasattr(llm, "invoke") else llm("Hello")
            logger.info("✅ LLM test successful")
        except Exception as e:
            logger.warning(f"LLM test warning: {e}")
    except Exception as e:
        logger.error(f"❌ LLM load failed: {e}")
        logger.error(traceback.format_exc())
        llm_instance = None

    # ベクトルストア
    try:
        from rag.ingested_text import load_vectorstore
        vectorstore = load_vectorstore()
        logger.info("✅ Vectorstore loaded successfully")
    except Exception as e:
        logger.warning(f"⚠️ Vectorstore load failed: {e}")
        vectorstore = None

    # RAGチェーン構築
    if vectorstore:
        try:
            if llm_instance:
                from rag.ingested_text import get_rag_chain
                rag_chain_template = get_rag_chain(vectorstore=vectorstore, return_source=True)
                logger.info("✅ RAG chain created with LLM")
            else:
                from langchain.chains import RetrievalQA
                from langchain.schema import BaseRetriever

                class SimpleSearchChain:
                    def __init__(self, vectorstore):
                        self.retriever = vectorstore.as_retriever()

                    def invoke(self, inputs):
                        query = inputs.get("query", "")
                        docs = self.retriever.get_relevant_documents(query)
                        result = "関連文書が見つかりました:\n\n" if docs else "関連する文書が見つかりませんでした。"
                        for i, doc in enumerate(docs[:3], 1):
                            result += f"{i}. {doc.page_content[:200]}...\n"
                            result += f"   出典: {doc.metadata.get('source', '不明')} (p{doc.metadata.get('page', '?')})\n\n"
                        return {"result": result, "source_documents": docs[:3]}

                rag_chain_template = SimpleSearchChain(vectorstore)
                logger.info("✅ Search-only chain created")
        except Exception as e:
            logger.error(f"❌ RAG chain creation failed: {e}")
            logger.error(traceback.format_exc())
            rag_chain_template = None

    logger.info("=== Startup complete ===")
    logger.info(f"  - LLM: {'✅ Loaded' if llm_instance else '❌ Not loaded'}")
    logger.info(f"  - VectorStore: {'✅ Loaded' if vectorstore else '❌ Not loaded'}")
    logger.info(f"  - RAG Chain: {'✅ Created' if rag_chain_template else '❌ Not created'}")

# ルーター登録
from api.routers import upload, chat, google_oauth, healthz, line_bot
app.include_router(upload.router, prefix="/upload", tags=["upload"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(google_oauth.router, tags=["auth"])
app.include_router(healthz.router, prefix="", tags=["healthz"])
app.include_router(line_bot.router, tags=["line"])

# 静的ファイルマウント
pdf_dir = os.path.join("rag", "vectorstore", "pdfs")
if os.path.isdir(pdf_dir):
    app.mount("/pdfs", StaticFiles(directory=pdf_dir), name="pdfs")

# ルート
@app.get("/")
def read_root():
    return {
        "message": "Hello from FastAPI on Cloud Run with LINE Bot + LangSmith!",
        "status": {
            "llm": llm_instance is not None,
            "vectorstore": vectorstore is not None,
            "rag_chain": rag_chain_template is not None,
            "line_bot": bool(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
        }
    }

@app.get("/status")
def get_status():
    return {
        "llm_loaded": llm_instance is not None,
        "vectorstore_loaded": vectorstore is not None,
        "rag_chain_loaded": rag_chain_template is not None,
        "openai_api_key_set": bool(os.environ.get("OPENAI_API_KEY")),
        "gcs_bucket": os.environ.get("GCS_BUCKET_NAME", "Not set"),
        "line_bot_configured": bool(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") and os.environ.get("LINE_CHANNEL_SECRET")),
        "langsmith_enabled": os.environ.get("LANGCHAIN_TRACING_V2") == "true"
    }

@app.get("/debug/env")
def debug_env():
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
    try:
        from langsmith import Client
        key = os.environ.get("LANGSMITH_API_KEY")
        tracing = os.environ.get("LANGCHAIN_TRACING_V2")
        if not key:
            return {"status": "error", "message": "LANGSMITH_API_KEY not found"}
        if tracing != "true":
            return {"status": "error", "message": f"LANGCHAIN_TRACING_V2 must be 'true', got '{tracing}'"}
        client = Client(api_key=key)
        return {
            "status": "success",
            "client_created": True,
            "project": os.environ.get("LANGCHAIN_PROJECT"),
            "key_prefix": key[:10] + "...",
            "tracing_enabled": tracing
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.options("/{path:path}")
async def handle_options(path: str):
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