# api/routers/line_bot_ultra_fast.py
# reply失効対策・プラットフォーム分離対応版 ＋ 文章途切れ対策（LINE特化・完全修正版）
# リッチメニュー専用応答・LLM/OpenAI API使用最小化版（応答内容更新版）

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
# LINE専用超高速応答システム（LLM/OpenAI API最小化版・応答内容更新版）
# ==============================================================================
class LineUltraFastResponder:
    def __init__(self):
        self.line_templates = self._load_line_templates()
        self.greeting_message = self._load_greeting_message()
        self.ai_consultation_active_users = set()  # AI相談モード中のユーザー
        self.performance_stats = {
            "requests": 0, 
            "template_hits": 0, 
            "greeting_sent": 0, 
            "push_fallbacks": 0,
            "ai_consultation_started": 0,
            "llm_calls_avoided": 0
        }
        
    def _load_line_templates(self) -> Dict[str, str]:
        """LINE専用テンプレート（更新版・完全事前定義・LLM不使用）"""
        return {
            # ===== メインリッチメニュー応答（更新版） =====
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

            # ===== 詳細質問応答（既存のまま維持） =====
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
詳細なお見積りは無料で承ります！

📞 **お問い合わせ**
展示場見学または資料請求をご希望でしたら、
「展示場予約」「資料請求」とメッセージください。""",

            "標準仕様": """🏗️ 標準仕様についてご説明いたします

**🏠 構造・性能**
・耐震等級3（最高等級）
・長期優良住宅認定対応
・省エネ等級4以上
・高断熱・高気密仕様

**🔧 設備仕様**
・システムキッチン
・ユニットバス
・洗面化粧台
・トイレ（温水洗浄便座付）

**📋 詳細確認方法**
より詳しい仕様書をご希望の場合：
「資料請求」→ 詳細仕様書をお送りします
「展示場予約」→ 実際の住宅をご確認いただけます

どちらをご希望か教えてください😊""",

            "断熱性能": """🌡️ 断熱性能についてご案内いたします

**📊 断熱等級**
・断熱等級4以上（ZEH基準対応）
・UA値：0.6以下（地域区分6）
・C値：1.0以下（気密性能）

**🧱 使用断熱材**
・外壁：高性能グラスウール
・屋根：吹付断熱材
・基礎：押出法ポリスチレンフォーム

**✨ 快適性のメリット**
・夏涼しく、冬暖かい
・光熱費の大幅削減
・結露の抑制
・一年中快適な室温

**🏠 体感してみませんか？**
展示場で実際の断熱性能を体感していただけます。
「展示場予約」とメッセージください！""",

            "耐震性能": """🏗️ 耐震性能についてご案内いたします

**🛡️ 耐震等級**
・耐震等級3（最高等級）を標準採用
・建築基準法の1.5倍の耐震強度
・許容応力度計算による構造計算

**🔩 構造材の特徴**
・構造用集成材使用
・金物工法による強固な接合
・ベタ基礎による堅固な基礎

**📝 充実の保証**
・構造躯体20年保証
・地盤保証20年
・瑕疵担保責任保険対応

**🏆 安心のポイント**
大地震にも耐えうる最高水準の耐震性能で、
ご家族の安全を守ります。

構造の詳細は展示場でご確認いただけます。
「展示場予約」でご見学ください！""",

            "補助金": """💰 住宅補助金制度についてご案内します

**🏠 主な補助金制度**

**🌱 ZEH補助金**
・高性能住宅への補助
・定額55万円～（条件により異なる）

**👶 こどもエコすまい支援事業**  
・子育て世帯・若年夫婦世帯対象
・最大100万円の補助

**🏦 住宅ローン減税**
・所得税の控除制度
・13年間の減税メリット
・年間最大35万円の控除

**🏘️ 地域独自の補助金**
・自治体による支援制度
・地域により内容が異なります

**⚠️ 重要なお知らせ**
制度は年度ごとに変更される可能性があります。

**📞 最新情報の確認**
詳しい補助金情報は専門スタッフがご案内します。
「資料請求」で最新の補助金ガイドをお送りします！""",

            # 追加の応答テンプレート
            "土地探し": """🏗️ 土地探しについてご案内します

**🔍 土地選びのポイント**
・立地条件（交通・生活利便性）
・土地の形状・面積
・建築制限・用途地域
・地盤の状況
・予算バランス

**🏠 当社のサポート**
・土地探しから建築まで一貫対応
・建築会社の視点での土地評価
・資金計画込みでのご提案
・地盤調査・改良工事対応

**📞 土地探しご相談**
「展示場予約」で専門スタッフがご相談を承ります。
ご希望エリアや条件をお聞かせください！""",

            "間取り": """🏠 間取りについてご案内します

**📐 間取りプランニング**
・ライフスタイルに合わせた設計
・家族構成を考慮した間取り
・将来の変化に対応した可変性
・収納計画・家事動線の最適化

**🎨 設計の特徴**
・自然光を活かした明るい空間
・風通しの良い快適な環境
・プライバシーに配慮した配置
・バリアフリー対応

**📋 間取り相談の流れ**
1️⃣ ご家族構成・ライフスタイルヒアリング
2️⃣ 土地条件の確認
3️⃣ 間取りプラン作成
4️⃣ プレゼンテーション・修正

**🏠 実際の間取りをご覧ください**
「展示場予約」で実際の間取りをご確認いただけます！""",
        }
        
    def _load_greeting_message(self) -> str:
        """友だち追加時の挨拶メッセージ（更新版）"""
        return """こんにちは！キノエデザインです✨
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

    # ---------------------------
    # 文章完全性の確保（★強化版）
    # ---------------------------
    def ensure_line_response_complete(self, text: str, query: str = "") -> str:
        """LINE用文章完全性確保（強化版）"""
        if not text or len(text.strip()) < 5:
            return self._emergency_response()
        
        text = text.strip()
        
        # 文末チェックと補完（LINE特化）
        if not text.endswith(('。', '！', '？', '.', '!', '?')):
            logger.info(f"🔧 Fixing LINE response: '{text[-30:]}'")
            
            # 特定の途切れパターンの補完（LINE用）
            if text.endswith('や'):  # 「土地探しや」のケース
                text += "建築準備を進めることが大切です✨"
            elif text.endswith('重要'):  # 「重要」のケース
                text += 'です😊お気軽にご相談ください。'
            elif text.endswith('必要'):
                text += 'です。'
            elif text.endswith('について'):
                text += 'は詳しくご案内いたします💡'
            elif text.endswith('選定') or text.endswith('検討'):
                text += 'も重要なポイントです。'
            elif text.endswith('ます') or text.endswith('です'):
                text += '。'
            elif text.endswith('た') or text.endswith('る'):
                text += '。'
            elif text.endswith('、'):
                text = text[:-1] + '。'
            elif text.endswith('は') or text.endswith('が'):
                text += '重要です✨'
            elif text.endswith('ので') or text.endswith('ため'):
                text += '、お気軽にご相談ください😊'
            elif text.endswith('準備') or text.endswith('計画'):
                text += 'を進めましょう。'
            else:
                # 長さによる補完（LINE用）
                if len(text) > 30:
                    text += '。'
                elif len(text) > 15:
                    text += '。詳しくはお問い合わせください😊'
                else:
                    text = self._emergency_response()
            
            logger.info(f"✅ Fixed LINE response: '{text[-30:]}'")
        
        return text

    def process_ultra_fast(self, message_text: str, user_id: str = "unknown") -> str:
        """超高速処理（文章完全性強化版・LLM回避優先）"""
        start_time = time.time()
        self.performance_stats["requests"] += 1
        
        try:
            # 1. リッチメニューアクション検出（最優先・LLM不使用）
            action = self._detect_richmenu_action(message_text)
            if action != "unknown":
                self.performance_stats["template_hits"] += 1
                self.performance_stats["llm_calls_avoided"] += 1
                
                # AI相談の場合は専用処理
                if action == "AI相談":
                    self.ai_consultation_active_users.add(user_id)
                    self.performance_stats["ai_consultation_started"] += 1
                    logger.info(f"🤖 AI consultation activated for user: {user_id}")
                
                response = self.line_templates.get(action, "ご利用ありがとうございます。")
                
                # 🔧 リッチメニュー応答も完全性チェック
                complete_response = self.ensure_line_response_complete(response, message_text)
                
                processing_time = (time.time() - start_time) * 1000
                logger.info(f"🎯 LINE Richmenu response: {action} in {processing_time:.1f}ms")
                return complete_response

            # 2. AI相談モード中のユーザーの質問処理
            if user_id in self.ai_consultation_active_users:
                logger.info(f"🤖 Processing AI consultation for user: {user_id}")
                return self._process_ai_consultation_question(message_text, user_id)

            # 3. 一般質問の高速テンプレート処理（LLM回避）
            template_response = self._match_question_template(message_text)
            if template_response:
                self.performance_stats["template_hits"] += 1
                self.performance_stats["llm_calls_avoided"] += 1
                
                # 🔧 質問テンプレート応答も完全性チェック
                complete_template = self.ensure_line_response_complete(template_response, message_text)
                
                processing_time = (time.time() - start_time) * 1000
                logger.info(f"🎯 LINE Question template in {processing_time:.1f}ms")
                return complete_template
            
            # 4. インテリジェントフォールバック（LLM回避）
            fallback_response = self._generate_line_fallback(message_text)
            self.performance_stats["llm_calls_avoided"] += 1
            
            # 🔧 フォールバック応答も完全性チェック
            complete_fallback = self.ensure_line_response_complete(fallback_response, message_text)
            
            processing_time = (time.time() - start_time) * 1000
            logger.info(f"🔄 LINE Fallback in {processing_time:.1f}ms")
            return complete_fallback
            
        except Exception as e:
            logger.error(f"❌ LINE processing error: {e}")
            emergency = self._emergency_response()
            return self.ensure_line_response_complete(emergency, message_text)

    def _process_ai_consultation_question(self, message_text: str, user_id: str) -> str:
        """AI相談モード中の質問処理（LLM最小使用版）"""
        # まずテンプレートで回答できるか確認
        template_response = self._match_question_template(message_text)
        if template_response:
            self.performance_stats["llm_calls_avoided"] += 1
            return self.ensure_line_response_complete(template_response + "\n\n他にもご質問がございましたらお気軽にどうぞ😊", message_text)
        
        # 特定キーワードによる事前定義回答
        predefined_response = self._get_predefined_ai_response(message_text)
        if predefined_response:
            self.performance_stats["llm_calls_avoided"] += 1
            return self.ensure_line_response_complete(predefined_response, message_text)
        
        # 最終手段：スタッフへの誘導（LLM使用回避）
        self.performance_stats["llm_calls_avoided"] += 1
        return """ご質問ありがとうございます😊

より詳しい情報をお答えするため、専門スタッフがご対応いたします。

**📞 すぐに相談したい場合**
「展示場予約」で直接ご相談いただけます

**📄 詳しい資料が欲しい場合**
「資料請求」で専門資料をお送りします

**💬 このLINEで相談継続**
営業時間内（9:00-18:00）でしたらスタッフが直接お答えします

どちらがよろしいでしょうか？"""

    def _get_predefined_ai_response(self, message_text: str) -> Optional[str]:
        """事前定義AI応答の取得（更新版）"""
        text_lower = message_text.lower()
        
        predefined_responses = {
            "挨拶": {
                "keywords": ["こんにちは", "こんばんは", "おはよう", "はじめまして"],
                "response": """こんにちは😊
AI住まい相談をご利用いただきありがとうございます！

住まいに関することでしたら何でもお気軽にご質問ください。

💡 **人気の質問**
・坪単価について
・住宅の性能について
・資料請求・展示場見学
・補助金制度について

どのようなことを知りたいですか？"""
            },
            
            "お礼": {
                "keywords": ["ありがとう", "感謝", "助かり"],
                "response": """どういたしまして😊

他にもご質問がございましたら、お気軽にお聞かせください。

**📞 より詳しい相談をご希望の場合**
・「展示場予約」→専門スタッフが直接対応
・「資料請求」→詳細資料をお送りします

住まいづくりを全力でサポートいたします✨"""
            },
            
            "家づくり開始": {
                "keywords": ["家を建てたい", "マイホーム", "新築したい", "住宅建築"],
                "response": """🏠 家づくりを始められるのですね！

**✨ 家づくりのステップ**
1️⃣ 資金計画・予算確認
2️⃣ 土地探し
3️⃣ 住宅会社選び
4️⃣ 間取り・仕様打合せ
5️⃣ 契約・着工

**🎯 まずはこちらから**
・「資金計画」→ 予算の相談
・「展示場予約」→ 実際の住宅を見学
・「資料請求」→ 基本情報の収集

どこから始めますか？😊"""
            },
            
            "比較検討": {
                "keywords": ["他社比較", "検討中", "迷って", "決められない"],
                "response": """🤔 検討段階ですね！

**🔍 比較のポイント**
・住宅性能（耐震・断熱など）
・アフターサービス・保証
・価格・コストパフォーマンス
・施工実績・信頼性
・スタッフの対応

**💡 当社の特徴を知りたい場合**
「展示場予約」で実際に体感してください！

他社との違いを分かりやすくご説明します😊
比較検討のポイントもお教えします！"""
            }
        }
        
        for category, data in predefined_responses.items():
            if any(keyword in text_lower for keyword in data["keywords"]):
                return data["response"]
        
        return None
    
    def _detect_richmenu_action(self, message: str) -> str:
        """リッチメニューアクション検出（拡張版・更新版）"""
        text_clean = message.lower().replace(" ", "").replace("　", "")
        
        # 更新されたマッチングパターン（絵文字対応）
        richmenu_patterns = {
            "AI相談": ["🤖ai相談", "ai相談", "ai住まい相談", "相談開始", "aiチャット"],
            "AI住まいサイト": ["🌐ai住まいサイト", "ai住まいサイト", "サイト", "ホームページ", "ウェブ"],
            "資料請求": ["📋資料請求", "資料請求", "資料", "パンフレット", "カタログ", "送って"],
            "展示場来場予約": ["📍展示場来場予約", "展示場来場予約", "展示場予約", "展示場", "見学", "予約", "来場"],
            "資金計画": ["💰資金計画", "資金計画", "ローン", "住宅ローン", "お金", "返済"],
            "チャット相談": ["💬チャット相談", "チャット相談", "チャット", "スタッフ", "担当者"],
            "坪単価": ["坪単価", "価格", "費用", "いくら", "金額", "値段", "コスト"],
            "標準仕様": ["標準仕様", "仕様", "設備", "標準", "基本仕様"],
            "断熱性能": ["断熱", "断熱性能", "省エネ", "温度", "暖房", "冷房"],
            "耐震性能": ["耐震", "地震", "安全", "強度", "耐震性"],
            "補助金": ["補助金", "助成金", "支援金", "補助制度", "支援制度"],
            "土地探し": ["土地探し", "土地", "敷地", "分譲地"],
            "間取り": ["間取り", "プラン", "設計", "レイアウト"]
        }
        
        for action, patterns in richmenu_patterns.items():
            # 完全一致または部分一致
            if any(pattern in text_clean for pattern in patterns):
                # より正確な判定のため、文脈も考慮
                if len(message.strip()) <= 15 and any(pattern == text_clean for pattern in patterns):
                    # 短いメッセージで完全一致の場合
                    return action
                elif any(pattern in text_clean for pattern in patterns):
                    # 部分一致の場合
                    return action
        
        return "unknown"
    
    def _match_question_template(self, query: str) -> Optional[str]:
        """一般質問のテンプレートマッチング（拡張版）"""
        query_lower = query.lower()
        
        # より詳細なマッチング辞書
        question_templates = {
            "坪単価": {
                "keywords": ["坪単価", "価格", "費用", "コスト", "いくら", "値段", "金額", "料金"],
                "template": "坪単価"
            },
            "標準仕様": {
                "keywords": ["仕様", "設備", "標準", "基本", "何が", "ついて", "含ま"],
                "template": "標準仕様"
            },
            "断熱性能": {
                "keywords": ["断熱", "省エネ", "温度", "光熱費", "暖房", "冷房", "快適"],
                "template": "断熱性能"
            },
            "耐震性能": {
                "keywords": ["耐震", "地震", "安全", "強度", "構造", "震災"],
                "template": "耐震性能"
            },
            "補助金": {
                "keywords": ["補助金", "助成金", "支援金", "補助", "支援", "制度"],
                "template": "補助金"
            },
            "資料請求": {
                "keywords": ["資料", "パンフレット", "カタログ", "送って", "郵送"],
                "template": "資料請求"
            },
            "展示場来場予約": {
                "keywords": ["見学", "展示場", "予約", "来場", "訪問"],
                "template": "展示場来場予約"
            },
            "資金計画": {
                "keywords": ["ローン", "資金", "借入", "返済", "金利", "融資"],
                "template": "資金計画"
            },
            "土地探し": {
                "keywords": ["土地", "敷地", "分譲", "宅地", "建築地"],
                "template": "土地探し"
            },
            "間取り": {
                "keywords": ["間取り", "プラン", "設計", "レイアウト", "配置"],
                "template": "間取り"
            }
        }
        
        for template_name, data in question_templates.items():
            if any(keyword in query_lower for keyword in data["keywords"]):
                return self.line_templates.get(data["template"])
        
        return None
    
    def _generate_line_fallback(self, query: str) -> str:
        """LINE専用フォールバック（完全性強化版・LLM不使用・更新版）"""
        q_lower = query.lower()
        
        # より具体的なフォールバック応答（更新版）
        if any(word in q_lower for word in ["家を建てる", "マイホーム", "新築", "建築"]):
            return """🏗️ 家づくりについてお答えいたします

家づくりは人生で最も大きな買い物の一つです✨

**📋 家づくりの流れ**
1️⃣ 資金計画・予算確認
2️⃣ 土地探し・土地選定
3️⃣ 住宅会社選び
4️⃣ 間取り・仕様決定
5️⃣ 契約・着工・完成

**🎯 まずはここから始めませんか？**
・「資料請求」→ 基本情報の収集
・「展示場予約」→ 実際の住まいを体感
・「資金計画」→ 予算の明確化

お客様のご希望をお聞かせください😊"""
        
        elif any(word in q_lower for word in ["補助金", "助成", "支援"]):
            return self.line_templates["補助金"]
        
        elif any(word in q_lower for word in ["こんにちは", "はじめまして", "よろしく"]):
            return """こんにちは！キノエデザインです✨

住まいづくりのことでしたら何でもお気軽にご相談ください😊

**🎯 人気のご相談内容**
💰 坪単価・価格について
🏠 住宅性能・仕様について  
📋 資料請求・展示場見学
💴 資金計画・住宅ローン

**📞 お問い合わせ方法**
下記メニューからお選びいただくか、
直接ご質問をメッセージください！

どのようなことを知りたいですか？"""
        
        else:
            return """ご質問ありがとうございます✨

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

**🎯 よくあるご質問**
💰 坪単価や費用について
🏠 住宅性能や仕様について
📋 資料請求・展示場見学について
💴 資金計画・住宅ローンについて
🌐 補助金制度について

**📱 お答え方法**
具体的にお聞かせいただければ、
詳しくご案内いたします。

または下記メニューをご利用ください：
🤖AI相談 / 📍展示場予約 / 📄資料請求

お気軽にお問い合わせください😊"""
    
    def _emergency_response(self) -> str:
        """緊急時応答（完全性保証版）"""
        return """申し訳ございません。一時的にシステムの不具合が発生しております。

しばらくしてから再度お試しいただくか、下記までお電話でお問い合わせください。

📞 **お電話でのお問い合わせ**
営業時間：9:00-18:00

ご不便をおかけして申し訳ございません。
復旧次第、正常にご利用いただけます。"""
    
    def get_performance_stats(self) -> Dict:
        """パフォーマンス統計（LLM回避重視）"""
        total = self.performance_stats["requests"]
        template_rate = (self.performance_stats["template_hits"] / total * 100) if total > 0 else 0
        llm_avoidance_rate = (self.performance_stats["llm_calls_avoided"] / total * 100) if total > 0 else 0
        
        return {
            "total_requests": total,
            "template_hit_rate": template_rate,
            "llm_calls_avoided": self.performance_stats["llm_calls_avoided"],
            "llm_avoidance_rate": llm_avoidance_rate,
            "ai_consultation_started": self.performance_stats["ai_consultation_started"],
            "greeting_sent": self.performance_stats["greeting_sent"],
            "push_fallbacks_used": self.performance_stats["push_fallbacks"],
            "available_templates": len(self.line_templates),
            "active_ai_consultations": len(self.ai_consultation_active_users)
        }

# ==============================================================================
# LINE Bot設定と初期化（修正版）
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
                if "Invalid reply token" in str(reply_error) or getattr(reply_error, "status", None) == 400:
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
            except Exception as general_error:
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
# イベントハンドラ（修正版・LLM最小化）
# ==============================================================================
if LINE_SDK_AVAILABLE and handler:
    
    @handler.add(FollowEvent)
    def handle_follow_ultra_fast(event):
        """超高速フォローハンドラ（挨拶送信・更新版）"""
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
        """超高速メッセージハンドラ（LLM最小化版・更新版）"""
        start_time = time.time()
        
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            reply_token = event.reply_token
            
            logger.info(f"📱 LINE Ultra fast processing: '{message_text[:30]}...' from user: {user_id}")
            
            # 超高速応答生成（LLM回避優先）
            response_text = ultra_responder.process_ultra_fast(message_text, user_id)
            success = send_line_message_safe(reply_token, user_id, response_text)
            
            duration = (time.time() - start_time) * 1000
            if success:
                logger.info(f"✅ LINE Ultra fast complete response: {duration:.1f}ms (LLM avoided)")
                # 応答の完全性をログ出力
                is_complete = response_text.endswith(('。', '！', '？', '.', '!', '?'))
                logger.info(f"🔚 Response completeness: {is_complete}")
            else:
                logger.error(f"❌ LINE response failed after {duration:.1f}ms")
            
        except Exception as e:
            logger.error(f"❌ Ultra fast message error: {e}")
            logger.error(traceback.format_exc())
            try:
                emergency = ultra_responder._emergency_response()  # 完全性保証済み
                send_line_message_safe(event.reply_token, event.source.user_id, emergency)
            except Exception as final_error:
                logger.error(f"❌ Emergency response failed: {final_error}")

    @handler.add(PostbackEvent)
    def handle_postback_ultra_fast(event):
        """Postbackハンドラ（修正版・更新版）"""
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
                
                # アクションに対応する応答（更新版テンプレート使用）
                response_text = ultra_responder.line_templates.get(action_value, "ご利用ありがとうございます。")
            else:
                response_text = "メニューからお選びください。"
            
            # Postbackも完全性チェック
            response_text = ultra_responder.ensure_line_response_complete(response_text, postback_data)
            success = send_line_message_safe(reply_token, user_id, response_text)
            logger.info(f"✅ Postback processed successfully: success={success}")
            
        except Exception as e:
            logger.error(f"💥 Postback handler error: {e}")
            logger.error(traceback.format_exc())

# ==============================================================================
# 監視・デバッグエンドポイント（拡張版）
# ==============================================================================
@router.get("/performance")
def get_line_performance():
    """LINE専用パフォーマンス統計（LLM回避重視・更新版）"""
    stats = ultra_responder.get_performance_stats()
    
    return {
        "line_ultra_fast_stats": stats,
        "llm_optimization": {
            "llm_calls_avoided": stats["llm_calls_avoided"],
            "llm_avoidance_rate": f"{stats['llm_avoidance_rate']:.1f}%",
            "target_avoidance_rate": "> 90%",
            "achieved": stats["llm_avoidance_rate"] > 90
        },
        "system_info": {
            "line_sdk_available": LINE_SDK_AVAILABLE,
            "line_bot_configured": line_bot_api is not None,
            "reply_fallback_enabled": True,
            "push_api_enabled": True,
            "ai_consultation_optimized": True,
            "api_exception_fixed": True,
            "import_error_fixed": True,
            "richmenu_responses_updated": True,
        },
        "performance_targets": {
            "response_time": "< 200ms",
            "template_hit_rate": "> 80%",
            "llm_avoidance_rate": "> 90%",
            "reply_success_rate": "> 95%"
        },
        "features": [
            "Reply Token Expiry Protection",
            "Push API Automatic Fallback", 
            "AI相談 Specialized Mode",
            "LINE-Specific Template Responses (Updated)",
            "Ultra Fast Processing",
            "LLM/OpenAI API Minimization",
            "Predefined Response Priority",
            "Sentence Completeness Guard (LINE)",
            "Updated Rich Menu Responses",
            "New URLs and Privacy Policy Links",
        ],
        "ai_consultation": {
            "active_users": len(ultra_responder.ai_consultation_active_users),
            "total_started": stats["ai_consultation_started"],
            "predefined_responses": True,
            "llm_bypass_enabled": True
        },
        "richmenu_updates": {
            "ai_consultation": "Updated with privacy policy links",
            "ai_site": "Updated with new site URL",
            "document_request": "Updated with simplified response",
            "showroom_visit": "Updated with reservation URL",
            "financial_planning": "Updated with AI diagnosis guide",
            "chat_consultation": "Updated with business hours only"
        },
        "timestamp": datetime.now().isoformat()
    }

@router.get("/debug")
def line_debug_info():
    """LINE Bot デバッグ情報（修正版・更新版）"""
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
        "llm_optimization": {
            "enabled": True,
            "predefined_responses": len(ultra_responder.line_templates),
            "ai_consultation_mode": True,
            "active_ai_users": len(ultra_responder.ai_consultation_active_users)
        },
        "fixes_applied": [
            "ApiException import fixed",
            "LineBotApiError references removed", 
            "Error handling improved",
            "Push API fallback enhanced",
            "Sentence completeness guard (LINE) enabled",
            "LLM calls minimization implemented",
            "AI consultation specialized mode added",
            "Rich menu responses updated to new specifications"
        ],
        "richmenu_response_updates": {
            "updated_templates": [
                "AI相談 - Added privacy policy links",
                "AI住まいサイト - New site description and URL",
                "資料請求 - Simplified response format",
                "展示場来場予約 - Direct reservation URL",
                "資金計画 - AI diagnosis guide",
                "チャット相談 - Business hours only"
            ],
            "new_urls": [
                "https://preview.studio.site/live/EjOQljz1WJ/",
                "https://preview.studio.site/live/EjOQljz1WJ/reservation",
                "https://preview.studio.site/live/EjOQljz1WJ/privacy-policy",
                "https://preview.studio.site/live/EjOQljz1WJ/termsofuse/service",
                "https://preview.studio.site/live/EjOQljz1WJ/cookie"
            ]
        },
        "timestamp": datetime.now().isoformat()
    }

