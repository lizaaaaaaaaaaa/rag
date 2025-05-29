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

router = APIRouter()

# グローバル履歴（MVP用、運用時はDB化が◎）
history_logs = []

class ChatRequest(BaseModel):
    question: str
    username: str = None  # ← 追加！

# prefix="/chat" なら、ここは "/" だけでOK
@router.post("/", summary="AIチャット")
async def chat_endpoint(req: ChatRequest):
    query = req.question
    user = req.username or "guest"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    answer = ""
    sources = []
    try:
        vectorstore = load_vectorstore()
        rag_chain = get_rag_chain(vectorstore=vectorstore, return_source=True, question=query)
        result = rag_chain.invoke({"query": query})
        answer = result.get("result", "")
        # 出典情報の構造化
        sources = []
        for doc in result.get("source_documents", []):
            meta = {k: str(v) for k, v in doc.metadata.items()}
            meta["source"] = Path(meta.get("source", "unknown")).name
            meta.setdefault("page", "?")
            sources.append({"metadata": meta})
    except Exception as e:
        answer = f"【エラー】RAG回答に失敗しました: {e}"

    log = {
        "id": str(uuid4()),
        "question": query,
        "username": user,   # ← 追加！
        "answer": answer,
        "timestamp": now,
        "sources": sources,
    }
    history_logs.append(log)
    return {"answer": answer, "sources": sources}

# --- チャット履歴取得 ---
@router.get("/history", summary="チャット履歴取得")
def get_history():
    return {"logs": history_logs}

# --- CSVエクスポート ---
@router.get("/export/csv", summary="チャット履歴CSVダウンロード")
def export_csv():
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(["id", "question", "username", "answer", "timestamp"])  # username追加
    for log in history_logs:
        writer.writerow([
            log.get("id", ""),
            log.get("question", ""),
            log.get("username", ""),  # username追加
            log.get("answer", ""),
            log.get("timestamp", ""),
        ])
    si.seek(0)
    return StreamingResponse(
        si,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=chat_history.csv"}
    )

# --- JSONエクスポート ---
@router.get("/export/json", summary="チャット履歴JSONダウンロード")
def export_json():
    return JSONResponse(
        content=history_logs,
        headers={"Content-Disposition": "attachment; filename=chat_history.json"}
    )
