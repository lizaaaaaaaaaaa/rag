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
    print(f"=== DEBUG: vectorstore type: {type(main.vectorstore)}")
    print(f"=== DEBUG: rag_chain_template type: {type(main.rag_chain_template)}")
    print(f"=== DEBUG: vectorstore is None: {main.vectorstore is None}")
    print(f"=== DEBUG: rag_chain_template is None: {main.rag_chain_template is None}")
    sys.stdout.flush()
    logging.warning("=== chat_endpoint called === %s %s", req.question, req.username)

    query = req.question
    user = req.username or "guest"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    answer = ""
    sources: list[dict] = []

    try:
        vectorstore = main.vectorstore
        rag_chain_template = main.rag_chain_template

        if not vectorstore or not rag_chain_template:
            print("!!! vectorstore or rag_chain_template is None: fallback to basic response")
            answer = f"申し訳ございませんが、現在システムは準備中です。お問い合わせ内容「{query}」については、システム管理者にお問い合わせください。"
            sources = [{"metadata": {"source": "システム応答", "page": "N/A"}}]
        else:
            # 通常のRAG処理
            chain = rag_chain_template.copy()
            result = chain.invoke({"query": query})
            answer = result.get("result", "回答を生成できませんでした。")
            for doc in result.get("source_documents", []):
                meta = {k: str(v) for k, v in doc.metadata.items()}
                meta["source"] = Path(meta.get("source", "unknown")).name
                meta.setdefault("page", "?")
                sources.append({"metadata": meta})
    except Exception as e:
        error_id = str(uuid4())[:8]
        answer = f"【エラー】システムエラーが発生しました。しばらく時間をおいてから再度お試しください。（エラーID: {error_id}）"
        logging.exception(f"Chat endpoint error [{error_id}]")
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