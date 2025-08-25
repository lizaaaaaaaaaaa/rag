# api/routers/line_bot_fixed.py - 文章途切れ対策版（完全修正版）

import logging
import os
import re
import json
import asyncio
import traceback
import time
from datetime import datetime
from typing import Dict, Optional, Any, List
import hashlib

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# LINE SDK v3 import
try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.exceptions import InvalidSignatureError
    from linebot.v3.messaging import (
        Configuration, ApiClient, MessagingApi, ReplyMessageRequest, PushMessageRequest, TextMessage,
        ApiException
    )
    from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent, FollowEvent
    LINE_SDK_AVAILABLE = True
    logger.info("✅ LINE Bot SDK v3 imported successfully")
except ImportError as e:
    logger.error(f"❌ LINE Bot SDK not available: {e}")
    LINE_SDK_AVAILABLE = False
    class WebhookHandler:
        def __init__(self, *args, **kwargs): pass
        def add(self, *args, **kwargs):
            def decorator(func): return func
            return decorator
        def handle(self, *args, **kwargs): pass

router = APIRouter(tags=["line-fixed"])

# ==============================================================================
# LINE Bot設定と初期化
# ==============================================================================
def get_line_credentials():
    """LINE認証情報を取得"""
    access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    channel_secret = os.getenv("LINE_CHANNEL_SECRET")
    
    # Secret Manager対応
    if not access_token or not channel_secret:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "rag-cloud-project")
            
            if not access_token:
                name = f"projects/{project_id}/secrets/LINE_CHANNEL_ACCESS_TOKEN/versions/latest"
                response = client.access_secret_version(request={"name": name})
                access_token = response.payload.data.decode("UTF-8")
            
            if not channel_secret:
                name = f"projects/{project_id}/secrets/LINE_CHANNEL_SECRET/versions/latest"
                response = client.access_secret_version(request={"name": name})
                channel_secret = response.payload.data.decode("UTF-8")
                
        except Exception as e:
            logger.warning(f"Secret Manager access failed: {e}")
    
    return access_token, channel_secret

def normalize_token(token):
    """トークンの正規化"""
    if not token:
        return ""
    
    token_str = str(token)
    token_str = token_str.replace('\r', '').replace('\n', '').replace('\t', '').strip()
    
    if token_str.lower().startswith("bearer "):
        token_str = token_str[7:].strip()
    
    if token_str.startswith("b'") and token_str.endswith("'"):
        token_str = token_str[2:-1]
    
    token_str = token_str.replace('"', '').replace("'", "")
    return ''.join(token_str.split())

# 初期化
LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET = get_line_credentials()
line_bot_api = None
handler = None

if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        normalized_token = normalize_token(LINE_CHANNEL_ACCESS_TOKEN)
        normalized_secret = normalize_token(LINE_CHANNEL_SECRET)
        
        if normalized_token and normalized_secret:
            configuration = Configuration(access_token=normalized_token)
            handler = WebhookHandler(normalized_secret)
            
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
            
            logger.info("✅ LINE Bot initialized successfully")
        else:
            raise ValueError("Empty normalized credentials")
            
    except Exception as e:
        logger.error(f"❌ LINE Bot initialization failed: {e}")
        line_bot_api = None
        handler = None

