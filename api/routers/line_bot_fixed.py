# api/routers/line_bot_fixed.py - 友達追加挨拶メッセージ対応版

import logging
import os
import traceback
from datetime import datetime
from typing import Dict, Optional, Any

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# LINE Bot SDK v3
try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.exceptions import InvalidSignatureError
    from linebot.v3.messaging import (
        Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage,
    )
    # FollowEventを追加でインポート
    from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent, FollowEvent
    LINE_SDK_AVAILABLE = True
    logger.info("✅ LINE Bot SDK v3 imported successfully")
except ImportError as e:
    logger.error(f"❌ LINE Bot SDK not available: {e}")
    LINE_SDK_AVAILABLE = False
    
    # ダミークラス
    class WebhookHandler:
        def __init__(self, *args, **kwargs): pass
        def add(self, *args, **kwargs): 
            def decorator(func): return func
            return decorator
        def handle(self, *args, **kwargs): pass

router = APIRouter(prefix="/line", tags=["line"])

def get_line_credentials_safe():
    """LINE認証情報を安全に取得（完全修正版）"""
    access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    channel_secret = os.getenv("LINE_CHANNEL_SECRET")
    
    logger.info("🔍 Getting LINE credentials with enhanced safety...")
    
    # Secret Manager からも試行
    if not access_token or not channel_secret:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "rag-cloud-project")
            
            if not access_token:
                try:
                    secret_name = f"projects/{project_id}/secrets/LINE_CHANNEL_ACCESS_TOKEN/versions/latest"
                    response = client.access_secret_version(request={"name": secret_name})
                    access_token = response.payload.data.decode("UTF-8")
                    logger.info("✅ Access token loaded from Secret Manager")
                except Exception as e:
                    logger.warning(f"Failed to load access token from Secret Manager: {e}")
            
            if not channel_secret:
                try:
                    secret_name = f"projects/{project_id}/secrets/LINE_CHANNEL_SECRET/versions/latest"
                    response = client.access_secret_version(request={"name": secret_name})
                    channel_secret = response.payload.data.decode("UTF-8")
                    logger.info("✅ Channel secret loaded from Secret Manager")
                except Exception as e:
                    logger.warning(f"Failed to load channel secret from Secret Manager: {e}")
                    
        except ImportError:
            logger.warning("Google Cloud Secret Manager not available")
        except Exception as e:
            logger.error(f"Secret Manager error: {e}")
    
    return access_token, channel_secret

def normalize_line_token_ultimate(token: Any) -> str:
    """究極のLINEトークン正規化（問題完全解決版）"""
    if token is None:
        logger.error("❌ Token is None")
        return ""
    
    # ログ用のオリジナル情報
    original_type = type(token).__name__
    original_len = len(str(token)) if token else 0
    
    logger.info(f"🔧 Normalizing token: type={original_type}, len={original_len}")
    
    # 1. bytes オブジェクトの処理
    if isinstance(token, bytes):
        try:
            token = token.decode("utf-8")
            logger.info("✅ Decoded token from bytes")
        except UnicodeDecodeError as e:
            logger.error(f"❌ Failed to decode token from bytes: {e}")
            return ""
    
    # 2. 文字列に変換
    token_str = str(token)
    
    # 3. 改行文字の完全除去（優先度最高）
    original_has_newlines = any(char in token_str for char in ['\r', '\n', '\t'])
    if original_has_newlines:
        logger.warning("⚠️ Token contains newline characters - removing")
        token_str = token_str.replace('\r', '').replace('\n', '').replace('\t', '')
    
    # 4. 前後の空白除去
    token_str = token_str.strip()
    
    # 5. Bearer プレフィックスの処理
    if token_str.lower().startswith("bearer "):
        token_str = token_str[7:].strip()
        logger.info("✅ Removed 'Bearer ' prefix")
    
    # 6. Python bytes表現の除去 (b'...')
    if token_str.startswith("b'") and token_str.endswith("'"):
        token_str = token_str[2:-1]
        logger.info("✅ Removed Python bytes notation")
    
    # 7. 引用符の除去
    token_str = token_str.replace('"', '').replace("'", "")
    
    # 8. 残存空白文字の除去
    if any(char in token_str for char in ['\n', '\r', '\t', ' ']):
        logger.warning("⚠️ Token still contains whitespace - final cleanup")
        token_str = ''.join(token_str.split())
    
    # 9. 最終検証
    final_len = len(token_str)
    has_newlines = any(char in token_str for char in ['\r', '\n', '\t'])
    starts_with_bearer = token_str.lower().startswith("bearer")
    
    logger.info(f"✅ Token normalized: len={final_len}, has_newlines={has_newlines}, starts_with_bearer={starts_with_bearer}")
    
    # 10. 最終検査
    if not token_str:
        logger.error("❌ Token is empty after normalization")
        return ""
    
    if final_len < 50:
        logger.warning(f"⚠️ Token seems short: {final_len} characters")
    
    if has_newlines:
        logger.error("❌ Token still contains newlines after normalization")
        return ""
    
    return token_str

