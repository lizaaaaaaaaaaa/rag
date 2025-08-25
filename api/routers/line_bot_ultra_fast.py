# api/routers/line_bot_ultra_fast.py
# スマートルーティング統合版（複数応答問題解決版）
# 単一ハンドラ内でテンプレート応答・RAG処理を振り分け

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
import concurrent.futures

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

router = APIRouter(tags=["line-smart-integrated"])

# ==============================================================================
# LINE統合スマートルーティングシステム
# ==============================================================================
class LineSmartRouter:
    """LINE専用スマートルーティングシステム（統合版）"""
    
    def __init__(self):
        self.routing_stats = {
            "template_responses": 0,
            "rag_responses": 0,
            "fallback_responses": 0,
            "total_requests": 0,
            "processing_times": []
        }
        
        # テンプレート即座応答キーワード（最優先）
        self.template_keywords = {
            # リッチメニュー項目（完全一致）
            "ai相談": "AI相談",
            "🤖ai相談": "AI相談", 
            "ai住まいサイト": "AI住まいサイト",
            "🌐ai住まいサイト": "AI住まいサイト",
            "資料請求": "資料請求",
            "📋資料請求": "資料請求",
            "展示場来場予約": "展示場来場予約",
            "📍展示場来場予約": "展示場来場予約",
            "資金計画": "資金計画",
            "💰資金計画": "資金計画",
            "チャット相談": "チャット相談",
            "💬チャット相談": "チャット相談",
            
            # 挨拶・基本応答
            "こんにちは": "挨拶",
            "はじめまして": "挨拶",
            "よろしく": "挨拶",
            "ありがとう": "お礼",
            "助かり": "お礼"
        }
        
        # RAG処理が必要なキーワード（専門知識）
        self.rag_keywords = [
            "坪単価", "価格", "費用", "金額", "コスト", "値段", "見積り", "料金",
            "仕様", "標準", "設備", "グレード", "オプション", "何が含ま", "含まれる",
            "断熱", "性能", "省エネ", "ZEH", "UA値", "C値", "気密", "光熱費",
            "耐震", "地震", "安全", "構造", "基礎", "工法", "強度", "震災",
            "補助金", "助成金", "支援金", "制度", "控除", "減税", "支援制度",
            "間取り", "プラン", "設計", "レイアウト", "配置", "部屋数",
            "土地", "敷地", "分譲", "宅地", "建築地", "土地探し",
            "建ぺい率", "容積率", "法規", "規制", "基準", "建築基準法",
            "ローン", "融資", "金利", "審査", "借入", "返済", "資金繰り"
        ]
        
        # テンプレートを読み込み
        self.templates = self._load_templates()
        
    def _load_templates(self) -> Dict[str, str]:
        """統合テンプレート読み込み"""
        return {
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
お気軽にお声かけください！""",

            "挨拶": """こんにちは！キノエデザインです✨

住まいづくりのことでしたら何でもお気軽にご相談ください😊

**🎯 人気のご相談内容**
💰 坪単価・価格について
🏠 住宅性能・仕様について  
📋 資料請求・展示場見学
💴 資金計画・住宅ローン

どのようなことを知りたいですか？""",

            "お礼": """どういたしまして😊

他にもご質問がございましたら、お気軽にお聞かせください。

**📞 より詳しい相談をご希望の場合**
・「展示場予約」→専門スタッフが直接対応
・「資料請求」→詳細資料をお送りします

住まいづくりを全力でサポートいたします✨"""
        }
    
    def determine_response_route(self, message_text: str) -> Dict[str, Any]:
        """メッセージに基づく応答ルート決定"""
        start_time = time.time()
        self.routing_stats["total_requests"] += 1
        
        message_lower = message_text.lower().replace(" ", "").replace("　", "")
        
        # 1. テンプレート応答チェック（最優先・最高速）
        for keyword, template_key in self.template_keywords.items():
            if keyword in message_lower or keyword == message_lower:
                self.routing_stats["template_responses"] += 1
                processing_time = time.time() - start_time
                self.routing_stats["processing_times"].append(processing_time)
                
                return {
                    "route": "template",
                    "template_key": template_key,
                    "response": self.templates.get(template_key, ""),
                    "processing_time": processing_time,
                    "reason": f"Template match: {keyword}"
                }
        
        # 2. RAG処理が必要なキーワードチェック
        rag_matched = []
        for keyword in self.rag_keywords:
            if keyword in message_text:
                rag_matched.append(keyword)
        
        if rag_matched:
            self.routing_stats["rag_responses"] += 1
            processing_time = time.time() - start_time
            self.routing_stats["processing_times"].append(processing_time)
            
            return {
                "route": "rag",
                "rag_keywords": rag_matched,
                "processing_time": processing_time,
                "reason": f"RAG keywords matched: {', '.join(rag_matched[:3])}"
            }
        
        # 3. 質問の複雑さと長さで判定
        question_indicators = ["？", "?", "教えて", "知りたい", "どう", "なぜ", "どこ", "いつ", "いくら"]
        is_question = any(indicator in message_text for indicator in question_indicators)
        
        if is_question and len(message_text) > 15:
            self.routing_stats["rag_responses"] += 1
            processing_time = time.time() - start_time
            self.routing_stats["processing_times"].append(processing_time)
            
            return {
                "route": "rag",
                "rag_keywords": ["complex_question"],
                "processing_time": processing_time,
                "reason": f"Complex question detected (length: {len(message_text)})"
            }
        
        # 4. フォールバック（基本応答）
        self.routing_stats["fallback_responses"] += 1
        processing_time = time.time() - start_time
        self.routing_stats["processing_times"].append(processing_time)
        
        return {
            "route": "fallback",
            "processing_time": processing_time,
            "reason": "No specific pattern matched"
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """統計情報取得"""
        total = self.routing_stats["total_requests"]
        avg_processing_time = sum(self.routing_stats["processing_times"]) / len(self.routing_stats["processing_times"]) if self.routing_stats["processing_times"] else 0
        
        return {
            "total_requests": total,
            "template_responses": self.routing_stats["template_responses"],
            "rag_responses": self.routing_stats["rag_responses"],
            "fallback_responses": self.routing_stats["fallback_responses"],
            "template_rate": (self.routing_stats["template_responses"] / total * 100) if total > 0 else 0,
            "rag_rate": (self.routing_stats["rag_responses"] / total * 100) if total > 0 else 0,
            "fallback_rate": (self.routing_stats["fallback_responses"] / total * 100) if total > 0 else 0,
            "avg_processing_time_ms": avg_processing_time * 1000,
            "duplicate_prevention": True,
            "single_handler": True
        }

# ==============================================================================
# RAG処理統合クラス
# ==============================================================================
class LineRAGIntegration:
    """LINE用RAG処理統合"""
    
    def __init__(self):
        self.rag_cache = {}
        self.rag_available = False
        self._initialize_rag()
    
    def _initialize_rag(self):
        """RAGシステム初期化"""
        try:
            from main import vectorstore, rag_chain_template, llm_instance, is_initialized
            if is_initialized and rag_chain_template:
                self.rag_available = True
                logger.info("✅ RAG integration initialized for LINE")
            else:
                logger.info("ℹ️ RAG not initialized, will use fallback")
        except Exception as e:
            logger.warning(f"⚠️ RAG integration failed: {e}")
    
    async def process_rag_query(self, query: str, user_id: str) -> str:
        """RAG処理実行"""
        if not self.rag_available:
            return self._generate_rag_fallback(query)
        
        # キャッシュチェック
        cache_key = hashlib.md5(f"{query}::{user_id}".encode()).hexdigest()
        if cache_key in self.rag_cache:
            cached_result = self.rag_cache[cache_key]
            if time.time() - cached_result["timestamp"] < 3600:  # 1時間キャッシュ
                logger.info(f"🎯 RAG cache hit for: {query[:30]}...")
                return cached_result["answer"]
        
        try:
            # メインアプリのRAGチェーンを使用
            from main import rag_chain_template
            if rag_chain_template:
                # タイムアウト付きRAG処理
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(self._execute_rag, query, rag_chain_template)
                    try:
                        result = future.result(timeout=8)  # 8秒タイムアウト
                        if result and len(result.strip()) > 10:
                            # キャッシュ保存
                            self.rag_cache[cache_key] = {
                                "answer": result,
                                "timestamp": time.time()
                            }
                            return self._ensure_line_format(result)
                    except concurrent.futures.TimeoutError:
                        logger.warning("⚠️ RAG processing timeout")
            
            return self._generate_rag_fallback(query)
            
        except Exception as e:
            logger.error(f"❌ RAG processing error: {e}")
            return self._generate_rag_fallback(query)
    
    def _execute_rag(self, query: str, rag_chain):
        """RAG実行（同期処理）"""
        result = rag_chain.invoke({"query": query})
        return result.get("result", "")
    
    def _ensure_line_format(self, text: str) -> str:
        """LINE用フォーマット調整"""
        if not text.endswith(('。', '！', '？', '.', '!', '?')):
            text += '。'
        
        # LINE用に長すぎる場合は短縮
        if len(text) > 1500:
            text = text[:1400] + "...\n\n詳しくはお問い合わせください😊"
        
        return text
    
    def _generate_rag_fallback(self, query: str) -> str:
        """RAG処理失敗時のフォールバック"""
        query_lower = query.lower()
        
        if any(keyword in query_lower for keyword in ["坪単価", "価格", "費用", "金額"]):
            return """💰 坪単価についてご案内いたします

🏠 **当社の坪単価目安**
・標準仕様：約70～85万円/坪
・高性能仕様：約85～100万円/坪

✨ **含まれる内容**
・耐震等級3の構造
・長期優良住宅対応
・高断熱・高気密仕様
・標準設備一式

詳細なお見積りは「展示場予約」でご相談ください😊"""
        
        elif any(keyword in query_lower for keyword in ["断熱", "性能", "省エネ"]):
            return """🌡️ 断熱性能についてご案内いたします

**断熱等級**
・断熱等級4以上（ZEH基準対応）
・UA値：0.6以下
・C値：1.0以下（高気密）

**快適性**
・夏涼しく、冬暖かい
・光熱費の削減効果
・一年中快適な室温

詳しくは展示場で体感してください✨
「展示場予約」でお申し込みいただけます！"""
        
        elif any(keyword in query_lower for keyword in ["耐震", "地震", "安全"]):
            return """🏗️ 耐震性能についてご案内いたします

**耐震等級**
・耐震等級3（最高等級）を標準採用
・建築基準法の1.5倍の強度
・許容応力度計算による構造計算

**保証**
・構造躯体20年保証
・地盤保証20年
・瑕疵担保責任保険対応

安心・安全な住まいをお約束します✨"""
        
        else:
            return """ご質問ありがとうございます😊

より詳しい情報をお答えするため、専門スタッフがご対応いたします。

**📞 すぐに相談したい場合**
「展示場予約」で直接ご相談いただけます

**📄 詳しい資料が欲しい場合**  
「資料請求」で専門資料をお送りします

どちらがよろしいでしょうか？"""

# ==============================================================================
# LINE Bot設定と初期化
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

# グローバルインスタンス
smart_router = LineSmartRouter()
rag_integration = LineRAGIntegration()

if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        normalized_token = normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)
        normalized_secret = normalize_line_token(LINE_CHANNEL_SECRET)
        
        if normalized_token and normalized_secret:
            configuration = Configuration(access_token=normalized_token)
            handler = WebhookHandler(normalized_secret)
            
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
            
            logger.info("✅ LINE Smart Integrated Bot initialized successfully")
        else:
            raise ValueError("Empty normalized credentials")
            
    except Exception as e:
        logger.error(f"❌ LINE Bot initialization failed: {e}")
        line_bot_api, handler = None, None

# ==============================================================================
# 安全送信関数（reply失効対策付き）
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
                logger.info(f"✅ Single reply sent: {len(message)} chars")
                return True
                
            except ApiException as reply_error:
                # Reply失効時はPush APIにフォールバック
                if "Invalid reply token" in str(reply_error) or getattr(reply_error, "status", None) == 400:
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
async def smart_integrated_webhook(request: Request, background_tasks: BackgroundTasks):
    """スマート統合Webhook（単一ハンドラ・複数応答防止）"""
    logger.info("🚀 LINE Smart Integrated Webhook called")
    
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
        logger.info(f"📨 Single webhook processing: {body_text[:200]}...")
        
        handler.handle(body_text, signature)
        
        logger.info("✅ Single webhook processed successfully")
        return {"status": "ok", "timestamp": datetime.now().isoformat()}
        
    except InvalidSignatureError as sig_error:
        logger.error(f"❌ Invalid signature: {sig_error}")
        return {"status": "signature_error"}
    except Exception as e:
        logger.error(f"💥 Smart integrated webhook error: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "error": str(e)}

# ==============================================================================
# イベントハンドラ（スマートルーティング統合版）
# ==============================================================================
if LINE_SDK_AVAILABLE and handler:
    
    @handler.add(FollowEvent)
    def handle_follow_smart_integrated(event):
        """フォローハンドラ（統合版）"""
        start_time = time.time()
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            
            logger.info(f"👤 New follower (smart integrated): {user_id}")
            
            greeting_message = """こんにちは！キノエデザインです✨
この度は友だち追加ありがとうございます。

**🎯 目的のボタンをタップ👇**
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画 / 🌐サイト / 💬チャット

**⚡ 応答について**
・AIは24時間対応
・スタッフは営業日に対応
・営業時間：9:00-18:00

**🔒 プライバシー**
取扱い：https://preview.studio.site/live/EjOQljz1WJ/privacy-policy

住まいのことなら何でもお気軽にご相談ください😊"""
            
            success = send_line_message_safe(reply_token, user_id, greeting_message)
            
            duration = (time.time() - start_time) * 1000
            logger.info(f"✅ Single greeting sent: {duration:.1f}ms, success: {success}")
            
        except Exception as e:
            logger.error(f"❌ Smart follow error: {e}")
            logger.error(traceback.format_exc())
    
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_message_smart_integrated(event):
        """メッセージハンドラ（スマートルーティング統合版・単一応答保証）"""
        start_time = time.time()
        
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            reply_token = event.reply_token
            
            logger.info(f"📱 Smart processing (SINGLE): '{message_text[:30]}...' from user: {user_id}")
            
            # スマートルーティング実行
            routing_result = smart_router.determine_response_route(message_text)
            route = routing_result["route"]
            
            logger.info(f"🧠 Route selected: {route} - {routing_result['reason']}")
            
            # ルート別処理（単一ハンドラ内で完結）
            if route == "template":
                # テンプレート即座応答
                response_text = routing_result["response"]
                success = send_line_message_safe(reply_token, user_id, response_text)
                
                duration = (time.time() - start_time) * 1000
                logger.info(f"⚡ Template response: {duration:.1f}ms, success: {success}")
                
            elif route == "rag":
                # RAG処理（非同期実行）
                def process_rag():
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        result = loop.run_until_complete(
                            rag_integration.process_rag_query(message_text, user_id)
                        )
                        loop.close()
                        return result
                    except Exception as e:
                        logger.error(f"RAG processing error: {e}")
                        return smart_router.templates.get("挨拶", "申し訳ございません。")
                
                # タイムアウト付きRAG実行
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(process_rag)
                    try:
                        response_text = future.result(timeout=10)  # 10秒タイムアウト
                    except concurrent.futures.TimeoutError:
                        logger.error("❌ RAG processing timeout")
                        response_text = """処理に時間がかかっています。

もう一度お試しいただくか、「展示場予約」で直接ご相談ください😊"""
                
                success = send_line_message_safe(reply_token, user_id, response_text)
                
                duration = (time.time() - start_time) * 1000
                logger.info(f"🤖 RAG response: {duration:.1f}ms, success: {success}")
                
            else:
                # フォールバック応答
                response_text = smart_router.templates.get("挨拶", """ご質問ありがとうございます😊

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

メニューからお選びいただくか、具体的にお聞かせください✨""")
                
                success = send_line_message_safe(reply_token, user_id, response_text)
                
                duration = (time.time() - start_time) * 1000
                logger.info(f"🔄 Fallback response: {duration:.1f}ms, success: {success}")
            
            # 統計更新
            total_duration = (time.time() - start_time) * 1000
            logger.info(f"✅ SINGLE message processed: {total_duration:.1f}ms, route: {route}")
            
        except Exception as e:
            logger.error(f"❌ Smart message handler error: {e}")
            logger.error(traceback.format_exc())
            try:
                emergency = """申し訳ございません。一時的にシステムの不具合が発生しています。

しばらくしてから再度お試しください😊"""
                send_line_message_safe(event.reply_token, event.source.user_id, emergency)
                logger.info("🆘 Emergency response sent")
            except Exception as final_error:
                logger.error(f"❌ Emergency response failed: {final_error}")

    @handler.add(PostbackEvent)
    def handle_postback_smart_integrated(event):
        """Postbackハンドラ（統合版）"""
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            postback_data = event.postback.data or ""
            
            logger.info(f"🔙 Single postback from {user_id}: {postback_data}")
            
            # Postbackデータの解析
            if "action=" in postback_data:
                action_value = ""
                for part in postback_data.split("&"):
                    if part.startswith("action="):
                        action_value = part.split("=", 1)[1]
                        break
                
                response_text = smart_router.templates.get(action_value, "ご利用ありがとうございます。")
            else:
                response_text = "メニューからお選びください。"
            
            success = send_line_message_safe(reply_token, user_id, response_text)
            logger.info(f"✅ Single postback processed: success={success}")
            
        except Exception as e:
            logger.error(f"💥 Postback handler error: {e}")
            logger.error(traceback.format_exc())

# ==============================================================================
# 監視・デバッグエンドポイント
# ==============================================================================
@router.get("/performance")
def get_smart_performance():
    """スマート統合パフォーマンス統計"""
    stats = smart_router.get_stats()
    
    return {
        "line_smart_integrated_stats": stats,
        "system_info": {
            "line_sdk_available": LINE_SDK_AVAILABLE,
            "line_bot_configured": line_bot_api is not None,
            "rag_integration_available": rag_integration.rag_available,
            "single_handler": True,
            "duplicate_prevention": True
        },
        "features": [
            "Single Handler Processing (No Duplicates)",
            "Smart Route Selection (Template/RAG/Fallback)",
            "Template Instant Response (< 200ms)",
            "RAG Integration with Timeout",
            "Reply Token Expiry Protection",
            "Push API Automatic Fallback",
            "LINE-Specific Response Formatting",
            "Response Caching"
        ],
        "performance_targets": {
            "template_response_time": "< 200ms",
            "rag_response_time": "< 10s",
            "duplicate_messages": "0 (prevented)",
            "success_rate": "> 99%"
        },
        "routing_efficiency": {
            "template_rate": f"{stats['template_rate']:.1f}%",
            "rag_rate": f"{stats['rag_rate']:.1f}%", 
            "fallback_rate": f"{stats['fallback_rate']:.1f}%"
        },
        "timestamp": datetime.now().isoformat()
    }

@router.get("/debug")
def smart_debug_info():
    """スマート統合デバッグ情報"""
    return {
        "line_sdk_available": LINE_SDK_AVAILABLE,
        "line_bot_api_initialized": line_bot_api is not None,
        "handler_initialized": handler is not None,
        "smart_router": {
            "available_templates": len(smart_router.templates),
            "template_keywords": len(smart_router.template_keywords),
            "rag_keywords": len(smart_router.rag_keywords),
            "single_handler": True,
            "duplicate_prevention": True
        },
        "rag_integration": {
            "available": rag_integration.rag_available,
            "cache_entries": len(rag_integration.rag_cache)
        },
        "credentials_set": {
            "access_token_set": bool(LINE_CHANNEL_ACCESS_TOKEN),
            "channel_secret_set": bool(LINE_CHANNEL_SECRET)
        },
        "fixes_applied": [
            "Single webhook handler (no duplicates)",
            "Smart routing integration",
            "RAG processing with timeout",
            "Template instant response",
            "Reply token expiry handling",
            "Error recovery with fallback"
        ],
        "timestamp": datetime.now().isoformat()
    }

@router.post("/clear-cache")
def clear_smart_cache():
    """スマート統合キャッシュクリア"""
    old_stats = smart_router.get_stats()
    old_rag_cache = len(rag_integration.rag_cache)
    
    # 統計リセット
    smart_router.routing_stats = {
        "template_responses": 0,
        "rag_responses": 0,
        "fallback_responses": 0,
        "total_requests": 0,
        "processing_times": []
    }
    
    # RAGキャッシュクリア
    rag_integration.rag_cache = {}
    
    return {
        "status": "smart_integrated_cache_cleared",
        "previous_stats": old_stats,
        "previous_rag_cache_size": old_rag_cache,
        "features_reset": ["routing_stats", "rag_cache"],
        "single_handler_maintained": True,
        "duplicate_prevention_active": True,
        "timestamp": datetime.now().isoformat()
    }

@router.get("/health")
def smart_health_check():
    """スマート統合ヘルスチェック"""
    stats = smart_router.get_stats()
    
    health_status = {
        "status": "healthy" if LINE_SDK_AVAILABLE and line_bot_api else "degraded",
        "components": {
            "line_sdk": "ok" if LINE_SDK_AVAILABLE else "error",
            "line_bot_api": "ok" if line_bot_api else "error",
            "handler": "ok" if handler else "error",
            "smart_router": "ok",
            "rag_integration": "ok" if rag_integration.rag_available else "available_fallback",
            "credentials": "ok" if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET else "error"
        },
        "metrics": stats,
        "single_handler": True,
        "duplicate_prevention": True,
        "timestamp": datetime.now().isoformat()
    }
    
    return health_status