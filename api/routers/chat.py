import os
import logging
import traceback
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from langchain_core.documents import Document

from rag.ingested_text import load_vectorstore, get_rag_chain
from utils.cleanup import cleanup_answer   # ★ 追加

# --- .env の安全な読み込み（開発用） -------------------------
if Path(".env").exists():
    load_dotenv()

# --- OpenAI API キー設定（必要なら） ---------------------------
import openai
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

# --- ロギング --------------------------------------------------
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# --- FastAPI ルーター ------------------------------------------
router = APIRouter()

# ---------- リクエスト / レスポンス -----------------------------
class ChatRequest(BaseModel):
    query: str

@router.post("/")
async def chat_endpoint(request: ChatRequest):
    """
    ユーザーからの質問を受け取り、RAG チェーンで回答を生成。
    - cleanup_answer() で重複行・冗長行を除去
    - sources には file:page を必ず含める
    """
    try:
        query: str = request.query.strip()
        logger.info(f"📩 新しい質問を受信: {query}")

        # 1) Vectorstore と RAG チェーンを取得
        vectorstore = load_vectorstore()
        rag_chain = get_rag_chain(
            vectorstore=vectorstore,
            return_source=True,
            question=query
        )

        # 2) チェーン実行 → “raw” 結果を整形
        raw_result: Dict[str, Any] = rag_chain.invoke({"query": query})

        raw_answer: str = str(raw_result.get("result", ""))
        answer: str = cleanup_answer(
            raw_answer,
            int(os.getenv("ANSWER_MAX_LINES", 20))
        )

        # 3) ソース情報を整形（欠落フォールバック付き）
        sources: List[Dict[str, Any]] = []
        for doc in raw_result.get("source_documents", []):
            if isinstance(doc, Document):
                meta = {k: str(v) for k, v in doc.metadata.items()}
                meta.setdefault("source", Path(meta.get("source", "unknown")).name)
                meta.setdefault("page", "?")
                sources.append(
                    {
                        "page_content": str(doc.page_content),
                        "metadata": meta
                    }
                )
            else:
                # Document でない場合はそのまま文字列化
                sources.append({"data": str(doc)})

        # 4) レスポンスを返す
        return JSONResponse(
            content={
                "answer": answer,
                "sources": sources
            }
        )

    except Exception as e:  # noqa: E722
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal Server Error")
