# api/routers/line_bot_template_fast.py - 最高速度テンプレート応答専用LINE Bot

import logging
import os
import re
import json
import time
from datetime import datetime
from typing import Dict, Optional, Any, List

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

router = APIRouter(tags=["line-template-fast"])

# ==============================================================================
# 認証情報取得
# ==============================================================================
def get_line_credentials_safe():
    """LINE認証情報を安全に取得"""
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
                resp = client.access_secret_version(request={"name": name})
                access_token = resp.payload.data.decode("UTF-8")
            
            if not channel_secret:
                name = f"projects/{project_id}/secrets/LINE_CHANNEL_SECRET/versions/latest"
                resp = client.access_secret_version(request={"name": name})
                channel_secret = resp.payload.data.decode("UTF-8")
                
        except Exception as e:
            logger.warning(f"Secret Manager access failed: {e}")
    
    return access_token, channel_secret

def normalize_line_token(token) -> str:
    """LINE トークン正規化"""
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

# ==============================================================================
# 初期化
# ==============================================================================
LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET = get_line_credentials_safe()
line_bot_api = None
handler = None

if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        normalized_token = normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)
        normalized_secret = normalize_line_token(LINE_CHANNEL_SECRET)
        
        if normalized_token and normalized_secret:
            configuration = Configuration(access_token=normalized_token)
            handler = WebhookHandler(normalized_secret)
            
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
            
            logger.info("✅ Template Fast LINE Bot initialized successfully")
        else:
            raise ValueError("Empty normalized credentials")
            
    except Exception as e:
        logger.error(f"❌ LINE Bot initialization failed: {e}")
        line_bot_api, handler = None, None

