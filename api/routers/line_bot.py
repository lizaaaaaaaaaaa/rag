# line_bot.py - 修正されたLINE Bot実装（リッチメニュー応答更新版）

import logging
import os
import re
import json
import asyncio
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
    from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent
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

def get_line_credentials():
    """LINE認証情報を安全に取得"""
    access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    channel_secret = os.getenv("LINE_CHANNEL_SECRET")

    logger.info("Getting LINE credentials...")
    logger.info(f"Access token type: {type(access_token)}")
    logger.info(f"Channel secret type: {type(channel_secret)}")

    return access_token, channel_secret

# ========= 修正パッチ：トークン正規化（完全修正版） =========
def normalize_line_token_fixed(token: Any) -> str:
    """LINE トークン正規化関数（完全修正版）"""
    if token is None:
        logger.error("Token is None")
        return ""

    # ログ用情報
    logger.info(f"🔧 Normalizing token: type={type(token).__name__}, len={len(str(token))}")

    # bytes -> str
    if isinstance(token, bytes):
        try:
            token = token.decode("utf-8")
            logger.info("✅ Decoded token from bytes")
        except UnicodeDecodeError as e:
            logger.error(f"Failed to decode token from bytes: {e}")
            return ""

    # 文字列に変換
    token_str = str(token)

    # 改行文字の完全除去（最重要）
    if any(char in token_str for char in ['\r', '\n', '\t']):
        logger.warning("⚠️ Token contains newline characters - removing")
        token_str = token_str.replace('\r', '').replace('\n', '').replace('\t', '')

    # 前後の空白除去
    token_str = token_str.strip()

    # Bearer プレフィックス除去
    if token_str.lower().startswith("bearer "):
        token_str = token_str[7:].strip()
        logger.info("✅ Removed 'Bearer ' prefix")

    # Python bytes表現除去
    if token_str.startswith("b'") and token_str.endswith("'"):
        token_str = token_str[2:-1]
        logger.info("✅ Removed Python bytes notation")

    # 引用符除去
    token_str = token_str.replace('"', '').replace("'", "")

    # 残存空白文字の最終除去
    if any(char in token_str for char in ['\n', '\r', '\t', ' ']):
        logger.warning("⚠️ Final whitespace cleanup")
        token_str = ''.join(token_str.split())

    # 最終検証
    final_len = len(token_str)
    has_newlines = any(char in token_str for char in ['\r', '\n'])

    logger.info(f"✅ Token normalized: len={final_len}, has_newlines={has_newlines}")

    if not token_str:
        logger.error("❌ Token is empty after normalization")
        return ""

    if has_newlines:
        logger.error("❌ Token still contains newlines after normalization")
        return ""

    return token_str
# ===========================================================

# 認証情報のロード
LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET = get_line_credentials()

line_bot_api = None
handler = None

if LINE_SDK_AVAILABLE:
    if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
        try:
            # 正規化
            normalized_token = normalize_line_token_fixed(LINE_CHANNEL_ACCESS_TOKEN)
            normalized_secret = normalize_line_token_fixed(LINE_CHANNEL_SECRET)

            if not normalized_token:
                raise ValueError("Normalized access token is empty")
            if not normalized_secret:
                raise ValueError("Normalized channel secret is empty")

            # Configuration & Handler
            configuration = Configuration(access_token=normalized_token)
            handler = WebhookHandler(normalized_secret)

            # MessagingApi（初期化確認用。実運用は送信時に毎回クライアントを作成）
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)

            logger.info("✅ LINE Bot API v3 initialized successfully with normalized tokens")

        except Exception as e:
            logger.error(f"❌ LINE Bot API initialization failed: {e}")
            logger.error(traceback.format_exc())
            line_bot_api, handler = None, None
    else:
        logger.warning("⚠️ LINE Bot credentials not found")
        line_bot_api, handler = None, None
else:
    logger.warning("⚠️ LINE Bot SDK not available")

# リッチメニュー応答定義（更新版）
RICHMENU_RESPONSES = {
    "AI相談": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 例えば
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

    "資料請求": """📋 ありがとうございます！こちらからご覧いただけます。

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

    "資金計画": """💰 AI資金診断のご案内

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
    """リッチメニューアクションを検出（更新版）"""
    text_clean = message_text.lower().replace(" ", "").replace("　", "")

    # 更新されたキーワード検出
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
        "展示場": "展示場来場予約",
        "💰資金計画": "資金計画",
        "資金計画": "資金計画",
        "💬チャット相談": "チャット相談",
        "チャット相談": "チャット相談",
        "チャット": "チャット相談"
    }
    
    for keyword, action in richmenu_keywords.items():
        if keyword in text_clean:
            return action
    return "unknown"

