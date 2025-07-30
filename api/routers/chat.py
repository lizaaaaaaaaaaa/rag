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
    """RAG回答をクリーンアップして自然な形式に変換（大幅改良版）"""
    
    if not raw_response or len(raw_response.strip()) < 3:
        return "申し訳ございません。お尋ねの内容について詳細な情報が見つかりませんでした。"
    
    # 1. 最初に全体のクリーンアップ
    cleaned = raw_response
    
    # 2. 構造化情報の完全削除
    structure_patterns = [
        r"関連文書が見つかりました[:：]?\s*",
        r"関連情報が見つかりました[:：]?\s*",
        r"\d+\.\s*【質問】[^】]*】\s*",
        r"【回答】\s*",
        r"【質問】\s*",
        r"出典[:：]\s*[^\n]*",
        r"/tmp/tmp[a-zA-Z0-9_]*\.pdf",
        r"\([pP]\d+\)",
        r"^\d+\.\s*",
        r"【[^】]*】",
        r"^質問[:：]\s*",
        r"^回答[:：]\s*",
        r"出典[:：][^\n]*",
        r"\.pdf\s*\([pP]\d+\)",
        r"\.pdf\s+\(p\d+\)",
    ]
    
    for pattern in structure_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)
    
    # 3. 縦書き文字の修正（改良版）
    lines = cleaned.split('\n')
    fixed_lines = []
    char_buffer = []
    
    for line in lines:
        line = line.strip()
        
        # 空行はスキップ
        if not line:
            if char_buffer:
                combined = ''.join(char_buffer)
                if len(combined) > 2:
                    fixed_lines.append(combined)
                char_buffer = []
            continue
        
        # 1文字の行は結合候補
        if len(line) == 1:
            char_buffer.append(line)
        elif len(line) <= 3:
            # 2-3文字の短い行も結合候補
            char_buffer.append(line)
        else:
            # 長い行が来たら、バッファをクリア
            if char_buffer:
                combined = ''.join(char_buffer)
                if len(combined) > 2:
                    fixed_lines.append(combined)
                char_buffer = []
            fixed_lines.append(line)
    
    # 最後のバッファを処理
    if char_buffer:
        combined = ''.join(char_buffer)
        if len(combined) > 2:
            fixed_lines.append(combined)
    
    # 4. 重複する内容の削除
    unique_content = []
    seen_content = set()
    
    for line in fixed_lines:
        # 短すぎる行はスキップ
        if len(line) < 5:
            continue
            
        # 類似する内容をチェック
        line_normalized = re.sub(r'[。、\s]', '', line.lower())
        
        # 重複チェック
        is_duplicate = False
        for seen in seen_content:
            if line_normalized in seen or seen in line_normalized:
                is_duplicate = True
                break
        
        if not is_duplicate:
            seen_content.add(line_normalized)
            unique_content.append(line)
    
    # 5. 自然な文章に再構成
    if unique_content:
        # 最も長くて意味のある文章を選択
        best_content = max(unique_content, key=len)
        
        # 文章の整形
        result = best_content
        result = re.sub(r'\s+', ' ', result)  # 複数スペースを1つに
        result = re.sub(r'([。！？])\s*', r'\1', result)  # 句読点後のスペース削除
        result = result.strip()
        
        # 文末の調整
        if not result.endswith(('。', '！', '？')):
            if result.endswith('、'):
                result = result[:-1] + '。'
            elif not result.endswith('.'):
                result += '。'
    else:
        result = "申し訳ございません。お尋ねの内容について、詳細な情報をお答えできませんでした。"
    
    # 6. 最終的な品質チェック
    if len(result) < 10 or "..." in result:
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
    """チャットエンドポイント（大幅改良版）"""
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
                logger.info(f"Raw RAG response: {raw_answer[:200]}...")
                
                # 回答をクリーンアップ（大幅改良版を使用）
                answer = clean_rag_response(raw_answer)
                logger.info(f"Cleaned response: {answer[:200]}...")
                
                # --- 生成のトレース ---
                context = "\n".join([doc.page_content for doc in docs])
                tracer.trace_generation(query, context, answer)

                # 回答が不十分な場合、Web検索も使う
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
                answer = "申し訳ございません。システムが準備中です。しばらくしてから再度お試しください。"

    except Exception as e:
        error_id = str(uuid4())[:8]
        logger.error(f"Unexpected error [{error_id}]: {e}")
        logger.error(traceback.format_exc())
        answer = f"システムエラーが発生しました。管理者にお問い合わせください。（エラーID: {error_id}）"

    # 最終的な回答のクリーンアップ（二重の保険）
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
        "sources": [],  # 出典情報は非表示
        "status": "ok"
    }
    logger.info(f"Final response: {answer[:100]}...")
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