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

# langchain-community が提供する ChatOpenAI を使う
from langchain_community.chat_models import ChatOpenAI


def load_llm() -> Tuple[Any, None, int]:
    """
    LangChain-Community の ChatOpenAI クラスを使って OpenAI の ChatCompletion を呼び出す。
    openai>=1.0.0 の SDK と互換があり、内部で proxies を渡しません。

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
    #    - model_name は環境変数 OPENAI_MODEL_NAME から（デフォルト gpt-3.5-turbo-0613）
    #    - temperature は環境変数 OPENAI_TEMPERATURE から（デフォルト 0）
    model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo-0613")
    temperature = float(os.getenv("OPENAI_TEMPERATURE", "0"))

    llm = ChatOpenAI(
        model_name=model_name,
        temperature=temperature,
        openai_api_key=api_key
    )

    # 3) max_new_tokens は環境変数 MAX_NEW_TOKENS から（指定がなければ 256）
    max_new_tokens = int(os.getenv("MAX_NEW_TOKENS", 256))

    print(f">>> [load_llm] ChatOpenAI (langchain_community) loaded: {model_name}, temperature={temperature}")
    return llm, None, max_new_tokens
