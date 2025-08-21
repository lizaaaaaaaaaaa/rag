# api/routers/line_bot_fixed.py - 友達追加挨拶メッセージ対応版（ハルチネーション対策・同期化）

import logging
import os
import traceback
from datetime import datetime
from typing import Dict, Optional, Any

from fastapi import APIRouter, Request, BackgroundTasks

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# ハルチネーション対策（同期）: 外部統合が使えればそれを使用し、ダメならローカル実装にフォールバック
# ------------------------------------------------------------------------------
try:
    from integration.anti_hallucination_integration import (
        enhance_line_chat_response_sync as _external_enhance_sync,
    )

    def enhance_line_chat_response_sync(
        query: str,
        user_id: str,
        original_response: Optional[str] = None,
    ) -> Dict[str, Any]:
        return _external_enhance_sync(
            query=query, user_id=user_id, original_response=original_response
        )

    logger.info("✅ Using external sync anti-hallucination integration")
except Exception as _imp_err:
    logger.warning(f"⚠️ External sync anti-hallucination unavailable: {_imp_err}")

    class SyncAntiHallucinationIntegration:
        """同期版のハルチネーション対策統合クラス（イベントループエラー対策）"""

        def __init__(self):
            # 補助金や最新情報など、時事的・可変情報の検出キーワード
            self.subsidy_keywords = [
                "補助金",
                "助成金",
                "支援金",
                "給付金",
                "控除",
                "減税",
                "ZEH",
                "省エネ",
                "断熱",
                "耐震",
                "リフォーム",
                "改修",
                "住宅ローン",
                "フラット35",
                "こどもエコ",
                "子育て世帯",
                "若年夫婦",
                "新婚",
                "長期優良",
                "認定住宅",
                "2024",
                "2025",
                "令和6",
                "令和7",
                "最新",
                "現在",
            ]

        def should_use_anti_hallucination(self, query: str) -> bool:
            """ハルチネーション対策を使用すべきかの判定"""
            q = query.lower()
            has_subsidy_keyword = any(k in q for k in self.subsidy_keywords)
            needs_current_info = any(k in q for k in ["最新", "現在", "今", "2024", "2025"])
            return has_subsidy_keyword or needs_current_info

        def process_with_anti_hallucination_sync(
            self,
            query: str,
            platform: str,
            user_context: Optional[Dict] = None,
            original_rag_response: Optional[str] = None,
        ) -> Dict[str, Any]:
            """ハルチネーション対策付きの統合処理（同期版フォールバック）"""
            logger.info(
                f"🛡️ Sync anti-hallucination (fallback): platform={platform}, query={query[:50]}..."
            )
            try:
                if original_rag_response:
                    if len(original_rag_response.strip()) < 10:
                        answer = "お尋ねの件について、詳しくは直接お問い合わせください。"
                    elif "エラー" in original_rag_response or "申し訳" in original_rag_response:
                        answer = "お尋ねの件について、詳しくは直接お問い合わせください。"
                    else:
                        # 時事性の注意喚起を付与
                        answer = original_rag_response + "\n\n※最新情報については公式サイトでご確認ください。"
                else:
                    answer = "お尋ねの件について、詳しくは直接お問い合わせください。"

                return {
                    "answer": answer,
                    "confidence_level": 0.6,
                    "verification_method": "basic_filtering",
                    "verification_note": "⚠️ 基本的な品質チェック済み（同期フォールバック）",
                    "last_updated": datetime.now().strftime("%Y-%m-%d"),
                    "sources": [],
                    "warnings": ["同期処理のため限定的な検証"],
                    "anti_hallucination_used": True,
                }
            except Exception as e:
                logger.error(f"❌ Sync anti-hallucination fallback error: {e}")
                return {
                    "answer": "お尋ねの件について、詳しくは直接お問い合わせください。",
                    "confidence_level": 0.0,
                    "verification_method": "error_fallback",
                    "verification_note": "❌ 検索エラー",
                    "last_updated": None,
                    "sources": [],
                    "warnings": [f"検索エラー: {str(e)}"],
                    "anti_hallucination_used": True,
                }

    def enhance_line_chat_response_sync(
        query: str, user_id: str, original_response: Optional[str] = None
    ) -> Dict[str, Any]:
        integ = SyncAntiHallucinationIntegration()
        if integ.should_use_anti_hallucination(query):
            return integ.process_with_anti_hallucination_sync(
                query=query,
                platform="line",
                user_context={"user_id": user_id, "platform": "line"},
                original_rag_response=original_response,
            )
        # そのまま返す（RAGのみ）
        return {
            "answer": original_response or "申し訳ございません。お答えできませんでした。",
            "confidence_level": 0.8,
            "verification_method": "standard_rag",
            "verification_note": "📚 社内データ",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
        }