# ==============================================================================
# 文章完全性確保関数（強化版）
# ==============================================================================
def ensure_complete_line_response(text: str, query: str = "") -> str:
    """LINE用文章完全性確保（強化版）"""
    if not text or len(text.strip()) < 5:
        return generate_intelligent_fallback_response(query)
    
    text = text.strip()
    
    # 文末チェックと補完（LINE特化）
    if not text.endswith(('。', '！', '？', '.', '!', '?')):
        logger.info(f"🔧 Fixing incomplete sentence ending with: '{text[-20:]}'")
        
        # 特定の途切れパターンの補完
        if text.endswith('や'):  # 「土地探しや」のケース
            if "土地" in text:
                text += "建築準備を進めることが大切です。"
            else:
                text += "詳細についてお問い合わせください。"
        elif text.endswith('重要'):  # 「重要」のケース
            text += 'です。'
            if "選定" in text or "選択" in text:
                text += "詳しくはスタッフまでご相談ください。"
        elif text.endswith('必要'):
            text += 'です。'
        elif text.endswith('について'):
            text += 'は、詳細をご案内いたします。'
        elif text.endswith('ます') or text.endswith('です'):
            text += '。'
        elif text.endswith('た') or text.endswith('る'):
            text += '。'
        elif text.endswith('、'):
            text = text[:-1] + '。'
        elif text.endswith('は') or text.endswith('が'):
            text += '重要なポイントです。'
        elif text.endswith('ので') or text.endswith('ため'):
            text += '、お気軽にご相談ください。'
        elif text.endswith('選定') or text.endswith('検討'):
            text += 'も重要です。'
        elif text.endswith('など'):
            text += 'があります。詳細はお問い合わせください。'
        elif text.endswith('から'):
            text += '、ご検討ください。'
        elif text.endswith('して'):
            text += 'います。'
        elif text.endswith('また'):
            text += '、詳細についてはお問い合わせください。'
        elif text.endswith('で'):
            text += 'す。'
        elif text.endswith('と'):
            text += 'なります。'
        else:
            # 長さによる補完
            if len(text) > 30:
                text += '。'
            elif len(text) > 15:
                text += '。詳しくはお問い合わせください。'
            else:
                text = generate_intelligent_fallback_response(query)
        
        logger.info(f"✅ Fixed sentence now ends with: '{text[-20:]}'")
    
    return text

# ==============================================================================
# リッチメニュー応答管理（完全新規作成）
# ==============================================================================
def get_richmenu_responses() -> Dict[str, str]:
    """リッチメニュー用の応答を取得（新仕様）"""
    return {
        "AI相談": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 **例えば**
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？

何でもお聞きください😊

※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：https://preview.studio.site/live/EjOQljz1WJ/privacy-policy
利用規約：https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service
Cookie：https://preview.studio.site/live/EjOQljz1WJ/cookie""",

        "AI住まいサイト": """🌐 AI住まいサイトのご案内

キノエデザインの住まい情報サイトをご紹介します。（家づくりの疑問にAIが24時間即回答）

🏠 サイト内容：
・AIチャット相談（資金計画／補助金／間取り など）
・施工写真（実例）
・間取りの考え方・プラン例
・よくある質問（最初に迷う3つのこと ほか）
・保存版デジタル冊子 ZINE（無料ダウンロード）
・LINEで無料相談／来場予約

📱 サイトURL:
https://preview.studio.site/live/EjOQljz1WJ/""",

        "資料請求": """📋ありがとうございます！こちらからご覧いただけます。

〔資料タイトル〕（PDF）：〔URL〕

よろしければ簡単アンケート（任意）：
・ご計画時期：今すぐ / 3–6か月 / 1年以内 / 未定
・連絡方法（任意）：このLINE / メール / 連絡不要

※必ず以下の取り扱いをご確認ください。
プライバシーポリシー：https://preview.studio.site/live/EjOQljz1WJ/privacy-policy
利用規約：https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service
Cookie：https://preview.studio.site/live/EjOQljz1WJ/cookie""",

        "展示場来場予約": """📍 展示場のご来場予約につきましては、下記URLより必要事項のご入力をお願い申し上げます。

https://preview.studio.site/live/EjOQljz1WJ/reservation

スタッフ一同、心よりお待ちしております！""",

        "資金計画": """💬 AI資金診断のご案内

本診断は匿名でご利用いただけます。ご回答内容は保存いたしません。算出される金額は試算（概算）であり、目安としてご確認ください。

お手数ですが、以下の5点をご入力ください。
・年収（概算可）
・毎月のご希望返済額
・住宅ローンのご希望借入期間
・ご家族構成（例：大人2名・お子さま1名）
・その他の大きなご負担（例：自動車ローン 等）

未入力の項目があっても進められます。ご入力後、概算結果をご提示いたします。""",

        "チャット相談": """💬 スタッフとのご相談

【対応時間】
営業時間：9:00-18:00

📱 ご相談方法：
・このLINEでの直接相談
・お電話での相談
・展示場での対面相談

営業時間内でしたら迅速にお返事します。
お気軽にお声かけください！"""
    }

