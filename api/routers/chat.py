# api/routers/chat.py

import logging
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import traceback

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, JSONResponse

import csv
import io
import sys

import main

router = APIRouter()
history_logs: list[dict] = []

# ロガー設定
logger = logging.getLogger(__name__)

class ChatRequest(BaseModel):
    question: str
    username: str | None = None

@router.post("/", summary="AI チャット")
async def chat_endpoint(req: ChatRequest):
    logger.info(f"=== chat_endpoint called === question: {req.question}, username: {req.username}")
    
    query = req.question
    user = req.username or "guest"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    answer = ""
    sources: list[dict] = []
    
    try:
        # グローバル変数から取得
        vectorstore = main.vectorstore
        rag_chain_template = main.rag_chain_template
        
        logger.info(f"Vectorstore: {vectorstore is not None}, RAG chain: {rag_chain_template is not None}")
        
        if not vectorstore:
            # ベクトルストアがない場合
            answer = "申し訳ございません。システムが準備中です。しばらくしてから再度お試しください。"
            sources = [{"metadata": {"source": "システムメッセージ", "page": "N/A"}}]
            
        elif not rag_chain_template:
            # RAGチェーンがない場合、直接検索を試みる
            logger.info("RAG chain not available, trying direct search")
            try:
                retriever = vectorstore.as_retriever()
                docs = retriever.get_relevant_documents(query)
                
                if docs:
                    answer = "以下の関連情報が見つかりました：\n\n"
                    for i, doc in enumerate(docs[:3], 1):
                        answer += f"{i}. {doc.page_content[:200]}...\n"
                        answer += f"   出典: {doc.metadata.get('source', '不明')} (p{doc.metadata.get('page', '?')})\n\n"
                    
                    for doc in docs[:3]:
                        meta = {k: str(v) for k, v in doc.metadata.items()}
                        meta["source"] = Path(meta.get("source", "unknown")).name
                        meta.setdefault("page", "?")
                        sources.append({"metadata": meta})
                else:
                    answer = "関連する情報が見つかりませんでした。別の質問をお試しください。"
                    sources = [{"metadata": {"source": "検索結果なし", "page": "N/A"}}]
                    
            except Exception as e:
                logger.error(f"Direct search error: {e}")
                answer = f"検索中にエラーが発生しました。もう一度お試しください。"
                sources = [{"metadata": {"source": "エラー", "page": "N/A"}}]
                
        else:
            # 通常のRAG処理
            logger.info("Using RAG chain for processing")
            try:
                # 新しいLangChainの方法で実行
                if hasattr(rag_chain_template, '__call__'):
                    # 古いスタイル（callable chain）
                    result = rag_chain_template({"query": query})
                else:
                    # 新しいスタイル - invoke()の代わりに__call__を使用
                    # または、runメソッドがある場合はそれを使用
                    if hasattr(rag_chain_template, 'run'):
                        answer = rag_chain_template.run(query)
                        result = {"result": answer, "source_documents": []}
                    else:
                        # RetrievalQAの直接実行
                        result = rag_chain_template({"query": query}, callbacks=[])
                
                # 結果を取得
                answer = result.get("result", "")
                if not answer:
                    answer = "申し訳ございません。回答を生成できませんでした。"
                
                # ソースドキュメントを処理
                for doc in result.get("source_documents", []):
                    meta = {k: str(v) for k, v in doc.metadata.items()}
                    meta["source"] = Path(meta.get("source", "unknown")).name
                    meta.setdefault("page", "?")
                    sources.append({"metadata": meta})
                    
            except Exception as e:
                logger.error(f"RAG chain error: {e}")
                logger.error(traceback.format_exc())
                
                # エラー詳細からより具体的な対処を試みる
                error_msg = str(e)
                if "callbacks" in error_msg:
                    # callbacksエラーの場合、別の方法を試す
                    try:
                        # retrieverを直接使用してドキュメント検索
                        retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
                        docs = retriever.get_relevant_documents(query)
                        
                        if docs:
                            # LLMが利用可能な場合
                            if main.llm_instance:
                                # コンテキストを作成
                                context = "\n\n".join([doc.page_content for doc in docs[:3]])
                                
                                # プロンプトを構築
                                prompt = f"""以下のコンテキストを使用して質問に答えてください。

コンテキスト: {context}

質問: {query}

回答（日本語で分かりやすく）:"""
                                
                                # LLMを直接呼び出し
                                if hasattr(main.llm_instance, 'invoke'):
                                    llm_response = main.llm_instance.invoke(prompt)
                                    answer = llm_response.content if hasattr(llm_response, 'content') else str(llm_response)
                                else:
                                    answer = main.llm_instance(prompt)
                                    if hasattr(answer, 'content'):
                                        answer = answer.content
                                    else:
                                        answer = str(answer)
                                
                                # ソースドキュメントを追加
                                for doc in docs[:3]:
                                    meta = {k: str(v) for k, v in doc.metadata.items()}
                                    meta["source"] = Path(meta.get("source", "unknown")).name
                                    meta.setdefault("page", "?")
                                    sources.append({"metadata": meta})
                            else:
                                # LLMがない場合は検索結果のみ返す
                                answer = "関連情報が見つかりました:\n\n"
                                for i, doc in enumerate(docs[:3], 1):
                                    answer += f"{i}. {doc.page_content[:200]}...\n"
                                    answer += f"   出典: {doc.metadata.get('source', '不明')} (p{doc.metadata.get('page', '?')})\n\n"
                                
                                for doc in docs[:3]:
                                    meta = {k: str(v) for k, v in doc.metadata.items()}
                                    meta["source"] = Path(meta.get("source", "unknown")).name
                                    meta.setdefault("page", "?")
                                    sources.append({"metadata": meta})
                        else:
                            answer = "関連する情報が見つかりませんでした。"
                            sources = [{"metadata": {"source": "検索結果なし", "page": "N/A"}}]
                            
                    except Exception as e2:
                        logger.error(f"Fallback error: {e2}")
                        answer = f"申し訳ございません。質問の処理中にエラーが発生しました。"
                        sources = [{"metadata": {"source": "エラー応答", "page": "N/A"}}]
                else:
                    # その他のエラー
                    answer = f"申し訳ございません。質問の処理中にエラーが発生しました。"
                    sources = [{"metadata": {"source": "エラー応答", "page": "N/A"}}]
                
    except Exception as e:
        # 予期しないエラー
        error_id = str(uuid4())[:8]
        logger.error(f"Unexpected error [{error_id}]: {e}")
        logger.error(traceback.format_exc())
        answer = f"システムエラーが発生しました。管理者にお問い合わせください。（エラーID: {error_id}）"
        sources = [{"metadata": {"source": "システムエラー", "page": "N/A"}}]
    
    # ログを記録
    log = {
        "id": str(uuid4()),
        "question": query,
        "username": user,
        "answer": answer,
        "timestamp": now,
        "sources": sources,
    }
    history_logs.append(log)
    
    # レスポンスを返す
    response = {
        "answer": answer,
        "sources": sources,
        "status": "ok"
    }
    
    logger.info(f"Returning response: {response['answer'][:100]}...")
    return response

@router.post("", include_in_schema=False)
async def chat_endpoint_slashless(req: ChatRequest):
    """スラッシュなしのエンドポイント（互換性のため）"""
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