# LINE Bot初期化（問題解決版）
LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET = get_line_credentials_safe()

line_bot_api = None
handler = None

if LINE_SDK_AVAILABLE:
    if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
        try:
            # トークンを完全正規化
            normalized_token = normalize_line_token_ultimate(LINE_CHANNEL_ACCESS_TOKEN)
            normalized_secret = normalize_line_token_ultimate(LINE_CHANNEL_SECRET)
            
            # 正規化結果の最終確認
            if not normalized_token:
                raise ValueError("❌ Normalized access token is empty")
            if not normalized_secret:
                raise ValueError("❌ Normalized channel secret is empty")
            
            # 最終デバッグログ
            logger.info(f"🚀 Using normalized token: len={len(normalized_token)}, starts_with={normalized_token[:10]}...")
            
            # Configuration作成（正規化済みトークンを使用）
            configuration = Configuration(access_token=normalized_token)
            
            # WebhookHandler作成（正規化済みシークレットを使用）
            handler = WebhookHandler(normalized_secret)
            
            # MessagingApi作成
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
            
            logger.info("🎉 LINE Bot API v3 initialized successfully with normalized tokens")
            
        except Exception as e:
            logger.error(f"❌ LINE Bot API initialization failed: {e}")
            logger.error(traceback.format_exc())
            line_bot_api, handler = None, None
    else:
        logger.warning("⚠️ LINE Bot credentials not found")
        line_bot_api, handler = None, None
else:
    logger.warning("⚠️ LINE Bot SDK not available")

# 友達追加時の挨拶メッセージ
GREETING_MESSAGE = """こんにちは！キノエデザインです。
この度は友だち追加ありがとうございます✨

目的のボタンをタップ👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画 / 🌐サイト / 💬チャット

AIは24時間、担当者は当日〜翌営業日に返信します。

取扱い(プライバシーポリシー)：〔https://preview.studio.site/live/EjOQljz1WJ/privacy-policy〕"""