def detect_richmenu_action(message_text: str) -> str:
    """リッチメニューアクション検出（更新版）"""
    text_clean = message_text.lower().replace(" ", "").replace("　", "")
    
    richmenu_keywords = {
        "🤖ai相談": "AI相談",
        "ai相談": "AI相談",
        "🌐ai住まいサイト": "AI住まいサイト", 
        "ai住まいサイト": "AI住まいサイト",
        "aiサイト": "AI住まいサイト",
        "📋資料請求": "資料請求",
        "資料請求": "資料請求",
        "📍展示場来場予約": "展示場来場予約",
        "展示場来場予約": "展示場来場予約",
        "展示場予約": "展示場来場予約",
        "💰資金計画": "資金計画",
        "資金計画": "資金計画",
        "💬チャット相談": "チャット相談",
        "チャット相談": "チャット相談",
    }
    
    for keyword, action in richmenu_keywords.items():
        if keyword in text_clean:
            return action
    
    return "unknown"

# ==============================================================================
# 話題別応答検出
# ==============================================================================
def detect_topic_specific_response(message_text: str) -> Optional[str]:
    """話題別の事前定義応答を検出"""
    text_lower = message_text.lower()
    
    # 坪単価・価格関連
    if any(keyword in text_lower for keyword in ["坪単価", "価格", "費用", "いくら", "金額", "コスト", "値段"]):
        return """坪単価についてご案内いたします。

💰 **当社の坪単価目安**
・標準仕様：約70～85万円/坪
・高性能仕様：約85～100万円/坪

🏠 **含まれる内容**
・耐震等級3の構造
・長期優良住宅対応
・高断熱・高気密仕様
・標準設備一式

お客様のご要望や土地条件により変動いたします。詳細なお見積りをご希望の場合は、お気軽にお問い合わせください。"""
    
    # 他の話題も同様に追加...
    
    return None

# ==============================================================================
# インテリジェントフォールバック応答生成（完全性強化版）
# ==============================================================================
def generate_intelligent_fallback_response(message_text: str) -> str:
    """インテリジェントなフォールバック応答生成（完全性強化版）"""
    text_lower = message_text.lower()
    
    # より詳細なキーワード分析
    if any(keyword in text_lower for keyword in ["家を建てる", "住宅建築", "マイホーム", "新築", "建て方", "何から", "まず", "始め"]):
        return """家づくりを始める際のステップをご案内いたします。

🏗️ **家づくりの基本ステップ**

1️⃣ **予算の検討**
・総予算の確認
・住宅ローンの事前審査

2️⃣ **情報収集**
・住宅会社の比較検討
・施工事例の確認

3️⃣ **土地探し**
・希望エリアの選定
・土地の条件確認

4️⃣ **プラン検討**
・間取りの相談
・仕様の決定

まずは資料請求や展示場見学から始められることをお勧めします。お気軽にご相談ください。"""
    
    elif any(keyword in text_lower for keyword in ["坪単価", "価格", "費用", "いくら", "金額", "コスト", "値段"]):
        return """坪単価についてご案内いたします。

💰 **当社の坪単価目安**
・標準仕様：約70～85万円/坪
・高性能仕様：約85～100万円/坪

🏠 **含まれる内容**
・耐震等級3の構造
・長期優良住宅対応
・高断熱・高気密仕様
・標準設備一式

お客様のご要望や土地条件により変動いたします。詳細なお見積りをご希望の場合は、お気軽にお問い合わせください。"""
    
    elif any(keyword in text_lower for keyword in ["土地", "敷地", "建築地", "分譲"]):
        return """土地探しについてご案内いたします。

🏗️ **土地選びのポイント**

1️⃣ **立地条件**
・交通アクセス
・生活利便性
・教育環境

2️⃣ **土地の条件**
・面積・形状
・建築制限
・地盤状況

3️⃣ **予算配分**
・土地と建物の予算バランス
・諸費用の考慮

土地探しから建築まで、トータルでサポートいたします。ご希望条件をお聞かせください。"""
    
    else:
        return """ご質問ありがとうございます。

住まいづくりに関してお答えいたします。お客様のご質問にできる限り詳しくお答えしたいのですが、より具体的な情報をご提供するために、以下についてお聞かせください。

💡 **ご相談内容について**
・坪単価・価格について
・住宅性能（耐震・断熱など）
・標準仕様・設備について  
・資料請求・展示場見学
・資金計画・住宅ローン

スタッフ一同、お客様の理想の住まいづくりをお手伝いいたします。何でもお気軽にお問い合わせください。"""

