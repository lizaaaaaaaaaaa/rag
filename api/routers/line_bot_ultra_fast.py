# api/routers/line_bot_ultra_fast.py - 超高速LINE Bot実装

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

# LINE SDK v3 import
try:
    from linebot.v3 import WebhookHandler
    from linebot.v3.exceptions import InvalidSignatureError
    from linebot.v3.messaging import (
        Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage,
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
# 超高速キャッシュシステム
# ==============================================================================
class UltraFastLineCache:
    def __init__(self, max_size: int = 1000):
        self.cache: Dict[str, Dict] = {}
        self.access_times: Dict[str, float] = {}
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
        
    def _generate_key(self, query: str) -> str:
        normalized = query.lower().strip()[:100]
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def get(self, query: str) -> Optional[str]:
        key = self._generate_key(query)
        if key in self.cache:
            self.access_times[key] = time.time()
            self.hits += 1
            logger.info(f"⚡ LINE Cache HIT: {query[:20]}...")
            return self.cache[key]["answer"]
        self.misses += 1
        return None
    
    def set(self, query: str, answer: str):
        if len(self.cache) >= self.max_size:
            self._evict_oldest()
        
        key = self._generate_key(query)
        self.cache[key] = {
            "answer": answer,
            "timestamp": time.time(),
            "query": query[:50]
        }
        self.access_times[key] = time.time()
        logger.info(f"💾 LINE Cache SET: {query[:20]}...")
    
    def _evict_oldest(self):
        if self.access_times:
            oldest_key = min(self.access_times.keys(), key=lambda k: self.access_times[k])
            del self.cache[oldest_key]
            del self.access_times[oldest_key]

# ==============================================================================
# 超高速応答生成クラス
# ==============================================================================
class UltraFastLineResponder:
    def __init__(self):
        self.cache = UltraFastLineCache()
        self.template_responses = self._load_comprehensive_templates()
        self.performance_stats = {"total_requests": 0, "cache_hits": 0, "template_hits": 0}
        
    def _load_comprehensive_templates(self) -> Dict[str, str]:
        """包括的なテンプレート応答（大幅強化版）"""
        return {
            # =============  基本情報系 =============
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

            # =============  サービス系 =============
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

            # =============  よくある質問系 =============
            "家づくりの流れ": """🏗️ 家づくりの流れをご案内いたします

**1. ご相談・情報収集**
・資料請求、展示場見学
・ご要望のヒアリング

**2. プラン・資金計画**
・間取りプランの検討
・資金計画の立案

**3. ご契約・詳細打合せ**
・工事請負契約
・仕様・設備の決定

**4. 着工・完成**
・地鎮祭、上棟式
・お引渡し

詳しくはスタッフまでお問い合わせください。""",

            "補助金制度": """💰 住宅購入時の補助金制度についてご案内します

**主な補助金制度**
🏠 ZEH補助金：高性能住宅への補助
🌱 こどもエコすまい支援事業：子育て世帯への支援
🏦 住宅ローン減税：所得税の控除制度
📋 地域独自の補助金：自治体による支援

※制度は年度ごとに変更される可能性があります。最新情報については公式サイトでご確認いただくか、スタッフまでお問い合わせください。""",

            "ZEH": """🌱 ZEH（ゼッチ）についてご説明いたします

**ZEHとは**
Net Zero Energy Houseの略で、年間の一次エネルギー消費量が正味ゼロとなる住宅です。

**特徴**
・高断熱性能
・高効率設備
・太陽光発電システム
・HEMS（エネルギー管理システム）

**メリット**
・光熱費の大幅削減
・快適な室内環境
・補助金の活用可能
・資産価値の向上

詳しくは展示場でご確認ください。""",

            "長期優良住宅": """🏠 長期優良住宅についてご説明いたします

**長期優良住宅とは**
長期にわたり良好な状態で使用するための措置が講じられた優良な住宅です。

**認定基準**
・耐震性（耐震等級2以上）
・省エネ性（断熱等性能等級4以上）
・耐久性・維持管理性
・住戸面積・居住環境・維持保全計画

**メリット**
・住宅ローン減税の拡充
・不動産取得税の軽減
・固定資産税の軽減期間延長
・フラット35Sの金利優遇

当社では標準で長期優良住宅認定に対応しています。""",

            # =============  挨拶・リッチメニュー系 =============
            "AI相談": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです。
住まいに関するご質問をお気軽にどうぞ！

💡 **例えば**
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？
・資料請求したい
・展示場を見学したい

何でもお聞きください😊""",

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
お気軽にお声かけください！""",

            # =============  一般的な質問系 =============
            "挨拶": """こんにちは！キノエデザインです。
住まいづくりに関することなら何でもお気軽にお聞かせください。

目的のボタンをタップ👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画

AIは24時間、担当者は営業時間内に返信いたします。""",

            "ありがとう": """どういたしまして！
他にもご質問がございましたら、いつでもお聞かせください。

住まいづくりのお手伝いをさせていただきます😊""",

            "相談": """ご相談ありがとうございます。

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

・坪単価や費用について
・住宅性能について
・資料請求・展示場見学
・資金計画について

具体的にお聞かせいただければ、詳しくご案内いたします。""",
        }
    
    def process_ultra_fast(self, message_text: str, user_id: str = "unknown") -> str:
        """超高速処理メイン関数"""
        start_time = time.time()
        self.performance_stats["total_requests"] += 1
        
        try:
            # 1. キャッシュチェック（最優先）
            cached_response = self.cache.get(message_text)
            if cached_response:
                self.performance_stats["cache_hits"] += 1
                logger.info(f"⚡ LINE Cache hit in {(time.time() - start_time)*1000:.1f}ms")
                return cached_response
            
            # 2. 拡張テンプレートマッチング
            template_response = self._ultra_fast_template_match(message_text)
            if template_response:
                self.performance_stats["template_hits"] += 1
                self.cache.set(message_text, template_response)
                logger.info(f"🎯 LINE Template match in {(time.time() - start_time)*1000:.1f}ms")
                return template_response
            
            # 3. インテリジェントフォールバック
            fallback_response = self._generate_intelligent_fallback(message_text)
            self.cache.set(message_text, fallback_response)
            logger.info(f"🔄 LINE Fallback in {(time.time() - start_time)*1000:.1f}ms")
            return fallback_response
            
        except Exception as e:
            logger.error(f"❌ Ultra fast processing error: {e}")
            return self._emergency_response()
    
    def _ultra_fast_template_match(self, message_text: str) -> Optional[str]:
        """拡張テンプレートマッチング（大幅強化版）"""
        text_clean = message_text.lower().replace(" ", "").replace("　", "")
        
        # より詳細なキーワードマッピング
        enhanced_keyword_mapping = {
            "坪単価": [
                "坪単価", "坪たんか", "つぼたんか", "価格", "値段", "費用", "コスト", 
                "いくら", "金額", "料金", "単価", "建築費", "工事費", "総額"
            ],
            "標準仕様": [
                "標準仕様", "仕様", "設備", "標準", "基本", "スタンダード", "標準設備",
                "何が付いてる", "何がつく", "付属", "装備", "基本設備"
            ],
            "断熱性能": [
                "断熱", "断熱性能", "断熱材", "省エネ", "温度", "暖房", "冷房", 
                "光熱費", "ua値", "c値", "気密", "エネルギー", "快適性"
            ],
            "耐震性能": [
                "耐震", "地震", "耐震性能", "耐震等級", "安全", "強度", "地震対策",
                "安心", "構造", "耐久", "震災", "防災"
            ],
            "資料請求": [
                "資料", "パンフレット", "カタログ", "資料請求", "パンフ", "冊子",
                "送って", "郵送", "資料ほしい", "資料がほしい", "カタログほしい"
            ],
            "展示場予約": [
                "展示場", "見学", "予約", "モデルハウス", "見に行く", "見たい", "見学したい",
                "体験", "確認", "実際に見る", "現地", "ショールーム", "完成見学"
            ],
            "資金計画": [
                "資金計画", "資金", "ローン", "住宅ローン", "お金", "支払い", "月々",
                "返済", "借入", "融資", "金利", "頭金", "諸費用", "総予算"
            ],
            "家づくりの流れ": [
                "家づくり", "流れ", "進め方", "手順", "スケジュール", "工程", "期間",
                "何から", "始め方", "どうやって", "建てる流れ", "建築の流れ"
            ],
            "補助金制度": [
                "補助金", "助成金", "支援金", "給付金", "控除", "減税", "優遇",
                "制度", "政府", "国", "自治体", "市", "県", "支援制度"
            ],
            "ZEH": [
                "zeh", "ゼッチ", "ぜっち", "省エネ住宅", "エネルギーゼロ", "太陽光",
                "創エネ", "畜エネ", "ネットゼロ", "ゼロエネルギー"
            ],
            "長期優良住宅": [
                "長期優良", "長期優良住宅", "優良住宅", "認定住宅", "長期",
                "優良", "認定", "長持ち", "耐久性"
            ],
            "AI相談": [
                "ai相談", "AI相談", "ai住まい", "相談", "質問", "聞きたい",
                "教えて", "知りたい", "どうなの", "について"
            ],
            "AI住まいサイト": [
                "ai住まいサイト", "サイト", "ホームページ", "HP", "ウェブサイト",
                "見たい", "確認したい", "ウェブ", "オンライン"
            ],
            "チャット相談": [
                "チャット相談", "チャット", "スタッフ", "担当者", "人と話したい",
                "直接相談", "電話", "対面"
            ],
            "挨拶": [
                "こんにちは", "こんばんは", "おはよう", "はじめまして", "hello", "hi",
                "始めまして", "よろしく", "お疲れ"
            ],
            "ありがとう": [
                "ありがとう", "ありがとございます", "感謝", "助かる", "助かります",
                "thanks", "thank you", "サンキュー"
            ],
            "相談": [
                "相談", "聞きたい", "教えて", "質問", "どうしたら", "わからない",
                "困っている", "悩んでいる", "検討中", "迷っている"
            ]
        }
        
        # より精密なマッチング
        for template_key, keywords in enhanced_keyword_mapping.items():
            # 完全一致チェック
            if any(keyword == text_clean for keyword in keywords):
                logger.info(f"🎯 Perfect match: {template_key}")
                return self.template_responses.get(template_key)
            
            # 部分一致チェック（より緩い条件）
            if any(keyword in text_clean for keyword in keywords):
                # 文字数による信頼性チェック
                if len(text_clean) <= 50 or any(len(keyword) >= 3 and keyword in text_clean for keyword in keywords):
                    logger.info(f"🎯 Partial match: {template_key}")
                    return self.template_responses.get(template_key)
        
        return None
    
    def _generate_intelligent_fallback(self, message_text: str) -> str:
        """インテリジェントフォールバック（大幅強化版）"""
        text_lower = message_text.lower()
        
        # より詳細な意図分析
        if any(keyword in text_lower for keyword in ["家を建てる", "住宅建築", "マイホーム", "新築", "建て方"]):
            return """🏗️ 家づくりについてお答えいたします

家づくりは人生で最も大きな買い物の一つです。

**まずはこちらから始めませんか？**
1️⃣ 資料請求で情報収集
2️⃣ 展示場見学で実際の住まいを体感
3️⃣ 資金計画で予算を明確化

お客様のご希望をお聞かせいただければ、最適なプランをご提案いたします。何からお聞きになりたいでしょうか？"""

        elif any(keyword in text_lower for keyword in ["土地", "土地探し", "敷地", "立地", "場所"]):
            return """🗺️ 土地探しについてお答えいたします

**土地探しのポイント**
・立地条件（交通・買い物・学校）
・土地の形状・面積
・法的制限（建ぺい率・容積率）
・インフラ整備状況
・予算とのバランス

当社では土地探しからサポートいたします。ご希望のエリアや条件をお聞かせください。"""

        elif any(keyword in text_lower for keyword in ["間取り", "プラン", "設計", "レイアウト"]):
            return """📐 間取り・プランについてお答えいたします

**間取り検討のポイント**
・ご家族構成とライフスタイル
・将来の変化への対応
・動線・収納計画
・日当たり・風通し

無料でプランニングいたします。ご家族構成やご希望をお聞かせください。"""

        elif any(keyword in text_lower for keyword in ["期間", "工期", "スケジュール", "完成", "引渡し"]):
            return """📅 建築期間についてお答えいたします

**標準的な期間**
・プラン検討：1～2ヶ月
・詳細打合せ：1～2ヶ月
・建築工事：4～6ヶ月
・全体期間：約6～10ヶ月

お客様のご希望時期に合わせてスケジュール調整いたします。いつ頃の完成をお考えでしょうか？"""

        elif any(keyword in text_lower for keyword in ["保証", "アフター", "メンテナンス", "点検"]):
            return """🛡️ 保証・アフターサービスについて

**充実の保証体制**
・構造躯体20年保証
・設備機器メーカー保証
・地盤保証20年
・定期点検・メンテナンス

建てた後も安心してお住まいいただけるよう、責任を持ってサポートいたします。"""

        else:
            # 一般的な応答
            return """ご質問ありがとうございます。

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

**よくあるご質問**
💰 坪単価や費用について
🏠 住宅性能や仕様について
📋 資料請求・展示場見学
💴 資金計画・住宅ローン
🏗️ 家づくりの流れ

具体的にお聞かせいただければ、詳しくご案内いたします。お気軽にお問い合わせください。"""
    
    def _emergency_response(self) -> str:
        """緊急時応答"""
        return """申し訳ございません。一時的にシステムの不具合が発生しております。

しばらくしてから再度お試しいただくか、下記までお電話でお問い合わせください。

📞 お電話でのお問い合わせ
営業時間：9:00-18:00（水曜定休）

ご不便をおかけして申し訳ございません。"""
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """パフォーマンス統計取得"""
        total = self.performance_stats["total_requests"]
        cache_rate = (self.performance_stats["cache_hits"] / total * 100) if total > 0 else 0
        template_rate = (self.performance_stats["template_hits"] / total * 100) if total > 0 else 0
        
        return {
            "total_requests": total,
            "cache_hit_rate": cache_rate,
            "template_hit_rate": template_rate,
            "cache_size": len(self.cache.cache),
            "template_count": len(self.template_responses)
        }

# ==============================================================================
# LINE Bot設定と初期化
# ==============================================================================
def get_line_credentials_safe():
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
ultra_responder = UltraFastLineResponder()

if LINE_SDK_AVAILABLE and LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    try:
        normalized_token = normalize_line_token(LINE_CHANNEL_ACCESS_TOKEN)
        normalized_secret = normalize_line_token(LINE_CHANNEL_SECRET)
        
        if normalized_token and normalized_secret:
            configuration = Configuration(access_token=normalized_token)
            handler = WebhookHandler(normalized_secret)
            
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
            
            logger.info("✅ Ultra Fast LINE Bot initialized successfully")
        else:
            raise ValueError("Empty normalized credentials")
            
    except Exception as e:
        logger.error(f"❌ LINE Bot initialization failed: {e}")
        line_bot_api, handler = None, None

# 挨拶メッセージ
GREETING_MESSAGE = """こんにちは！キノエデザインです。
この度は友だち追加ありがとうございます✨

目的のボタンをタップ👇
🤖AI相談 / 📍来場予約 / 📄資料請求 / 💴資金計画 / 🌐サイト / 💬チャット

AIは24時間、担当者は当日〜翌営業日に返信します。

取扱い(プライバシーポリシー)：〔https://preview.studio.site/live/EjOQljz1WJ/privacy-policy〕"""

# ==============================================================================
# 安全送信関数
# ==============================================================================
def send_line_reply_ultra_safe(reply_token: str, message: str) -> bool:
    """超安全LINE返信送信"""
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
            messaging_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=message)]
                )
            )
        
        logger.info(f"✅ Ultra fast reply sent: {len(message)} chars")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ultra safe reply failed: {e}")
        return False

