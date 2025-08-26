# utils/chat_templates.py - 統合テンプレートシステム（プラットフォーム最適化）

import os
import json
import logging
import re
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import yaml

logger = logging.getLogger(__name__)

class ChatTemplateManager:
    """チャット用統合テンプレート管理システム"""
    
    def __init__(self, template_dir: str = "templates/chat"):
        self.template_dir = template_dir
        self.templates = {}
        self.metadata = {}
        self.keyword_mappings = {}
        self.dynamic_variables = {}
        self.template_stats = {
            "web_matches": 0,
            "line_matches": 0,
            "total_requests": 0,
            "template_hits": {},
            "fallback_uses": 0
        }
        
        # 設定
        self.enable_dynamic_content = True
        self.enable_personalization = True
        self.fallback_language = "ja"
        
        # テンプレート読み込み
        self._load_templates()
        self._setup_keyword_mappings()
        self._setup_dynamic_variables()

    def _load_templates(self) -> None:
        """テンプレートファイルの読み込み"""
        try:
            # 設定ファイルから読み込み
            config_file = os.path.join(self.template_dir, "template_config.yaml")
            if os.path.exists(config_file):
                self._load_from_config_file(config_file)
            else:
                # デフォルトテンプレート読み込み
                self._load_default_templates()
            
            logger.info(f"✅ Templates loaded: {len(self.templates)} templates")
            
        except Exception as e:
            logger.error(f"Template loading error: {e}")
            self._load_default_templates()

    def _load_from_config_file(self, config_file: str) -> None:
        """設定ファイルからテンプレート読み込み"""
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # プラットフォーム別テンプレート
        for platform in ["web", "line"]:
            if platform in config:
                self.templates[platform] = config[platform]
        
        # メタデータ読み込み
        if "metadata" in config:
            self.metadata = config["metadata"]
        
        # キーワードマッピング読み込み
        if "keyword_mappings" in config:
            self.keyword_mappings = config["keyword_mappings"]

    def _load_default_templates(self) -> None:
        """デフォルトテンプレートの読み込み"""
        
        # Web用テンプレート（詳細・フォーマル）
        self.templates["web"] = {
            "坪単価": {
                "content": """坪単価についてご案内いたします。

**当社の坪単価目安**
・標準仕様：約70～85万円/坪
・高性能仕様：約85～100万円/坪
・プレミアム仕様：約100～120万円/坪

**含まれる標準内容**
・耐震等級3の構造（建築基準法の1.5倍の耐震性）
・長期優良住宅認定対応
・高断熱・高気密仕様（省エネ等級4以上）
・標準設備一式（システムキッチン、ユニットバス等）

**価格に影響する要因**
- 建物の形状・間取りの複雑さ
- 設備・仕様のグレード
- 立地条件・地盤状況
- 付帯工事の内容

お客様のご希望される仕様や条件により変動いたします。より詳細なお見積りをご希望でしたら、お気軽にお問い合わせください。""",
                "tags": ["価格", "見積もり", "基本情報"],
                "priority": 10
            },

            "標準仕様": {
                "content": """標準仕様についてご説明いたします。

**構造・性能**
・耐震等級3（最高等級）を標準採用
・長期優良住宅認定対応
・省エネ等級4以上（ZEH基準対応可能）
・高断熱・高気密仕様（UA値0.6以下、C値1.0以下）

**主要設備仕様**
・システムキッチン（食器洗い乾燥機付き）
・ユニットバス（1坪タイプ、浴室乾燥機付き）
・洗面化粧台（3面鏡、LED照明）
・トイレ（温水洗浄便座付き、節水型）
・給湯設備（エコキュート標準）

**内外装仕様**
・外壁：高耐久サイディング
・屋根：カラーベスト（遮熱型）
・内装：クロス仕上げ、フローリング
・建具：室内ドア、収納扉一式

より詳しい仕様書については、資料請求または展示場見学でご確認いただけます。オプション仕様についてもご相談ください。""",
                "tags": ["仕様", "設備", "標準"],
                "priority": 9
            },

            "耐震性能": {
                "content": """耐震性能についてご案内いたします。

**耐震等級について**
・耐震等級3（最高等級）を標準採用
・建築基準法の1.5倍の耐震強度を実現
・大規模地震でも軽微な補修で継続使用可能なレベル

**構造計算・設計**
・許容応力度計算による詳細な構造計算を実施
・地盤調査に基づく基礎設計
・構造専門技術者による設計チェック

**使用材料・工法**
・構造用集成材（強度・品質が安定）
・金物工法による強固な接合部
・ベタ基礎による堅固な基礎構造
・制振ダンパー設置（オプション）

**品質保証**
・構造躯体20年保証
・地盤保証20年
・瑕疵担保責任保険対応
・第三者機関による施工検査

**地震対策の特徴**
- 建物の重心と剛心のバランス最適化
- 耐力壁の適切な配置
- 接合部の高強度化

安心・安全な住まいをお約束いたします。地震に関するご不安やご質問がございましたら、構造専門スタッフがご説明いたします。""",
                "tags": ["耐震", "安全", "構造"],
                "priority": 8
            },

            "断熱性能": {
                "content": """断熱性能についてご案内いたします。

**断熱等級・基準値**
・断熱等級4以上（ZEH基準対応）
・UA値：0.6以下（6地域基準）※地域により異なります
・C値：1.0以下（気密性能）
・省エネ基準をクリアした高性能住宅

**使用断熱材**
・外壁：高性能グラスウール16K（105mm）
・屋根：吹付硬質ウレタンフォーム（150mm）
・基礎：押出法ポリスチレンフォーム3種（65mm）
・窓：樹脂サッシ+Low-E複層ガラス（アルゴンガス入り）

**断熱工法の特徴**
- 充填断熱＋付加断熱によるダブル断熱
- 熱橋（ヒートブリッジ）の削減
- 防湿・気密シートによる高気密化
- 計画換気システム（第1種・第3種対応）

**快適性・経済性**
・夏涼しく、冬暖かい快適な室内環境
・光熱費の大幅削減（年間10～15万円削減例有り）
・結露の抑制・防止
・室内温度差の軽減

**ZEH対応**
- ZEH（ネット・ゼロ・エネルギー・ハウス）対応可能
- 太陽光発電システム設置で年間エネルギー収支ゼロ
- ZEH補助金対象

詳しくは展示場でご体感いただけます。実際の断熱性能を体感できるモデルハウスでお確かめください。""",
                "tags": ["断熱", "省エネ", "ZEH"],
                "priority": 8
            },

            "補助金": {
                "content": """住宅購入時の補助金・支援制度についてご案内いたします。

**主な国の補助金制度**

**1. ZEH補助金**
・対象：ゼロエネルギーハウス（ZEH）
・補助額：定額55万円～（条件により異なる）
・加算：蓄電池設置で最大20万円追加
・申請期間：年数回の公募制

**2. こどもエコすまい支援事業**
・対象：子育て世帯・若年夫婦世帯
・補助額：最大100万円
・省エネ性能に応じて補助額変動
・リフォームにも適用可能

**3. 住宅ローン減税**
・所得税の控除制度（住宅ローン残高の0.7%）
・控除期間：13年間（認定住宅等）
・年間最大控除額：35万円（条件により異なる）
・住民税からも一部控除可能

**4. 地域型住宅グリーン化事業**
・長期優良住宅：補助額110万円
・ゼロエネルギー住宅：補助額140万円
・地域材加算：最大20万円

**地方自治体の補助金**
・市町村独自の住宅取得支援制度
・移住・定住促進補助金
・多子世帯向け支援制度
・地域によって内容・金額が大きく異なります

**フラット35の優遇制度**
・フラット35S：金利引き下げ（当初5年間または10年間）
・維持保全型：長期優良住宅等で金利引き下げ
・地域連携型：地方公共団体と連携した金利引き下げ

**注意事項**
※制度は年度ごとに変更される可能性があります
※併用できない補助金もございます
※申請期限や予算上限にご注意ください

最新情報については、公式サイトでご確認いただくか、弊社スタッフまでお問い合わせください。お客様の条件に最適な補助金活用方法をご提案いたします。""",
                "tags": ["補助金", "支援制度", "税制"],
                "priority": 7
            },

            "資金計画": {
                "content": """住宅購入の資金計画についてご案内いたします。

**資金計画の基本的な考え方**
住宅購入は人生最大の買い物です。無理のない返済計画を立てることが重要です。

**必要資金の内訳**
1. **建物本体価格**（坪単価 × 延床面積）
2. **付帯工事費**（外構、地盤改良等：本体価格の15-20%）
3. **諸費用**（登記、融資手数料等：総額の5-8%）
4. **土地代**（土地購入の場合）

**自己資金の目安**
・頭金：総額の10-20%程度
・諸費用分：現金で準備推奨
・予備費：引越し、家具購入等

**住宅ローンの選び方**
・借入可能額の目安：年収の5-7倍
・返済比率：月収の25%以内（理想は20%以内）
・金利タイプ：変動/固定の特徴を理解
・返済期間：定年時までに完済が理想

**月々の返済例（35年返済の場合）**
- 借入3000万円：約84,000円（金利1.0%）
- 借入3500万円：約98,000円（金利1.0%）
- 借入4000万円：約113,000円（金利1.0%）

**ライフプランとの調整**
・子供の教育費
・車の買い替え
・老後資金
・その他のライフイベント

**資金計画サポート**
弊社では、ファイナンシャルプランナーによる無料の資金計画相談を承っております。お客様の年収、家族構成、将来設計に応じて、最適な資金計画をご提案いたします。

お気軽にご相談ください。""",
                "tags": ["資金計画", "住宅ローン", "予算"],
                "priority": 9
            },

            "AI相談": {
                "content": """AI住まい相談へようこそ！

住まいづくりに関するご質問に、AIがお答えいたします。どのようなことでもお気軽にお尋ねください。

**よくあるご質問**
・坪単価について教えて
・標準仕様はどのような内容？
・耐震性能について知りたい
・断熱性能はどの程度？
・利用できる補助金制度は？
・資金計画の立て方は？
・土地探しのポイントは？
・建築の流れを教えて

**専門分野**
- 住宅の性能・仕様
- 価格・見積もり
- 補助金・税制優遇
- 資金計画・住宅ローン
- 土地・立地条件
- 建築プロセス

何でもお聞きください。より詳しい情報が必要でしたら、専門スタッフにおつなぎすることも可能です。""",
                "tags": ["AI相談", "案内", "サポート"],
                "priority": 5
            }
        }
        
        # LINE用テンプレート（短文・絵文字・親しみやすい）
        self.templates["line"] = {
            "AI相談": {
                "content": """🤖 AI住まい相談を開始します！

キノエデザインの住まいAIコンシェルジュです✨
住まいに関するご質問をお気軽にどうぞ！

💡 **例えば**
・坪単価について教えて
・標準仕様はどんな感じ？
・耐震性能について知りたい
・断熱性能はどのくらい？
・補助金について教えて

何でもお聞きください😊

※ご利用前に、プライバシーポリシーをご確認ください
https://example.com/privacy""",
                "tags": ["AI相談", "案内"],
                "priority": 10
            },
            
            "資料請求": {
                "content": """📋 資料請求を承ります

以下の情報をお教えください📝

**必要項目**
・お名前（フルネーム）
・ご住所（〒から詳しく）
・お電話番号
・ご希望資料の種類

**お送りする資料**
🏠 会社案内・施工事例集
📐 間取りプラン集
💰 価格・仕様資料  
🏦 住宅ローンガイド

3営業日以内にお送りいたします📮

※必要に応じてお電話でご相談も承ります😊""",
                "tags": ["資料請求", "案内"],
                "priority": 9
            },

            "展示場見学": {
                "content": """🏠 展示場見学のご案内

実際の住まいを体感していただけます✨

**見学のメリット**
👀 実際の間取り・設備を確認
🌡️ 断熱・気密性能を体感
💡 住み心地を実感
👨‍👩‍👧‍👦 家族でじっくり検討

**ご予約方法**
📞 お電話：0120-xxx-xxx
📱 LINEでも予約OK
🌐 WebサイトからWEB予約

**営業時間**
🕘 平日：10:00-18:00
🕘 土日祝：10:00-18:00
定休日：火・水曜日

お気軽にお越しください😊""",
                "tags": ["展示場", "見学", "予約"],
                "priority": 8
            },

            "坪単価": {
                "content": """💰 坪単価についてご案内いたします

🏠 **当社の坪単価目安**
・標準仕様：約70～85万円/坪
・高性能仕様：約85～100万円/坪
・プレミアム：約100～120万円/坪

✨ **標準で含まれる内容**
・耐震等級3の構造🏗️
・長期優良住宅対応🏆
・高断熱・高気密仕様🌡️
・標準設備一式🛁

📋 **価格に影響する要素**
・間取り・建物の形
・設備のグレード
・立地・地盤条件
・外構工事の内容

お客様のご要望により変動します。
詳しいお見積りはお気軽にご相談ください😊""",
                "tags": ["坪単価", "価格", "見積もり"],
                "priority": 10
            },

            "標準仕様": {
                "content": """🏗️ 標準仕様についてご説明します

**🏠構造・性能**
・耐震等級3（最高等級）🏆
・長期優良住宅対応📜
・省エネ等級4以上⚡
・高断熱・高気密仕様🌡️

**🛁設備仕様**
・システムキッチン🍳
・ユニットバス♨️
・洗面化粧台🪞
・温水洗浄便座付きトイレ🚽
・エコキュート♻️

**✨特徴**
・ZEH基準対応可能🌞
・オール電化対応⚡
・24時間換気システム💨

より詳しい仕様書は資料請求で📋
展示場での確認もおすすめです🏠""",
                "tags": ["標準仕様", "設備", "性能"],
                "priority": 9
            },

            "耐震性能": {
                "content": """🏗️ 耐震性能についてご案内します

**🏆耐震等級**
・耐震等級3（最高等級）を標準採用
・建築基準法の1.5倍の耐震強度💪
・大地震でも安心の構造🛡️

**🔧構造材**
・構造用集成材使用🌲
・金物工法による強固な接合⚙️
・ベタ基礎による堅固な基礎🏗️

**📋保証**
・構造躯体20年保証📅
・地盤保証20年🌍
・瑕疵担保責任保険対応📝

**👨‍🔬専門技術**
・許容応力度計算実施📊
・構造専門技術者による設計チェック✅

安心・安全な住まいをお約束します🏠✨
詳しくはスタッフまでお気軽にご相談を😊""",
                "tags": ["耐震", "安全", "構造"],
                "priority": 8
            },

            "断熱性能": {
                "content": """🌡️ 断熱性能についてご案内します

**📊断熱等級**
・断熱等級4以上（ZEH基準対応）🌟
・UA値：0.6以下（地域区分6）📏
・C値：1.0以下（気密性能）🔒

**🏗️使用断熱材**
・外壁：高性能グラスウール🧱
・屋根：吹付断熱材☁️
・基礎：押出法ポリスチレン⬜
・窓：樹脂サッシ+Low-Eガラス🪟

**😊快適性**
・夏涼しく、冬暖かい❄️☀️
・光熱費の削減効果💰
・結露抑制でカビ予防🚫

**🌞ZEH対応**
・太陽光発電で年間エネルギーゼロ
・補助金対象💰

展示場でぜひ体感してください🏠✨""",
                "tags": ["断熱", "省エネ", "ZEH"],
                "priority": 8
            },

            "補助金": {
                "content": """💰 住宅購入時の補助金制度をご案内します

**🏠主な補助金制度**

**ZEH補助金🌞**
高性能住宅への補助
定額55万円～

**👶こどもエコすまい支援事業**
子育て世帯への支援💕
最大100万円

**🏦住宅ローン減税**
所得税の控除制度
13年間の減税メリット📉

**🏛️地域独自の補助金**
自治体による支援
地域により異なります

**⚠️注意事項**
・制度は年度ごとに変更の可能性
・併用できない場合あり
・申請期限要確認

最新情報はスタッフまでお問い合わせください😊
お客様に最適な活用方法をご提案します✨""",
                "tags": ["補助金", "支援制度", "税制"],
                "priority": 7
            },

            "資金計画": {
                "content": """💰 資金計画についてご案内します

住宅購入の資金計画、一緒に考えましょう😊

**💡基本的な考え方**
・無理のない返済計画が大切
・将来のライフプランも考慮
・余裕を持った資金設定を

**📊必要資金の内訳**
🏠建物本体価格
🚧付帯工事費（15-20%程度）
📄諸費用（5-8%程度）
🌍土地代（土地購入の場合）

**🏦住宅ローンの目安**
・借入額：年収の5-7倍程度
・返済比率：月収の25%以内
・返済期間：定年までに完済理想

**👨‍💼無料相談実施中**
ファイナンシャルプランナーによる
資金計画相談を承ります📋

お気軽にご相談ください😊""",
                "tags": ["資金計画", "住宅ローン", "相談"],
                "priority": 9
            },

            "チャット相談": {
                "content": """💬 スタッフとのチャット相談

【対応時間⏰】
平日：9:00-18:00
土日祝：9:00-18:00
定休日：火・水曜日

**📱ご相談方法**
・このLINEでの直接相談💬
・お電話での相談📞
・展示場での対面相談🏠

**👨‍💼対応内容**
・住宅に関するご質問
・資金計画のご相談
・土地探しのサポート
・建築プロセスのご説明

営業時間内でしたら迅速にお返事します📲
お気軽にお声かけください😊

何でもご相談ください✨""",
                "tags": ["チャット相談", "サポート", "対応時間"],
                "priority": 6
            }
        }

    def _setup_keyword_mappings(self) -> None:
        """キーワードマッピングの設定"""
        self.keyword_mappings = {
            # 価格関連
            "坪単価": ["坪単価", "坪たんか", "価格", "値段", "費用", "コスト", "いくら", "金額", "料金", "単価"],
            
            # 仕様・設備関連
            "標準仕様": ["標準仕様", "仕様", "設備", "標準", "基本", "スタンダード", "何が付く", "含まれる"],
            
            # 性能関連
            "耐震性能": ["耐震", "地震", "耐震性能", "安全", "強度", "構造", "震災", "耐震等級"],
            "断熱性能": ["断熱", "断熱性能", "省エネ", "温度", "暖房", "冷房", "光熱費", "ua値", "c値", "zeh"],
            
            # 支援制度関連
            "補助金": ["補助金", "助成金", "支援金", "補助制度", "支援制度", "zeh補助", "こどもエコ", "減税"],
            "資金計画": ["資金計画", "ローン", "予算", "返済", "借入", "融資", "計画", "お金"],
            
            # サービス関連
            "資料請求": ["資料請求", "資料", "カタログ", "パンフレット", "案内"],
            "展示場見学": ["展示場", "モデルハウス", "見学", "体感", "確認", "予約"],
            "チャット相談": ["相談", "質問", "聞きたい", "教えて", "スタッフ", "人間"],
            
            # AI関連
            "AI相談": ["ai相談", "🤖 ai相談", "ai", "人工知能", "チャットボット"]
        }

    def _setup_dynamic_variables(self) -> None:
        """動的変数の設定"""
        self.dynamic_variables = {
            "current_date": datetime.now().strftime("%Y年%m月%d日"),
            "current_year": datetime.now().year,
            "current_month": datetime.now().month,
            "current_season": self._get_current_season(),
            "business_hours": "平日・土日祝 9:00-18:00（定休日：火・水曜日）",
            "phone_number": "0120-xxx-xxx",
            "website_url": "https://example.com"
        }

    def find_template(self, query: str, platform: str = "web", 
                     user_context: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """クエリに最適なテンプレートを検索"""
        self.template_stats["total_requests"] += 1
        
        query_lower = query.lower().strip()
        platform_templates = self.templates.get(platform, {})
        
        if not platform_templates:
            logger.warning(f"No templates found for platform: {platform}")
            return None
        
        # 1. 完全一致チェック（リッチメニュー等）
        exact_match = self._find_exact_match(query_lower, platform_templates)
        if exact_match:
            return exact_match
        
        # 2. キーワードマッチング
        keyword_match = self._find_keyword_match(query_lower, platform_templates)
        if keyword_match:
            return keyword_match
        
        # 3. 部分一致・類似検索
        similarity_match = self._find_similarity_match(query_lower, platform_templates)
        if similarity_match:
            return similarity_match
        
        # 4. フォールバック
        return self._get_fallback_template(platform, user_context)

    def _find_exact_match(self, query: str, templates: Dict) -> Optional[Dict[str, Any]]:
        """完全一致検索"""
        # リッチメニュー等の完全一致パターン
        exact_patterns = [
            "🤖 ai相談", "ai相談",
            "📋 資料請求", "資料請求", 
            "🏠 展示場見学", "展示場見学",
            "💬 チャット相談", "チャット相談"
        ]
        
        for pattern in exact_patterns:
            if pattern in query:
                template_key = pattern.replace("🤖 ", "").replace("📋 ", "").replace("🏠 ", "").replace("💬 ", "")
                if template_key in templates:
                    return self._prepare_template_result(template_key, templates[template_key], "exact_match")
        
        return None

    def _find_keyword_match(self, query: str, templates: Dict) -> Optional[Dict[str, Any]]:
        """キーワードマッチング"""
        best_match = None
        max_score = 0
        
        for template_key, keywords in self.keyword_mappings.items():
            if template_key not in templates:
                continue
            
            # キーワードマッチングスコア計算
            score = 0
            matched_keywords = []
            
            for keyword in keywords:
                if keyword in query:
                    score += len(keyword)  # 長いキーワードほど高スコア
                    matched_keywords.append(keyword)
            
            # 優先度による重み付け
            template_priority = templates[template_key].get("priority", 5)
            weighted_score = score * (template_priority / 10)
            
            if weighted_score > max_score:
                max_score = weighted_score
                best_match = {
                    "template_key": template_key,
                    "template": templates[template_key],
                    "score": weighted_score,
                    "matched_keywords": matched_keywords,
                    "match_type": "keyword_match"
                }
        
        if best_match and max_score > 0:
            return self._prepare_template_result(
                best_match["template_key"], 
                best_match["template"], 
                "keyword_match",
                {"score": max_score, "matched_keywords": best_match["matched_keywords"]}
            )
        
        return None

    def _find_similarity_match(self, query: str, templates: Dict) -> Optional[Dict[str, Any]]:
        """類似度マッチング（簡易版）"""
        # 簡易的な類似度計算
        best_match = None
        max_similarity = 0.3  # 最低閾値
        
        for template_key, template_data in templates.items():
            tags = template_data.get("tags", [])
            
            # タグとの類似度計算
            similarity = 0
            for tag in tags:
                if tag in query:
                    similarity += 0.5
                
                # 部分一致
                tag_words = tag.split()
                for word in tag_words:
                    if word in query and len(word) > 2:
                        similarity += 0.2
            
            if similarity > max_similarity:
                max_similarity = similarity
                best_match = {
                    "template_key": template_key,
                    "template": template_data,
                    "similarity": similarity
                }
        
        if best_match:
            return self._prepare_template_result(
                best_match["template_key"],
                best_match["template"],
                "similarity_match",
                {"similarity": max_similarity}
            )
        
        return None

    def _get_fallback_template(self, platform: str, user_context: Optional[Dict]) -> Dict[str, Any]:
        """フォールバックテンプレート"""
        self.template_stats["fallback_uses"] += 1
        
        if platform == "line":
            fallback_content = """ご質問ありがとうございます✨

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

**よくあるご質問**
💰 坪単価や費用について
🏠 住宅性能や仕様について  
📋 資料請求・展示場見学
💬 スタッフとの相談

具体的にお聞かせいただければ、詳しくご案内いたします😊"""
        else:
            fallback_content = """お尋ねの内容について詳しくご案内いたします。

住まいづくりについて、どのようなことをお知りになりたいでしょうか？

・坪単価や費用について
・住宅性能や仕様について
・資料請求・展示場見学について  
・資金計画・住宅ローンについて
・補助金制度について

具体的にお聞かせいただければ、詳しくご案内いたします。住宅に関することでしたら何でもお気軽にお問い合わせください。"""
        
        return {
            "content": self._process_dynamic_content(fallback_content),
            "template_key": "fallback",
            "match_type": "fallback",
            "platform": platform,
            "metadata": {
                "is_fallback": True,
                "generated_at": datetime.now().isoformat()
            }
        }

    def _prepare_template_result(self, template_key: str, template_data: Dict, 
                               match_type: str, extra_metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """テンプレート結果の準備"""
        # 統計更新
        platform = "web" if match_type in ["exact_match", "keyword_match"] else "line"  # 推定
        self.template_stats[f"{platform}_matches"] += 1
        
        if template_key not in self.template_stats["template_hits"]:
            self.template_stats["template_hits"][template_key] = 0
        self.template_stats["template_hits"][template_key] += 1
        
        # 動的コンテンツ処理
        content = template_data["content"]
        if self.enable_dynamic_content:
            content = self._process_dynamic_content(content)
        
        result = {
            "content": content,
            "template_key": template_key,
            "match_type": match_type,
            "metadata": {
                "tags": template_data.get("tags", []),
                "priority": template_data.get("priority", 5),
                "generated_at": datetime.now().isoformat(),
                **(extra_metadata or {})
            }
        }
        
        logger.info(f"🎯 Template matched: {template_key} ({match_type})")
        
        return result

    def _process_dynamic_content(self, content: str) -> str:
        """動的コンテンツの処理"""
        if not self.enable_dynamic_content:
            return content
        
        processed_content = content
        
        # 動的変数の置換
        for var_name, var_value in self.dynamic_variables.items():
            placeholder = f"{{{var_name}}}"
            if placeholder in processed_content:
                processed_content = processed_content.replace(placeholder, str(var_value))
        
        return processed_content

    def _get_current_season(self) -> str:
        """現在の季節取得"""
        month = datetime.now().month
        if month in [12, 1, 2]:
            return "冬"
        elif month in [3, 4, 5]:
            return "春"
        elif month in [6, 7, 8]:
            return "夏"
        else:
            return "秋"

    def get_template_stats(self) -> Dict[str, Any]:
        """テンプレート統計取得"""
        total_requests = self.template_stats["total_requests"]
        total_matches = self.template_stats["web_matches"] + self.template_stats["line_matches"]
        
        return {
            "performance": {
                "total_requests": total_requests,
                "total_matches": total_matches,
                "match_rate": (total_matches / total_requests * 100) if total_requests > 0 else 0,
                "fallback_rate": (self.template_stats["fallback_uses"] / total_requests * 100) if total_requests > 0 else 0
            },
            "platform_distribution": {
                "web_matches": self.template_stats["web_matches"],
                "line_matches": self.template_stats["line_matches"]
            },
            "template_popularity": dict(sorted(
                self.template_stats["template_hits"].items(),
                key=lambda x: x[1],
                reverse=True
            )),
            "template_counts": {
                "web_templates": len(self.templates.get("web", {})),
                "line_templates": len(self.templates.get("line", {})),
                "total_templates": sum(len(templates) for templates in self.templates.values())
            },
            "configuration": {
                "dynamic_content_enabled": self.enable_dynamic_content,
                "personalization_enabled": self.enable_personalization,
                "fallback_language": self.fallback_language
            }
        }

    def add_custom_template(self, platform: str, template_key: str, 
                          content: str, tags: List[str] = None, 
                          priority: int = 5) -> bool:
        """カスタムテンプレート追加"""
        try:
            if platform not in self.templates:
                self.templates[platform] = {}
            
            self.templates[platform][template_key] = {
                "content": content,
                "tags": tags or [],
                "priority": priority,
                "custom": True,
                "created_at": datetime.now().isoformat()
            }
            
            logger.info(f"✅ Custom template added: {platform}/{template_key}")
            return True
            
        except Exception as e:
            logger.error(f"Custom template addition error: {e}")
            return False

    def remove_template(self, platform: str, template_key: str) -> bool:
        """テンプレート削除"""
        try:
            if platform in self.templates and template_key in self.templates[platform]:
                del self.templates[platform][template_key]
                logger.info(f"🗑️ Template removed: {platform}/{template_key}")
                return True
            return False
        except Exception as e:
            logger.error(f"Template removal error: {e}")
            return False

    def export_templates(self, file_path: str) -> bool:
        """テンプレートのエクスポート"""
        try:
            export_data = {
                "templates": self.templates,
                "keyword_mappings": self.keyword_mappings,
                "dynamic_variables": self.dynamic_variables,
                "metadata": {
                    "exported_at": datetime.now().isoformat(),
                    "version": "1.0",
                    "total_templates": sum(len(templates) for templates in self.templates.values())
                }
            }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                yaml.dump(export_data, f, default_flow_style=False, allow_unicode=True)
            
            logger.info(f"📤 Templates exported to: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Template export error: {e}")
            return False

# グローバルテンプレートマネージャー
_global_template_manager = None

def get_template_manager() -> ChatTemplateManager:
    """グローバルテンプレートマネージャー取得"""
    global _global_template_manager
    
    if _global_template_manager is None:
        template_dir = os.getenv("TEMPLATE_DIR", "templates/chat")
        _global_template_manager = ChatTemplateManager(template_dir)
    
    return _global_template_manager

def reset_template_manager() -> ChatTemplateManager:
    """テンプレートマネージャーリセット"""
    global _global_template_manager
    _global_template_manager = None
    return get_template_manager()