# ------------------------------------------------------------------------------
# LINE Bot SDK v3 読み込み
# ------------------------------------------------------------------------------
try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.exceptions import InvalidSignatureError
    from linebot.v3.messaging import (
        Configuration,
        ApiClient,
        MessagingApi,
        ReplyMessageRequest,
        TextMessage,
    )
    from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent, FollowEvent

    LINE_SDK_AVAILABLE = True
    logger.info("✅ LINE Bot SDK v3 imported successfully")
except ImportError as e:
    logger.error(f"❌ LINE Bot SDK not available: {e}")
    LINE_SDK_AVAILABLE = False

    # ダミー（ローカル/依存欠如時フォールバック）
    class WebhookHandler:
        def __init__(self, *args, **kwargs) -> None: ...
        def add(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
        def handle(self, *args, **kwargs) -> None: ...

# ルーター
router = APIRouter(prefix="/line", tags=["line"])

# ------------------------------------------------------------------------------
# 認証情報の安全取得＆正規化
# ------------------------------------------------------------------------------
def get_line_credentials_safe() -> tuple[Optional[str], Optional[str]]:
    """LINE認証情報を安全に取得（Secret Manager フォールバック対応）"""
    access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    channel_secret = os.getenv("LINE_CHANNEL_SECRET")

    logger.info("🔍 Getting LINE credentials with enhanced safety...")

    if not access_token or not channel_secret:
        try:
            from google.cloud import secretmanager

            client = secretmanager.SecretManagerServiceClient()
            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "rag-cloud-project")

            if not access_token:
                try:
                    name = f"projects/{project_id}/secrets/LINE_CHANNEL_ACCESS_TOKEN/versions/latest"
                    resp = client.access_secret_version(request={"name": name})
                    access_token = resp.payload.data.decode("UTF-8")
                    logger.info("✅ Access token loaded from Secret Manager")
                except Exception as e:
                    logger.warning(f"Failed to load access token from Secret Manager: {e}")

            if not channel_secret:
                try:
                    name = f"projects/{project_id}/secrets/LINE_CHANNEL_SECRET/versions/latest"
                    resp = client.access_secret_version(request={"name": name})
                    channel_secret = resp.payload.data.decode("UTF-8")
                    logger.info("✅ Channel secret loaded from Secret Manager")
                except Exception as e:
                    logger.warning(f"Failed to load channel secret from Secret Manager: {e}")
        except ImportError:
            logger.warning("Google Cloud Secret Manager not available")
        except Exception as e:
            logger.error(f"Secret Manager error: {e}")

    return access_token, channel_secret