# ==============================================================================
# テンプレート応答システム（LLM/OpenAI API不使用）
# ==============================================================================
class TemplateFastResponder:
    """超高速テンプレート応答（API呼び出しなし）"""
    
    def __init__(self):
        self.templates = self._load_instant_templates()
        self.action_flow = self._load_action_flows()
        self.stats = {"template_responses": 0, "follow_up_actions": 0, "total_response_time": 0}
        
    def _load_instant_templates(self) -> Dict[str, Dict]:
        """即座応答テンプレート（LLM/OpenAI API完全不使用）"""
        return {
            "AI相談": {
                "response": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 **例えば**
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？

何でもお聞きください😊

※ご使用の前に、必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",
                "next_action": "enable_ai_mode",
                "response_type": "template_instant"
            },
            
            "AI住まいサイト": {
                "response": """🌐 AI住まいサイトのご案内

キノエデザインの住まい情報サイトをご紹介します。（家づくりの疑問にAIが24時間即回答）

🏠 サイト内容：
・AIチャット相談（資金計画／補助金／間取り など）
・施工写真（実例）
・間取りの考え方・プラン例
・よくある質問（最初に迷う3つのこと ほか）
・保存版デジタル冊子 ZINE（無料ダウンロード）
・LINEで無料相談／来場予約

📱 サイトURL：
https://preview.studio.site/live/EjOQljz1WJ/""",
                "next_action": "show_menu",
                "response_type": "template_instant"
            },
            
            "資料請求": {
                "response": """📋ありがとうございます！こちらからご覧いただけます。

〔資料タイトル〕（PDF）：〔URL〕

よろしければ簡単アンケート（任意）：
・ご計画時期：今すぐ / 3–6か月 / 1年以内 / 未定
・連絡方法（任意）：このLINE / メール / 連絡不要

※必ず以下の取り扱いをご確認ください。
プライバシーポリシー：【https://preview.studio.site/live/EjOQljz1WJ/privacy-policy 】
利用規約：【https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service 】
Cookie：【https://preview.studio.site/live/EjOQljz1WJ/cookie 】""",
                "next_action": "collect_contact_info",
                "response_type": "template_instant"
            },
            
            "展示場来場予約": {
                "response": """📍 展示場のご来場予約につきましては、下記URLより必要事項のご入力をお願い申し上げます。

【https://preview.studio.site/live/EjOQljz1WJ/reservation 】

スタッフ一同、心よりお待ちしております！""",
                "next_action": "collect_visit_info",
                "response_type": "template_instant"
            },
            
            "資金計画": {
                "response": """💬 AI資金診断のご案内

本診断は匿名でご利用いただけます。ご回答内容は保存いたしません。算出される金額は試算（概算）であり、目安としてご確認ください。

お手数ですが、以下の5点をご入力ください。
・年収（概算可）
・毎月のご希望返済額
・住宅ローンのご希望借入期間
・ご家族構成（例：大人2名・お子さま1名）
・その他の大きなご負担（例：自動車ローン 等）

未入力の項目があっても進められます。ご入力後、概算結果をご提示いたします。""",
                "next_action": "collect_finance_info",
                "response_type": "template_instant"
            },
            
            "チャット相談": {
                "response": """💬 スタッフとのご相談

【対応時間】
営業時間：9:00-18:00

📱 ご相談方法：
・このLINEでの直接相談
・お電話での相談
・展示場での対面相談

営業時間内でしたら迅速にお返事します。
お気軽にお声かけください！""",
                "next_action": "enable_staff_mode",
                "response_type": "template_instant"
            }
        }
    
    def _load_action_flows(self) -> Dict[str, Dict]:
        """アクション後のフロー定義"""
        return {
            "enable_ai_mode": {
                "mode": "ai_consultation",
                "description": "AI相談モード有効化",
                "next_responses": self._get_ai_follow_up_templates()
            },
            "collect_contact_info": {
                "mode": "contact_collection",
                "description": "連絡先収集モード",
                "fields_required": ["name", "address", "phone", "material_type"]
            },
            "collect_visit_info": {
                "mode": "visit_booking",
                "description": "見学予約収集モード",
                "fields_required": ["datetime", "name", "phone", "participants"]
            },
            "collect_finance_info": {
                "mode": "finance_consultation",
                "description": "資金相談モード",
                "fields_required": ["income", "budget", "family_info"]
            },
            "enable_staff_mode": {
                "mode": "staff_consultation",
                "description": "スタッフ相談モード有効化"
            }
        }
    
    def _get_ai_follow_up_templates(self) -> Dict[str, str]:
        """AI相談モード後のフォローアップテンプレート（LLM不使用）"""
        return {
            "坪単価": """💰 坪単価についてご案内いたします

🏠 **当社の坪単価目安**
・標準仕様：約70～85万円/坪
・高性能仕様：約85～100万円/坪

✨ **含まれる内容**
・耐震等級3の構造
・長期優良住宅対応
・高断熱・高気密仕様
・標準設備一式

お客様のご要望により変動いたします。
詳細なお見積りをご希望でしたら、お気軽にお問い合わせください。""",
            
            "標準仕様": """🏗️ 標準仕様についてご説明いたします

**構造・性能**
・耐震等級3（最高等級）
・長期優良住宅認定対応
・省エネ等級4以上
・高断熱・高気密仕様

**設備仕様**
・システムキッチン
・ユニットバス
・洗面化粧台
・トイレ（温水洗浄便座付）

より詳しい仕様書をご希望の場合は、資料請求をお申し込みください。""",
            
            "断熱性能": """🌡️ 断熱性能についてご案内いたします

**断熱等級**
・断熱等級4以上（ZEH基準対応）
・UA値：0.6以下（地域区分6）
・C値：1.0以下（気密性能）

**使用断熱材**
・外壁：高性能グラスウール
・屋根：吹付断熱材
・基礎：押出法ポリスチレンフォーム

**快適性**
・夏涼しく、冬暖かい
・光熱費の削減効果
・結露抑制

詳しくは展示場でご体感いただけます。""",
            
            "耐震性能": """🏗️ 耐震性能についてご案内いたします

**耐震等級**
・耐震等級3（最高等級）を標準採用
・建築基準法の1.5倍の耐震強度
・許容応力度計算による構造計算

**構造材**
・構造用集成材使用
・金物工法による強固な接合
・ベタ基礎による堅固な基礎

**保証**
・構造躯体20年保証
・地盤保証20年
・瑕疵担保責任保険対応

安心・安全な住まいをお約束いたします。"""
        }
    
    def get_instant_response(self, message_text: str, user_id: str = "unknown") -> Dict[str, Any]:
        """即座応答取得（LLM/OpenAI API完全不使用）"""
        start_time = time.time()
        
        try:
            # 1. リッチメニューアクション検出
            action = self._detect_richmenu_action(message_text)
            
            if action and action in self.templates:
                template_data = self.templates[action]
                response_text = template_data["response"]
                next_action = template_data["next_action"]
                
                processing_time = time.time() - start_time
                self.stats["template_responses"] += 1
                self.stats["total_response_time"] += processing_time
                
                logger.info(f"⚡ INSTANT template response: {action} in {processing_time*1000:.1f}ms")
                
                return {
                    "response": response_text,
                    "next_action": next_action,
                    "processing_time": processing_time,
                    "response_type": "template_instant",
                    "api_calls": 0,  # LLM/OpenAI API不使用
                    "success": True
                }
            
            # 2. AI相談モード中のテンプレート応答
            ai_templates = self._get_ai_follow_up_templates()
            for keyword, template_response in ai_templates.items():
                if keyword in message_text:
                    processing_time = time.time() - start_time
                    self.stats["follow_up_actions"] += 1
                    
                    logger.info(f"⚡ AI follow-up template: {keyword} in {processing_time*1000:.1f}ms")
                    
                    return {
                        "response": template_response,
                        "next_action": "continue_ai_mode",
                        "processing_time": processing_time,
                        "response_type": "ai_template_instant",
                        "api_calls": 0,  # LLM/OpenAI API不使用
                        "success": True
                    }
            
            # 3. 一般的な挨拶・フォールバック
            fallback_response = self._get_fallback_response(message_text)
            processing_time = time.time() - start_time
            
            return {
                "response": fallback_response,
                "next_action": "general_response",
                "processing_time": processing_time,
                "response_type": "fallback_instant",
                "api_calls": 0,  # LLM/OpenAI API不使用
                "success": True
            }
            
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"❌ Template response error: {e}")
            
            return {
                "response": "申し訳ございません。一時的にエラーが発生しました。メニューからお選びください。",
                "next_action": "error_recovery",
                "processing_time": processing_time,
                "response_type": "error_instant",
                "api_calls": 0,
                "success": False,
                "error": str(e)
            }
    
    def _detect_richmenu_action(self, message: str) -> Optional[str]:
        """リッチメニューアクション検出（完全一致優先）"""
        message_clean = message.lower().replace(" ", "").replace("　", "")
        
        # 完全一致を最優先
        exact_matches = {
            "ai相談": "AI相談",
            "🤖ai相談": "AI相談",
            "ai住まいサイト": "AI住まいサイト",
            "🌐ai住まいサイト": "AI住まいサイト",
            "aiサイト": "AI住まいサイト", 
            "資料請求": "資料請求",
            "📋資料請求": "資料請求",
            "展示場来場予約": "展示場来場予約",
            "📍展示場来場予約": "展示場来場予約",
            "展示場予約": "展示場来場予約",
            "資金計画": "資金計画",
            "💰資金計画": "資金計画",
            "チャット相談": "チャット相談",
            "💬チャット相談": "チャット相談"
        }
        
        for keyword, action in exact_matches.items():
            if keyword == message_clean:
                return action
        
        # 部分一致（より寛容）
        partial_matches = {
            "ai相談": "AI相談",
            "住まいサイト": "AI住まいサイト",
            "資料": "資料請求",
            "展示場": "展示場来場予約",
            "見学": "展示場来場予約",
            "資金": "資金計画",
            "ローン": "資金計画",
            "チャット": "チャット相談",
            "相談": "チャット相談"
        }
        
        for keyword, action in partial_matches.items():
            if keyword in message_clean:
                return action
        
        return None
    
    def _get_fallback_response(self, message: str) -> str:
        """フォールバック応答（LLM不使用）"""
        message_lower = message.lower()
        
        # 挨拶パターン
        if any(greeting in message_lower for greeting in ["こんにちは", "はじめまして", "よろしく"]):
            return """こんにちは！キノエデザインです✨

住まいづくりのことでしたら何でもお気軽にご相談ください😊

下記メニューからお選びいただけます👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画 / 🌐サイト / 💬チャット

お気軽にお声かけください。"""
        
        # 質問パターン
        elif "?" in message or "？" in message or any(q in message for q in ["何", "どう", "いくら"]):
            return """ご質問ありがとうございます✨

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

**よくあるご質問**
💰 坪単価や費用について
🏠 住宅性能や仕様について  
📋 資料請求・展示場見学
💴 資金計画・住宅ローン

具体的にお聞かせいただければ、詳しくご案内いたします。お気軽にお問い合わせください😊"""
        
        # その他
        else:
            return """メッセージありがとうございます。

住まいづくりに関することでしたら、何でもお気軽にお聞かせください。

メニューからお選びいただくか、直接ご質問をお送りください👇

🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画

スタッフ一同、お客様のお手伝いをさせていただきます。"""
    
    def get_stats(self) -> Dict[str, Any]:
        """統計情報取得"""
        total_responses = self.stats["template_responses"] + self.stats["follow_up_actions"]
        avg_response_time = (self.stats["total_response_time"] / total_responses) if total_responses > 0 else 0
        
        return {
            "total_responses": total_responses,
            "template_responses": self.stats["template_responses"],
            "follow_up_actions": self.stats["follow_up_actions"],
            "average_response_time_ms": avg_response_time * 1000,
            "api_calls_made": 0,  # LLM/OpenAI API完全不使用
            "template_count": len(self.templates),
            "follow_up_template_count": len(self._get_ai_follow_up_templates())
        }

