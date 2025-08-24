# llm/llm_runner.py - 修正版（文章途切れ完全対策）

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
    文章完全性重視のLLM読み込み（修正版 - max_tokens大幅増量）
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not api_key.startswith("sk-"):
        raise RuntimeError("OPENAI_API_KEY が未設定、または形式が不正です！")

    # 文章完全性重視の設定（大幅改良）
    model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")
    temperature = 0.1  # 一貫性重視
    max_new_tokens = 800  # 🔧 大幅増量：400→800（文章途切れ完全対策）

    try:
        llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            openai_api_key=api_key,
            max_retries=3,  # リトライ回数増加
            request_timeout=30,  # タイムアウト延長
            max_tokens=max_new_tokens,  # 🔧 大幅増量
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
    logger.info(f"    Timeout: 30s")
    
    return llm, None, max_new_tokens

def ensure_complete_sentence(text: str, query: str = "") -> str:
    """文章の完全性を確保（強化版）"""
    if not text or len(text.strip()) < 5:
        return generate_fallback_response(query)
    
    text = text.strip()
    
    # 文末が途切れている場合の補完（包括的対応）
    if not text.endswith(('。', '！', '？', '.', '!', '?')):
        logger.info(f"🔧 Fixing incomplete sentence: '{text[-50:]}'")
        
        # 語尾パターンによる詳細補完
        if text.endswith('や'):  # 「土地探しや」のケース
            if "土地" in text:
                text += "建築に関する準備を総合的に進めることをお勧めします。"
            elif "資金" in text:
                text += "住宅ローンの検討も併せて進めることが重要です。"
            else:
                text += "関連する事項についても併せて検討することをお勧めします。"
        elif text.endswith('重要'):  # 「重要」のケース
            if "選定" in text:
                text += 'です。詳しい選び方についてはお気軽にご相談ください。'
            elif "計画" in text:
                text += 'なポイントです。段階的に進めることをお勧めします。'
            else:
                text += 'な要素です。詳細についてはお問い合わせください。'
        elif text.endswith('必要'):
            if "確認" in text:
                text += 'です。具体的な手続きについてはご相談ください。'
            else:
                text += 'です。'
        elif text.endswith('について'):
            text += 'は、詳細をご案内いたします。'
        elif text.endswith('選定') or text.endswith('検討'):
            text += 'も重要な工程です。'
        elif text.endswith('確認') or text.endswith('準備'):
            text += 'を進めることをお勧めします。'
        elif text.endswith('計画') or text.endswith('設計'):
            text += 'が成功の鍵となります。'
        elif text.endswith('性能') or text.endswith('品質'):
            text += 'にこだわっています。'
        elif text.endswith('対応') or text.endswith('仕様'):
            text += 'となっております。'
        elif text.endswith('条件') or text.endswith('基準'):
            text += 'を満たしています。'
        elif text.endswith('など'):
            text += 'があります。詳細はお問い合わせください。'
        elif text.endswith('から'):
            text += '、ご検討ください。'
        elif text.endswith('して'):
            text += 'います。'
        elif text.endswith('また'):
            text += '、詳細についてはお問い合わせください。'
        elif text.endswith('ます') or text.endswith('です'):
            text += '。'
        elif text.endswith('た') or text.endswith('る'):
            text += '。'
        elif text.endswith('、'):
            text = text[:-1] + '。'
        elif text.endswith('は') or text.endswith('が'):
            text += '重要なポイントです。'
        elif text.endswith('ので') or text.endswith('ため'):
            text += '、詳しくはお気軽にご相談ください。'
        else:
            # 長さと内容による補完
            if len(text) > 100:
                text += '。'
            elif len(text) > 50:
                text += '。詳しくはお問い合わせください。'
            elif len(text) > 20:
                text += '。お気軽にご相談ください。'
            else:
                text = generate_fallback_response(query)
        
        logger.info(f"✅ Fixed sentence: '{text[-50:]}'")
    
    return text

