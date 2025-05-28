# Force new build trigger on [日付]

import os

# ローカル環境だけ .env を読み込み
if os.getenv("ENV") != "production":
    from dotenv import load_dotenv
    load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="RAG FastAPI Backend",
    description="RAG + LLM連携 API（Cloud Run対応）",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 本番は制限推奨
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== ルーター分割・インポート =====
print("=== before healthz import ===")    # ←ここ！
from api.routers import upload, chat, google_oauth, healthz
print("=== after healthz import ===")     # ←ここ！

# ===== ルーター登録 =====
app.include_router(upload.router, prefix="/upload", tags=["upload"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(google_oauth.router, tags=["auth"])
app.include_router(healthz.router, prefix="", tags=["healthz"])  # prefix=""で直下

# ===== 静的ファイル（PDF）の公開 =====
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
