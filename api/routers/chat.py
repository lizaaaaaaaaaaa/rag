import logging
from pathlib import Path
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel
from rag.ingested_text import load_vectorstore, get_rag_chain

from fastapi.responses import StreamingResponse, JSONResponse
import csv
import io
import sys  # ← flushのために追加

router = APIRouter()

# グローバル履歴（MVP用、運用時はDB化が◎）
history_logs = []

class ChatRequest(BaseModel):
    question: str
    username: str | None = None  # 型ヒントも追加 (Python3.10以降なら)

@router.post("/", summary="AIチャット")
async def chat_endpoint(req: ChatRequest):
    # ★ここで必ずログ出力（Cloud Runで検知用）
    print("=== chat_endpoint called ===", req.question, req.username)
    print(f"=== Request received ===")
    print(f"Method: POST")
    print(f"Path: /chat")
    print(f"Question: {req.question}")
    print(f"Username: {req.username}")
    sys.stdout.flush()
    logging.warning("=== chat_endpoint called === %s %s", req.question, req.username)

    query = req.question
    user = req.username or "guest"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    answer = ""
    sources = []
    try:
        # ベクトルストア読み込み
        vectorstore = load_vectorstore()
        # RAGチェーン取得
        rag_chain = get_rag_chain(vectorstore=vectorstore, return_source=True, question=query)
        # 正しくは "query" キーで渡す
        result = rag_chain.invoke({"query": query})
        answer = result.get("result", "")
        sources = []
        for doc in result.get("source_documents", []):
            meta = {k: str(v) for k, v in doc.metadata.items()}
            meta["source"] = Path(meta.get("source", "unknown")).name
            meta.setdefault("page", "?")
            sources.append({"metadata": meta})
    except Exception as e:
        answer = f"【エラー】RAG回答に失敗しました: {e}"
        # 必要ならログ出力も
        logging.exception("RAG回答エラー")

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

@router.get("/history", summary="チャット履歴取得")
def get_history():
    return {"logs": history_logs}

@router.get("/export/csv", summary="チャット履歴CSVダウンロード")
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

@router.get("/export/json", summary="チャット履歴JSONダウンロード")
def export_json():
    return JSONResponse(
        content=history_logs,
        headers={"Content-Disposition": "attachment; filename=chat_history.json"}
    )
