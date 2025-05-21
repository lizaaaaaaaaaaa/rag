import logging
from pathlib import Path
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel
from rag.ingested_text import load_vectorstore, get_rag_chain

# === エクスポート用 ===
from fastapi.responses import StreamingResponse, JSONResponse
import csv
import io

router = APIRouter()

# グローバル履歴（MVP用）/本番はDB化
history_logs = []

class ChatRequest(BaseModel):
    question: str

@router.post("/", summary="AIチャット", response_description="RAG回答（出典付き）")
async def chat_endpoint(req: ChatRequest):
    query = req.question
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
        "answer": answer,
        "timestamp": now,
        "sources": sources,
    }
    history_logs.append(log)
    return {"answer": answer, "sources": sources}

@router.get("/history", summary="チャット履歴取得")
def get_history():
    return {"logs": history_logs}

# ===========================
# チャット履歴のエクスポートAPI
# ===========================

@router.get("/export/csv", summary="チャット履歴CSVダウンロード")
def export_csv():
    si = io.StringIO()
    writer = csv.writer(si)
    # CSVヘッダー
    writer.writerow(["id", "question", "answer", "timestamp"])
    # データ行
    for log in history_logs:
        writer.writerow([
            log.get("id", ""),
            log.get("question", ""),
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
