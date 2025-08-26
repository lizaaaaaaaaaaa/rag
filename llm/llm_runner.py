# llm/llm_runner.py - 高速化版（応答速度最適化）

from __future__ import annotations
import os
import logging
import time  # time モジュールを追加
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
    """ダミートレーサー"""
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
    高速化重視のLLM読み込み（応答速度最適化版）
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not api_key.startswith("sk-"):
        raise RuntimeError("OPENAI_API_KEY が未設定、または形式が不正です！")

    # 🚀 高速化設定（大幅改善）
    model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")
    temperature = 0.1  # 一貫性重視
    max_new_tokens = 250  # 🔧 大幅削減：800→250（応答速度優先）
    request_timeout = 12  # 🔧 短縮：30→12秒
    streaming = True      # 🔧 ストリーミング有効化

    try:
        llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            openai_api_key=api_key,
            max_retries=2,  # リトライ回数削減：3→2
            request_timeout=request_timeout,  # 🔧 タイムアウト短縮
            max_tokens=max_new_tokens,  # 🔧 トークン数大幅削減
            streaming=streaming,  # 🔧 ストリーミング有効
        )

        logger.info(f"✅ High-speed LLM loaded: {model_name}, tokens: {max_new_tokens}")

    except Exception as e:
        logger.error(f"❌ Failed to initialize ChatOpenAI: {e}")
        raise

    logger.info(f">>> [load_llm] High-Speed ChatOpenAI Configuration:")
    logger.info(f"    Model: {model_name}")
    logger.info(f"    Temperature: {temperature}")
    logger.info(f"    Max tokens: {max_new_tokens} (optimized for speed)")
    logger.info(f"    Timeout: {request_timeout}s (reduced)")
    logger.info(f"    Streaming: {streaming} (enabled)")
    logger.info(f"    🚀 Speed Optimization: ENABLED")
    
    return llm, None, max_new_tokens

def ensure_complete_sentence_fast(text: str, query: str = "") -> str:
    """高速文章完全性確保（軽量版）"""
    if not text or len(text.strip()) < 3:
        return generate_fast_fallback_response(query)
    
    text = text.strip()
    
    # 🚀 高速補完（最小限のパターンマッチング）
    if not text.endswith(('。', '！', '？', '.', '!', '?')):
        logger.debug(f"🔧 Fast completion: '{text[-30:]}'")
        
        # 最頻出パターンのみ対応
        if text.endswith(('や', 'について', 'ます', 'です', '重要', '必要')):
            text += '。'
        elif text.endswith('、'):
            text = text[:-1] + '。'
        elif len(text) > 20:
            text += '。'
        else:
            text = generate_fast_fallback_response(query)
        
        logger.debug(f"✅ Fast completion done: '{text[-30:]}'")
    
    return text

def generate_fast_fallback_response(query: str) -> str:
    """高速フォールバック応答生成（キーワードベース）"""
    q_lower = query.lower()
    
    # 🚀 高速キーワードマッチング（最小限）
    if "坪単価" in q_lower or "価格" in q_lower:
        return "坪単価は約70〜85万円/坪です。詳細なお見積りをご提供いたします。"
    elif "仕様" in q_lower or "標準" in q_lower:
        return "標準仕様は耐震等級3の長期優良住宅基準です。詳細は展示場でご確認ください。"
    elif "断熱" in q_lower:
        return "高性能断熱材を使用し、快適な住環境を実現しています。"
    elif "資料" in q_lower:
        return "資料請求を承ります。お気軽にお申し付けください。"
    elif "展示" in q_lower:
        return "展示場見学を承ります。スタッフが丁寧にご案内いたします。"
    else:
        return "住宅に関することでしたら何でもお気軽にお問い合わせください。"

@traceable(name="fast_chat_response")
def chat_with_tracing(query: str, user: str):
    """
    高速チャット処理（応答速度最優先版）
    """
    logger.info(f"🚀 Fast response processing: user={user}, query={query[:30]}...")
    
    try:
        llm, _, _ = load_llm()
        
        # 🚀 高速化プロンプト（簡潔版）
        prompt = f"""住宅専門AIとして簡潔に回答してください。

【重要ルール】
1. 150文字以内で回答
2. 「です・ます」調で丁寧に
3. 句点（。）で終わる
4. 推測での回答禁止

質問: {query}

回答:"""
        
        response = llm.invoke(prompt)
        result = response.content if hasattr(response, "content") else str(response)
        
        # 🚀 高速完全性チェック（軽量版）
        complete_result = ensure_complete_sentence_fast(result, query)
        
        logger.info(f"✅ Fast chat response: {len(complete_result)} chars")
        logger.debug(f"🔚 Response ends: '{complete_result[-15:]}'")
        
        return complete_result
        
    except Exception as e:
        logger.error(f"❌ Fast chat error: {e}")
        # 高速フォールバック
        return ensure_complete_sentence_fast(
            "一時的にエラーが発生しました。しばらく後に再度お試しください。",
            query
        )

def health_check_llm() -> dict:
    """高速化LLMヘルスチェック"""
    try:
        llm, _, max_tokens = load_llm()
        test_response = llm.invoke("住宅について簡潔に教えてください。")
        response_text = test_response.content if hasattr(test_response, 'content') else str(test_response)
        
        is_complete = response_text.endswith(('。', '！', '？', '.', '!', '?'))
        
        return {
            "status": "healthy",
            "model": os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo"),
            "max_tokens": max_tokens,
            "timeout": 12,
            "streaming": True,
            "optimization_level": "high_speed",
            "response_time": "optimized",
            "test_response_length": len(response_text),
            "sentence_complete": is_complete,
            "speed_features": [
                "Reduced max_tokens (800→250)",
                "Shorter timeout (30→12s)",
                "Streaming enabled",
                "Fast completion check",
                "Lightweight fallback"
            ]
        }
        
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

# LLMインスタンスキャッシュ（高速化用）
_cached_llm = None
_cache_timestamp = 0

def get_cached_llm_instance():
    """キャッシュされたLLMインスタンス取得（高速化）"""
    global _cached_llm, _cache_timestamp
    
    current_time = time.time()
    if _cached_llm is None or (current_time - _cache_timestamp) > 3600:  # 1時間キャッシュ
        _cached_llm, _, _ = load_llm()
        _cache_timestamp = current_time
        logger.info("🚀 LLM instance cached for high-speed access")
    
    return _cached_llm

if __name__ == "__main__":
    print("🚀 High-Speed LLM Runner Test")
    config = {
        "model_name": os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo"),
        "max_tokens": 250,  # 🔧 削減
        "timeout": 12,      # 🔧 短縮
        "streaming": True,  # 🔧 有効化
        "optimization": "high_speed_mode"
    }
    print("📋 Speed-Optimized Configuration:", config)
    
    health = health_check_llm()
    print("🔍 Health Check:", health)
    
    if health["status"] == "healthy":
        test_queries = [
            "坪単価は？",
            "標準仕様について",
            "断熱性能は？"
        ]
        
        for test_query in test_queries:
            start_time = time.time()
            response = chat_with_tracing(test_query, "speed-test")
            processing_time = time.time() - start_time
            
            print(f"💬 Query: {test_query}")
            print(f"🤖 Response: {response}")
            print(f"⚡ Speed: {processing_time:.2f}s")
            print(f"✅ Complete: {response.endswith(('。', '！', '？', '.', '!', '?'))}")
            print("-" * 50)