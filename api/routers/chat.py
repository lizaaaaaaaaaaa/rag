import os
import logging
import traceback  # ← 🔧 忘れず追加！

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from langchain_core.documents import Document
from rag.ingested_text import load_vectorstore, get_rag_chain

# 🔐 .env 読み込み（ローカル開発用）
load_dotenv()

# 🔑 OpenAI APIキーを設定（Cloud Runでは環境変数から注入）
import openai
openai.api_key = os.getenv("OPENAI_API_KEY")

# 🔧 Logging設定（Cloud Loggingに連携しやすく）
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter()

class ChatRequest(BaseModel):
    query: str

@router.post("/")
async def chat_endpoint(request: ChatRequest):
    try:
        query = request.query

        # ベクトルストアとRAGチェーンを構築
        vectorstore = load_vectorstore()
        rag_chain = get_rag_chain(vectorstore, return_source=True, question=query)
        result = rag_chain.invoke({"query": query})

        # ソースをJSON化可能な形に変換
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

