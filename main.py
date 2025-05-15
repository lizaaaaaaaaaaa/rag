import os
from fastapi import FastAPI
from dotenv import load_dotenv

# ✅ 開発環境用に .env を読み込む（Cloud Run では環境変数から直接読み取られる）
load_dotenv()

from api.routers import chat
from auth import google_oauth

app = FastAPI(
    title="RAG FastAPI Backend",
    description="RAG + LLM連携 API（Cloud Run対応）",
    version="1.0.0"
)

app.include_router(chat.router, prefix="/chat")
app.include_router(google_oauth.router, prefix="/auth")

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI on Cloud Run!"}

# ✅ ローカル用起動コード（Cloud Runでは使われない）
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)

