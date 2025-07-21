import os
import traceback
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import logging
import sys

# ログ設定を最初に
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 環境変数のデバッグログ
logger.info("==== DEBUG: ENV = %s", os.environ.get("ENV"))
logger.info("==== DEBUG: OPENAI_API_KEY = %s****", (os.environ.get("OPENAI_API_KEY") or "")[:10])
logger.info("==== DEBUG: GCS_BUCKET_NAME = %s", os.environ.get("GCS_BUCKET_NAME"))
logger.info("==== DEBUG: LANGSMITH_API_KEY = %s****", (os.environ.get("LANGSMITH_API_KEY") or "")[:10])
logger.info("==== DEBUG: LANGCHAIN_TRACING_V2 = %s", os.environ.get("LANGCHAIN_TRACING_V2"))
logger.info("==== DEBUG: LANGCHAIN_PROJECT = %s", os.environ.get("LANGCHAIN_PROJECT"))

if os.getenv("ENV") != "production":
    from dotenv import load_dotenv
    load_dotenv(".env")
    logger.info(">>> Loaded .env for local development")
else:
    logger.info(">>> Running in production mode")

# FastAPIアプリケーションの初期化
app = FastAPI(
    title="RAG FastAPI Backend",
    description="RAG + LLM 連携 API (Cloud Run 対応)",
    version="1.0.0"
)

# ★★★ 修正: 正しいCORS設定（重複を削除し、正しいオリジンを追加）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://leafy-kitsune-eb4566.netlify.app",  # Netlify URL
        "https://preview.studio.site/live/EjOQljz1WJ",  # Studio preview domain
        "http://localhost:3000",
        "http://localhost:8501",
        "*"  # 開発用（本番では削除推奨）
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # OPTIONSを明示的に追加
    allow_headers=["*"],
    expose_headers=["*"]
)

# グローバル変数
vectorstore = None
rag_chain_template = None
llm_instance = None

@app.on_event("startup")
async def load_models_on_startup():
    global vectorstore, rag_chain_template, llm_instance
   
    logger.info("=== startup: begin loading models ===")
   
    # 1) LLM を確実にロード
    try:
        from llm.llm_runner import load_llm
        llm, tokenizer, max_tokens = load_llm()
        llm_instance = llm
        logger.info(f"✅ LLM loaded successfully: {type(llm).__name__}")
       
        # LLMのテスト
        try:
            if hasattr(llm, "invoke"):
                test_result = llm.invoke("Hello")
                logger.info(f"✅ LLM test successful")
            else:
                # ChatOpenAIの場合
                test_result = llm("Hello")
                logger.info(f"✅ LLM test successful")
        except Exception as e:
            logger.warning(f"LLM test warning: {e}")
           
    except Exception as e:
        logger.error(f"❌ LLM load failed: {e}")
        logger.error(traceback.format_exc())
        # LLMなしでも続行
        llm_instance = None
   
    # 2) ベクトルストアを確実にロード
    try:
        from rag.ingested_text import load_vectorstore
        vectorstore = load_vectorstore()
        logger.info("✅ Vectorstore loaded successfully")
    except Exception as e:
        logger.warning(f"⚠️ Vectorstore load failed, creating empty one: {e}")
        # 空のベクトルストアを作成
        try:
            from rag.ingested_text import MyEmbedding
            from langchain_community.vectorstores import FAISS
            from langchain.schema import Document
           
            embeddings = MyEmbedding("intfloat/multilingual-e5-small")
            dummy_docs = [
                Document(
                    page_content="システムは正常に動作しています。PDFをアップロードしてRAG検索を開始してください。",
                    metadata={"source": "システム初期化", "page": 1}
                ),
                Document(
                    page_content="RAG（Retrieval-Augmented Generation）は、検索と生成を組み合わせたAI技術です。",
                    metadata={"source": "システム初期化", "page": 2}
                )
            ]
            vectorstore = FAISS.from_documents(dummy_docs, embeddings)
           
            # ローカルに保存
            os.makedirs("rag/vectorstore", exist_ok=True)
            vectorstore.save_local("rag/vectorstore", index_name="index")
            logger.info("✅ Empty vectorstore created and saved")
           
        except Exception as e2:
            logger.error(f"❌ Failed to create empty vectorstore: {e2}")
            vectorstore = None
   
    # 3) RAG チェーンを構築
    if vectorstore:
        try:
            if llm_instance:
                # LLMがある場合は通常のRAGチェーンを構築
                from rag.ingested_text import get_rag_chain
                rag_chain_template = get_rag_chain(vectorstore=vectorstore, return_source=True)
                logger.info("✅ RAG chain created successfully with LLM")
            else:
                # LLMがない場合はシンプルな検索のみのチェーンを作成
                logger.info("⚠️ Creating search-only chain without LLM")
                from langchain.chains import RetrievalQA
                from langchain.schema import BaseRetriever
               
                # ダミーのチェーンオブジェクトを作成
                class SimpleSearchChain:
                    def __init__(self, vectorstore):
                        self.vectorstore = vectorstore
                        self.retriever = vectorstore.as_retriever()
                   
                    def invoke(self, inputs):
                        query = inputs.get("query", "")
                        docs = self.retriever.get_relevant_documents(query)
                        if docs:
                            result = f"関連文書が見つかりました:\n\n"
                            for i, doc in enumerate(docs[:3], 1):
                                result += f"{i}. {doc.page_content[:200]}...\n"
                                result += f"   出典: {doc.metadata.get('source', '不明')} (p{doc.metadata.get('page', '?')})\n\n"
                        else:
                            result = "関連する文書が見つかりませんでした。"
                       
                        return {
                            "result": result,
                            "source_documents": docs[:3]
                        }
               
                rag_chain_template = SimpleSearchChain(vectorstore)
                logger.info("✅ Search-only chain created")
               
        except Exception as e:
            logger.error(f"❌ RAG chain creation failed: {e}")
            logger.error(traceback.format_exc())
            rag_chain_template = None
   
    # ステータスログ
    logger.info(f"=== Startup complete ===")
    logger.info(f"  - LLM: {'✅ Loaded' if llm_instance else '❌ Not loaded'}")
    logger.info(f"  - VectorStore: {'✅ Loaded' if vectorstore else '❌ Not loaded'}")
    logger.info(f"  - RAG Chain: {'✅ Created' if rag_chain_template else '❌ Not created'}")

