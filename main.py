import os

# --- Cloud Run環境変数デバッグ出力 ---
print("==== DEBUG: OPENAI_API_KEY =", (os.environ.get("OPENAI_API_KEY") or "")[:10], "**** ====")
print("==== DEBUG: USE_LOCAL_LLM =", os.environ.get("USE_LOCAL_LLM"))
print("==== DEBUG: GOOGLE_CLIENT_ID:", os.environ.get("GOOGLE_CLIENT_ID"))
print("==== DEBUG: GOOGLE_CLIENT_SECRET:", os.environ.get("GOOGLE_CLIENT_SECRET"))
print("==== DEBUG: GOOGLE_REDIRECT_URI:", os.environ.get("GOOGLE_REDIRECT_URI"))
print("==== DEBUG: JWT_SECRET:", os.environ.get("JWT_SECRET"))

# --- ローカルだけ .env を読む ---
if os.getenv("ENV") != "production":
    from dotenv import load_dotenv
    load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# --- 本番フロントURL ---
FRONTEND_URL = "https://rag-frontend-190389115361.asia-northeast1.run.app"

# --- FastAPIアプリ ---
app = FastAPI(
    title="RAG FastAPI Backend",
    description="RAG + LLM連携 API（Cloud Run対応）",
    version="1.0.0"
)

# --- CORS設定 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- モデル・ベクトルストアのキャッシュ用グローバル変数 ---
vectorstore = None
rag_chain_template = None

# --- 起動時に一度だけモデル＆ベクトルストアを読み込む ---
@app.on_event("startup")
async def load_models_on_startup():
    """
    Cloud Run コンテナが立ち上がる（＝FastAPIアプリケーションが起動する）タイミングで、
    RAG チェーンを構築するための下準備（モデルロードやベクトルストア読み込み）を一度だけ行います。
    """
    global vectorstore, rag_chain_template

    from rag.ingested_text import load_vectorstore, get_rag_chain

    print("=== startup event: loading vectorstore & rag_chain_template ===")
    # 1) ベクトルストアを一度だけ読み込む
    vectorstore = load_vectorstore()  # 既存の vectorstore ディレクトリや GCS から読み込む想定

    # 2) LLM とベクトルストアを組み合わせた RAG チェーンの「雛形」を作成
    #    DUMMY_QUESTION は実際には使わないダミー。invoke() 呼び出し時に query を差し替えます。
    rag_chain_template = get_rag_chain(
        vectorstore=vectorstore,
        return_source=True,
        question="DUMMY_QUESTION"
    )
    print("=== startup event completed ===")


# --- ルーター分割 ---
print("=== before router imports ===")
from api.routers import upload, chat, google_oauth, healthz
print("=== after router imports ===")

# --- ルーター登録 ---
app.include_router(upload.router, prefix="/upload", tags=["upload"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(google_oauth.router, tags=["auth"])
app.include_router(healthz.router, prefix="", tags=["healthz"])

# --- 静的ファイル ---
pdf_dir = os.path.join("rag", "vectorstore", "pdfs")
if os.path.isdir(pdf_dir):
    app.mount("/pdfs", StaticFiles(directory=pdf_dir), name="pdfs")

# --- ルートテスト ---
@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI on Cloud Run!"}


# --- ローカル実行用 ---
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
