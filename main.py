import os
from fastapi import FastAPI
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

if __name__ == "__main__" and os.getenv("CLOUD_RUN", "false").lower() != "true":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)