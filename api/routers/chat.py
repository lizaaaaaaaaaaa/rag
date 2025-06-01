# api/routers/chat.py

import logging
from pathlib import Path
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, JSONResponse

import csv
import io
import sys  # flush 用

# main.pyでstartup eventが終わるとvectorstore/rag_chain_templateが格納されている
import main

router = APIRouter()
history_logs: list[dict] = []

class ChatRequest(BaseModel):
    question: str
    username: str | None = None

@router.post("/", summary="AI チャット")
async def chat_endpoint(req: ChatRequest):
    print("=== chat_endpoint called ===", req.question, req.username)
    print("=== Request received ===")
    print("Method: POST")
    print("Path: /chat/")
    print("Question:", req.question)
    print("Username:", req.username)
    sys.stdout.flush()
    logging.warning("=== chat_endpoint called === %s %s", req.question, req.username)

    query = req.question
    user = req.username or "guest"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    answer = ""
    sources: list[dict] = []

    try:
        # main.pyでキャッシュされたグローバル変数
        vectorstore = main.vectorstore
        rag_chain_template = main.rag_chain_template

        # どちらかがNoneなら通常LLMのみで返答（システムが起動しきっていない状況など）
        if not vectorstore or not rag_chain_template:
            print("!!! vectorstore or rag_chain_template is None: fallback to LLM only")
            from llm.llm_runner import load_llm
            llm, _, _ = load_llm()
            if hasattr(llm, 'invoke'):
                result = llm.invoke(f"質問: {query}\n\n上記の質問に日本語で簡潔に答えてください。")
                answer = str(result) if result else "申し訳ございませんが、現在システムの準備中です。"
            else:
                answer = "現在システムの準備中です。しばらく時間をおいてから再度お試しください。"
            sources = [{"metadata": {"source": "システム応答", "page": "N/A"}}]
        else:
            # 通常のRAG応答
            chain = rag_chain_template.copy()
            result = chain.invoke({"query": query})

            answer = result.get("result", "")
            for doc in result.get("source_documents", []):
                meta = {k: str(v) for k, v in doc.metadata.items()}
                meta["source"] = Path(meta.get("source", "unknown")).name
                meta.setdefault("page", "?")
                sources.append({"metadata": meta})

    except Exception as e:
        answer = f"【エラー】RAG 回答に失敗しました: {e}"
        logging.exception("RAG 回答エラー")
        sources = [{"metadata": {"source": "エラー応答", "page": "N/A"}}]

    log = {
        "id": str(uuid4()),
        "question": query,
        "username": user,
        "answer": answer,
        "timestamp": now,
        "sources": sources,
    }
    history_logs.append(log)

    return {"answer": answer, "sources": sources}

@router.post("", include_in_schema=False)
async def chat_endpoint_slashless(req: ChatRequest):
    return await chat_endpoint(req)

@router.get("/history", summary="チャット履歴取得")
def get_history():
    return {"logs": history_logs}

@router.get("/export/csv", summary="チャット履歴 CSV ダウンロード")
def export_csv():
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(["id", "question", "username", "answer", "timestamp"])
    for log in history_logs:
        writer.writerow([
            log.get("id", ""),
            log.get("question", ""),
            log.get("username", ""),
            log.get("answer", ""),
            log.get("timestamp", ""),
        ])
    si.seek(0)
    return StreamingResponse(
        si,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=chat_history.csv"}
    )

@router.get("/export/json", summary="チャット履歴 JSON ダウンロード")
def export_json():
    return JSONResponse(
        content=history_logs,
        headers={"Content-Disposition": "attachment; filename=chat_history.json"}
    )
