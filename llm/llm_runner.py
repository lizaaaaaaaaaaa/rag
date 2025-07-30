# llm/llm_runner.py - 完全版（LangSmithエラー修正済み）

from __future__ import annotations
import os
import logging
from typing import Any, Tuple

# ── 先頭で必ず proxies 関連の環境変数を消す ──────────────
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
# ────────────────────────────────────────────────

# ── ロガーを最初に定義 ────────────────
logger = logging.getLogger(__name__)

# ── LangSmithを完全に無効化してエラーを回避 ────────────────
def disable_langsmith():
    """LangSmithを完全に無効化"""
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["DISABLE_LANGSMITH"] = "true"
    os.environ.pop("LANGSMITH_API_KEY", None)  # API keyも削除
    logger.info("🔒 LangSmith completely disabled to avoid errors")

# LangSmith無効化を実行
disable_langsmith()

# ── ダミートレーサーの定義 ────────────────
def traceable(name=None, **kwargs):
    """ダミートレーサー（エラー回避用）"""
    def decorator(func):
        return func
    return decorator

# LangSmithライブラリが存在してもダミーを使用
HAS_LANGSMITH = False
logger.info("⚠️ LangSmith functionality disabled by design")

# langchain-openaiを使用（より安定）
try:
    from langchain_openai import ChatOpenAI
    logger.info("✅ ChatOpenAI imported successfully")
except ImportError as e:
    logger.error(f"❌ Failed to import ChatOpenAI: {e}")
    raise

@traceable(name="load_llm_trace")
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
    model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")
    temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.3"))  # デフォルトを0.3に変更

    try:
        # 基本的なChatOpenAIインスタンス（LangSmith関連設定を除外）
        llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            openai_api_key=api_key,
            max_retries=3,
            request_timeout=60,  # タイムアウトを60秒に延長
        )

        # テスト呼び出し（エラーハンドリング強化）
        logger.info(f"Testing LLM connection with model: {model_name}")
        try:
            test_response = llm.invoke("Hello")
            logger.info("✅ LLM test successful")
        except Exception as test_error:
            logger.warning(f"⚠️ LLM test warning (non-critical): {test_error}")
            # テスト失敗でも続行（実際の使用時に再試行）

    except Exception as e:
        logger.error(f"❌ Failed to initialize ChatOpenAI: {e}")
        raise

    # 3) max_new_tokens は環境変数 MAX_NEW_TOKENS から（指定がなければ 256）
    max_new_tokens = int(os.getenv("MAX_NEW_TOKENS", 512))  # デフォルトを512に増加

    logger.info(f">>> [load_llm] ChatOpenAI loaded successfully:")
    logger.info(f"    Model: {model_name}")
    logger.info(f"    Temperature: {temperature}")
    logger.info(f"    Max tokens: {max_new_tokens}")
    
    return llm, None, max_new_tokens


# === ダミーのトレース関数（互換性のため） ===
@traceable(name="rag_chain_evaluation")
def load_llm_with_tracing():
    """トレース機能付きのLLM読み込み（ダミー実装）"""
    logger.info("🔄 Loading LLM with dummy tracing...")
    return load_llm()


@traceable(name="rag_chat_complete")
def chat_with_tracing(query: str, user: str):
    """
    トレース機能付きチャット処理（ダミー実装）
    ここにRAGなど既存のチャット処理を実装
    """
    logger.info(f"🤖 Processing chat with dummy tracing: user={user}, query={query[:50]}...")
    
    try:
        llm, _, _ = load_llm()
        
        # より自然な日本語プロンプト
        prompt = f"""あなたは親切で知識豊富な住宅・建築の専門アドバイザーです。
ユーザー（{user}）からの以下の質問に対して、自然で分かりやすい日本語で回答してください。

質問: {query}

回答は簡潔で具体的にお願いします。"""
        
        response = llm.invoke(prompt)
        result = response.content if hasattr(response, "content") else str(response)
        
        logger.info(f"✅ Chat processing successful: {len(result)} characters")
        return result
        
    except Exception as e:
        logger.error(f"❌ Chat processing error: {e}")
        return "申し訳ございません。一時的にエラーが発生しました。しばらくしてから再度お試しください。"


# === LLM健康チェック関数 ===
def health_check_llm() -> dict:
    """LLMの健康状態をチェック"""
    try:
        llm, _, max_tokens = load_llm()
        
        # 簡単なテスト
        test_response = llm.invoke("こんにちは")
        response_text = test_response.content if hasattr(test_response, 'content') else str(test_response)
        
        return {
            "status": "healthy",
            "model": os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo"),
            "temperature": float(os.getenv("OPENAI_TEMPERATURE", "0.3")),
            "max_tokens": max_tokens,
            "test_response_length": len(response_text),
            "langsmith_disabled": True
        }
        
    except Exception as e:
        logger.error(f"LLM health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "langsmith_disabled": True
        }


# === エラー回復機能 ===
def recover_llm_connection() -> bool:
    """LLM接続の回復を試行"""
    try:
        logger.info("🔄 Attempting to recover LLM connection...")
        
        # 環境変数を再確認
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.error("❌ OPENAI_API_KEY not found during recovery")
            return False
        
        # 新しいインスタンスを作成してテスト
        llm, _, _ = load_llm()
        test_response = llm.invoke("テスト")
        
        logger.info("✅ LLM connection recovered successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to recover LLM connection: {e}")
        return False


# === 設定情報取得関数 ===
def get_llm_config() -> dict:
    """現在のLLM設定情報を取得"""
    return {
        "model_name": os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo"),
        "temperature": float(os.getenv("OPENAI_TEMPERATURE", "0.3")),
        "max_new_tokens": int(os.getenv("MAX_NEW_TOKENS", 512)),
        "api_key_set": bool(os.environ.get("OPENAI_API_KEY")),
        "langsmith_disabled": True,
        "langchain_tracing": os.environ.get("LANGCHAIN_TRACING_V2", "false"),
        "disable_langsmith": os.environ.get("DISABLE_LANGSMITH", "false")
    }


# === メイン実行部分（テスト用） ===
if __name__ == "__main__":
    print("🧪 LLM Runner Test")
    print("=" * 50)
    
    # 設定情報を表示
    config = get_llm_config()
    print("📋 Current Configuration:")
    for key, value in config.items():
        print(f"  {key}: {value}")
    
    print("\n🔍 Health Check:")
    health = health_check_llm()
    for key, value in health.items():
        print(f"  {key}: {value}")
    
    if health["status"] == "healthy":
        print("\n✅ LLM is working correctly!")
        
        # サンプルチャットテスト
        print("\n💬 Sample Chat Test:")
        test_query = "住宅の坪単価について教えてください"
        response = chat_with_tracing(test_query, "test-user")
        print(f"Query: {test_query}")
        print(f"Response: {response[:200]}...")
    else:
        print("\n❌ LLM is not working properly!")
        
        # 回復を試行
        print("\n🔄 Attempting recovery...")
        if recover_llm_connection():
            print("✅ Recovery successful!")
        else:
            print("❌ Recovery failed!")