def generate_fallback_response(query: str) -> str:
    """フォールバック応答生成"""
    if "坪単価" in query or "価格" in query:
        return "坪単価については、お客様のご要望や仕様によって異なりますので、詳細なお見積りをご提供いたします。お気軽にお問い合わせください。"
    elif "仕様" in query or "標準" in query:
        return "住宅の仕様について詳しくご案内いたします。お客様のご要望に合わせて最適な仕様をご提案いたします。"
    elif "土地" in query:
        return "土地探しから建築まで、トータルでサポートいたします。お客様のご希望条件をお聞かせください。"
    elif "ローン" in query or "資金" in query:
        return "住宅ローンや資金計画について、専門スタッフがご相談を承ります。お気軽にお問い合わせください。"
    else:
        return "お尋ねの内容について詳しくご案内いたします。住宅に関することでしたら何でもお気軽にお問い合わせください。"

@traceable(name="complete_chat_response")
def chat_with_tracing(query: str, user: str):
    """
    完全回答重視チャット処理（文章途切れ対策強化版）
    """
    logger.info(f"🚀 Complete response processing: user={user}, query={query[:30]}...")
    
    try:
        llm, _, _ = load_llm()
        
        # 🔧 文章完全性重視プロンプト（大幅改良）
        prompt = f"""あなたは住宅専門のAIアドバイザーです。
質問に対して完全で自然な文章で回答してください。

【最重要ルール】
1. 必ず最後まで完結した文章で回答する
2. 文章の途中で絶対に切れないようにする
3. 「や」「重要」「必要」「について」などで終わらない
4. 「です・ます」調で丁寧に
5. 500文字以内で要点を整理
6. 文末は必ず句点（。）で終わる
7. 具体的で実用的な情報を含める
8. 自然で読みやすい文章構成

【禁止事項】
- 文章の途中で切れること
- 不完全な文末
- 推測や憶測での回答
- 〜しましょうの使用

質問: {query}

上記のルールを厳守して、完全で自然な回答をお願いします："""
        
        response = llm.invoke(prompt)
        result = response.content if hasattr(response, "content") else str(response)
        
        # 🔧 文章完全性チェック強化（二重チェック）
        complete_result = ensure_complete_sentence(result, query)
        
        # 🔧 最終チェック：まだ不完全な場合は再補完
        if not complete_result.endswith(('。', '！', '？', '.', '!', '?')):
            complete_result = ensure_complete_sentence(complete_result, query)
        
        logger.info(f"✅ Complete chat response: {len(complete_result)} chars")
        logger.info(f"📝 Response ends with: '{complete_result[-20:]}'")
        logger.info(f"🔚 Sentence complete: {complete_result.endswith(('。', '！', '？', '.', '!', '?'))}")
        
        return complete_result
        
    except Exception as e:
        logger.error(f"❌ Complete chat error: {e}")
        # フォールバック応答も完全な文章で
        return ensure_complete_sentence(
            "申し訳ございません。一時的にエラーが発生しました。しばらく後に再度お試しください。",
            query
        )

def health_check_llm() -> dict:
    """完全性重視ヘルスチェック"""
    try:
        llm, _, max_tokens = load_llm()
        test_response = llm.invoke("住宅について簡潔に教えてください。完全な文章で回答してください。")
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
            "last_20_chars": response_text[-20:] if response_text else "",
            "completeness_features": [
                "Double completion check",
                "Pattern-based completion",
                "Fallback generation",
                "800 token limit"
            ]
        }
        
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

if __name__ == "__main__":
    print("🧪 Complete Response LLM Runner Test (Enhanced)")
    config = {
        "model_name": os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo"),
        "max_tokens": 800,  # 🔧 増量
        "timeout": 30,
        "complete_sentences": "double_check_enabled",
        "completion_patterns": 25
    }
    print("📋 Enhanced Configuration:", config)
    
    health = health_check_llm()
    print("🔍 Health Check:", health)
    
    if health["status"] == "healthy":
        test_queries = [
            "坪単価について教えて",
            "家を建てる前にまずなにから調べたらいいですか",
            "土地探しや建築会社の選定が重要",  # 途切れやすいパターン
            "住宅ローンの準備も必要"  # 途切れやすいパターン
        ]
        
        for test_query in test_queries:
            response = chat_with_tracing(test_query, "test-user")
            print(f"💬 Test Query: {test_query}")
            print(f"🤖 Complete Response: {response}")
            print(f"✅ Ends properly: {response.endswith(('。', '！', '？', '.', '!', '?'))}")
            print(f"📏 Length: {len(response)} chars")
            print("-" * 70)