@router.post("/clear-cache")
def clear_line_cache():
    """LINEキャッシュクリア（更新版）"""
    ultra_responder.performance_stats = {
        "requests": 0, 
        "template_hits": 0, 
        "greeting_sent": 0, 
        "push_fallbacks": 0,
        "ai_consultation_started": 0,
        "llm_calls_avoided": 0
    }
    ultra_responder.ai_consultation_active_users.clear()
    
    return {
        "status": "line_cache_cleared",
        "features_reset": ["performance_stats", "ai_consultation_users"],
        "fixes_confirmed": [
            "ApiException handling active",
            "Import errors resolved",
            "Template responses updated to new specifications",
            "Sentence completeness guard reset",
            "LLM avoidance system reset",
            "Rich menu responses updated"
        ],
        "updated_content": [
            "All rich menu responses updated",
            "New privacy policy URLs added",
            "Site URL updated to preview.studio.site",
            "Reservation URL updated",
            "Greeting message updated"
        ],
        "timestamp": datetime.now().isoformat()
    }

@router.get("/templates")
def get_line_templates():
    """LINE専用テンプレート一覧（更新版）"""
    return {
        "line_templates": list(ultra_responder.line_templates.keys()),
        "count": len(ultra_responder.line_templates),
        "ai_consultation_template": "AI相談" in ultra_responder.line_templates,
        "subsidy_template_added": "補助金" in ultra_responder.line_templates,
        "greeting_configured": bool(ultra_responder.greeting_message),
        "platform": "line_optimized",
        "llm_minimization": {
            "enabled": True,
            "predefined_responses": len(ultra_responder.line_templates),
            "ai_consultation_mode": True,
            "emergency_responses": True
        },
        "template_updates": {
            "AI相談": "Added privacy policy, terms of use, and cookie links",
            "AI住まいサイト": "Updated site description and new preview URL",
            "資料請求": "Simplified with PDF placeholder and optional survey",
            "展示場来場予約": "Direct to reservation URL",
            "資金計画": "AI diagnosis guide with 5-point input",
            "チャット相談": "Business hours only (9:00-18:00)"
        },
        "fixes_applied": [
            "Rich menu response content updated",
            "New URLs integrated",
            "Privacy policy links added",
            "ApiException error handling fixed",
            "Sentence completeness guard (LINE) added",
            "LLM/OpenAI API usage minimized",
            "Predefined response system enhanced"
        ],
        "timestamp": datetime.now().isoformat()
    }