# グローバルインスタンス
template_responder = TemplateFastResponder()

# ==============================================================================
# 安全送信関数
# ==============================================================================
def send_line_message_safe(reply_token: str, user_id: str, message: str) -> bool:
    """安全なLINE送信（reply失効時はPush APIにフォールバック）"""
    if not line_bot_api:
        logger.error("❌ LINE Bot API not initialized")
        return False
    
    try:
        normalized_token = normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)
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
                if "Invalid reply token" in str(reply_error) or getattr(reply_error, "status", None) == 400:
                    logger.warning(f"⚠️ Reply token expired, using Push API fallback for user: {user_id}")
                    
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
async def template_fast_webhook(request: Request, background_tasks: BackgroundTasks):
    """テンプレート高速Webhook（LLM/OpenAI API完全不使用）"""
    logger.info("🚀 LINE Template Fast Webhook called")
    
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
        logger.error(f"💥 Template fast webhook error: {e}")
        return {"status": "error", "error": str(e)}

# ==============================================================================
# イベントハンドラ（テンプレート高速処理）
# ==============================================================================
if LINE_SDK_AVAILABLE and handler:
    
    @handler.add(FollowEvent)
    def handle_follow_template_fast(event):
        """フォローハンドラ（テンプレート高速）"""
        start_time = time.time()
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            
            logger.info(f"👤 New follower (template fast): {user_id}")
            
            greeting_message = """こんにちは！キノエデザインです。
この度は友だち追加ありがとうございます✨

目的のボタンをタップ👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画 / 🌐サイト / 💬チャット

AIは24時間、担当者は当日〜翌営業日に返信します。

取扱い(プライバシーポリシー)：〔https://preview.studio.site/live/EjOQljz1WJ/privacy-policy〕"""
            
            success = send_line_message_safe(reply_token, user_id, greeting_message)
            
            duration = (time.time() - start_time) * 1000
            logger.info(f"✅ Template fast greeting sent: {duration:.1f}ms, success: {success}")
            
        except Exception as e:
            logger.error(f"❌ Template fast follow error: {e}")
    
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_message_template_fast(event):
        """メッセージハンドラ（テンプレート高速処理・LLM/OpenAI API完全不使用）"""
        start_time = time.time()
        
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            reply_token = event.reply_token
            
            logger.info(f"📱 Template fast processing: '{message_text[:30]}...' from user: {user_id}")
            
            # テンプレート高速処理（LLM/OpenAI API完全不使用）
            response_data = template_responder.get_instant_response(message_text, user_id)
            
            if response_data["success"]:
                response_text = response_data["response"]
                success = send_line_message_safe(reply_token, user_id, response_text)
                
                duration = (time.time() - start_time) * 1000
                logger.info(f"✅ Template fast response sent: {duration:.1f}ms, "
                           f"type={response_data['response_type']}, "
                           f"api_calls={response_data['api_calls']}, "
                           f"success={success}")
            else:
                # エラー時も高速応答
                error_response = "申し訳ございません。メニューからお選びください。"
                success = send_line_message_safe(reply_token, user_id, error_response)
                
                duration = (time.time() - start_time) * 1000
                logger.error(f"❌ Template fast error response: {duration:.1f}ms, success={success}")
            
        except Exception as e:
            logger.error(f"❌ Template fast message error: {e}")
            try:
                emergency = "システムエラーが発生しました。メニューからお選びください。"
                send_line_message_safe(event.reply_token, event.source.user_id, emergency)
            except Exception as final_error:
                logger.error(f"❌ Emergency response failed: {final_error}")

    @handler.add(PostbackEvent)
    def handle_postback_template_fast(event):
        """Postbackハンドラ（テンプレート高速）"""
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
                
                # テンプレート即座応答
                response_data = template_responder.get_instant_response(action_value, user_id)
                response_text = response_data["response"]
            else:
                response_text = "メニューからお選びください。"
            
            success = send_line_message_safe(reply_token, user_id, response_text)
            logger.info(f"✅ Postback template response: success={success}")
            
        except Exception as e:
            logger.error(f"💥 Postback handler error: {e}")

