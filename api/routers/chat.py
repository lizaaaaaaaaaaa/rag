import logging
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import sys  # ← flush 用

from fastapi import APIRouter
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, JSONResponse

import csv
import io

# main.py で startup event が終わると vectorstore と rag_chain_template がセットされているはず
import main

router = APIRouter()
history_logs: list[dict] = []


class ChatRequest(BaseModel):
    question: str
    username: str | None = None


@router.post("/", summary="AI チャット")
async def chat_endpoint(req: ChatRequest):
    # ── デバッグログを全部出す ──
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
        # ① startup event でキャッシュされた vectorstore と rag_chain_template を参照
        vectorstore = main.vectorstore
        rag_chain_template = main.rag_chain_template

        # もし startup で失敗して　rag_chain_template が None　なら例外にする
        if rag_chain_template is None:
            raise RuntimeError("RAG chain template is not initialized. Please try again later.")

        # ② テンプレートをコピーして query を渡す
        #    （LangChain の Chain が .copy() メソッドを持つ前提）
        chain = rag_chain_template.copy()
        result = chain.invoke({"query": query})

        # ③ 結果の整形
        answer = result.get("result", "")
        for doc in result.get("source_documents", []):
            meta = {k: str(v) for k, v in doc.metadata.items()}
            meta["source"] = Path(meta.get("source", "unknown")).name
            meta.setdefault("page", "?")
            sources.append({"metadata": meta})

    except Exception as e:
        # 何か例外が起きたら answer にエラー文を載せて後続処理は止めない
        answer = f"【エラー】RAG 回答に失敗しました: {e}"
        logging.exception("RAG 回答エラー")

    # ④ 履歴に追加
    log = {
        "id": str(uuid4()),
        "question": query,
        "username": user,
        "answer": answer,
        "timestamp": now,
        "sources": sources,
    }
    history_logs.append(log)

    # ⑤ レスポンス
    return {"answer": answer, "sources": sources}


@router.post("", include_in_schema=False)
async def chat_endpoint_slashless(req: ChatRequest):
    # 「/chat/」の末尾スラッシュなしでも動くように
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