# ========= 修正パッチ：安全送信（完全修正版） =========
def send_line_reply_safe(reply_token: str, message_text: str) -> bool:
    """安全なLINE返信送信（修正版）"""
    if not line_bot_api:
        logger.error("LINE Bot API not initialized")
        return False

    try:
        # トークンの再正規化（最重要）
        normalized_token = normalize_line_token_fixed(LINE_CHANNEL_ACCESS_TOKEN)
        if not normalized_token:
            logger.error("Failed to normalize access token for reply")
            return False

        # 送信前デバッグ
        logger.info(f"📤 Sending LINE reply: token_len={len(normalized_token)}, message_len={len(message_text)}")

        # 新しいConfiguration作成（正規化済みトークン使用）
        configuration = Configuration(access_token=normalized_token)

        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            # メッセージ送信
            messaging_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=message_text)]
                )
            )

        logger.info(f"✅ Reply sent successfully (length: {len(message_text)})")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to send LINE reply: {e}")
        logger.error(traceback.format_exc())
        return False
# =====================================================

# Webhook エンドポイント
@router.post("/webhook")
async def line_webhook_fixed(request: Request, background_tasks: BackgroundTasks):
    """修正されたLINE Webhook"""
    logger.info("🚀 LINE Webhook called")

    if not line_bot_api or not handler:
        logger.error("❌ LINE Bot not configured properly")
        return {"status": "error", "message": "LINE Bot not configured"}

    try:
        body = await request.body()
        signature = request.headers.get("X-Line-Signature", "")

        logger.info(f"📨 Webhook - Body length: {len(body)}, Has signature: {'Yes' if signature else 'No'}")

        if not signature:
            logger.error("❌ Missing X-Line-Signature header")
            return {"status": "error", "message": "Missing signature"}

        try:
            body_text = body.decode("utf-8")
            logger.info(f"📄 Body preview: {body_text[:200]}...")

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

# イベントハンドラ（修正版）
if LINE_SDK_AVAILABLE and handler:

    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message_fixed(event):
        """修正されたメッセージハンドラ"""
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
                response_text = RICHMENU_RESPONSES.get(action, RICHMENU_RESPONSES.get("unknown", "申し訳ございません。"))
            else:
                logger.info("💬 General message processing")
                response_text = process_general_question(message_text)

            # 返信送信
            success = send_line_reply_safe(reply_token, response_text)

            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ Message processed: success={success}, time={duration:.3f}s")

        except Exception as e:
            logger.error(f"💥 Message handler error: {e}")
            logger.error(traceback.format_exc())
            try:
                emergency_text = "申し訳ございません。一時的にエラーが発生しました。しばらくしてから再度お試しください。"
                send_line_reply_safe(event.reply_token, emergency_text)
            except Exception as final_error:
                logger.error(f"💥 Emergency response failed: {final_error}")

    @handler.add(PostbackEvent)
    def handle_postback_fixed(event):
        """修正されたPostbackハンドラ"""
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

            send_line_reply_safe(event.reply_token, response_text)
            logger.info("✅ Postback processed successfully")

        except Exception as e:
            logger.error(f"💥 Postback handler error: {e}")

def process_general_question(message_text: str) -> str:
    """一般的な質問の処理"""
    try:
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

# デバッグエンドポイント
@router.get("/debug")
def line_debug_info():
    """LINE Bot デバッグ情報"""
    return {
        "line_sdk_available": LINE_SDK_AVAILABLE,
        "line_bot_api_initialized": line_bot_api is not None,
        "handler_initialized": handler is not None,
        "credentials_set": {
            "access_token_set": bool(LINE_CHANNEL_ACCESS_TOKEN),
            "channel_secret_set": bool(LINE_CHANNEL_SECRET)
        },
        "normalized_token_length": len(normalize_line_token_fixed(LINE_CHANNEL_ACCESS_TOKEN)) if LINE_CHANNEL_ACCESS_TOKEN else 0,
        "timestamp": datetime.now().isoformat()
    }

@router.get("/test-credentials")
def test_line_credentials():
    """LINE認証情報テスト"""
    access_token, channel_secret = get_line_credentials()
    return {
        "original_token_type": str(type(access_token)),
        "original_secret_type": str(type(channel_secret)),
        "normalized_token_length": len(normalize_line_token_fixed(access_token)) if access_token else 0,
        "normalized_secret_length": len(normalize_line_token_fixed(channel_secret)) if channel_secret else 0,
        "token_preview": normalize_line_token_fixed(access_token)[:10] + "..." if access_token else "None",
        "timestamp": datetime.now().isoformat()
    }