import os

# --- ローカルだけ .env を読む ---
if os.getenv("ENV") != "production":
    from dotenv import load_dotenv
    load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# --- ★Cloud Runログ用に主要環境変数をデバッグ出力 ---
print("==== GOOGLE_CLIENT_ID:", os.environ.get("GOOGLE_CLIENT_ID"), "====")
print("==== GOOGLE_CLIENT_SECRET:", os.environ.get("GOOGLE_CLIENT_SECRET"), "====")
print("==== GOOGLE_REDIRECT_URI:", os.environ.get("GOOGLE_REDIRECT_URI"), "====")
print("==== JWT_SECRET:", os.environ.get("JWT_SECRET"), "====")  # JWTもチェック
print("==== OPENAI_API_KEY:", (os.environ.get("OPENAI_API_KEY") or "")[:5], "**** ====")

# --- 本番フロントURLを1か所で管理 ---
FRONTEND_URL = "https://rag-frontend-190389115361.asia-northeast1.run.app"

# --- FastAPIアプリ ---
app = FastAPI(
    title="RAG FastAPI Backend",
    description="RAG + LLM連携 API（Cloud Run対応）",
    version="1.0.0"
)

# --- CORS設定（本番はallow_origins推奨ドメインに絞ってね！）---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],  # ← 本番はフロントURLだけ厳守！
    allow_credentials=True,        # Cookie認証時は必須
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ルーター分割 ---
print("=== before healthz import ===")
from api.routers import upload, chat, google_oauth, healthz
print("=== after healthz import ===")

# --- ルーター登録 ---
app.include_router(upload.router, prefix="/upload", tags=["upload"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])    # POST /chat でRAG
app.include_router(google_oauth.router, tags=["auth"])            # Google OAuth
app.include_router(healthz.router, prefix="", tags=["healthz"])   # /healthz

# --- 静的ファイル（PDF公開用） ---
pdf_dir = os.path.join("rag", "vectorstore", "pdfs")
if os.path.isdir(pdf_dir):
    app.mount("/pdfs", StaticFiles(directory=pdf_dir), name="pdfs")

# --- ルートテスト ---
@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI on Cloud Run!"}

# --- ローカル実行用（Cloud Runでは不要） ---
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
