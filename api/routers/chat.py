import logging
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import traceback
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, JSONResponse

from utils.web_search import GoogleSearcher as WebSearcher

# ←ここにLangSmithトレースユーティリティをimport
from utils.langsmith_tracer import RAGTracer
from langsmith import traceable

router = APIRouter()
history_logs: list[dict] = []

logger = logging.getLogger(__name__)

# ★ 追加: LangSmith環境変数デバッグログ
logger.info(f"Chat router - LANGSMITH_API_KEY set: {bool(os.environ.get('LANGSMITH_API_KEY'))}")
logger.info(f"Chat router - LANGCHAIN_TRACING_V2: {os.environ.get('LANGCHAIN_TRACING_V2')}")
logger.info(f"Chat router - LANGCHAIN_PROJECT: {os.environ.get('LANGCHAIN_PROJECT')}")

class ChatRequest(BaseModel):
    question: str
    username: str | None = None

def is_general_greeting_or_chat(query: str) -> bool:
    greetings = [
        "こんにちは", "こんばんは", "おはよう", "はじめまして",
        "hello", "hi", "hey", "ありがとう", "さようなら",
        "元気", "調子はどう", "お疲れ様", "よろしく"
    ]
    query_lower = query.lower()
    for greeting in greetings:
        if greeting in query_lower:
            return True
    if len(query.strip()) <= 5:
        return True
    question_words = ["何", "どう", "いつ", "どこ", "誰", "なぜ", "どんな", "どの", "？", "?"]
    has_question = any(word in query for word in question_words)
    if len(query) <= 20 and not has_question:
        return True
    return False

def get_general_response_from_llm(query: str, llm_instance):
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
        if "こんにちは" in query:
            return "こんにちは！今日はどのようなご用件でしょうか？お手伝いできることがあれば、お気軽にお尋ねください。"
        elif "ありがとう" in query:
            return "どういたしまして！他にもご質問がございましたら、いつでもお聞きください。"
        else:
            return "申し訳ございません。もう一度お聞かせいただけますか？"

def get_app_globals():
    import main
    return {
        'vectorstore': getattr(main, 'vectorstore', None),
        'rag_chain_template': getattr(main, 'rag_chain_template', None),
        'llm_instance': getattr(main, 'llm_instance', None)
    }

tracer = RAGTracer()

@router.post("/", summary="AI チャット")
@traceable(name="chat_endpoint")
async def chat_endpoint(req: ChatRequest):
    logger.info(f"=== chat_endpoint called === question: {req.question}, username: {req.username}")

    query = req.question
    user = req.username or "guest"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    answer = ""
    docs = []
    web_searcher = WebSearcher()

    try:
        globals_dict = get_app_globals()
        vectorstore = globals_dict['vectorstore']
        rag_chain_template = globals_dict['rag_chain_template']
        llm_instance = globals_dict['llm_instance']

        logger.info(f"Vectorstore: {vectorstore is not None}, RAG chain: {rag_chain_template is not None}, LLM: {llm_instance is not None}")

        if is_general_greeting_or_chat(query):
            logger.info("Detected general chat/greeting - using direct LLM response")
            if llm_instance:
                answer = get_general_response_from_llm(query, llm_instance)
            else:
                if "こんにちは" in query:
                    answer = "こんにちは！ご質問をお聞かせください。"
                else:
                    answer = "申し訳ございません。お手伝いできることがあれば、お気軽にお尋ねください。"
        elif vectorstore and rag_chain_template:
            logger.info("Using RAG chain for technical/document-based query")
            try:
                # --- RAG検索とトレース ---
                docs = vectorstore.similarity_search(query, k=3)
                tracer.trace_retrieval(query, docs)
                # --- RAG生成 ---
                if hasattr(rag_chain_template, '__call__'):
                    result = rag_chain_template({"query": query})
                elif hasattr(rag_chain_template, 'invoke'):
                    result = rag_chain_template.invoke({"query": query})
                else:
                    result = rag_chain_template({"query": query}, callbacks=[])
                answer = result.get("result", "")
                # --- 生成のトレース ---
                context = "\n".join([doc.page_content for doc in docs])
                tracer.trace_generation(query, context, answer)

                # 回答が見つからない場合、Web検索も使う
                if not answer or "関連する情報が見つかりませんでした" in answer:
                    logger.info("No relevant documents found, trying enhanced response with web search")
                    answer = web_searcher.get_enhanced_answer(query, context="", use_web_search=True)
                else:
                    if web_searcher.should_search_web(query):
                        logger.info("Enhancing RAG answer with web search")
                        answer = web_searcher.get_enhanced_answer(query, context=answer, use_web_search=True)
            except Exception as e:
                logger.error(f"RAG chain error: {e}")
                if llm_instance:
                    answer = get_general_response_from_llm(query, llm_instance)
                else:
                    answer = "申し訳ございません。質問の処理中にエラーが発生しました。"
        else:
            if llm_instance:
                answer = get_general_response_from_llm(query, llm_instance)
            else:
                answer = "申し訳ございません。システムが準備中です。しばらくしてから再度お試しください。"

    except Exception as e:
        error_id = str(uuid4())[:8]
        logger.error(f"Unexpected error [{error_id}]: {e}")
        logger.error(traceback.format_exc())
        answer = f"システムエラーが発生しました。管理者にお問い合わせください。（エラーID: {error_id}）"

    log = {
        "id": str(uuid4()),
        "question": query,
        "username": user,
        "answer": answer,
        "timestamp": now,
        "sources": [],
    }
    history_logs.append(log)

    response = {
        "answer": answer,
        "sources": [],
        "status": "ok"
    }
    logger.info(f"Returning response: {response['answer'][:100]}...")
    return response

@router.post("", include_in_schema=False)
async def chat_endpoint_slashless(req: ChatRequest):
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