def normalize_line_token_ultimate(token: Any) -> str:
    """究極のLINEトークン正規化（改行・空白・表記ゆれを完全除去）"""
    if token is None:
        logger.error("❌ Token is None")
        return ""

    original_type = type(token).__name__
    original_len = len(str(token)) if token else 0
    logger.info(f"🔧 Normalizing token: type={original_type}, len={original_len}")

    if isinstance(token, bytes):
        try:
            token = token.decode("utf-8")
            logger.info("✅ Decoded token from bytes")
        except UnicodeDecodeError as e:
            logger.error(f"❌ Failed to decode token from bytes: {e}")
            return ""

    token_str = str(token)

    # 改行・タブの完全除去
    if any(c in token_str for c in ["\r", "\n", "\t"]):
        logger.warning("⚠️ Token contains newline characters - removing")
        token_str = token_str.replace("\r", "").replace("\n", "").replace("\t", "")

    token_str = token_str.strip()

    if token_str.lower().startswith("bearer "):
        token_str = token_str[7:].strip()
        logger.info("✅ Removed 'Bearer ' prefix")

    if token_str.startswith("b'") and token_str.endswith("'"):
        token_str = token_str[2:-1]
        logger.info("✅ Removed Python bytes notation")

    token_str = token_str.replace('"', "").replace("'", "")

    if any(c in token_str for c in ["\n", "\r", "\t", " "]):
        logger.warning("⚠️ Token still contains whitespace - final cleanup")
        token_str = "".join(token_str.split())

    final_len = len(token_str)
    has_newlines = any(c in token_str for c in ["\r", "\n", "\t"])
    starts_with_bearer = token_str.lower().startswith("bearer")

    logger.info(
        f"✅ Token normalized: len={final_len}, has_newlines={has_newlines}, starts_with_bearer={starts_with_bearer}"
    )

    if not token_str:
        logger.error("❌ Token is empty after normalization")
        return ""

    if final_len < 50:
        logger.warning(f"⚠️ Token seems short: {final_len} characters")

    if has_newlines:
        logger.error("❌ Token still contains newlines after normalization")
        return ""

    return token_str

# ------------------------------------------------------------------------------
# LINE Bot 初期化
# ------------------------------------------------------------------------------
LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET = get_line_credentials_safe()

line_bot_api = None
handler = None

if LINE_SDK_AVAILABLE:
    if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
        try:
            normalized_token = normalize_line_token_ultimate(LINE_CHANNEL_ACCESS_TOKEN)
            normalized_secret = normalize_line_token_ultimate(LINE_CHANNEL_SECRET)
            if not normalized_token:
                raise ValueError("❌ Normalized access token is empty")
            if not normalized_secret:
                raise ValueError("❌ Normalized channel secret is empty")

            logger.info(
                f"🚀 Using normalized token: len={len(normalized_token)}, starts_with={normalized_token[:10]}..."
            )

            configuration = Configuration(access_token=normalized_token)
            handler = WebhookHandler(normalized_secret)

            # MessagingApi を一度生成しておく（動作確認）
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

# ------------------------------------------------------------------------------
# 応答テンプレート
# ------------------------------------------------------------------------------
GREETING_MESSAGE = """こんにちは！キノエデザインです。
この度は友だち追加ありがとうございます✨

目的のボタンをタップ👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画 / 🌐サイト / 💬チャット

AIは24時間、担当者は当日〜翌営業日に返信します。

取扱い(プライバシーポリシー)：〔https://preview.studio.site/live/EjOQljz1WJ/privacy-policy〕"""

