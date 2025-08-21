import logging
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import traceback
import os
import re
import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, JSONResponse

# 既存のWeb検索ラッパー（必要に応じてフォールバック等で利用）
from utils.web_search import GoogleSearcher as WebSearcher

# LangSmithトレースユーティリティ
from utils.langsmith_tracer import RAGTracer

# ハルチネーション対策の統合機能
from integration.anti_hallucination_integration import enhance_web_chat_response

# traceable の条件付きインポート（本番で未導入でも壊れないように）
try:
    from langsmith import traceable
except ImportError:
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

    cleaned = raw_response

    # 構造化・出典表記などの除去
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

    # 縦書き由来の分断行を連結
    lines = cleaned.split('\n')
    fixed_lines = []
    char_buffer = []
    for line in lines:
        line = line.strip()
        if not line:
            if char_buffer:
                combined = ''.join(char_buffer)
                if len(combined) > 2:
                    fixed_lines.append(combined)
                char_buffer = []
            continue
        if len(line) <= 3:
            char_buffer.append(line)
        else:
            if char_buffer:
                combined = ''.join(char_buffer)
                if len(combined) > 2:
                    fixed_lines.append(combined)
                char_buffer = []
            fixed_lines.append(line)
    if char_buffer:
        combined = ''.join(char_buffer)
        if len(combined) > 2:
            fixed_lines.append(combined)

    # 重複行の排除
    unique_content = []
    seen_content = set()
    for line in fixed_lines:
        if len(line) < 5:
            continue
        line_normalized = re.sub(r'[。、\s]', '', line.lower())
        if any(line_normalized in s or s in line_normalized for s in seen_content):
            continue
        seen_content.add(line_normalized)
        unique_content.append(line)

    # 一番意味のある行を採用し整形
    if unique_content:
        result = max(unique_content, key=len)
        result = re.sub(r'\s+', ' ', result)
        result = re.sub(r'([。！？])\s*', r'\1', result).strip()
        if not result.endswith(('。', '！', '？')):
            if result.endswith('、'):
                result = result[:-1] + '。'
            elif not result.endswith('.'):
                result += '。'
    else:
        result = "申し訳ございません。お尋ねの内容について、詳細な情報をお答えできませんでした。"

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

@router.post("/", summary="AI チャット（ハルチネーション対策強化版）")
async def chat_endpoint(req: ChatRequest, request: Request):
    """チャットエンドポイント（ハルチネーション対策強化版）"""
    logger.info(f"=== chat_endpoint called === question: {req.question}, username: {req.username}")

    query = req.question
    user = req.username or "guest"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    answer = ""
    enhanced_info: dict = {}
    docs = []

    try:
        globals_dict = get_app_globals()
        vectorstore = globals_dict['vectorstore']
        rag_chain_template = globals_dict['rag_chain_template']
        llm_instance = globals_dict['llm_instance']

        logger.info(
            f"System status - Vectorstore: {vectorstore is not None}, "
            f"RAG chain: {rag_chain_template is not None}, LLM: {llm_instance is not None}"
        )

        # 初期化未完了
        if not vectorstore and not llm_instance:
            logger.error("System not properly initialized")
            return JSONResponse(
                status_code=503,
                content={
                    "answer": "システムが正しく初期化されていません。管理者にお問い合わせください。",
                    "sources": [],
                    "status": "error",
                    "error": "Service temporarily unavailable"
                }
            )

        # 雑談/挨拶は最短経路でLLMに
        if is_general_greeting_or_chat(query):
            logger.info("Detected general chat/greeting - using direct LLM response")
            answer = (
                get_general_response_from_llm(query, llm_instance)
                if llm_instance else
                ("こんにちは！ご質問をお聞かせください。" if "こんにちは" in query else "申し訳ございません。お手伝いできることがあれば、お気軽にお尋ねください。")
            )

        # RAG経路
        elif vectorstore and rag_chain_template:
            logger.info("Using RAG chain for technical/document-based query")
            try:
                # 検索 + トレース
                docs = vectorstore.similarity_search(query, k=3)
                tracer.trace_retrieval(query, docs)

                # 生成
                if hasattr(rag_chain_template, '__call__'):
                    result = rag_chain_template({"query": query})
                elif hasattr(rag_chain_template, 'invoke'):
                    result = rag_chain_template.invoke({"query": query})
                else:
                    result = rag_chain_template({"query": query}, callbacks=[])

                raw_answer = result.get("result", "")
                logger.info(f"Raw RAG response: {raw_answer[:200]}...")

                # ハルチネーション対策の強化（外部統合）
                enhanced_result = await enhance_web_chat_response(
                    query=query,
                    original_response=raw_answer,
                    user_context={"username": user}
                )
                answer = enhanced_result.get("answer") or ""
                enhanced_info = enhanced_result or {}

                # 生成のトレース
                context = "\n".join([getattr(doc, "page_content", "") for doc in docs])
                tracer.trace_generation(query, context, answer)

                logger.info(
                    f"Enhanced response: {answer[:200]}... "
                    f"(anti_hallucination_used={enhanced_result.get('anti_hallucination_used', False)})"
                )

            except Exception as e:
                logger.error(f"RAG chain error: {e}")
                logger.error(traceback.format_exc())
                answer = (
                    get_general_response_from_llm(query, llm_instance)
                    if llm_instance else
                    "申し訳ございません。質問の処理中にエラーが発生しました。"
                )

        # LLMのみ
        else:
            answer = (
                get_general_response_from_llm(query, llm_instance)
                if llm_instance else
                "申し訳ございません。システムが準備中です。しばらくしてから再度お試しください。"
            )

    except Exception as e:
        error_id = str(uuid4())[:8]
        logger.error(f"Unexpected error [{error_id}]: {e}")
        logger.error(traceback.format_exc())
        answer = f"システムエラーが発生しました。管理者にお問い合わせください。（エラーID: {error_id}）"

    # 最終整形（保険）
    answer = clean_rag_response(answer)

    # ログ保存
    log = {
        "id": str(uuid4()),
        "question": query,
        "username": user,
        "answer": answer,
        "timestamp": now,
        "sources": [],
        "enhanced_info": enhanced_info
    }
    history_logs.append(log)

    # レスポンス
    resp = {
        "answer": answer,
        "sources": enhanced_info.get("sources", []),
        "status": "ok"
    }

    # デバッグモード: 検証情報を同梱
    if os.getenv("DEBUG_MODE", "").lower() == "true":
        resp["verification"] = {
            "method": enhanced_info.get("verification_method"),
            "note": enhanced_info.get("verification_note"),
            "confidence": enhanced_info.get("confidence_level"),
            "last_updated": enhanced_info.get("last_updated"),
            "warnings": enhanced_info.get("warnings", [])
        }

    logger.info(f"Final response: {answer[:100]}...")
    return resp

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
