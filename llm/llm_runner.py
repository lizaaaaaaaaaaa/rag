from __future__ import annotations
import os
import logging
from typing import Any, Tuple

# ── LangSmith（LangChain Tracing v2）追加 ────────────────
from langsmith import traceable

# LangSmithトレース用の環境変数をセット（起動時に自動設定）
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = "rag-chat-evaluation"
# ────────────────────────────────────────────────

# ── 先頭で必ず proxies 関連の環境変数を消す ──────────────
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
# ────────────────────────────────────────────────

logger = logging.getLogger(__name__)

# langchain-openaiを使用（より安定）
from langchain_openai import ChatOpenAI


def load_llm() -> Tuple[Any, None, int]:
    """
    langchain-openai の ChatOpenAI クラスを使って OpenAI の ChatCompletion を呼び出す。

    戻り値: (llm, tokenizer, max_new_tokens)
      - llm: ChatOpenAI のインスタンス
      - tokenizer: 使わないので None
      - max_new_tokens: 環境変数 MAX_NEW_TOKENS から（指定がなければ 256）
    """

    # 1) API キーをチェック
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not api_key.startswith("sk-"):
        raise RuntimeError(
            "OPENAI_API_KEY が未設定、または形式が不正です！（sk- から始まるキーが必要）"
        )

    # 2) ChatOpenAI のインスタンス化
    #    最新のモデル名に更新
    model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")
    temperature = float(os.getenv("OPENAI_TEMPERATURE", "0"))

    try:
        llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            openai_api_key=api_key,
            max_retries=3,
            request_timeout=30
        )

        # テスト呼び出し
        logger.info(f"Testing LLM connection...")
        test_response = llm.invoke("Hello")
        logger.info(f"LLM test successful")

    except Exception as e:
        logger.error(f"Failed to initialize ChatOpenAI: {e}")
        raise

    # 3) max_new_tokens は環境変数 MAX_NEW_TOKENS から（指定がなければ 256）
    max_new_tokens = int(os.getenv("MAX_NEW_TOKENS", 256))

    logger.info(f">>> [load_llm] ChatOpenAI (langchain-openai) loaded: {model_name}, temperature={temperature}")
    return llm, None, max_new_tokens


# === LangSmithトレース用のラッパー関数（LLM読み込み） ===
@traceable(name="rag_chain_evaluation")
def load_llm_with_tracing():
    """トレース機能付きのLLM読み込み"""
    return load_llm()


# === LangSmithトレース付きのチャット処理（RAG本体） ===
@traceable(name="rag_chat_complete")
def chat_with_tracing(query: str, user: str):
    """
    トレース機能付きチャット処理
    ここにRAGなど既存のチャット処理を実装
    """
    # 既存のRAG（もしくはLLM直接呼び出し）ロジックをここに書く
    # 例（疑似実装）:
    llm, _, _ = load_llm()
    prompt = f"ユーザー({user})からの質問: {query}"
    response = llm.invoke(prompt)
    return response.content if hasattr(response, "content") else str(response)