RICHMENU_RESPONSES: Dict[str, str] = {
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
お気軽にお声かけください！""",
}

# ------------------------------------------------------------------------------
# 判定・返信ユーティリティ
# ------------------------------------------------------------------------------
def detect_richmenu_action(message_text: str) -> str:
    """リッチメニューアクションを検出"""
    text_clean = message_text.lower().replace(" ", "").replace("　", "")

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
        "チャット": "チャット相談",
    }

    for keyword, action in richmenu_keywords.items():
        if keyword in text_clean:
            return action

    return "unknown"


def send_line_reply_ultimate_safe(reply_token: str, message_text: str) -> bool:
    """究極に安全なLINE返信送信（同期・毎回Configuration再生成）"""
    if not line_bot_api:
        logger.error("❌ LINE Bot API not initialized")
        return False

    try:
        current_token = normalize_line_token_ultimate(LINE_CHANNEL_ACCESS_TOKEN)
        if not current_token:
            logger.error("❌ Failed to normalize access token for reply")
            return False

        logger.info(
            f"📤 Sending LINE reply: token_len={len(current_token)}, message_len={len(message_text)}"
        )
        logger.info(
            f"🔍 Token debug: type={type(current_token)}, has_newlines={any(c in current_token for c in [chr(13), chr(10)])}"
        )

        configuration = Configuration(access_token=current_token)
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            messaging_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=reply_token, messages=[TextMessage(text=message_text)]
                )
            )

        logger.info(f"✅ LINE reply sent successfully (message length: {len(message_text)})")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to send LINE reply: {e}")
        logger.error(f"🔍 Error details: {traceback.format_exc()}")
        return False

# ------------------------------------------------------------------------------
# Webhook エンドポイント
# ------------------------------------------------------------------------------
@router.post("/webhook")
async def line_webhook_ultimate(request: Request, background_tasks: BackgroundTasks):
    """究極に安全なLINE Webhook（友達追加対応・同期ハンドラ前提）"""
    logger.info("🚀 LINE Webhook called (Ultimate Safe Version with Follow Support)")

    if not line_bot_api or not handler:
        logger.error("❌ LINE Bot not configured properly")
        return {"status": "error", "message": "LINE Bot not configured"}

    try:
        body = await request.body()
        signature = request.headers.get("X-Line-Signature", "")

        logger.info(
            f"📨 Webhook - Body length: {len(body)}, Signature: {'Present' if signature else 'Missing'}"
        )

        if not signature:
            logger.error("❌ Missing X-Line-Signature header")
            return {"status": "error", "message": "Missing signature"}

        try:
            body_text = body.decode("utf-8")
            logger.info(f"📄 Processing webhook body: {body_text[:200]}...")

            # イベント処理（同期ハンドラ群が処理）
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

# ------------------------------------------------------------------------------
# RAG 連携（同期版）
# ------------------------------------------------------------------------------
def get_app_globals() -> Dict[str, Any]:
    """アプリのグローバル変数を取得"""
    try:
        import main

        return {
            "vectorstore": getattr(main, "vectorstore", None),
            "rag_chain_template": getattr(main, "rag_chain_template", None),
            "llm_instance": getattr(main, "llm_instance", None),
        }
    except Exception as e:
        logger.error(f"Failed to get app globals: {e}")
        return {}

def process_general_question_sync(message_text: str, user_id: str = "unknown") -> str:
    """一般的な質問の処理（同期版・ハルチネーション対策適用）"""
    try:
        globals_dict = get_app_globals()
        original_response: Optional[str] = None

        if globals_dict.get("rag_chain_template"):
            try:
                result = globals_dict["rag_chain_template"].invoke({"query": message_text})
                original_response = result.get("result", "申し訳ございません。お答えできませんでした。")
            except Exception as e:
                logger.warning(f"RAG invoke warning (sync): {e}")

        enhanced = enhance_line_chat_response_sync(
            query=message_text, user_id=user_id, original_response=original_response
        )
        final_answer = enhanced.get("answer") or "申し訳ございません。お答えできませんでした。"

        logger.info(
            f"LINE response enhanced - Anti-hallucination: {enhanced.get('anti_hallucination_used', False)}"
        )
        if enhanced.get("last_updated"):
            logger.info(f"Last updated: {enhanced['last_updated']}")
        if enhanced.get("warnings"):
            logger.info(f"Warnings: {enhanced['warnings']}")

        return final_answer
    except Exception as e:
        logger.error(f"Error processing general question (sync): {e}")
        return "申し訳ございません。エラーが発生しました。"

# ------------------------------------------------------------------------------
# イベントハンドラ（Follow / Message / Postback）— 同期化済み
# ------------------------------------------------------------------------------
if LINE_SDK_AVAILABLE and handler:

    @handler.add(FollowEvent)
    def handle_follow_event(event):
        """友達追加時のハンドラー（挨拶メッセージ送信）"""
        start_time = datetime.now()
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token

            logger.info(f"👤 New follower: {user_id}")
            logger.info("📬 Sending greeting message...")

            success = send_line_reply_ultimate_safe(reply_token, GREETING_MESSAGE)
            duration = (datetime.now() - start_time).total_seconds()

            if success:
                logger.info(
                    f"✅ Greeting message sent successfully: user={user_id}, time={duration:.3f}s"
                )
            else:
                logger.error(f"❌ Failed to send greeting message: user={user_id}")
        except Exception as e:
            logger.error(f"💥 Follow event handler error: {e}")
            logger.error(traceback.format_exc())
            try:
                emergency = "こんにちは！キノエデザインです。友だち追加ありがとうございます！"
                send_line_reply_ultimate_safe(event.reply_token, emergency)
            except Exception as final_error:
                logger.error(f"💥 Emergency greeting failed: {final_error}")

    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_text_message_ultimate(event):
        """究極のメッセージハンドラ（ハルチネーション対策強化版・同期処理）"""
        start_time = datetime.now()
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            reply_token = event.reply_token

            logger.info(f"📱 Message from {user_id}: '{message_text}'")

            action = detect_richmenu_action(message_text)
            if action != "unknown":
                logger.info(f"🎯 Richmenu action detected: {action}")
                response_text = RICHMENU_RESPONSES.get(action, "ご利用ありがとうございます。")
            else:
                logger.info("💬 General message processing with sync anti-hallucination")
                response_text = process_general_question_sync(message_text, user_id)

            success = send_line_reply_ultimate_safe(reply_token, response_text)
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ Message processed: success={success}, time={duration:.3f}s")

            if not success:
                logger.error(f"❌ Failed to send reply for message: '{message_text}'")
        except Exception as e:
            logger.error(f"💥 Message handler error: {e}")
            logger.error(traceback.format_exc())
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

# ------------------------------------------------------------------------------
# デバッグ系エンドポイント
# ------------------------------------------------------------------------------
@router.get("/debug-ultimate")
def line_debug_ultimate():
    """LINE Bot デバッグ情報（完全版）"""
    raw_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    normalized_token = normalize_line_token_ultimate(raw_token) if raw_token else ""

    return {
        "line_sdk_available": LINE_SDK_AVAILABLE,
        "line_bot_api_initialized": line_bot_api is not None,
        "handler_initialized": handler is not None,
        "follow_event_supported": True,
        "greeting_message_configured": True,
        "anti_hallucination_enabled": True,
        "credentials_debug": {
            "raw_token_type": type(raw_token).__name__ if raw_token else "None",
            "raw_token_length": len(str(raw_token)) if raw_token else 0,
            "raw_token_has_newlines": any(c in str(raw_token) for c in ["\r", "\n"]) if raw_token else False,
            "normalized_token_length": len(normalized_token),
            "normalized_token_valid": len(normalized_token) > 50,
            "normalized_starts_with_bearer": normalized_token.startswith("Bearer ") if normalized_token else False,
        },
        "initialization_status": "✅ Success with Follow Support + Anti-Hallucination"
        if line_bot_api and handler
        else "❌ Failed",
        "greeting_message_preview": GREETING_MESSAGE[:100] + "..." if len(GREETING_MESSAGE) > 100 else GREETING_MESSAGE,
        "timestamp": datetime.now().isoformat(),
    }

@router.get("/test-greeting")
def test_greeting_message():
    """挨拶メッセージのテスト表示"""
    return {
        "greeting_message": GREETING_MESSAGE,
        "message_length": len(GREETING_MESSAGE),
        "follow_event_configured": True,
        "anti_hallucination_configured": True,
        "test_info": "This is the message that will be sent when users follow the LINE bot",
        "timestamp": datetime.now().isoformat(),
    }
