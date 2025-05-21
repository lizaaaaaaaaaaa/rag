import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles

# .envの読み込み（Cloud Run上は不要だけどローカル開発用）
load_dotenv()

# FastAPIアプリ作成
app = FastAPI(
    title="RAG FastAPI Backend",
    description="RAG + LLM連携 API（Cloud Run対応）",
    version="1.0.0"
)

# CORS（本番は制限推奨！）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== ルーター分割・インポート =====
from api.routers import healthz, upload, chat, google_oauth

# ===== ルーター登録（healthzは一番最初に） =====
app.include_router(healthz.router, prefix="", tags=["healthz"])
app.include_router(upload.router, prefix="", tags=["upload"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(google_oauth.router, prefix="/auth", tags=["auth"])

# ===== 静的ファイル（PDF）の公開 =====
pdf_dir = os.path.join("rag", "vectorstore", "pdfs")
if not os.path.exists(pdf_dir):
    os.makedirs(pdf_dir, exist_ok=True)  # 必要なら自動作成
app.mount("/pdfs", StaticFiles(directory=pdf_dir), name="pdfs")

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI on Cloud Run!"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
