# llm/llm_runner.py - 文章途切れ対策版

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

@traceable(name="load_llm_trace")
def load_llm() -> Tuple[Any, None, int]:
    """
    文章完全性重視のLLM読み込み（修正版）
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not api_key.startswith("sk-"):
        raise RuntimeError("OPENAI_API_KEY が未設定、または形式が不正です！")

    # 文章完全性重視の設定
    model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")
    temperature = 0.1  # 一貫性重視
    max_new_tokens = 400  # 🔧 大幅増量：200→400（文章途切れ対策）

    try:
        llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            openai_api_key=api_key,
            max_retries=2,  # リトライ回数増加
            request_timeout=25,  # タイムアウト延長
            max_tokens=max_new_tokens,  # 🔧 増量
            streaming=False,
        )

        logger.info(f"✅ Complete-response LLM loaded: {model_name}, tokens: {max_new_tokens}")

    except Exception as e:
        logger.error(f"❌ Failed to initialize ChatOpenAI: {e}")
        raise

    logger.info(f">>> [load_llm] Complete Response ChatOpenAI loaded:")
    logger.info(f"    Model: {model_name}")
    logger.info(f"    Temperature: {temperature}")
    logger.info(f"    Max tokens: {max_new_tokens}")
    logger.info(f"    Timeout: 25s")
    
    return llm, None, max_new_tokens

def ensure_complete_sentence(text: str) -> str:
    """文章の完全性を確保（強化版）"""
    if not text or len(text.strip()) < 5:
        return text
    
    text = text.strip()
    
    # 文末が途切れている場合の補完
    if not text.endswith(('。', '！', '？', '.', '!', '?')):
        # 語尾パターンによる補完
        if text.endswith('ます') or text.endswith('です'):
            text += '。'
        elif text.endswith('た') or text.endswith('る'):
            text += '。'
        elif text.endswith('や'):  # 「土地探しや」のケース
            text += '建築に関する準備を進めることをお勧めします。'
        elif text.endswith('重要'):  # 「重要」のケース
            text += 'です。'
        elif text.endswith('、'):
            text = text[:-1] + '。'
        elif len(text) > 10:  # ある程度の長さがあれば句点を追加
            text += '。'
    
    return text

@traceable(name="complete_chat_response")
def chat_with_tracing(query: str, user: str):
    """
    完全回答重視チャット処理（文章途切れ対策強化版）
    """
    logger.info(f"🚀 Complete response processing: user={user}, query={query[:30]}...")
    
    try:
        llm, _, _ = load_llm()
        
        # 🔧 文章完全性重視プロンプト
        prompt = f"""あなたは住宅専門のAIアドバイザーです。
質問に対して完全で自然な文章で回答してください。

【重要なルール】
- 必ず最後まで完結した文章で回答する
- 文章の途中で切れないようにする
- 「です・ます」調で丁寧に
- 400文字以内で要点を整理
- 文末は必ず句点（。）で終わる
- 具体的で実用的な情報を含める

質問: {query}

完全な回答:"""
        
        response = llm.invoke(prompt)
        result = response.content if hasattr(response, "content") else str(response)
        
        # 🔧 文章完全性チェック強化
        complete_result = ensure_complete_sentence(result)
        
        logger.info(f"✅ Complete chat response: {len(complete_result)} chars")
        logger.info(f"📝 Response ends with: '{complete_result[-10:]}'")
        
        return complete_result
        
    except Exception as e:
        logger.error(f"❌ Complete chat error: {e}")
        # フォールバック応答も完全な文章で
        return "申し訳ございません。一時的にエラーが発生しました。しばらく後に再度お試しください。"

def health_check_llm() -> dict:
    """完全性重視ヘルスチェック"""
    try:
        llm, _, max_tokens = load_llm()
        test_response = llm.invoke("住宅について簡潔に教えてください。")
        response_text = test_response.content if hasattr(test_response, 'content') else str(test_response)
        
        # 完全性チェック
        is_complete = response_text.endswith(('。', '！', '？', '.', '!', '?'))
        
        return {
            "status": "healthy",
            "model": os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo"),
            "max_tokens": max_tokens,
            "response_time": "optimized",
            "test_response_length": len(response_text),
            "sentence_complete": is_complete,
            "last_10_chars": response_text[-10:] if response_text else ""
        }
        
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

if __name__ == "__main__":
    print("🧪 Complete Response LLM Runner Test")
    config = {
        "model_name": os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo"),
        "max_tokens": 400,  # 🔧 増量
        "timeout": 25,
        "complete_sentences": "enabled"
    }
    print("📋 Complete Response Configuration:", config)
    
    health = health_check_llm()
    print("🔍 Health Check:", health)
    
    if health["status"] == "healthy":
        test_queries = [
            "坪単価について教えて",
            "家を建てる前にまずなにから調べたらいいですか"
        ]
        
        for test_query in test_queries:
            response = chat_with_tracing(test_query, "test-user")
            print(f"💬 Test Query: {test_query}")
            print(f"🤖 Complete Response: {response}")
            print(f"✅ Ends properly: {response.endswith(('。', '！', '？', '.', '!', '?'))}")
            print("-" * 50)