# ==============================================================================
# アンチハルシネーション処理（同期版）
# ==============================================================================
def enhance_line_chat_response_sync(query: str, user_id: str, original_response: str) -> Dict[str, Any]:
    """LINE用アンチハルシネーション処理（同期版）"""
    try:
        # ハルシネーション対策統合が利用可能な場合
        from integration.anti_hallucination_integration import enhance_web_chat_response
        
        # 非同期関数を同期的に実行
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            enhance_web_chat_response(
                query=query,
                original_response=original_response,
                user_context={"username": user_id, "platform": "line"}
            )
        )
        loop.close()
        
        return result
        
    except ImportError:
        logger.warning("Anti-hallucination integration not available")
        return {"answer": original_response, "anti_hallucination_used": False}
    except Exception as e:
        logger.error(f"Anti-hallucination processing failed: {e}")
        return {"answer": original_response, "anti_hallucination_used": False}

# ==============================================================================
# RAGシステムアクセス関数
# ==============================================================================
def get_app_globals() -> Dict[str, Any]:
    """アプリケーションのグローバル変数を取得"""
    try:
        import main
        return {
            "rag_chain_template": getattr(main, 'rag_chain_template', None),
            "llm_instance": getattr(main, 'llm_instance', None),
            "vectorstore": getattr(main, 'vectorstore', None),
            "is_initialized": getattr(main, 'is_initialized', False)
        }
    except ImportError:
        logger.warning("Main module not available")
        return {}

