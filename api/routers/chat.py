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
import sys  # ← flush のために追加

# ここでは、startup イベントで作成済みの rag_chain_template を利用するため、
# main.py からグローバル変数をインポートします。
import main  # ただし、main.py で vectorstore / rag_chain_template をロード済みである必要があります

router = APIRouter()

# グローバル履歴（MVP 用。運用時は DB 化するのが望ましい）
history_logs: list[dict] = []


class ChatRequest(BaseModel):
    question: str
    username: str | None = None  # 型ヒント (Python 3.10 以降なら)


@router.post("/", summary="AI チャット")
async def chat_endpoint(req: ChatRequest):
    """
    クライアントから { "question": "...", "username": "..." } を受け取り、
    事前にロード済みの 'rag_chain_template' をコピーして invoke() を呼び出し、
    { "answer": "...", "sources": [...] } を返します。
    """

    # --- ログを出力（Cloud Run のログで検知するため）---
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
        # --- 事前にロード済みの rag_chain_template と vectorstore を使いまわす ---

        # 1) vectorstore は main.vectorstore、rag_chain_template は main.rag_chain_template から取得
        vectorstore = main.vectorstore
        rag_chain_template = main.rag_chain_template

        # 2) 起動時に作成した rag_chain_template をコピーし、クエリだけ差し替えて invoke() に渡す
        #    ※ LangChain のチェーンは .copy() や .bind() などでクローンして使い回せます
        chain = rag_chain_template.copy()  # または chain = rag_chain_template.bind({"query": query}) など
        result = chain.invoke({"query": query})

        # 3) レスポンスから答えだけ取り出す
        answer = result.get("result", "")

        # 4) 出典ドキュメントを整形
        for doc in result.get("source_documents", []):
            meta = {k: str(v) for k, v in doc.metadata.items()}
            # ファイル名だけに絞る
            meta["source"] = Path(meta.get("source", "unknown")).name
            meta.setdefault("page", "?")
            sources.append({"metadata": meta})

    except Exception as e:
        # 例外時はエラーメッセージを返す
        answer = f"【エラー】RAG 回答に失敗しました: {e}"
        logging.exception("RAG 回答エラー")

    # 5) 履歴に追加しておく（MVP 用）
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
    """
    スラッシュなし (/chat) で POST された場合も、同じ chat_endpoint を呼び出す。
    これにより、クライアントが末尾スラッシュを付け忘れても 405 エラーになりません。
    """
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
