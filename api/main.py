from fastapi import FastAPI
from routers import chat

app = FastAPI(title="RAG API")

app.include_router(chat.router)