# ==============================================================================
# 一般的な質問処理（文章完全性強化版）
# ==============================================================================
def process_general_question_sync(message_text: str, user_id: str = "unknown") -> str:
    """一般的な質問の処理（文章完全性強化版）"""
    logger.info(f"🔄 Processing question: '{message_text}' for user: {user_id}")
    
    try:
        # 事前定義された話題の応答をチェック
        topic_response = detect_topic_specific_response(message_text)
        if topic_response:
            logger.info(f"✅ Found topic-specific response")
            # 🔧 トピック応答も完全性チェック
            return ensure_complete_line_response(topic_response, message_text)
        
        # RAGシステムの状態を確認
        globals_dict = get_app_globals()
        original_response: Optional[str] = None

        # RAG chain が利用可能かチェック
        rag_chain = globals_dict.get("rag_chain_template")
        logger.info(f"🔍 RAG chain status: {rag_chain is not None}")
        
        if rag_chain:
            try:
                logger.info("🤖 Using RAG chain for response generation...")
                
                # 🔧 完全性重視のクエリ修正
                enhanced_query = {
                    "query": f"{message_text}（完全な文章で回答してください）"
                }
                
                result = rag_chain.invoke(enhanced_query)
                original_response = result.get("result", "")
                
                logger.info(f"📊 RAG response details: length={len(original_response) if original_response else 0}")
                
                if original_response and len(original_response.strip()) >= 10:
                    # 🔧 RAG回答の完全性チェック
                    complete_response = ensure_complete_line_response(original_response, message_text)
                    logger.info(f"✅ RAG processing successful: {len(complete_response)} chars")
                    logger.info(f"🔚 Response ends with: '{complete_response[-5:]}'")
                    
                    # アンチハルシネーション処理
                    enhanced_result = enhance_line_chat_response_sync(
                        query=message_text,
                        user_id=user_id,
                        original_response=complete_response,
                    )
                    
                    # 🔧 最終回答も完全性チェック
                    final_answer = enhanced_result.get("answer", "")
                    complete_final_answer = ensure_complete_line_response(final_answer, message_text)
                    
                    return complete_final_answer
                else:
                    logger.warning(f"⚠️ RAG response was too short: '{original_response}'")
                    original_response = None
                    
            except Exception as e:
                logger.warning(f"⚠️ RAG processing failed: {e}")
                original_response = None
        
        # LLMに直接問い合わせ
        llm_instance = globals_dict.get("llm_instance")
        logger.info(f"🔍 LLM instance status: {llm_instance is not None}")
        
        if llm_instance:
            try:
                # 🔧 完全性重視プロンプト
                prompt = f"""あなたは住宅・建築の専門アドバイザーです。
以下の質問に対して、完全で自然な文章で回答してください。

【重要な指示】
- 必ず最後まで完結した文章で回答する
- 文章の途中で切れないようにする
- 自然で分かりやすい日本語で回答する
- 350文字以内で簡潔にまとめる
- 文末は必ず句点（。）で終わる
- 住宅に関する具体的で有用な情報を含める

質問: {message_text}

完全な回答:"""
                
                response = llm_instance.invoke(prompt)
                original_response = response.content if hasattr(response, 'content') else str(response)
                
                # 🔧 LLM回答の完全性チェック
                complete_llm_response = ensure_complete_line_response(original_response, message_text)
                
                logger.info(f"✅ Direct LLM response successful: {len(complete_llm_response)} chars")
                logger.info(f"🔚 LLM response ends with: '{complete_llm_response[-5:]}'")
                
                # アンチハルシネーション処理
                enhanced_result = enhance_line_chat_response_sync(
                    query=message_text,
                    user_id=user_id,
                    original_response=complete_llm_response,
                )
                
                # 🔧 最終回答も完全性チェック
                final_answer = enhanced_result.get("answer", "")
                complete_final_answer = ensure_complete_line_response(final_answer, message_text)
                
                return complete_final_answer
                
            except Exception as e:
                logger.error(f"❌ Direct LLM processing failed: {e}")
                original_response = None

        # RAGもLLMも利用できない場合のフォールバック
        logger.warning("⚠️ Both RAG and LLM failed, using intelligent fallback")
        fallback_response = generate_intelligent_fallback_response(message_text)
        
        # 🔧 フォールバック応答も完全性チェック
        complete_fallback = ensure_complete_line_response(fallback_response, message_text)

        # アンチハルシネーション処理
        enhanced_result = enhance_line_chat_response_sync(
            query=message_text,
            user_id=user_id,
            original_response=complete_fallback,
        )

        final_answer = enhanced_result.get("answer", "")
        
        # 🔧 最終チェック: 空の場合は緊急フォールバック
        if not final_answer or len(final_answer.strip()) < 5:
            logger.error("❌ Final answer is empty, using emergency fallback")
            final_answer = generate_intelligent_fallback_response(message_text)
        
        # 🔧 最終的な完全性チェック
        complete_final_answer = ensure_complete_line_response(final_answer, message_text)

        logger.info(f"✅ LINE response enhanced - Complete: {complete_final_answer.endswith(('。', '！', '？'))}")
        logger.info(f"📤 Final answer length: {len(complete_final_answer)} chars")
        logger.info(f"🔚 Final answer ends with: '{complete_final_answer[-10:]}'")
        
        return complete_final_answer

    except Exception as e:
        logger.error(f"❌ Error processing general question: {e}")
        logger.error(traceback.format_exc())
        fallback = generate_intelligent_fallback_response(message_text)
        return ensure_complete_line_response(fallback, message_text)

