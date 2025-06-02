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

if os.getenv("ENV") != "production":
    from dotenv import load_dotenv
    load_dotenv(".env")
    logger.info(">>> Loaded .env for local development")
else:
    logger.info(">>> Running in production mode")

FRONTEND_URL = "https://rag-frontend-190389115361.asia-northeast1.run.app"

app = FastAPI(
    title="RAG FastAPI Backend",
    description="RAG + LLM 連携 API (Cloud Run 対応)",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000", "http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)