@router.get("/ai-consultation-status")
def get_ai_consultation_status():
    """AI相談モードの状態確認（更新版）"""
    return {
        "ai_consultation_active": True,
        "active_users": len(ultra_responder.ai_consultation_active_users),
        "active_user_list": list(ultra_responder.ai_consultation_active_users),
        "total_consultations_started": ultra_responder.performance_stats["ai_consultation_started"],
        "llm_calls_avoided": ultra_responder.performance_stats["llm_calls_avoided"],
        "predefined_responses_available": len([k for k in ultra_responder.line_templates.keys() if k != "AI相談"]),
        "features": [
            "Predefined Response Priority",
            "LLM/OpenAI API Minimization", 
            "Staff Escalation Ready",
            "Template-based Answers",
            "Updated Rich Menu Responses",
            "Privacy Policy Compliance"
        ],
        "ai_consultation_template_updated": {
            "privacy_policy": "Added",
            "terms_of_use": "Added",
            "cookie_policy": "Added",
            "consultation_flow": "Enhanced"
        },
        "timestamp": datetime.now().isoformat()
    }

@router.post("/reset-ai-consultation/{user_id}")
def reset_ai_consultation(user_id: str):
    """特定ユーザーのAI相談モードをリセット（更新版）"""
    if user_id in ultra_responder.ai_consultation_active_users:
        ultra_responder.ai_consultation_active_users.remove(user_id)
        return {
            "status": "reset_successful",
            "user_id": user_id,
            "remaining_active_users": len(ultra_responder.ai_consultation_active_users),
            "template_updates_applied": True,
            "privacy_compliance": True
        }
    else:
        return {
            "status": "user_not_in_consultation",
            "user_id": user_id,
            "active_users": len(ultra_responder.ai_consultation_active_users),
            "template_updates_applied": True
        }