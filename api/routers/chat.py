# api/routers/chat.py

import logging
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import traceback
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, JSONResponse

# mainからのインポートを削除し、関数内で動的に取得するように変更
from utils.web_search import GoogleSearcher as WebSearcher

router = APIRouter()
history_logs: list[dict] = []

# ロガー設定
logger = logging.getLogger(__name__)

class ChatRequest(BaseModel):
    question: str
    username: str | None = None

def is_general_greeting_or_chat(query: str) -> bool:
    """一般的な挨拶や雑談かどうかを判定"""
    greetings = [
        "こんにちは", "こんばんは", "おはよう", "はじめまして",
        "hello", "hi", "hey", "ありがとう", "さようなら",
        "元気", "調子はどう", "お疲れ様", "よろしく"
    ]
    
    # クエリを小文字に変換して判定
    query_lower = query.lower()
    
    # 挨拶パターンのチェック
    for greeting in greetings:
        if greeting in query_lower:
            return True
    
    # 短い質問（5文字以下）は雑談として扱う
    if len(query.strip()) <= 5:
        return True
    
    # 質問っぽくない文章（疑問詞がない）も雑談として扱う可能性
    question_words = ["何", "どう", "いつ", "どこ", "誰", "なぜ", "どんな", "どの", "？", "?"]
    has_question = any(word in query for word in question_words)
    
    # 20文字以下で疑問詞がない場合は雑談の可能性が高い
    if len(query) <= 20 and not has_question:
        return True
    
    return False

def get_general_response_from_llm(query: str, llm_instance):
    """LLMを使って一般的な応答を生成"""
    try:
        prompt = f"""あなたは親切で丁寧な日本語のAIアシスタントです。
以下のユーザーの入力に対して、自然で親しみやすい日本語で応答してください。
技術的な内容ではなく、一般的な会話として応答してください。

ユーザー: {query}

アシスタント:"""

        if hasattr(llm_instance, 'invoke'):
            response = llm_instance.invoke(prompt)
            return response.content if hasattr(response, 'content') else str(response)
        else:
            response = llm_instance(prompt)
            return response if isinstance(response, str) else str(response)
            
    except Exception as e:
        logger.error(f"Error generating general response: {e}")
        # フォールバック応答
        if "こんにちは" in query:
            return "こんにちは！今日はどのようなご用件でしょうか？お手伝いできることがあれば、お気軽にお尋ねください。"
        elif "ありがとう" in query:
            return "どういたしまして！他にもご質問がございましたら、いつでもお聞きください。"
        else:
            return "申し訳ございません。もう一度お聞かせいただけますか？"

def get_app_globals():
    """mainモジュールからグローバル変数を動的に取得"""
    import main
    return {
        'vectorstore': getattr(main, 'vectorstore', None),
        'rag_chain_template': getattr(main, 'rag_chain_template', None),
        'llm_instance': getattr(main, 'llm_instance', None)
    }

@router.post("/", summary="AI チャット")
async def chat_endpoint(req: ChatRequest):
    logger.info(f"=== chat_endpoint called === question: {req.question}, username: {req.username}")
    
    query = req.question
    user = req.username or "guest"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    answer = ""
    sources: list[dict] = []
    web_searcher = WebSearcher()
    
    try:
        # グローバル変数を動的に取得
        globals_dict = get_app_globals()
        vectorstore = globals_dict['vectorstore']
        rag_chain_template = globals_dict['rag_chain_template']
        llm_instance = globals_dict['llm_instance']
        
        logger.info(f"Vectorstore: {vectorstore is not None}, RAG chain: {rag_chain_template is not None}, LLM: {llm_instance is not None}")
        
        # 一般的な挨拶や雑談の判定
        if is_general_greeting_or_chat(query):
            logger.info("Detected general chat/greeting - using direct LLM response")
            
            if llm_instance:
                answer = get_general_response_from_llm(query, llm_instance)
                # 一般的な会話の場合、ソースは不要
                sources = []
            else:
                # LLMがない場合のフォールバック
                if "こんにちは" in query:
                    answer = "こんにちは！ご質問をお聞かせください。"
                else:
                    answer = "申し訳ございません。お手伝いできることがあれば、お気軽にお尋ねください。"
                sources = []
        
        # RAG検索が必要な質問の場合
        elif vectorstore and rag_chain_template:
            logger.info("Using RAG chain for technical/document-based query")
            
            try:
                # RAGチェーンで回答生成
                if hasattr(rag_chain_template, '__call__'):
                    result = rag_chain_template({"query": query})
                elif hasattr(rag_chain_template, 'invoke'):
                    result = rag_chain_template.invoke({"query": query})
                else:
                    result = rag_chain_template({"query": query}, callbacks=[])
                
                answer = result.get("result", "")
                
                # ソースドキュメントの処理（表示しない設定）
                # sources = [] とすることで出典情報を非表示にする
                sources = []
                
                # 回答が見つからない場合、Web検索を含む強化された応答を生成
                if not answer or "関連する情報が見つかりませんでした" in answer:
                    logger.info("No relevant documents found, trying enhanced response with web search")
                    answer = web_searcher.get_enhanced_answer(query, context="", use_web_search=True)
                else:
                    # RAGで回答が見つかった場合も、Web検索が必要かチェック
                    if web_searcher.should_search_web(query):
                        logger.info("Enhancing RAG answer with web search")
                        # RAGの回答をコンテキストとして使用
                        answer = web_searcher.get_enhanced_answer(query, context=answer, use_web_search=True)
                        
            except Exception as e:
                logger.error(f"RAG chain error: {e}")
                # エラー時は一般的なLLM応答を試みる
                if llm_instance:
                    answer = get_general_response_from_llm(query, llm_instance)
                else:
                    answer = "申し訳ございません。質問の処理中にエラーが発生しました。"
                sources = []
        
        # ベクトルストアまたはRAGチェーンがない場合
        else:
            if llm_instance:
                # LLMだけで応答
                answer = get_general_response_from_llm(query, llm_instance)
            else:
                answer = "申し訳ございません。システムが準備中です。しばらくしてから再度お試しください。"
            sources = []
            
    except Exception as e:
        # 予期しないエラー
        error_id = str(uuid4())[:8]
        logger.error(f"Unexpected error [{error_id}]: {e}")
        logger.error(traceback.format_exc())
        answer = f"システムエラーが発生しました。管理者にお問い合わせください。（エラーID: {error_id}）"
        sources = []
    
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
    
    # レスポンスを返す（sourcesは空にして出典情報を非表示）
    response = {
        "answer": answer,
        "sources": [],  # 常に空の配列を返すことで出典情報を非表示
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
    import csv
    import io
    
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