# ==============================================================================
# Webhook エンドポイント
# ==============================================================================
@router.post("/webhook")
async def ultra_fast_webhook(request: Request, background_tasks: BackgroundTasks):
    """超高速Webhook"""
    logger.info("🚀 Ultra Fast LINE Webhook called")
    
    if not line_bot_api or not handler:
        return {"status": "error", "message": "LINE Bot not configured"}
    
    try:
        body = await request.body()
        signature = request.headers.get("X-Line-Signature", "")
        
        if not signature:
            return {"status": "error", "message": "Missing signature"}
        
        body_text = body.decode("utf-8")
        handler.handle(body_text, signature)
        
        return {"status": "ok", "timestamp": datetime.now().isoformat()}
        
    except InvalidSignatureError:
        return {"status": "signature_error"}
    except Exception as e:
        logger.error(f"Ultra fast webhook error: {e}")
        return {"status": "error", "error": str(e)}

# ==============================================================================
# イベントハンドラ
# ==============================================================================
if LINE_SDK_AVAILABLE and handler:
    
    @handler.add(FollowEvent)
    def handle_follow_ultra_fast(event):
        """超高速フォローハンドラ"""
        start_time = time.time()
        try:
            user_id = event.source.user_id
            reply_token = event.reply_token
            
            logger.info(f"👤 New follower (ultra fast): {user_id}")
            
            success = send_line_reply_ultra_safe(reply_token, GREETING_MESSAGE)
            duration = (time.time() - start_time) * 1000
            
            logger.info(f"✅ Ultra fast greeting sent: {duration:.1f}ms")
            
        except Exception as e:
            logger.error(f"❌ Ultra fast follow error: {e}")
    
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_message_ultra_fast(event):
        """超高速メッセージハンドラ"""
        start_time = time.time()
        
        try:
            user_id = event.source.user_id
            message_text = event.message.text
            reply_token = event.reply_token
            
            logger.info(f"📱 Ultra fast processing: '{message_text[:30]}...'")
            
            # 超高速応答生成
            response_text = ultra_responder.process_ultra_fast(message_text, user_id)
            
            # 返信送信
            success = send_line_reply_ultra_safe(reply_token, response_text)
            
            duration = (time.time() - start_time) * 1000
            logger.info(f"✅ Ultra fast response: {duration:.1f}ms")
            
        except Exception as e:
            logger.error(f"❌ Ultra fast message error: {e}")
            try:
                emergency = "申し訳ございません。一時的にエラーが発生しました。しばらくしてから再度お試しください。"
                send_line_reply_ultra_safe(event.reply_token, emergency)
            except Exception as final_error:
                logger.error(f"❌ Emergency response failed: {final_error}")

