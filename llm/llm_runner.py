# llm/llm_runner.py

from __future__ import annotations
import os
import logging
from typing import Any, Tuple

# ── まずプロキシ環境変数をクリアしておく ─────────────────────────────────────────────
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
# ───────────────────────────────────────────────────────────────────────────────────

print("==== [llm_runner] DEBUG: OPENAI_API_KEY =", (os.environ.get("OPENAI_API_KEY") or "")[:10], "****")
print("==== [llm_runner] DEBUG: USE_LOCAL_LLM =", os.environ.get("USE_LOCAL_LLM"))

from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    BitsAndBytesConfig,
    pipeline,
)
from langchain_community.llms import HuggingFacePipeline

# LangChain 0.2.x 系では langchain_community.chat_models からインポートするか、
# または別途 pip install langchain-openai している場合は langchain_openai からインポートする
# ここでは langchain-openai を使う想定で書いています。
try:
    # 優先： langchain_openai がインストールされている場合
    from langchain_openai import ChatOpenAI
except ImportError:
    # pip install langchain-openai を行っていない場合はこちら
    from langchain_community.chat_models import ChatOpenAI

logger = logging.getLogger(__name__)


def _load_local_rinna() -> Tuple[Any, Any, int]:
    """
    rinna/japanese-gpt-neox-3.6b-instruction-ppo モデルを 8bit or float16 でロードし、
    HuggingFacePipeline に変換して返す。
    """
    model_name = "rinna/japanese-gpt-neox-3.6b-instruction-ppo"
    cache_dir = os.getenv("HF_HOME", "/tmp/huggingface")
    max_new_tokens = int(os.getenv("MAX_NEW_TOKENS", 256))

    tokenizer = AutoTokenizer.from_pretrained(
        model_name, use_fast=False, trust_remote_code=True, cache_dir=cache_dir
    )
    try:
        logger.info("🧠 Loading rinna 3.6B in 8-bit")
        bnb_cfg = BitsAndBytesConfig(load_in_8bit=True)
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            device_map="auto",
            quantization_config=bnb_cfg,
            trust_remote_code=True,
            cache_dir=cache_dir,
        )
    except Exception as e:
        logger.warning(f"⚠️ 8-bit load failed: {e} / fallback to float16")
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype="auto",
            device_map="auto",
            trust_remote_code=True,
            cache_dir=cache_dir,
        )

    gen_pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=max_new_tokens,
        temperature=0.7,
        top_p=0.95,
        repetition_penalty=1.1,
    )
    llm = HuggingFacePipeline(pipeline=gen_pipe)
    return llm, tokenizer, max_new_tokens


def load_llm() -> Tuple[Any, Any | None, int]:
    """
    USE_LOCAL_LLM と MODEL_PRESET に応じて LLM（OpenAI か Rinna）を返す。
    プロキシ環境変数はすでにファイル冒頭でクリア済みなので、
    ChatOpenAI のインスタンス化時に proxies が渡されることはありません。
    """
    print(">>> [load_llm] ChatOpenAI is from:", ChatOpenAI)

    preset = os.getenv("MODEL_PRESET", "auto").lower()
    max_new_tokens = int(os.getenv("MAX_NEW_TOKENS", 256))
    api_key = os.environ.get("OPENAI_API_KEY")

    # auto/heavy の場合、API キー必須チェック
    if preset in ("auto", "heavy"):
        if not api_key or not api_key.startswith("sk-"):
            raise RuntimeError(
                "OPENAI_API_KEY が未設定、または形式が不正です！（sk- から始まる値が必要）"
            )

    # ローカルモデル（軽量版）を使いたい場合
    if preset == "light":
        llm, tokenizer, max_new_tokens = _load_local_rinna()
        return llm, tokenizer, max_new_tokens

    # heavy preset: GPT-4o など、OpenAI 使う場合
    if preset == "heavy":
        llm = ChatOpenAI(
            model_name="gpt-4o",
            temperature=0,
            openai_api_key=api_key
        )
        return llm, None, max_new_tokens

    # auto（デフォルト）: gpt-3.5-turbo
    llm = ChatOpenAI(
        model_name="gpt-3.5-turbo-0125",
        temperature=0,
        openai_api_key=api_key
    )
    return llm, None, max_new_tokens
