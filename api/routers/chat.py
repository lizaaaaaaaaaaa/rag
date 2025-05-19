# api/routers/chat.py
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
from utils.cleanup import cleanup_answer

# ---------- .env 読み込み（開発環境のみ） ----------
if Path(".env").exists():
    load_dotenv()

# ---------- OpenAI API キー設定（必要なら） ----------
import openai  # noqa: E402
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

# ---------- ロギング ----------------------------------
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ---------- FastAPI ルーター ---------------------------
router = APIRouter()

# ---------- スキーマ -----------------------------------
class ChatRequest(BaseModel):
    query: str


@router.post("/")
async def chat_endpoint(request: ChatRequest):
    """
    ユーザーの query を受け取り、RAG で回答を返す。
    - cleanup_answer() で冗長行を除去
    - sources には file.pdf:page を示す 'ref' キーを必ず含める
    """
    try:
        query: str = request.query.strip()
        logger.info(f"📩 新しい質問を受信: {query}")

        # 1) Vectorstore & RAG チェーン用意
        vectorstore = load_vectorstore()
        rag_chain = get_rag_chain(
            vectorstore=vectorstore,
            return_source=True,
            question=query,
        )

        # 2) 生成
        raw_result: Dict[str, Any] = rag_chain.invoke({"query": query})

        # 3) 回答加工（重複行カット）
        raw_answer: str = str(raw_result.get("result", ""))
        answer: str = cleanup_answer(
            raw_answer,
            int(os.getenv("ANSWER_MAX_LINES", 20)),
        )

        # 4) ソース整形
        sources: List[Dict[str, Any]] = []
        for doc in raw_result.get("source_documents", []):
            if isinstance(doc, Document):
                meta = {k: str(v) for k, v in doc.metadata.items()}
                meta.setdefault("source", Path(meta.get("source", "unknown")).name)
                meta.setdefault("page", "?")

                # ★ テストが期待する "file.pdf:page" を 'ref' に追加
                filename = Path(meta["source"]).name
                meta["ref"] = f"{filename}:{meta['page']}"

                sources.append(
                    {
                        "page_content": str(doc.page_content),
                        "metadata": meta,
                    }
                )
            else:
                sources.append({"data": str(doc)})

        # 5) レスポンス
        return JSONResponse(
            content={
                "answer": answer,
                "sources": sources,
            }
        )

    except Exception:  # noqa: BLE001
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal Server Error")