# ルーターをインポート
from api.routers import upload, chat, google_oauth, healthz

app.include_router(upload.router, prefix="/upload", tags=["upload"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(google_oauth.router, tags=["auth"])
app.include_router(healthz.router, prefix="", tags=["healthz"])

# 静的ファイルマウント
pdf_dir = os.path.join("rag", "vectorstore", "pdfs")
if os.path.isdir(pdf_dir):
    app.mount("/pdfs", StaticFiles(directory=pdf_dir), name="pdfs")

@app.get("/")
def read_root():
    return {
        "message": "Hello from FastAPI on Cloud Run!",
        "status": {
            "llm": llm_instance is not None,
            "vectorstore": vectorstore is not None,
            "rag_chain": rag_chain_template is not None
        }
    }

@app.get("/status")
def get_status():
    """システムステータス確認用エンドポイント"""
    return {
        "llm_loaded": llm_instance is not None,
        "vectorstore_loaded": vectorstore is not None,
        "rag_chain_loaded": rag_chain_template is not None,
        "openai_api_key_set": bool(os.environ.get("OPENAI_API_KEY")),
        "gcs_bucket": os.environ.get("GCS_BUCKET_NAME", "Not set")
    }

# デバッグエンドポイントの追加
@app.get("/debug/env")
def debug_env():
    """環境変数のデバッグ情報を返す"""
    return {
        "environment": os.environ.get("ENV"),
        "langsmith_api_key_set": bool(os.environ.get("LANGSMITH_API_KEY")),
        "langsmith_api_key_length": len(os.environ.get("LANGSMITH_API_KEY", "")),
        "langsmith_api_key_prefix": (os.environ.get("LANGSMITH_API_KEY", ""))[:10] + "..." if os.environ.get("LANGSMITH_API_KEY") else "NOT_SET",
        "langchain_tracing": os.environ.get("LANGCHAIN_TRACING_V2"),
        "langchain_project": os.environ.get("LANGCHAIN_PROJECT"),
        "openai_api_key_set": bool(os.environ.get("OPENAI_API_KEY")),
        "gcs_bucket": os.environ.get("GCS_BUCKET_NAME"),
        "db_host": os.environ.get("DB_HOST"),
        "db_port": os.environ.get("DB_PORT"),
        "all_langchain_vars": {
            k: v for k, v in os.environ.items() 
            if k.startswith("LANGCHAIN_") or k.startswith("LANGSMITH_")
        },
        "total_env_vars": len(os.environ)
    }

@app.get("/debug/langsmith-test")
def test_langsmith():
    """LangSmithの初期化テスト"""
    try:
        langsmith_key = os.environ.get("LANGSMITH_API_KEY")
        tracing_enabled = os.environ.get("LANGCHAIN_TRACING_V2")
        project = os.environ.get("LANGCHAIN_PROJECT")
        
        if not langsmith_key:
            return {"status": "error", "message": "LANGSMITH_API_KEY not found"}
        
        if tracing_enabled != "true":
            return {"status": "error", "message": f"LANGCHAIN_TRACING_V2 is '{tracing_enabled}', should be 'true'"}
        
        # LangSmithライブラリのテスト
        try:
            from langsmith import Client
            client = Client(api_key=langsmith_key)
            return {
                "status": "success",
                "langsmith_key_length": len(langsmith_key),
                "langsmith_key_prefix": langsmith_key[:10] + "...",
                "tracing_enabled": tracing_enabled,
                "project": project,
                "client_created": True,
                "message": "LangSmith client successfully created"
            }
        except Exception as e:
            return {
                "status": "error", 
                "message": f"LangSmith client creation failed: {str(e)}",
                "langsmith_key_length": len(langsmith_key) if langsmith_key else 0,
                "tracing_enabled": tracing_enabled,
                "project": project
            }
    except Exception as e:
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}

# ★★★ 追加: OPTIONS メソッドのハンドリング（明示的に）
@app.options("/chat")
@app.options("/chat/")
async def chat_options():
    return {"message": "OK"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)