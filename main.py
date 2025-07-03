# main.py（CORS設定追加・完全版）
import os
import traceback
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import logging
import sys

# ログ設定を最初に
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 環境変数のデバッグログ
logger.info("==== DEBUG: ENV = %s", os.environ.get("ENV"))
logger.info("==== DEBUG: OPENAI_API_KEY = %s****", (os.environ.get("OPENAI_API_KEY") or "")[:10])
logger.info("==== DEBUG: GCS_BUCKET_NAME = %s", os.environ.get("GCS_BUCKET_NAME"))

if os.getenv("ENV") != "production":
    from dotenv import load_dotenv
    load_dotenv(".env")
    logger.info(">>> Loaded .env for local development")
else:
    logger.info(">>> Running in production mode")

# ★NetlifyやStudioのiframe埋め込み用にCORS許可するURLをリストアップ
ALLOWED_ORIGINS = [
    "https://leafy-kitsune-eb4566.netlify.app",  # ←Netlify公開URLに置き換え
    "http://localhost:3000",
    "http://localhost:8501"
]

app = FastAPI(
    title="RAG FastAPI Backend",
    description="RAG + LLM 連携 API (Cloud Run 対応)",
    version="1.0.0"
)

# ▼ここでCORSを許可！
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,  # 本番は必要なドメインのみ
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# グローバル変数
vectorstore = None
rag_chain_template = None
llm_instance = None

@app.on_event("startup")
async def load_models_on_startup():
    global vectorstore, rag_chain_template, llm_instance
    # ...（以降は元のコードと同じなので省略）...

# ---以下、ルーターなどは元のコードと同じ---
from api.routers import upload, chat, google_oauth, healthz

app.include_router(upload.router, prefix="/upload", tags=["upload"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(google_oauth.router, tags=["auth"])
app.include_router(healthz.router, prefix="", tags=["healthz"])

# 静的ファイルマウント
pdf_dir = os.path.join("rag", "vectorstore", "pdfs")
if os.path.isdir(pdf_dir):
    app.mount("/pdfs", StaticFiles(directory=pdf_dir), name="pdfs")

@app.get("/")
def read_root():
    return {
        "message": "Hello from FastAPI on Cloud Run!",
        "status": {
            "llm": llm_instance is not None,
            "vectorstore": vectorstore is not None,
            "rag_chain": rag_chain_template is not None
        }
    }

@app.get("/status")
def get_status():
    """システムステータス確認用エンドポイント"""
    return {
        "llm_loaded": llm_instance is not None,
        "vectorstore_loaded": vectorstore is not None,
        "rag_chain_loaded": rag_chain_template is not None,
        "openai_api_key_set": bool(os.environ.get("OPENAI_API_KEY")),
        "gcs_bucket": os.environ.get("GCS_BUCKET_NAME", "Not set")
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