# リッチメニュー応答定義（修正版）
RICHMENU_RESPONSES = {
    "AI相談": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 例えば：
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？

何でもお聞きください😊""",

    "AI住まいサイト": """🌐 AI住まいサイトのご案内

キノエデザインの住まい情報サイトをご紹介します。

🏠 サイト内容：
・施工事例・間取りプラン
・住宅性能・標準仕様
・価格・坪単価情報
・お客様の声

📱 サイトURL:
https://kinoe-design.com

詳しい住まい情報をご確認いただけます！""",

    "資料請求": """📋 資料請求を承ります

以下の情報をお送りください：

📝 必要情報：
1️⃣ お名前（フルネーム）
2️⃣ ご住所（〒郵便番号から）
3️⃣ お電話番号
4️⃣ ご希望資料の種類

📮 お送りする資料：
・会社案内・施工事例集
・間取りプラン集
・価格・仕様資料
・住宅ローンガイド

3営業日以内にお送いたします！""",

    "展示場来場予約": """📍 展示場来場予約を承ります

以下をメッセージでお送りください：

📅 予約情報：
・ご希望日時（第1・第2希望）
・お名前・お電話番号
・参加人数（大人・お子様）
・ご質問・ご要望

🕒 見学時間：約90分
🏠 展示場：最新の住宅仕様をご確認

スタッフ一同、心よりお待ちしております！
ご質問もお気軽にどうぞ。""",

    "資金計画": """💰 資金計画・住宅ローン相談

住宅購入の資金計画をサポートします。

📊 ご相談内容：
・住宅ローンの種類・金利比較
・月々の返済計画
・頭金・諸費用の計算
・住宅ローン控除について

💡 お聞かせください：
・ご年収・自己資金
・ご希望借入額・返済期間
・家族構成・将来計画

最適なプランをご提案いたします！""",

    "チャット相談": """💬 スタッフとのご相談

【対応時間】
平日・土日：9:00-18:00
定休日：水曜日

📱 ご相談方法：
・このLINEでの直接相談
・お電話での相談
・展示場での対面相談

🏠 ご相談内容：
・住まいづくり全般
・土地探し・資金計画
・間取り・デザイン
・住宅性能について

営業時間内でしたら迅速にお返事します。
お気軽にお声かけください！"""
}

def detect_richmenu_action(message_text: str) -> str:
    """リッチメニューアクションを検出"""
    text_clean = message_text.lower().replace(" ", "").replace("　", "")
    
    # 完全一致を優先
    richmenu_keywords = {
        "ai相談": "AI相談",
        "ai住まいサイト": "AI住まいサイト", 
        "aiサイト": "AI住まいサイト",
        "資料請求": "資料請求",
        "展示場来場予約": "展示場来場予約",
        "展示場予約": "展示場来場予約",
        "展示場": "展示場来場予約",
        "資金計画": "資金計画",
        "チャット相談": "チャット相談",
        "チャット": "チャット相談"
    }
    
    for keyword, action in richmenu_keywords.items():
        if keyword in text_clean:
            return action
    
    return "unknown"

def send_line_reply_ultimate_safe(reply_token: str, message_text: str) -> bool:
    """究極に安全なLINE返信送信（問題完全解決版）"""
    if not line_bot_api:
        logger.error("❌ LINE Bot API not initialized")
        return False
    
    try:
        # トークンの再度正規化（念のため）
        current_token = normalize_line_token_ultimate(LINE_CHANNEL_ACCESS_TOKEN)
        if not current_token:
            logger.error("❌ Failed to normalize access token for reply")
            return False
        
        # 送信前のデバッグログ
        logger.info(f"📤 Sending LINE reply: token_len={len(current_token)}, message_len={len(message_text)}")
        logger.info(f"🔍 Token debug: type={type(current_token)}, has_newlines={any(c in current_token for c in [chr(13), chr(10)])}")
        
        # 新しいConfiguration作成（正規化済みトークン）
        configuration = Configuration(access_token=current_token)
        
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            
            # メッセージ送信
            messaging_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=message_text)]
                )
            )
        
        logger.info(f"✅ LINE reply sent successfully (message length: {len(message_text)})")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to send LINE reply: {e}")
        logger.error(f"🔍 Error details: {traceback.format_exc()}")
        return False

# Webhook エンドポイント
@router.post("/webhook")
async def line_webhook_ultimate(request: Request, background_tasks: BackgroundTasks):
    """究極に安全なLINE Webhook（友達追加対応版）"""
    logger.info("🚀 LINE Webhook called (Ultimate Safe Version with Follow Support)")
    
    if not line_bot_api or not handler:
        logger.error("❌ LINE Bot not configured properly")
        return {"status": "error", "message": "LINE Bot not configured"}
    
    try:
        body = await request.body()
        signature = request.headers.get("X-Line-Signature", "")
        
        logger.info(f"📨 Webhook - Body length: {len(body)}, Signature: {'Present' if signature else 'Missing'}")
        
        if not signature:
            logger.error("❌ Missing X-Line-Signature header")
            return {"status": "error", "message": "Missing signature"}
        
        try:
            body_text = body.decode("utf-8")
            logger.info(f"📄 Processing webhook body: {body_text[:200]}...")
            
            # イベント処理
            handler.handle(body_text, signature)
            
            logger.info("✅ Webhook processed successfully")
            return {"status": "ok", "timestamp": datetime.now().isoformat()}
            
        except InvalidSignatureError as sig_error:
            logger.error(f"❌ Invalid signature: {sig_error}")
            return {"status": "signature_error", "timestamp": datetime.now().isoformat()}
            
    except Exception as e:
        logger.error(f"💥 Webhook error: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}

# イベントハンドラ（友達追加対応版）
if LINE_SDK_AVAILABLE and handler:
    
    # 🆕 友達追加イベントハンドラー
    @handler.add(FollowEvent)
    def handle_follow_event(event):
        """友達追加時のハンドラー（挨拶メッセージ送信）"""
        start_time = datetime.now()
        
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            
            logger.info(f"👤 New follower: {user_id}")
            logger.info("📬 Sending greeting message...")
            
            # 挨拶メッセージを送信
            success = send_line_reply_ultimate_safe(reply_token, GREETING_MESSAGE)
            
            duration = (datetime.now() - start_time).total_seconds()
            
            if success:
                logger.info(f"✅ Greeting message sent successfully: user={user_id}, time={duration:.3f}s")
            else:
                logger.error(f"❌ Failed to send greeting message: user={user_id}")
            
        except Exception as e:
            logger.error(f"💥 Follow event handler error: {e}")
            logger.error(traceback.format_exc())
            
            # 緊急時の応答
            try:
                emergency_greeting = "こんにちは！キノエデザインです。友だち追加ありがとうございます！"
                send_line_reply_ultimate_safe(event.reply_token, emergency_greeting)
            except Exception as final_error:
                logger.error(f"💥 Emergency greeting failed: {final_error}")
    
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message_ultimate(event):
        """究極のメッセージハンドラ（問題完全解決版）"""
        start_time = datetime.now()
        
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            reply_token = event.reply_token
            
            logger.info(f"📱 Message from {user_id}: '{message_text}'")
            
            # リッチメニューアクション検出
            action = detect_richmenu_action(message_text)
            
            if action != "unknown":
                logger.info(f"🎯 Richmenu action detected: {action}")
                response_text = RICHMENU_RESPONSES.get(action, "ご利用ありがとうございます。")
            else:
                logger.info("💬 General message processing")
                # 一般的な質問処理
                response_text = process_general_question(message_text)
            
            # 返信送信（問題修正版）
            success = send_line_reply_ultimate_safe(reply_token, response_text)
            
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ Message processed: success={success}, time={duration:.3f}s")
            
            if not success:
                logger.error(f"❌ Failed to send reply for message: '{message_text}'")
            
        except Exception as e:
            logger.error(f"💥 Message handler error: {e}")
            logger.error(traceback.format_exc())
            
            # 緊急時の応答
            try:
                emergency_text = "申し訳ございません。一時的にエラーが発生しました。しばらくしてから再度お試しください。"
                send_line_reply_ultimate_safe(event.reply_token, emergency_text)
            except Exception as final_error:
                logger.error(f"💥 Emergency response failed: {final_error}")
    
    @handler.add(PostbackEvent)
    def handle_postback_ultimate(event):
        """究極のPostbackハンドラ（修正版）"""
        try:
            user_id = event.source.user_id
            postback_data = event.postback.data or ""
            
            logger.info(f"🔙 Postback from {user_id}: {postback_data}")
            
            # Postbackデータの解析
            if "action=" in postback_data:
                action_value = ""
                for part in postback_data.split("&"):
                    if part.startswith("action="):
                        action_value = part.split("=", 1)[1]
                        break
                
                response_text = RICHMENU_RESPONSES.get(action_value, "ご利用ありがとうございます。")
            else:
                response_text = "メニューからお選びください。"
            
            send_line_reply_ultimate_safe(event.reply_token, response_text)
            logger.info("✅ Postback processed successfully")
            
        except Exception as e:
            logger.error(f"💥 Postback handler error: {e}")

def process_general_question(message_text: str) -> str:
    """一般的な質問の処理"""
    try:
        # RAGシステムとの連携
        globals_dict = get_app_globals()
        if globals_dict.get('rag_chain_template'):
            result = globals_dict['rag_chain_template'].invoke({"query": message_text})
            return result.get("result", "申し訳ございません。お答えできませんでした。")
        else:
            return "ご質問ありがとうございます。詳しくはお問い合わせください。"
            
    except Exception as e:
        logger.error(f"Error processing general question: {e}")
        return "申し訳ございません。エラーが発生しました。"

def get_app_globals():
    """アプリのグローバル変数を取得"""
    try:
        import main
        return {
            'vectorstore': getattr(main, 'vectorstore', None),
            'rag_chain_template': getattr(main, 'rag_chain_template', None),
            'llm_instance': getattr(main, 'llm_instance', None)
        }
    except Exception as e:
        logger.error(f"Failed to get app globals: {e}")
        return {}

# デバッグエンドポイント（強化版）
@router.get("/debug-ultimate")
def line_debug_ultimate():
    """LINE Bot デバッグ情報（完全版）"""
    
    # 現在のトークン状態
    raw_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    normalized_token = normalize_line_token_ultimate(raw_token) if raw_token else ""
    
    return {
        "line_sdk_available": LINE_SDK_AVAILABLE,
        "line_bot_api_initialized": line_bot_api is not None,
        "handler_initialized": handler is not None,
        "follow_event_supported": True,  # 友達追加対応フラグ
        "greeting_message_configured": True,  # 挨拶メッセージ設定フラグ
        "credentials_debug": {
            "raw_token_type": type(raw_token).__name__ if raw_token else "None",
            "raw_token_length": len(str(raw_token)) if raw_token else 0,
            "raw_token_has_newlines": any(char in str(raw_token) for char in ['\r', '\n']) if raw_token else False,
            "normalized_token_length": len(normalized_token),
            "normalized_token_valid": len(normalized_token) > 50,
            "normalized_starts_with_bearer": normalized_token.startswith("Bearer ") if normalized_token else False
        },
        "initialization_status": "✅ Success with Follow Support" if line_bot_api and handler else "❌ Failed",
        "greeting_message_preview": GREETING_MESSAGE[:100] + "..." if len(GREETING_MESSAGE) > 100 else GREETING_MESSAGE,
        "timestamp": datetime.now().isoformat()
    }

# 友達追加テスト用エンドポイント
@router.get("/test-greeting")
def test_greeting_message():
    """挨拶メッセージのテスト表示"""
    return {
        "greeting_message": GREETING_MESSAGE,
        "message_length": len(GREETING_MESSAGE),
        "follow_event_configured": True,
        "test_info": "This is the message that will be sent when users follow the LINE bot",
        "timestamp": datetime.now().isoformat()
    }