# ==============================================================================
# LINE メッセージ送信関数
# ==============================================================================
def send_line_message_with_fallback(reply_token: str, user_id: str, message: str) -> bool:
    """LINE メッセージ送信（Push API フォールバック付き）"""
    if not line_bot_api:
        logger.error("❌ LINE Bot API not initialized")
        return False
    
    try:
        normalized_token = normalize_token(LINE_CHANNEL_ACCESS_TOKEN)
        if not normalized_token:
            logger.error("❌ Failed to normalize token")
            return False
        
        configuration = Configuration(access_token=normalized_token)
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            
            # まずReply APIを試行
            try:
                messaging_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=reply_token,
                        messages=[TextMessage(text=message)]
                    )
                )
                logger.info(f"✅ Reply message sent: {len(message)} chars")
                return True
                
            except ApiException as reply_error:
                # Reply失効時はPush APIにフォールバック
                if "Invalid reply token" in str(reply_error) or reply_error.status == 400:
                    logger.warning(f"⚠️ Reply token expired, using Push API fallback")
                    
                    try:
                        messaging_api.push_message_with_http_info(
                            PushMessageRequest(
                                to=user_id,
                                messages=[TextMessage(text=message)]
                            )
                        )
                        logger.info(f"✅ Push message sent as fallback: {len(message)} chars")
                        return True
                    except Exception as push_error:
                        logger.error(f"❌ Push API also failed: {push_error}")
                        return False
                else:
                    logger.error(f"❌ Reply API error: {reply_error}")
                    return False
                    
    except Exception as e:
        logger.error(f"❌ Line message sending failed: {e}")
        return False

