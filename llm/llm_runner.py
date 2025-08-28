# llm/llm_runner.py - 応答切れ対策・完全修正版

from __future__ import annotations
import os
import logging
import time
from typing import Any, Tuple

# LangSmith 完全無効化
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["DISABLE_LANGSMITH"] = "true"

logger = logging.getLogger(__name__)


def disable_langsmith():
    """LangSmith を完全に無効化"""
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["DISABLE_LANGSMITH"] = "true"
    os.environ.pop("LANGSMITH_API_KEY", None)


disable_langsmith()


def traceable(name=None, **kwargs):
    """ダミートレーサー（互換維持用）"""
    def decorator(func):
        return func
    return decorator


try:
    from langchain_openai import ChatOpenAI
    logger.info("✅ ChatOpenAI imported successfully")
except ImportError as e:
    logger.error(f"❌ Failed to import ChatOpenAI: {e}")
    raise


@traceable(name="load_optimized_llm")
def load_llm() -> Tuple[Any, None, int]:
    """
    LLM 読み込み（応答切れ対策）
    - 生成長さ/タイムアウトは環境変数で調整可能
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not api_key.startswith("sk-"):
        raise RuntimeError("OPENAI_API_KEY が未設定、または形式が不正です！")

    # ⬇︎ ここを環境変数で柔軟化（既定を十分大きく）
    model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")
    temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.1"))
    max_new_tokens = int(os.getenv("MAX_NEW_TOKENS", "900"))    # 既定900
    request_timeout = int(os.getenv("LLM_TIMEOUT", "45"))       # 既定45s
    streaming = os.getenv("OPENAI_STREAMING", "false").lower() == "true"
    max_retries = int(os.getenv("OPENAI_RETRIES", "2"))

    try:
        llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            openai_api_key=api_key,
            max_retries=max_retries,
            request_timeout=request_timeout,
            max_tokens=max_new_tokens,
            streaming=streaming,
        )
        logger.info(
            "✅ LLM loaded: model=%s, max_tokens=%s, timeout=%ss, streaming=%s",
            model_name, max_new_tokens, request_timeout, streaming
        )
    except Exception as e:
        logger.error(f"❌ Failed to initialize ChatOpenAI: {e}")
        raise

    return llm, None, max_new_tokens


def ensure_complete_sentence_fast(text: str, query: str = "") -> str:
    """簡易文章終端整形（句点で終わらせる等）"""
    if not text or len(text.strip()) < 3:
        return generate_fast_fallback_response(query)

    text = text.strip()
    if not text.endswith(("。", "！", "？", ".", "!", "?")):
        if text.endswith(("や", "について", "ます", "です", "重要", "必要", "ので")):
            text += "。"
        elif text.endswith("、"):
            text = text[:-1] + "。"
        elif len(text) > 20:
            text += "。"
        else:
            text = generate_fast_fallback_response(query)
    return text


def generate_fast_fallback_response(query: str) -> str:
    """高速フォールバック（最低限の定型）"""
    q = (query or "").lower()
    if "坪単価" in q or "価格" in q:
        return "坪単価は目安で70〜85万円/坪です。詳細は個別にお見積もりいたします。"
    if "仕様" in q or "標準" in q:
        return "標準仕様は耐震等級3・省エネ基準適合です。詳細は展示場でご案内します。"
    if "断熱" in q:
        return "高性能断熱材と高断熱サッシで快適な住環境を実現します。"
    if "資料" in q:
        return "資料請求を承ります。お気軽にお申し付けください。"
    if "展示" in q:
        return "展示場見学をご案内できます。ご希望日時をお知らせください。"
    return "住宅に関するご質問があれば何でもお聞かせください。"


def _build_prompt(query: str) -> str:
    """
    返信方針を柔軟化。
    - 既定では文字数制限なし
    - FAST_REPLY_CHAR_LIMIT を設定した場合のみ上限を明示
    """
    limit = int(os.getenv("FAST_REPLY_CHAR_LIMIT", "0"))
    rules = [
        "日本語で丁寧に回答してください。",
        "推測や誤情報は避け、分からない場合はその旨を伝えてください。",
        "必要なら箇条書きや段落で整理して構いません。",
        "最後は句点（。）で終えてください。",
    ]
    if limit > 0:
        rules.insert(0, f"{limit}文字以内で簡潔にまとめてください。")

    rules_block = "\n".join(f"{i+1}. {r}" for i, r in enumerate(rules))

    return f"""あなたは住宅専門のAIアシスタントです。以下のルールに従って回答してください。

