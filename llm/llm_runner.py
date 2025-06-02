# llm/llm_runner.py

from __future__ import annotations
import os
import logging
from typing import Any, Tuple

# ── 先頭で必ず proxies 関連の環境変数を消す ─────────────────────────────────────────────
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
# ───────────────────────────────────────────────────────────────────────────────────────

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
    model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")  # 0613は古いので削除
    temperature = float(os.getenv("OPENAI_TEMPERATURE", "0"))

    try:
        llm = ChatOpenAI(
            model=model_name,  # model_nameではなくmodel
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