# ==============================================================================
# Webhook エンドポイント
# ==============================================================================
@router.post("/webhook")
async def line_webhook(request: Request, background_tasks: BackgroundTasks):
    """LINE Webhook with sentence completion"""
    logger.info("🚀 LINE Webhook called")
    
    if not line_bot_api or not handler:
        logger.error("❌ LINE Bot not configured properly")
        return {"status": "error", "message": "LINE Bot not configured"}
    
    try:
        body = await request.body()
        signature = request.headers.get("X-Line-Signature", "")
        
        if not signature:
            logger.error("❌ Missing X-Line-Signature header")
            return {"status": "error", "message": "Missing signature"}
        
        body_text = body.decode("utf-8")
        logger.info(f"📨 Webhook body preview: {body_text[:200]}...")
        
        handler.handle(body_text, signature)
        
        logger.info("✅ Webhook processed successfully")
        return {"status": "ok", "timestamp": datetime.now().isoformat()}
        
    except InvalidSignatureError as sig_error:
        logger.error(f"❌ Invalid signature: {sig_error}")
        return {"status": "signature_error"}
    except Exception as e:
        logger.error(f"💥 Webhook error: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

# ==============================================================================
# イベントハンドラ（文章完全性強化版）
# ==============================================================================
if LINE_SDK_AVAILABLE and handler:
    
    @handler.add(FollowEvent)
    def handle_follow(event):
        """フォローハンドラ"""
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            
            logger.info(f"👤 New follower: {user_id}")
            
            greeting = """こんにちは！キノエデザインです。
この度は友だち追加ありがとうございます✨

目的のボタンをタップ👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画 / 🌐サイト / 💬チャット

AIは24時間、担当者は当日〜翌営業日に返信します。

取扱い(プライバシーポリシー)：〔https://preview.studio.site/live/EjOQljz1WJ/privacy-policy〕"""
            
            success = send_line_message_with_fallback(reply_token, user_id, greeting)
            logger.info(f"✅ Greeting sent: success={success}")
            
        except Exception as e:
            logger.error(f"❌ Follow error: {e}")
    
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_message(event):
        """メッセージハンドラ（文章完全性強化版）"""
        start_time = time.time()
        
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            reply_token = event.reply_token
            
            logger.info(f"📱 Message from {user_id}: '{message_text[:30]}...'")
            
            # リッチメニューアクション検出
            richmenu_action = detect_richmenu_action(message_text)
            
            if richmenu_action != "unknown":
                richmenu_responses = get_richmenu_responses()
                response_text = richmenu_responses.get(richmenu_action, "ご利用ありがとうございます。")
                logger.info(f"📱 Richmenu action: {richmenu_action}")
            else:
                # 一般的な質問の処理（文章完全性強化版）
                response_text = process_general_question_sync(message_text, user_id)
                
                # 🔧 最終的な完全性確認
                response_text = ensure_complete_line_response(response_text, message_text)
                
                logger.info(f"📤 Response complete: {response_text.endswith(('。', '！', '？'))}")
                logger.info(f"📤 Response length: {len(response_text)} chars")
            
            # メッセージ送信
            success = send_line_message_with_fallback(reply_token, user_id, response_text)
            
            duration = (time.time() - start_time) * 1000
            logger.info(f"✅ Message processed: {duration:.1f}ms, success={success}")
            
        except Exception as e:
            logger.error(f"❌ Message handler error: {e}")
            logger.error(traceback.format_exc())
            
            # エラー時のフォールバック
            try:
                error_message = """申し訳ございません。一時的にシステムの不具合が発生しております。

しばらくしてから再度お試しいただくか、お電話でお問い合わせください。

📞 営業時間：9:00-18:00（水曜定休）"""
                
                send_line_message_with_fallback(event.reply_token, event.source.user_id, error_message)
            except Exception as final_error:
                logger.error(f"❌ Emergency response failed: {final_error}")
    
    @handler.add(PostbackEvent)
    def handle_postback(event):
        """Postbackハンドラ"""
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            postback_data = event.postback.data or ""
            
            logger.info(f"🔙 Postback from {user_id}: {postback_data}")
            
            # Postbackデータの解析
            if "action=" in postback_data:
                action_value = ""
                for part in postback_data.split("&"):
                    if part.startswith("action="):
                        action_value = part.split("=", 1)[1]
                        break
                
                richmenu_responses = get_richmenu_responses()
                response_text = richmenu_responses.get(action_value, "ご利用ありがとうございます。")
            else:
                response_text = "メニューからお選びください。"
            
            success = send_line_message_with_fallback(reply_token, user_id, response_text)
            logger.info(f"✅ Postback processed: success={success}")
            
        except Exception as e:
            logger.error(f"💥 Postback handler error: {e}")

# ==============================================================================
# 監視・デバッグエンドポイント
# ==============================================================================
@router.get("/performance")
def get_performance_stats():
    """パフォーマンス統計"""
    return {
        "line_bot_status": "operational",
        "features": [
            "Sentence Completion Enhancement",
            "RAG Integration",
            "Anti-Hallucination",
            "Push API Fallback",
            "Intelligent Fallback Responses"
        ],
        "sentence_completion": {
            "enabled": True,
            "patterns_supported": 15,
            "fallback_types": 4
        },
        "timestamp": datetime.now().isoformat()
    }

@router.get("/debug")
def debug_info():
    """デバッグ情報"""
    globals_dict = get_app_globals()
    
    return {
        "line_sdk_available": LINE_SDK_AVAILABLE,
        "line_bot_api_initialized": line_bot_api is not None,
        "handler_initialized": handler is not None,
        "rag_system": {
            "rag_chain": globals_dict.get("rag_chain_template") is not None,
            "llm_instance": globals_dict.get("llm_instance") is not None,
            "vectorstore": globals_dict.get("vectorstore") is not None,
            "is_initialized": globals_dict.get("is_initialized", False)
        },
        "sentence_completion_enabled": True,
        "timestamp": datetime.now().isoformat()
    }