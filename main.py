import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles

load_dotenv()

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
from api.routers import upload, chat, google_oauth, healthz  # ← healthzを追加！
#from api import users  # ← users.py（FastAPI-Users用/自作ユーザー管理用）

# ===== ルーター登録 =====
app.include_router(upload.router, prefix="", tags=["upload"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(google_oauth.router, prefix="/auth", tags=["auth"])
app.include_router(healthz.router, prefix="", tags=["healthz"])  # ← 追加！

# --- FastAPI-Usersなど追加する場合 ---
# 例:
# app.include_router(users.fastapi_users.get_auth_router(users.auth_backend), prefix="/auth/jwt", tags=["auth"])
# app.include_router(users.fastapi_users.get_register_router(), prefix="/auth", tags=["auth"])
# app.include_router(
#     users.fastapi_users.get_oauth_router(
#         users.google_oauth_backend,
#         state_secret="YOUR_RANDOM_SECRET",    # ランダム文字列でOK
#         redirect_url="http://localhost:3000"  # ログイン後フロントエンドURL
#     ),
#     prefix="/auth/google",
#     tags=["auth"]
# )

# ===== 静的ファイル（PDF）の公開 =====
pdf_dir = os.path.join("rag", "vectorstore", "pdfs")
app.mount("/pdfs", StaticFiles(directory=pdf_dir), name="pdfs")

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI on Cloud Run!"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
