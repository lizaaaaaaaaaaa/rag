# llm/llm_runner.py - レスポンス速度最適化版

from __future__ import annotations
import os
import logging
from typing import Any, Tuple

# LangSmith無効化
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["DISABLE_LANGSMITH"] = "true"

logger = logging.getLogger(__name__)

def disable_langsmith():
    """LangSmithを完全に無効化"""
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["DISABLE_LANGSMITH"] = "true"
    os.environ.pop("LANGSMITH_API_KEY", None)

disable_langsmith()

def traceable(name=None, **kwargs):
    """ダミートレーサー（パフォーマンス重視）"""
    def decorator(func):
        return func
    return decorator

try:
    from langchain_openai import ChatOpenAI
    logger.info("✅ ChatOpenAI imported successfully")
except ImportError as e:
    logger.error(f"❌ Failed to import ChatOpenAI: {e}")
    raise

@traceable(name="load_llm_trace")
def load_llm() -> Tuple[Any, None, int]:
    """
    レスポンス速度最適化されたLLM読み込み
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not api_key.startswith("sk-"):
        raise RuntimeError("OPENAI_API_KEY が未設定、または形式が不正です！")

    # パフォーマンス重視の設定
    model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")
    temperature = 0.1  # 一貫性重視でレスポンス高速化
    max_new_tokens = 200  # トークン数を大幅削減してレスポンス高速化

    try:
        llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            openai_api_key=api_key,
            max_retries=1,  # リトライ回数を削減
            request_timeout=15,  # タイムアウトを短縮
            max_tokens=max_new_tokens,  # 最大トークン数を制限
            streaming=False,  # ストリーミング無効化で安定性確保
        )

        logger.info(f"✅ High-performance LLM loaded: {model_name}, tokens: {max_new_tokens}")

    except Exception as e:
        logger.error(f"❌ Failed to initialize ChatOpenAI: {e}")
        raise

    logger.info(f">>> [load_llm] Fast ChatOpenAI loaded:")
    logger.info(f"    Model: {model_name}")
    logger.info(f"    Temperature: {temperature}")
    logger.info(f"    Max tokens: {max_new_tokens}")
    logger.info(f"    Timeout: 15s")
    
    return llm, None, max_new_tokens

@traceable(name="fast_chat_complete")
def chat_with_tracing(query: str, user: str):
    """
    高速チャット処理（LINE Bot最適化版）
    """
    logger.info(f"🚀 Fast processing: user={user}, query={query[:30]}...")
    
    try:
        llm, _, _ = load_llm()
        
        # 簡潔で高速なプロンプト
        prompt = f"""あなたは住宅専門のAIアドバイザーです。
質問に対して簡潔で分かりやすく答えてください。

【重要】
- 150文字以内で回答
- 「〜しましょう」は使わない
- 「です・ます」調で丁寧に
- 具体的で実用的に

質問: {query}

回答:"""
        
        response = llm.invoke(prompt)
        result = response.content if hasattr(response, "content") else str(response)
        
        # 簡潔性チェック
        if len(result) > 300:
            result = result[:280] + "詳細はお問い合わせください。"
        
        logger.info(f"✅ Fast chat completed: {len(result)} chars")
        return result
        
    except Exception as e:
        logger.error(f"❌ Fast chat error: {e}")
        return "申し訳ございません。一時的にエラーが発生しました。再度お試しください。"

def health_check_llm() -> dict:
    """高速ヘルスチェック"""
    try:
        llm, _, max_tokens = load_llm()
        test_response = llm.invoke("テスト")
        response_text = test_response.content if hasattr(test_response, 'content') else str(test_response)
        
        return {
            "status": "healthy",
            "model": os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo"),
            "max_tokens": max_tokens,
            "response_time": "optimized",
            "test_response_length": len(response_text)
        }
        
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

if __name__ == "__main__":
    print("🧪 Fast LLM Runner Test")
    config = {
        "model_name": os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo"),
        "max_tokens": 200,
        "timeout": 15,
        "optimization": "enabled"
    }
    print("📋 Fast Configuration:", config)
    
    health = health_check_llm()
    print("🔍 Health Check:", health)
    
    if health["status"] == "healthy":
        test_query = "坪単価について教えて"
        response = chat_with_tracing(test_query, "test-user")
        print(f"💬 Test Query: {test_query}")
        print(f"🤖 Response: {response}")