# ==============================================================================
# 監視・デバッグエンドポイント
# ==============================================================================
@router.get("/performance")
def get_template_performance():
    """テンプレート高速処理パフォーマンス統計"""
    stats = template_responder.get_stats()
    
    return {
        "template_fast_stats": stats,
        "system_info": {
            "line_sdk_available": LINE_SDK_AVAILABLE,
            "line_bot_configured": line_bot_api is not None,
            "llm_api_usage": "COMPLETELY_DISABLED",  # LLM/OpenAI API完全不使用
            "openai_api_usage": "COMPLETELY_DISABLED",
            "response_method": "TEMPLATE_ONLY"
        },
        "features": [
            "Instant Template Responses (0 API calls)",
            "Rich Menu Action Detection",
            "Follow-up Action Flows",
            "Reply Token Expiry Protection",
            "Push API Automatic Fallback",
            "Complete LLM/OpenAI API Independence",
            "Sub-100ms Response Times"
        ],
        "performance_targets": {
            "response_time": "< 100ms",
            "api_calls": "0 (Template Only)",
            "success_rate": "> 99%"
        },
        "timestamp": datetime.now().isoformat()
    }

@router.get("/debug")
def template_debug_info():
    """テンプレート高速デバッグ情報"""
    return {
        "line_sdk_available": LINE_SDK_AVAILABLE,
        "line_bot_api_initialized": line_bot_api is not None,
        "handler_initialized": handler is not None,
        "template_system": {
            "template_count": len(template_responder.templates),
            "follow_up_template_count": len(template_responder._get_ai_follow_up_templates()),
            "llm_dependency": "NONE",
            "openai_dependency": "NONE",
            "api_calls_per_response": 0
        },
        "processing_method": "TEMPLATE_INSTANT",
        "timestamp": datetime.now().isoformat()
    }

@router.get("/templates")
def get_template_list():
    """テンプレート一覧"""
    return {
        "instant_templates": list(template_responder.templates.keys()),
        "follow_up_templates": list(template_responder._get_ai_follow_up_templates().keys()),
        "total_templates": len(template_responder.templates) + len(template_responder._get_ai_follow_up_templates()),
        "api_dependency": "NONE",
        "response_method": "INSTANT_TEMPLATE",
        "timestamp": datetime.now().isoformat()
    }