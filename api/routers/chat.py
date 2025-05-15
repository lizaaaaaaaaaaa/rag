import os
import logging
import traceback

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from langchain_core.documents import Document
from rag.ingested_text import load_vectorstore, get_rag_chain

# ✅ .env の安全な読み込み（開発用）
if os.path.exists(".env"):
    load_dotenv()

# ✅ OpenAI APIキーの安全設定
import openai
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

# ✅ ロギング初期化（Cloud Logging 対応）
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter()

class ChatRequest(BaseModel):
    query: str

@router.post("/")
async def chat_endpoint(request: ChatRequest):
    try:
        query = request.query
        logger.info(f"📩 新しい質問を受信: {query}")

        vectorstore = load_vectorstore()
        rag_chain = get_rag_chain(vectorstore, return_source=True, question=query)
        result = rag_chain.invoke({"query": query})

        sources = []
        for doc in result.get("source_documents", []):
            if isinstance(doc, Document):
                sources.append({
                    "page_content": str(doc.page_content),
                    "metadata": {k: str(v) for k, v in doc.metadata.items()}
                })
            else:
                sources.append(str(doc))

        return JSONResponse(content={
            "answer": str(result.get("result", "")),
            "sources": sources
        })

    except Exception as e:
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal Server Error")


