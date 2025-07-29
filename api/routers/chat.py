import logging
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import traceback
import os
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, JSONResponse

from utils.web_search import GoogleSearcher as WebSearcher

# LangSmithトレースユーティリティをimport
from utils.langsmith_tracer import RAGTracer

# traceableのインポートを条件付きに
try:
    from langsmith import traceable
except ImportError:
    # ダミーデコレータ
    def traceable(name=None, **kwargs):
        def decorator(func):
            return func
        return decorator

router = APIRouter()
history_logs: list[dict] = []

logger = logging.getLogger(__name__)

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

def clean_rag_response(raw_response: str) -> str:
    """RAG回答をクリーンアップして自然な形式に変換"""
    
    # 不要なパターンを削除
    unwanted_patterns = [
        r"関連文書が見つかりました[:：]?\s*",
        r"関連情報が見つかりました[:：]?\s*",
        r"\d+\.\s*【質問】[^】]*】\s*",
        r"【回答】\s*",
        r"出典[:：]\s*[^\n]*\.pdf\s*\([^)]*\)\s*",
        r"/tmp/tmp[a-zA-Z0-9]*\.pdf",
        r"\(p\d+\)",
        r"^\d+\.\s*",
        r"【[^】]*】",
    ]
    
    # パターンマッチングで不要部分を削除
    cleaned = raw_response
    for pattern in unwanted_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE)
    
    # 縦書き文字の修正（連続する単一文字を結合）
    lines = cleaned.split('\n')
    processed_lines = []
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # 空行はスキップ
        if not line:
            i += 1
            continue
            
        # 1文字の行が連続している場合は結合
        if len(line) == 1 and i + 1 < len(lines):
            combined_text = line
            j = i + 1
            
            # 次の行も1-2文字の場合は結合を続ける
            while j < len(lines) and len(lines[j].strip()) <= 2 and lines[j].strip():
                combined_text += lines[j].strip()
                j += 1
            
            # 結合したテキストが意味のある長さの場合
            if len(combined_text) > 3:
                processed_lines.append(combined_text)
                i = j
                continue
        
        # 意味のあるテキストのみ追加
        if len(line) > 2:
            processed_lines.append(line)
        
        i += 1
    
    # 文章を結合
    result = ' '.join(processed_lines)
    
    # 追加のクリーンアップ
    result = re.sub(r'\s+', ' ', result)  # 複数スペースを1つに
    result = re.sub(r'\.{3,}', '。', result)  # 3つ以上のドットを句点に
    result = result.strip()
    
    # 最終チェック：意味のない短い回答は置き換え
    if not result or len(result) < 10 or result.count(' ') < 3:
        result = "申し訳ございません。お尋ねの内容について、より詳しい情報をご提供するため、直接お問い合わせいただければと思います。"
    
    return result

def get_app_globals():
    import main
    return {
        'vectorstore': getattr(main, 'vectorstore', None),
        'rag_chain_template': getattr(main, 'rag_chain_template', None),
        'llm_instance': getattr(main, 'llm_instance', None)
    }

tracer = RAGTracer()

@router.post("/", summary="AI チャット")
async def chat_endpoint(req: ChatRequest, request: Request):
    """チャットエンドポイント（改善版）"""
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

        logger.info(f"System status - Vectorstore: {vectorstore is not None}, RAG chain: {rag_chain_template is not None}, LLM: {llm_instance is not None}")

        # グローバル変数が初期化されていない場合のエラーハンドリング
        if not vectorstore and not llm_instance:
            logger.error("System not properly initialized")
            answer = "システムが正しく初期化されていません。管理者にお問い合わせください。"
            return JSONResponse(
                status_code=503,
                content={
                    "answer": answer,
                    "sources": [],
                    "status": "error",
                    "error": "Service temporarily unavailable"
                }
            )

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
                
                raw_answer = result.get("result", "")
                
                # 回答をクリーンアップ
                answer = clean_rag_response(raw_answer)
                
                # --- 生成のトレース ---
                context = "\n".join([doc.page_content for doc in docs])
                tracer.trace_generation(query, context, answer)

                # 回答が見つからない場合、Web検索も使う
                if not answer or len(answer) < 20 or "関連する情報が見つかりませんでした" in answer:
                    logger.info("No relevant documents found, trying enhanced response with web search")
                    answer = web_searcher.get_enhanced_answer(query, context="", use_web_search=True)
                elif web_searcher.should_search_web(query):
                    logger.info("Enhancing RAG answer with web search")
                    # Web検索で補強するが、メインはRAGの回答を使用
                    web_enhanced = web_searcher.get_enhanced_answer(query, context=answer, use_web_search=True)
                    if len(web_enhanced) > len(answer):
                        answer = web_enhanced
                        
            except Exception as e:
                logger.error(f"RAG chain error: {e}")
                logger.error(traceback.format_exc())
                if llm_instance:
                    answer = get_general_response_from_llm(query, llm_instance)
                else:
                    answer = "申し訳ございません。質問の処理中にエラーが発生しました。"
        else:
            if llm_instance:
                answer = get_general_response_from_llm(query, llm_instance)
            else:
                answer = "申し訳ございません。システムが準備中です。しばらくしてから再度お試ください。"

    except Exception as e:
        error_id = str(uuid4())[:8]
        logger.error(f"Unexpected error [{error_id}]: {e}")
        logger.error(traceback.format_exc())
        answer = f"システムエラーが発生しました。管理者にお問い合わせください。（エラーID: {error_id}）"

    # 最終的な回答のクリーンアップ
    answer = clean_rag_response(answer)

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
    logger.info(f"Returning response: {answer[:100]}...")
    return response

@router.post("", include_in_schema=False)
async def chat_endpoint_slashless(req: ChatRequest, request: Request):
    return await chat_endpoint(req, request)

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