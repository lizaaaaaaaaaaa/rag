# llm/llm_runner.py
from __future__ import annotations
import os, logging
from typing import Any, Tuple

# --- OPENAI_API_KEY デバッグ出力 ---
print("==== [llm_runner] DEBUG: OPENAI_API_KEY =", (os.environ.get("OPENAI_API_KEY") or "")[:10], "****")
print("==== [llm_runner] DEBUG: USE_LOCAL_LLM =", os.environ.get("USE_LOCAL_LLM"))

from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    BitsAndBytesConfig,
    pipeline,
)
from langchain_community.llms import HuggingFacePipeline
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

def _load_local_rinna() -> Tuple[Any, Any, int]:
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
    preset = os.getenv("MODEL_PRESET", "auto").lower()
    max_new_tokens = int(os.getenv("MAX_NEW_TOKENS", 256))
    api_key = os.environ.get("OPENAI_API_KEY")

    if preset in ("auto", "heavy"):
        if not api_key or not api_key.startswith("sk-"):
            raise RuntimeError("OPENAI_API_KEYが未設定、または形式が不正です！（sk- から始まる値が必要）")

    if preset == "light":
        llm, tokenizer, max_new_tokens = _load_local_rinna()
        return llm, tokenizer, max_new_tokens

    if preset == "heavy":
        return ChatOpenAI(model_name="gpt-4o", temperature=0, openai_api_key=api_key), None, max_new_tokens

    # auto（デフォルト：gpt-3.5-turbo）
    return ChatOpenAI(model_name="gpt-3.5-turbo-0125", temperature=0, openai_api_key=api_key), None, max_new_tokens
