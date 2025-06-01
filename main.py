import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

print("==== DEBUG: ENV =", os.environ.get("ENV"))
print("==== DEBUG: OPENAI_API_KEY =", (os.environ.get("OPENAI_API_KEY") or "")[:10], "****")
print("==== DEBUG: USE_LOCAL_LLM =", os.environ.get("USE_LOCAL_LLM"))
print("==== DEBUG: GOOGLE_CLIENT_ID:", os.environ.get("GOOGLE_CLIENT_ID"))
print("==== DEBUG: GOOGLE_CLIENT_SECRET:", os.environ.get("GOOGLE_CLIENT_SECRET"))
print("==== DEBUG: GOOGLE_REDIRECT_URI:", os.environ.get("GOOGLE_REDIRECT_URI"))
print("==== DEBUG: JWT_SECRET:", os.environ.get("JWT_SECRET"))

if os.getenv("ENV") != "production":
    from dotenv import load_dotenv
    load_dotenv(".env")
    print(">>> Loaded .env for local development")
else:
    print(">>> Running in production mode, skipping .env load")

FRONTEND_URL = "https://rag-frontend-190389115361.asia-northeast1.run.app"

app = FastAPI(
    title="RAG FastAPI Backend",
    description="RAG + LLM 連携 API (Cloud Run 対応)",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

vectorstore = None
rag_chain_template = None

@app.on_event("startup")
async def load_models_on_startup():
    """
    アプリ起動時にLLM→ベクトルストア→RAGチェーンの順で初期化。
    失敗しても空ベクトルストアで復旧し、すべての状況をprintで残す。
    """
    global vectorstore, rag_chain_template

    print("=== startup: begin loading vectorstore & rag_chain_template ===")

    # 1) LLMロード
    try:
        from llm.llm_runner import load_llm
        llm, tokenizer, max_tokens = load_llm()
        print(f">>> LLM loaded successfully: {type(llm).__name__}")
    except Exception as e:
        print(f"!!! LLM load failed: {e}")
        return

    # 2) ベクトルストア読み込み（失敗したら空で初期化）
    try:
        from rag.ingested_text import load_vectorstore
        vectorstore = load_vectorstore()
        print(">>> vectorstore loaded successfully")
    except Exception as e:
        print(f"!!! WARNING: load_vectorstore() failed: {e}")
        print(">>> Creating empty vectorstore for initial setup")
        from rag.ingested_text import MyEmbedding
        from langchain_community.vectorstores import FAISS
        from langchain.schema import Document
        embeddings = MyEmbedding("intfloat/multilingual-e5-small")
        dummy_doc = Document(page_content="初期化用ダミーテキスト", metadata={"source": "init", "page": 1})
        vectorstore = FAISS.from_documents([dummy_doc], embeddings)
        print(">>> Empty vectorstore created")

    # 3) RAG チェーン構築
    try:
        if vectorstore:
            from rag.ingested_text import get_rag_chain
            rag_chain_template = get_rag_chain(
                vectorstore=vectorstore,
                return_source=True,
                question="DUMMY_QUESTION"
            )
            print(">>> rag_chain_template constructed successfully")
        else:
            print(">>> vectorstore is None, creating basic chain template")
            rag_chain_template = None
    except Exception as e:
        print(f"!!! WARNING: get_rag_chain() failed: {e}")
        rag_chain_template = None

    print("=== startup: done ===")

print("=== before router imports ===")
from api.routers import upload, chat, google_oauth, healthz
print("=== after router imports ===")

# ルーターprefixそのまま運用！ 例: /upload/ingest
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