# ==============================================================================
# 監視・デバッグエンドポイント
# ==============================================================================
@router.get("/ultra-performance")
def get_ultra_performance():
    """超高速パフォーマンス統計"""
    stats = ultra_responder.get_performance_stats()
    
    return {
        "ultra_fast_stats": stats,
        "system_info": {
            "line_sdk_available": LINE_SDK_AVAILABLE,
            "line_bot_configured": line_bot_api is not None,
            "template_count": len(ultra_responder.template_responses),
            "cache_enabled": True
        },
        "performance_targets": {
            "response_time": "< 100ms (template/cache)",
            "cache_hit_rate": "> 60%",
            "template_coverage": "> 80%"
        },
        "timestamp": datetime.now().isoformat()
    }

@router.post("/clear-ultra-cache")
def clear_ultra_cache():
    """超高速キャッシュクリア"""
    old_stats = ultra_responder.get_performance_stats()
    ultra_responder.cache = UltraFastLineCache()
    
    return {
        "status": "ultra_cache_cleared",
        "previous_stats": old_stats,
        "timestamp": datetime.now().isoformat()
    }

@router.get("/templates")
def get_template_list():
    """テンプレート一覧"""
    return {
        "templates": list(ultra_responder.template_responses.keys()),
        "count": len(ultra_responder.template_responses),
        "ultra_fast_enabled": True,
        "timestamp": datetime.now().isoformat()
    }