import os

# --- ローカルだけ .env を読む ---
if os.getenv("ENV") != "production":
    from dotenv import load_dotenv
    load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# --- FastAPIアプリ ---
app = FastAPI(
    title="RAG FastAPI Backend",
    description="RAG + LLM連携 API（Cloud Run対応）",
    version="1.0.0"
)

# --- CORS設定（本番はallow_origins推奨ドメインに絞ってね！）---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://rag-frontend-190389115361.asia-northeast1.run.app"],  # ここに本番のフロントURL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ルーター分割（import順は好みだけど一応コメントで可視化！）---
print("=== before healthz import ===")
from api.routers import upload, chat, google_oauth, healthz
print("=== after healthz import ===")

# --- ルーター登録 ---
app.include_router(upload.router, prefix="/upload", tags=["upload"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])  # <--- ココが重要！
app.include_router(google_oauth.router, tags=["auth"])
app.include_router(healthz.router, prefix="", tags=["healthz"])  # prefix=""で直下（/healthz）

# --- 静的ファイル（PDF公開用） ---
pdf_dir = os.path.join("rag", "vectorstore", "pdfs")
if os.path.isdir(pdf_dir):
    app.mount("/pdfs", StaticFiles(directory=pdf_dir), name="pdfs")

# --- ルートテスト（任意・Swagger以外にも） ---
@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI on Cloud Run!"}

# --- ローカル実行用（Cloud Runだと不要だけど、デバッグには◎） ---
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