【ルール】
{rules_block}

【質問】
{query}

【回答】"""


@traceable(name="fast_chat_response")
def chat_with_tracing(query: str, user: str) -> str:
    """
    高速チャット処理（応答切れ対策版）
    - 文字数制限は ENV で必要なときだけ有効化
    """
    logger.info("🚀 Fast response: user=%s, query=%.30s...", user, (query or ""))
    try:
        llm, _, _ = load_llm()
        prompt = _build_prompt(query or "")
        resp = llm.invoke(prompt)
        text = resp.content if hasattr(resp, "content") else str(resp)
        return ensure_complete_sentence_fast(text, query)
    except Exception as e:
        logger.error(f"❌ Fast chat error: {e}")
        return ensure_complete_sentence_fast(
            "一時的に処理が混み合っています。時間をおいて再度お試しください。", query
        )


def chat_completion(prompt: str) -> str:
    """
    互換API：`chat_unified.py` からの呼び出し用。
    ここ経由でも ENV の max_tokens / timeout 設定が反映されます。
    """
    try:
        llm = get_cached_llm_instance()
        resp = llm.invoke(prompt)
        return resp.content if hasattr(resp, "content") else str(resp)
    except Exception as e:
        logger.error(f"chat_completion error: {e}")
        return "ただいま回答の生成に時間がかかっています。少し間をおいてお試しください。"


def health_check_llm() -> dict:
    """LLM ヘルスチェック（設定値も返す）"""
    try:
        llm, _, max_tokens = load_llm()
        test = llm.invoke("住宅について簡潔に教えてください。")
        text = test.content if hasattr(test, "content") else str(test)
        return {
            "status": "healthy",
            "model": os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo"),
            "max_tokens": max_tokens,
            "timeout": int(os.getenv("LLM_TIMEOUT", "45")),
            "streaming": os.getenv("OPENAI_STREAMING", "false").lower() == "true",
            "temperature": float(os.getenv("OPENAI_TEMPERATURE", "0.1")),
            "fast_reply_char_limit": int(os.getenv("FAST_REPLY_CHAR_LIMIT", "0")),
            "test_response_length": len(text),
            "sentence_complete": text.endswith(("。", "！", "？", ".", "!", "?")),
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


# LLM インスタンスキャッシュ
_cached_llm = None
_cache_timestamp = 0


def get_cached_llm_instance():
    """キャッシュされた LLM インスタンス取得（1時間キャッシュ）"""
    global _cached_llm, _cache_timestamp
    now = time.time()
    if _cached_llm is None or (now - _cache_timestamp) > 3600:
        _cached_llm, _, _ = load_llm()
        _cache_timestamp = now
        logger.info("🚀 LLM instance cached")
    return _cached_llm


if __name__ == "__main__":
    print("🚀 LLM Runner — config preview")
    print({
        "model": os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo"),
        "max_tokens": int(os.getenv("MAX_NEW_TOKENS", "900")),
        "timeout": int(os.getenv("LLM_TIMEOUT", "45")),
        "streaming": os.getenv("OPENAI_STREAMING", "false"),
        "fast_reply_char_limit": int(os.getenv("FAST_REPLY_CHAR_LIMIT", "0")),
    })
    health = health_check_llm()
    print("🔍 Health:", health)
