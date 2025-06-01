# main.py

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# --- 環境変数デバッグ (Cloud Run のログに出ます) ---
print("==== DEBUG: OPENAI_API_KEY =", (os.environ.get("OPENAI_API_KEY") or "")[:10], "**** ====")
print("==== DEBUG: USE_LOCAL_LLM =", os.environ.get("USE_LOCAL_LLM"))
print("==== DEBUG: GOOGLE_CLIENT_ID:", os.environ.get("GOOGLE_CLIENT_ID"))
print("==== DEBUG: GOOGLE_CLIENT_SECRET:", os.environ.get("GOOGLE_CLIENT_SECRET"))
print("==== DEBUG: GOOGLE_REDIRECT_URI:", os.environ.get("GOOGLE_REDIRECT_URI"))
print("==== DEBUG: JWT_SECRET:", os.environ.get("JWT_SECRET"))

if os.getenv("ENV") != "production":
    from dotenv import load_dotenv
    load_dotenv()

# --- 本番 Frontend URL ---
FRONTEND_URL = "https://rag-frontend-190389115361.asia-northeast1.run.app"

app = FastAPI(
    title="RAG FastAPI Backend",
    description="RAG + LLM 連携 API (Cloud Run 対応)",
    version="1.0.0"
)

# --- CORS 設定 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# startup event 用のグローバルキャッシュ
vectorstore = None
rag_chain_template = None

@app.on_event("startup")
async def load_models_on_startup():
    """
    起動時に一度だけベクトルストア読み込み & RAGチェーン構築を試みる。
    例外はキャッチしてアプリケーション自体がクラッシュしないようにする。
    """
    global vectorstore, rag_chain_template

    from rag.ingested_text import load_vectorstore, get_rag_chain

    print("=== startup: begin loading vectorstore & rag_chain_template ===")
    try:
        vectorstore = load_vectorstore()
        print(">>> vectorstore loaded successfully")
    except Exception as e:
        print("!!! WARNING: load_vectorstore() failed:", e)
        vectorstore = None

    try:
        if vectorstore:
            # DUMMY_QUESTION は実際には使わない。invoke() 時に query を渡す。
            rag_chain_template = get_rag_chain(
                vectorstore=vectorstore,
                return_source=True,
                question="DUMMY_QUESTION"
            )
            print(">>> rag_chain_template constructed successfully")
    except Exception as e:
        print("!!! WARNING: get_rag_chain() failed:", e)
        rag_chain_template = None

    print("=== startup: done ===")


print("=== before router imports ===")
from api.routers import upload, chat, google_oauth, healthz
print("=== after router imports ===")

app.include_router(upload.router, prefix="/upload", tags=["upload"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(google_oauth.router, tags=["auth"])
app.include_router(healthz.router, prefix="", tags=["healthz"])

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
