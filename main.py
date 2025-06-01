import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

print("==== DEBUG: ENV =", os.environ.get("ENV"))
print("==== DEBUG: OPENAI_API_KEY =", (os.environ.get("OPENAI_API_KEY") or "")[:10], "****")
print("==== DEBUG: USE_LOCAL_LLM =", os.environ.get("USE_LOCAL_LLM"))
print("==== DEBUG: GOOGLE_CLIENT_ID:", os.environ.get("GOOGLE_CLIENT_ID"))
print("==== DEBUG: GOOGLE_CLIENT_SECRET:", os.environ.get("GOOGLE_CLIENT_SECRET"))
print("==== DEBUG: GOOGLE_REDIRECT_URI:", os.environ.get("GOOGLE_REDIRECT_URI"))
print("==== DEBUG: JWT_SECRET:", os.environ.get("JWT_SECRET"))

if os.getenv("ENV") != "production":
    # ローカル開発用に .env をロード
    from dotenv import load_dotenv
    # .env ファイルがある場合に読み込む
    load_dotenv(".env")
    print(">>> Loaded .env for local development")
else:
    print(">>> Running in production mode, skipping .env load")


FRONTEND_URL = "https://rag-frontend-190389115361.asia-northeast1.run.app"

# FastAPI アプリ作成
app = FastAPI(
    title="RAG FastAPI Backend",
    description="RAG + LLM 連携 API (Cloud Run 対応)",
    version="1.0.0"
)

# CORS 設定：フロントエンドの URL だけを許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

vectorstore = None
rag_chain_template = None

@app.on_event("startup")
async def load_models_on_startup():
    """
    アプリ起動時に一度だけベクトルストアを読み込み＆RAGチェーンを構築する。
    例外はキャッチして、Cloud Run のログに出力するだけに留める。
    """
    global vectorstore, rag_chain_template

    # RAG 関連のヘルパーをインポート
    from rag.ingested_text import load_vectorstore, get_rag_chain

    print("=== startup: begin loading vectorstore & rag_chain_template ===")
    # 1) ベクトルストア読み込み
    try:
        vectorstore = load_vectorstore()
        print(">>> vectorstore loaded successfully")
    except Exception as e:
        print("!!! WARNING: load_vectorstore() failed:", e)
        vectorstore = None

    # 2) RAG チェーンの構築
    try:
        if vectorstore:
            # DUMMY_QUESTION はサンプル用。実際に invoke() 時には query を渡す。
            rag_chain_template = get_rag_chain(
                vectorstore=vectorstore,
                return_source=True,
                question="DUMMY_QUESTION"
            )
            print(">>> rag_chain_template constructed successfully")
        else:
            print(">>> vectorstore is None, skipping get_rag_chain")
    except Exception as e:
        print("!!! WARNING: get_rag_chain() failed:", e)
        rag_chain_template = None

    print("=== startup: done ===")


print("=== before router imports ===")
from api.routers import upload, chat, google_oauth, healthz
print("=== after router imports ===")

# ルーターをマウント
app.include_router(upload.router, prefix="/upload", tags=["upload"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(google_oauth.router, tags=["auth"])
app.include_router(healthz.router, prefix="", tags=["healthz"])

# PDF 配下を静的ファイルで公開（あれば）
pdf_dir = os.path.join("rag", "vectorstore", "pdfs")
if os.path.isdir(pdf_dir):
    app.mount("/pdfs", StaticFiles(directory=pdf_dir), name="pdfs")


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI on Cloud Run!"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
