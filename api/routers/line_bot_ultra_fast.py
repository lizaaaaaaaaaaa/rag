# api/routers/line_bot_ultra_fast.py - reply失効対策・プラットフォーム分離対応版（修正版）

import logging
import os
import re
import json
import asyncio
import traceback
import time
import hashlib
from datetime import datetime
from typing import Dict, Optional, Any, List

from fastapi import APIRouter, Request, BackgroundTasks
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# LINE SDK v3 import（修正版 - LineBotApiError問題解決）
try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.exceptions import InvalidSignatureError
    from linebot.v3.messaging import (
        Configuration, ApiClient, MessagingApi, ReplyMessageRequest, PushMessageRequest, TextMessage,
        ApiException  # 修正: LineBotApiError → ApiException
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

router = APIRouter(tags=["line-ultra-fast"])

# ==============================================================================
# LINE専用テンプレート応答システム
# ==============================================================================
class LineUltraFastResponder:
    def __init__(self):
        self.line_templates = self._load_line_templates()
        self.greeting_message = self._load_greeting_message()
        self.performance_stats = {"requests": 0, "template_hits": 0, "greeting_sent": 0, "push_fallbacks": 0}
        
    def _load_line_templates(self) -> Dict[str, str]:
        """LINE専用テンプレート（絵文字・改行最適化）"""
        return {
            "AI相談": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 例えば：
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？

何でもお聞きください😊""",

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

より詳しい仕様書をご希望の場合は、資料請求または展示場見学をお申し込みください。""",

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

安心・安全な住まいをお約束いたします。""",

            "補助金": """💰 住宅購入時の補助金制度についてご案内します

**主な補助金制度**
🏠 ZEH補助金：高性能住宅への補助
🌱 こどもエコすまい支援事業：子育て世帯への支援
🏦 住宅ローン減税：所得税の控除制度
📋 地域独自の補助金：自治体による支援

※制度は年度ごとに変更される可能性があります。最新情報については公式サイトでご確認いただくか、スタッフまでお問い合わせください。""",

            "資料請求": """📋 資料請求を承ります

**必要情報をお送りください**
1️⃣ お名前（フルネーム）
2️⃣ ご住所（〒郵便番号から）
3️⃣ お電話番号
4️⃣ ご希望資料の種類

**お送りする資料**
・会社案内・施工事例集
・間取りプラン集
・価格・仕様資料
・住宅ローンガイド

3営業日以内にお送りいたします！""",

            "展示場予約": """📍 展示場見学を承ります

**予約情報をお送りください**
・ご希望日時（第1・第2希望）
・お名前・お電話番号
・参加人数（大人・お子様）
・ご質問・ご要望

🕒 見学時間：約90分
🏠 展示場：最新の住宅仕様をご確認

スタッフ一同、心よりお待ちしております！""",

            "資金計画": """💰 資金計画についてサポートします

**ご相談内容**
・住宅ローンの種類・金利比較
・月々の返済計画
・頭金・諸費用の計算
・住宅ローン控除について

**お聞かせください**
・ご年収・自己資金
・ご希望借入額・返済期間
・家族構成・将来計画

最適なプランをご提案いたします！""",

            "AI住まいサイト": """🌐 AI住まいサイトのご案内

キノエデザインの住まい情報サイトをご紹介します。

🏠 **サイト内容**
・施工事例・間取りプラン
・住宅性能・標準仕様
・価格・坪単価情報
・お客様の声

📱 **サイトURL**
https://kinoe-design.com

詳しい住まい情報をご確認いただけます！""",

            "チャット相談": """💬 スタッフとのご相談

**対応時間**
平日・土日：9:00-18:00
定休日：水曜日

**ご相談方法**
・このLINEでの直接相談
・お電話での相談
・展示場での対面相談

**ご相談内容**
・住まいづくり全般
・土地探し・資金計画
・間取り・デザイン
・住宅性能について

営業時間内でしたら迅速にお返事します。
お気軽にお声かけください！"""
        }
    
    def _load_greeting_message(self) -> str:
        """友だち追加時の挨拶メッセージ"""
        return """こんにちは！キノエデザインです。
この度は友だち追加ありがとうございます✨

目的のボタンをタップ👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画 / 🌐サイト / 💬チャット

AIは24時間、担当者は当日〜翌営業日に返信します。

取扱い(プライバシーポリシー)：〔https://preview.studio.site/live/EjOQljz1WJ/privacy-policy〕"""
    
    def process_ultra_fast(self, message_text: str, user_id: str = "unknown") -> str:
        """超高速処理（LINE専用）"""
        start_time = time.time()
        self.performance_stats["requests"] += 1
        
        try:
            # リッチメニューアクション検出
            action = self._detect_richmenu_action(message_text)
            if action != "unknown":
                self.performance_stats["template_hits"] += 1
                response = self.line_templates.get(action, "ご利用ありがとうございます。")
                logger.info(f"🎯 LINE Template match: {action} in {(time.time() - start_time)*1000:.1f}ms")
                return response
            
            # 一般質問の高速処理
            template_response = self._match_question_template(message_text)
            if template_response:
                self.performance_stats["template_hits"] += 1
                logger.info(f"🎯 LINE Question match in {(time.time() - start_time)*1000:.1f}ms")
                return template_response
            
            # インテリジェントフォールバック
            fallback_response = self._generate_line_fallback(message_text)
            logger.info(f"🔄 LINE Fallback in {(time.time() - start_time)*1000:.1f}ms")
            return fallback_response
            
        except Exception as e:
            logger.error(f"❌ LINE processing error: {e}")
            return self._emergency_response()
    
    def _detect_richmenu_action(self, message: str) -> str:
        """リッチメニューアクション検出（拡張版）"""
        text_clean = message.lower().replace(" ", "").replace("　", "")
        
        richmenu_actions = {
            "AI相談": ["ai相談", "ai住まい相談", "相談開始"],
            "坪単価": ["坪単価", "価格", "費用", "いくら", "金額"],
            "標準仕様": ["標準仕様", "仕様", "設備", "標準"],
            "断熱性能": ["断熱", "断熱性能", "省エネ", "温度"],
            "耐震性能": ["耐震", "地震", "安全", "強度"],
            "補助金": ["補助金", "助成金", "支援金", "補助制度"],  # 追加
            "資料請求": ["資料請求", "資料", "パンフレット", "カタログ"],
            "展示場予約": ["展示場予約", "展示場", "見学", "予約"],
            "資金計画": ["資金計画", "ローン", "住宅ローン", "お金"],
            "AI住まいサイト": ["ai住まいサイト", "サイト", "ホームページ"],
            "チャット相談": ["チャット相談", "チャット", "スタッフ", "担当者"]
        }
        
        for action, keywords in richmenu_actions.items():
            if any(keyword in text_clean for keyword in keywords):
                return action
        
        return "unknown"
    
    def _match_question_template(self, query: str) -> Optional[str]:
        """一般質問のテンプレートマッチング"""
        query_lower = query.lower()
        
        # より詳細なマッチング
        if any(word in query_lower for word in ["坪単価", "価格", "費用", "コスト", "いくら"]):
            return self.line_templates["坪単価"]
        elif any(word in query_lower for word in ["仕様", "設備", "標準", "基本"]):
            return self.line_templates["標準仕様"]
        elif any(word in query_lower for word in ["断熱", "省エネ", "温度", "光熱費"]):
            return self.line_templates["断熱性能"]
        elif any(word in query_lower for word in ["耐震", "地震", "安全", "強度"]):
            return self.line_templates["耐震性能"]
        elif any(word in query_lower for word in ["補助金", "助成金", "支援金"]):  # 追加
            return self.line_templates["補助金"]
        elif any(word in query_lower for word in ["資料", "パンフレット", "カタログ"]):
            return self.line_templates["資料請求"]
        elif any(word in query_lower for word in ["見学", "展示場", "予約"]):
            return self.line_templates["展示場予約"]
        
        return None
    
    def _generate_line_fallback(self, query: str) -> str:
        """LINE専用フォールバック"""
        q_lower = query.lower()
        
        if any(word in q_lower for word in ["家を建てる", "マイホーム", "新築"]):
            return """🏗️ 家づくりについてお答えいたします

家づくりは人生で最も大きな買い物の一つです✨

**まずはこちらから始めませんか？**
1️⃣ 資料請求で情報収集
2️⃣ 展示場見学で実際の住まいを体感
3️⃣ 資金計画で予算を明確化

お客様のご希望をお聞かせいただければ、最適なプランをご提案いたします。何からお聞きになりたいでしょうか？"""
        
        elif any(word in q_lower for word in ["補助金", "助成金", "支援"]):
            return self.line_templates["補助金"]  # 補助金テンプレートを直接使用
        
        elif any(word in q_lower for word in ["こんにちは", "はじめまして", "よろしく"]):
            return """こんにちは！キノエデザインです✨

住まいづくりのことでしたら何でもお気軽にご相談ください😊

下記メニューからお選びいただけます👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画"""
        
        else:
            return """ご質問ありがとうございます✨

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

**よくあるご質問**
💰 坪単価や費用について
🏠 住宅性能や仕様について
📋 資料請求・展示場見学
💴 資金計画・住宅ローン

具体的にお聞かせいただければ、詳しくご案内いたします。お気軽にお問い合わせください😊"""
    
    def _emergency_response(self) -> str:
        """緊急時応答"""
        return """申し訳ございません。一時的にシステムの不具合が発生しております。

しばらくしてから再度お試しいただくか、下記までお電話でお問い合わせください。

📞 **お電話でのお問い合わせ**
営業時間：9:00-18:00（水曜定休）

ご不便をおかけして申し訳ございません。"""
    
    def get_performance_stats(self) -> Dict:
        """パフォーマンス統計"""
        total = self.performance_stats["requests"]
        template_rate = (self.performance_stats["template_hits"] / total * 100) if total > 0 else 0
        
        return {
            "total_requests": total,
            "template_hit_rate": template_rate,
            "greeting_sent": self.performance_stats["greeting_sent"],
            "push_fallbacks_used": self.performance_stats["push_fallbacks"],
            "available_templates": len(self.line_templates)
        }

# ==============================================================================
# LINE Bot設定と初期化（reply失効対策付き・修正版）
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

# 初期化
LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET = get_line_credentials_safe()
line_bot_api = None
handler = None
ultra_responder = LineUltraFastResponder()

if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        normalized_token = normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)
        normalized_secret = normalize_line_token(LINE_CHANNEL_SECRET)
        
        if normalized_token and normalized_secret:
            configuration = Configuration(access_token=normalized_token)
            handler = WebhookHandler(normalized_secret)
            
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
            
            logger.info("✅ LINE Ultra Fast Bot initialized successfully")
        else:
            raise ValueError("Empty normalized credentials")
            
    except Exception as e:
        logger.error(f"❌ LINE Bot initialization failed: {e}")
        line_bot_api, handler = None, None

# ==============================================================================
# 安全送信関数（reply失効対策付き・修正版）
# ==============================================================================
def send_line_message_safe(reply_token: str, user_id: str, message: str) -> bool:
    """安全なLINE送信（reply失効時はPush APIにフォールバック・修正版）"""
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
                
            except ApiException as reply_error:  # 修正: LineBotApiError → ApiException
                # Reply失効時はPush APIにフォールバック
                if "Invalid reply token" in str(reply_error) or reply_error.status == 400:
                    logger.warning(f"⚠️ Reply token expired, using Push API fallback for user: {user_id}")
                    ultra_responder.performance_stats["push_fallbacks"] += 1
                    
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
                    logger.error(f"❌ Reply API error (not token expiry): {reply_error}")
                    return False
            except Exception as general_error:  # 追加: 一般的なエラーのキャッチ
                logger.error(f"❌ Reply API general error: {general_error}")
                # 一般エラーでもPush APIフォールバックを試行
                try:
                    messaging_api.push_message_with_http_info(
                        PushMessageRequest(
                            to=user_id,
                            messages=[TextMessage(text=message)]
                        )
                    )
                    logger.info(f"✅ Push message sent as general fallback: {len(message)} chars")
                    ultra_responder.performance_stats["push_fallbacks"] += 1
                    return True
                except Exception as push_error:
                    logger.error(f"❌ Push API general fallback failed: {push_error}")
                    return False
        
    except Exception as e:
        logger.error(f"❌ Line message sending failed: {e}")
        return False

# ==============================================================================
# Webhook エンドポイント
# ==============================================================================
@router.post("/webhook")
async def ultra_fast_webhook(request: Request, background_tasks: BackgroundTasks):
    """超高速Webhook（reply失効対策付き）"""
    logger.info("🚀 LINE Ultra Fast Webhook called")
    
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
        logger.error(f"💥 Ultra fast webhook error: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

# ==============================================================================
# イベントハンドラ（reply失効対策・AI相談対応付き）
# ==============================================================================
if LINE_SDK_AVAILABLE and handler:
    
    @handler.add(FollowEvent)
    def handle_follow_ultra_fast(event):
        """超高速フォローハンドラ（挨拶送信）"""
        start_time = time.time()
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            
            logger.info(f"👤 New follower (ultra fast): {user_id}")
            
            success = send_line_message_safe(reply_token, user_id, ultra_responder.greeting_message)
            if success:
                ultra_responder.performance_stats["greeting_sent"] += 1
            
            duration = (time.time() - start_time) * 1000
            logger.info(f"✅ Ultra fast greeting sent: {duration:.1f}ms, success: {success}")
            
        except Exception as e:
            logger.error(f"❌ Ultra fast follow error: {e}")
            logger.error(traceback.format_exc())
    
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_message_ultra_fast(event):
        """超高速メッセージハンドラ（AI相談対応・reply失効対策付き・修正版）"""
        start_time = time.time()
        
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            reply_token = event.reply_token
            
            logger.info(f"📱 LINE Ultra fast processing: '{message_text[:30]}...' from user: {user_id}")
            
            # 特別処理：AI相談ボタン押下の場合は必ず挨拶文を返す
            if "AI相談" in message_text or "ai相談" in message_text.lower():
                logger.info("🤖 AI相談 button detected - sending greeting")
                ai_greeting = ultra_responder.line_templates["AI相談"]
                success = send_line_message_safe(reply_token, user_id, ai_greeting)
            else:
                # 通常の超高速応答生成
                response_text = ultra_responder.process_ultra_fast(message_text, user_id)
                success = send_line_message_safe(reply_token, user_id, response_text)
            
            duration = (time.time() - start_time) * 1000
            if success:
                logger.info(f"✅ LINE Ultra fast response: {duration:.1f}ms")
            else:
                logger.error(f"❌ LINE response failed after {duration:.1f}ms")
            
        except Exception as e:
            logger.error(f"❌ Ultra fast message error: {e}")
            logger.error(traceback.format_exc())
            try:
                emergency = ultra_responder._emergency_response()
                send_line_message_safe(event.reply_token, event.source.user_id, emergency)
            except Exception as final_error:
                logger.error(f"❌ Emergency response failed: {final_error}")

    @handler.add(PostbackEvent)
    def handle_postback_ultra_fast(event):
        """Postbackハンドラ（修正版）"""
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
                
                # アクションに対応する応答
                response_text = ultra_responder.line_templates.get(action_value, "ご利用ありがとうございます。")
            else:
                response_text = "メニューからお選びください。"
            
            success = send_line_message_safe(reply_token, user_id, response_text)
            logger.info(f"✅ Postback processed successfully: success={success}")
            
        except Exception as e:
            logger.error(f"💥 Postback handler error: {e}")
            logger.error(traceback.format_exc())

# ==============================================================================
# 監視・デバッグエンドポイント
# ==============================================================================
@router.get("/performance")
def get_line_performance():
    """LINE専用パフォーマンス統計"""
    stats = ultra_responder.get_performance_stats()
    
    return {
        "line_ultra_fast_stats": stats,
        "system_info": {
            "line_sdk_available": LINE_SDK_AVAILABLE,
            "line_bot_configured": line_bot_api is not None,
            "reply_fallback_enabled": True,
            "push_api_enabled": True,
            "ai_consultation_optimized": True,
            "api_exception_fixed": True,  # 追加
            "import_error_fixed": True,  # 追加
        },
        "performance_targets": {
            "response_time": "< 200ms",
            "template_hit_rate": "> 80%",
            "reply_success_rate": "> 95%"
        },
        "features": [
            "Reply Token Expiry Protection",
            "Push API Automatic Fallback", 
            "AI相談 Button Optimized",
            "LINE-Specific Template Responses",
            "Ultra Fast Processing",
            "補助金テンプレート追加",  # 追加
            "ApiException Error Handling",  # 追加
        ],
        "fixes_applied": [  # 追加
            "LineBotApiError → ApiException 修正",
            "インポートエラー解決",
            "送信エラー処理改善",
            "補助金テンプレート追加"
        ],
        "timestamp": datetime.now().isoformat()
    }

@router.get("/debug")
def line_debug_info():
    """LINE Bot デバッグ情報（修正版）"""
    return {
        "line_sdk_available": LINE_SDK_AVAILABLE,
        "line_bot_api_initialized": line_bot_api is not None,
        "handler_initialized": handler is not None,
        "credentials_set": {
            "access_token_set": bool(LINE_CHANNEL_ACCESS_TOKEN),
            "channel_secret_set": bool(LINE_CHANNEL_SECRET)
        },
        "normalized_token_length": len(normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)) if LINE_CHANNEL_ACCESS_TOKEN else 0,
        "api_exception_handling": "Fixed - using ApiException instead of LineBotApiError",
        "import_status": "✅ All imports successful" if LINE_SDK_AVAILABLE else "❌ SDK import failed",
        "fixes_applied": [
            "ApiException import fixed",
            "LineBotApiError references removed", 
            "Error handling improved",
            "Push API fallback enhanced"
        ],
        "timestamp": datetime.now().isoformat()
    }

@router.post("/clear-cache")
def clear_line_cache():
    """LINEキャッシュクリア"""
    ultra_responder.performance_stats = {"requests": 0, "template_hits": 0, "greeting_sent": 0, "push_fallbacks": 0}
    
    return {
        "status": "line_cache_cleared",
        "features_reset": ["performance_stats"],
        "fixes_confirmed": [
            "ApiException handling active",
            "Import errors resolved",
            "Template responses updated"
        ],
        "timestamp": datetime.now().isoformat()
    }

@router.get("/templates")
def get_line_templates():
    """LINE専用テンプレート一覧"""
    return {
        "line_templates": list(ultra_responder.line_templates.keys()),
        "count": len(ultra_responder.line_templates),
        "ai_consultation_template": "AI相談" in ultra_responder.line_templates,
        "subsidy_template_added": "補助金" in ultra_responder.line_templates,  # 追加
        "greeting_configured": bool(ultra_responder.greeting_message),
        "platform": "line_optimized",
        "fixes_applied": [
            "補助金テンプレート追加",
            "ApiException エラー処理修正"
        ],
        "timestamp": datetime.now().isoformat()
    }