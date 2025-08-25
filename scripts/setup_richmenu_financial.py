# scripts/setup_richmenu_financial.py
# 資金計画対応リッチメニューセットアップスクリプト

import os
import json
import requests
import time
from datetime import datetime
from typing import Dict, Any, Optional

class LineRichMenuManager:
    """LINE リッチメニュー管理クラス（資金計画対応版）"""
    
    def __init__(self, channel_access_token: str):
        self.access_token = channel_access_token
        self.base_url = "https://api.line.me/v2/bot"
        self.headers = {
            "Authorization": f"Bearer {channel_access_token}",
            "Content-Type": "application/json"
        }
    
    def get_current_richmenus(self) -> Dict[str, Any]:
        """現在のリッチメニュー一覧を取得"""
        try:
            response = requests.get(
                f"{self.base_url}/richmenu/list",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"❌ リッチメニュー取得エラー: {e}")
            return {"richmenus": []}
    
    def delete_all_richmenus(self) -> bool:
        """全てのリッチメニューを削除"""
        try:
            current_menus = self.get_current_richmenus()
            deleted_count = 0
            
            for menu in current_menus.get("richmenus", []):
                menu_id = menu.get("richMenuId")
                if menu_id:
                    try:
                        response = requests.delete(
                            f"{self.base_url}/richmenu/{menu_id}",
                            headers=self.headers,
                            timeout=10
                        )
                        if response.status_code == 200:
                            print(f"✅ リッチメニュー削除: {menu_id}")
                            deleted_count += 1
                        else:
                            print(f"⚠️ リッチメニュー削除失敗: {menu_id} - {response.status_code}")
                    except Exception as e:
                        print(f"❌ リッチメニュー削除エラー: {menu_id} - {e}")
            
            print(f"🧹 リッチメニュー削除完了: {deleted_count}件")
            return True
            
        except Exception as e:
            print(f"❌ リッチメニュー削除処理エラー: {e}")
            return False
    
    def create_financial_planning_richmenu(self) -> Optional[str]:
        """資金計画対応リッチメニューを作成"""
        
        # 🆕 資金計画統合リッチメニュー定義
        richmenu_data = {
            "size": {
                "width": 2500,
                "height": 1686
            },
            "selected": True,
            "name": "キノエデザイン資金計画統合メニュー",
            "chatBarText": "メニュー",
            "areas": [
                {
                    "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
                    "action": {"type": "message", "text": "🤖 AI相談"}
                },
                {
                    "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
                    "action": {"type": "message", "text": "🌐 AI住まいサイト"}
                },
                {
                    "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                    "action": {"type": "message", "text": "📋 資料請求"}
                },
                {
                    "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
                    "action": {"type": "message", "text": "📍 展示場来場予約"}
                },
                {
                    # 🆕 資金計画ボタン（重要！）
                    "bounds": {"x": 833, "y": 843, "width": 834, "height": 843},
                    "action": {"type": "message", "text": "💰 資金計画"}
                },
                {
                    "bounds": {"x": 1667, "y": 843, "width": 833, "height": 843},
                    "action": {"type": "message", "text": "💬 チャット相談"}
                }
            ]
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/richmenu",
                headers=self.headers,
                json=richmenu_data,
                timeout=15
            )
            response.raise_for_status()
            
            result = response.json()
            richmenu_id = result.get("richMenuId")
            
            if richmenu_id:
                print(f"✅ 資金計画統合リッチメニュー作成成功: {richmenu_id}")
                return richmenu_id
            else:
                print(f"❌ リッチメニューID取得失敗: {result}")
                return None
                
        except Exception as e:
            print(f"❌ リッチメニュー作成エラー: {e}")
            return None
    
    def set_default_richmenu(self, richmenu_id: str) -> bool:
        """デフォルトリッチメニューに設定"""
        try:
            response = requests.post(
                f"{self.base_url}/user/all/richmenu/{richmenu_id}",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            
            print(f"✅ デフォルトリッチメニュー設定完了: {richmenu_id}")
            return True
            
        except Exception as e:
            print(f"❌ デフォルトリッチメニュー設定エラー: {e}")
            return False
    
    def upload_richmenu_image(self, richmenu_id: str, image_path: str) -> bool:
        """リッチメニュー画像をアップロード"""
        try:
            if not os.path.exists(image_path):
                print(f"❌ 画像ファイルが見つかりません: {image_path}")
                return False
            
            with open(image_path, 'rb') as f:
                headers = {
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "image/png"
                }
                
                response = requests.post(
                    f"{self.base_url}/richmenu/{richmenu_id}/content",
                    headers=headers,
                    data=f,
                    timeout=30
                )
                response.raise_for_status()
                
                print(f"✅ リッチメニュー画像アップロード完了: {richmenu_id}")
                return True
                
        except Exception as e:
            print(f"❌ 画像アップロードエラー: {e}")
            return False

def get_line_token_from_env() -> Optional[str]:
    """環境変数またはSecret ManagerからLINEトークンを取得"""
    
    # 1. 環境変数から取得
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    if token:
        return token.strip()
    
    # 2. Secret Managerから取得
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "rag-cloud-project")
        
        secret_name = f"projects/{project_id}/secrets/LINE_CHANNEL_ACCESS_TOKEN/versions/latest"
        response = client.access_secret_version(request={"name": secret_name})
        return response.payload.data.decode("UTF-8").strip()
        
    except Exception as e:
        print(f"❌ Secret Manager取得エラー: {e}")
        return None

def create_richmenu_image_template():
    """リッチメニュー画像テンプレート作成（説明）"""
    template_info = """
🎨 リッチメニュー画像作成ガイド

📐 **画像仕様**
- サイズ: 2500 x 1686 ピクセル
- フォーマット: PNG または JPEG
- ファイルサイズ: 1MB以下

🗂️ **レイアウト（6ボタン）**
┌─────────────────┬─────────────────┬─────────────────┐
│   🤖 AI相談     │  🌐 AI住まいサイト │    📋 資料請求    │
│   (833x843)     │    (834x843)    │   (833x843)     │
├─────────────────┼─────────────────┼─────────────────┤
│ 📍 展示場来場予約  │   💰 資金計画      │   💬 チャット相談   │
│   (833x843)     │    (834x843)    │   (833x843)     │
└─────────────────┴─────────────────┴─────────────────┘

🎯 **ボタン配置座標**
1. AI相談: (0, 0, 833, 843)
2. AI住まいサイト: (833, 0, 834, 843)  
3. 資料請求: (1667, 0, 833, 843)
4. 展示場来場予約: (0, 843, 833, 843)
5. 💰 資金計画: (833, 843, 834, 843) ← 新機能！
6. チャット相談: (1667, 843, 833, 843)

📝 **テキスト内容**
- 各ボタンに対応する絵文字とテキストを配置
- フォント: ゴシック体推奨
- 文字色: 白または濃色（背景との対比を考慮）

🎨 **デザイン推奨**
- ブランドカラーを使用
- 各ボタンの境界線を明確に
- 「💰 資金計画」ボタンを目立たせる（新機能のため）

📁 **ファイル保存**
- ファイル名: richmenu_financial_planning.png
- 保存場所: ./assets/richmenu/ 
    """
    
    print(template_info)
    
    # 画像ディレクトリ作成
    os.makedirs("assets/richmenu", exist_ok=True)
    
    with open("assets/richmenu/README.md", "w", encoding="utf-8") as f:
        f.write(template_info)
    
    print("📁 assets/richmenu/README.md に詳細を保存しました")

def main():
    """メイン実行関数"""
    print("🎨 LINE リッチメニュー資金計画統合セットアップ")
    print("=" * 60)
    
    # 1. アクセストークン取得
    print("🔑 LINE アクセストークン取得...")
    access_token = get_line_token_from_env()
    
    if not access_token:
        print("❌ LINE アクセストークンが取得できません")
        print("💡 以下のいずれかで設定してください:")
        print("   1. 環境変数 LINE_CHANNEL_ACCESS_TOKEN")
        print("   2. Google Secret Manager")
        return False
    
    print(f"✅ アクセストークン取得成功 (長さ: {len(access_token)})")
    
    # 2. リッチメニューマネージャー初期化
    manager = LineRichMenuManager(access_token)
    
    # 3. 現在のリッチメニュー確認
    print("\n📋 現在のリッチメニュー確認...")
    current_menus = manager.get_current_richmenus()
    menu_count = len(current_menus.get("richmenus", []))
    print(f"📊 現在のリッチメニュー数: {menu_count}")
    
    if menu_count > 0:
        print("🔍 既存のリッチメニュー:")
        for i, menu in enumerate(current_menus.get("richmenus", []), 1):
            print(f"   {i}. {menu.get('name', '名前なし')} (ID: {menu.get('richMenuId', 'N/A')})")
        
        response = input("\n既存のリッチメニューを削除して新しく作成しますか？ (y/n): ")
        if response.lower() == 'y':
            print("🧹 既存リッチメニュー削除中...")
            manager.delete_all_richmenus()
    
    # 4. 新しいリッチメニュー作成
    print("\n🆕 資金計画統合リッチメニュー作成...")
    richmenu_id = manager.create_financial_planning_richmenu()
    
    if not richmenu_id:
        print("❌ リッチメニュー作成失敗")
        return False
    
    # 5. 画像について案内
    print("\n🎨 リッチメニュー画像について...")
    create_richmenu_image_template()
    
    image_path = "assets/richmenu/richmenu_financial_planning.png"
    
    if os.path.exists(image_path):
        response = input(f"\n{image_path} が見つかりました。アップロードしますか？ (y/n): ")
        if response.lower() == 'y':
            success = manager.upload_richmenu_image(richmenu_id, image_path)
            if not success:
                print("❌ 画像アップロード失敗")
                return False
    else:
        print(f"⚠️ {image_path} が見つかりません")
        print("📝 上記の仕様に従って画像を作成し、再度実行してください")
        
        # とりあえずテキストのみでデフォルト設定
        response = input("画像なしでデフォルト設定しますか？ (y/n): ")
        if response.lower() != 'y':
            print("ℹ️ 画像作成後に再度実行してください")
            return False
    
    # 6. デフォルトリッチメニューに設定
    print(f"\n⚙️ デフォルトリッチメニュー設定: {richmenu_id}")
    success = manager.set_default_richmenu(richmenu_id)
    
    if success:
        print("🎉 リッチメニュー設定完了！")
        print(f"📱 リッチメニューID: {richmenu_id}")
        print("📲 LINEアプリでリッチメニューを確認してください")
        return True
    else:
        print("❌ デフォルト設定失敗")
        return False

# ==============================================================================
# 統合テスト実行クラス
# ==============================================================================
class FinancialPlanningIntegrationTester:
    """資金計画機能統合テストクラス"""
    
    def __init__(self, api_base_url: str = "http://localhost:8080"):
        self.base_url = api_base_url
        self.test_user_id = f"test_user_{int(time.time())}"
        self.test_results = []
    
    def test_line_bot_endpoints(self):
        """LINE Botエンドポイントテスト"""
        print("🤖 LINE Bot エンドポイントテスト")
        print("-" * 40)
        
        endpoints = [
            ("/line/debug", "デバッグ情報"),
            ("/line/health", "ヘルスチェック"),
            ("/line/performance", "パフォーマンス統計"),
            ("/line/financial-sessions", "資金計画セッション")
        ]
        
        for endpoint, description in endpoints:
            try:
                response = requests.get(f"{self.base_url}{endpoint}", timeout=10)
                if response.status_code == 200:
                    print(f"✅ {description}: OK")
                    self.test_results.append({"test": description, "status": "success"})
                else:
                    print(f"❌ {description}: {response.status_code}")
                    self.test_results.append({"test": description, "status": "failed"})
            except Exception as e:
                print(f"💥 {description}: {e}")
                self.test_results.append({"test": description, "status": "error"})
    
    def test_financial_planning_flow(self):
        """資金計画フロー全体テスト"""
        print("\n💰 資金計画フロー全体テスト")
        print("-" * 40)
        
        # テストケース
        test_messages = [
            ("💰 資金計画", "セッション開始"),
            ("年収600万円", "年収入力"),
            ("月8万円", "返済額入力"),
            ("35年", "借入期間入力"),
            ("夫婦と子ども1人", "家族構成入力"),
            ("車ローン月3万円", "その他負担入力・計算実行")
        ]
        
        for message, description in test_messages:
            try:
                # 資金計画メッセージ処理テスト
                test_data = {
                    "question": message,
                    "username": self.test_user_id,
                    "platform": "line",
                    "route_preference": "financial"
                }
                
                response = requests.post(
                    f"{self.base_url}/chat",
                    json=test_data,
                    timeout=15
                )
                
                if response.status_code == 200:
                    result = response.json()
                    answer = result.get("answer", "")
                    
                    print(f"✅ {description}: {len(answer)}文字")
                    
                    # 回答の妥当性チェック
                    if len(answer) > 10 and answer.endswith(('。', '！', '？', '.', '!', '?')):
                        print(f"   📝 完全な文章: OK")
                        self.test_results.append({"test": description, "status": "success"})
                    else:
                        print(f"   ⚠️ 文章が不完全: {answer[-20:]}")
                        self.test_results.append({"test": description, "status": "warning"})
                        
                else:
                    print(f"❌ {description}: {response.status_code}")
                    self.test_results.append({"test": description, "status": "failed"})
                    
                time.sleep(1)  # API制限対策
                
            except Exception as e:
                print(f"💥 {description}: {e}")
                self.test_results.append({"test": description, "status": "error"})
    
    def test_liff_page(self):
        """LIFF ページテスト"""
        print("\n📱 LIFF ページテスト")
        print("-" * 40)
        
        try:
            response = requests.get(f"{self.base_url}/financial/liff-page", timeout=10)
            
            if response.status_code == 200:
                content = response.text
                
                # HTML内容の基本チェック
                checks = [
                    ("<!DOCTYPE html>", "HTML構造"),
                    ("AI資金診断", "タイトル"),
                    ("liff.init", "LIFF初期化"),
                    ("annualIncome", "年収入力フィールド"),
                    ("monthlyPayment", "返済額入力フィールド"),
                    ("loanPeriod", "借入期間選択"),
                    ("familyComposition", "家族構成選択"),
                    ("otherExpenses", "その他負担入力"),
                    ("calculateBtn", "計算ボタン"),
                    ("progressBar", "プログレスバー")
                ]
                
                for check_text, description in checks:
                    if check_text in content:
                        print(f"✅ {description}: OK")
                        self.test_results.append({"test": f"liff_{description}", "status": "success"})
                    else:
                        print(f"❌ {description}: Missing")
                        self.test_results.append({"test": f"liff_{description}", "status": "failed"})
                
                print(f"📊 LIFF ページサイズ: {len(content):,} bytes")
                
            else:
                print(f"❌ LIFF ページアクセス失敗: {response.status_code}")
                self.test_results.append({"test": "liff_page_access", "status": "failed"})
                
        except Exception as e:
            print(f"💥 LIFF ページテストエラー: {e}")
            self.test_results.append({"test": "liff_page_test", "status": "error"})
    
    def test_financial_calculation_api(self):
        """資金計算APIテスト"""
        print("\n🧮 資金計算APIテスト")
        print("-" * 40)
        
        test_cases = [
            {
                "name": "標準ケース",
                "data": {
                    "annual_income": 6000000,   # 600万円
                    "monthly_payment": 80000,   # 8万円
                    "loan_period": 35,
                    "family_composition": "大人2名・お子さま1名",
                    "other_expenses": 30000     # 3万円
                },
                "expected_range": {
                    "min_budget": (2000, 3000),  # 2000万〜3000万円
                    "max_budget": (2500, 3500),  # 2500万〜3500万円
                }
            },
            {
                "name": "高所得ケース",
                "data": {
                    "annual_income": 10000000,  # 1000万円
                    "monthly_payment": 120000,  # 12万円
                    "loan_period": 30,
                    "family_composition": "大人2名・お子さま2名",
                    "other_expenses": 50000     # 5万円
                },
                "expected_range": {
                    "min_budget": (3500, 5000),  # 3500万〜5000万円
                    "max_budget": (4000, 6000),  # 4000万〜6000万円
                }
            }
        ]
        
        for test_case in test_cases:
            try:
                print(f"\n📊 {test_case['name']}テスト実行...")
                
                response = requests.post(
                    f"{self.base_url}/financial/calculate",
                    json=test_case["data"],
                    timeout=15
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if result.get("success"):
                        calc = result["calculation"]
                        
                        print(f"   💰 購入可能額: {calc['affordable_budget_min']}万〜{calc['affordable_budget_max']}万円")
                        print(f"   💳 推奨返済額: {calc['monthly_payment_suggestion']:,}円")
                        print(f"   📊 最大借入額: {calc['max_loan_amount']}万円")
                        print(f"   🎯 リスクレベル: {calc['risk_level']}")
                        
                        # 期待値範囲チェック
                        expected = test_case["expected_range"]
                        min_ok = expected["min_budget"][0] <= calc['affordable_budget_min'] <= expected["min_budget"][1]
                        max_ok = expected["max_budget"][0] <= calc['affordable_budget_max'] <= expected["max_budget"][1]
                        
                        if min_ok and max_ok:
                            print(f"✅ {test_case['name']}: 計算結果が期待範囲内")
                            self.test_results.append({"test": f"calc_{test_case['name']}", "status": "success"})
                        else:
                            print(f"⚠️ {test_case['name']}: 計算結果が期待値から外れています")
                            self.test_results.append({"test": f"calc_{test_case['name']}", "status": "warning"})
                    else:
                        print(f"❌ {test_case['name']}: {result}")
                        self.test_results.append({"test": f"calc_{test_case['name']}", "status": "failed"})
                else:
                    print(f"❌ {test_case['name']}: API呼び出し失敗 {response.status_code}")
                    self.test_results.append({"test": f"calc_{test_case['name']}", "status": "failed"})
                    
            except Exception as e:
                print(f"💥 {test_case['name']}テストエラー: {e}")
                self.test_results.append({"test": f"calc_{test_case['name']}", "status": "error"})
    
    def generate_test_report(self):
        """統合テストレポート生成"""
        print("\n📊 統合テスト結果サマリー")
        print("=" * 60)
        
        total = len(self.test_results)
        success = len([r for r in self.test_results if r["status"] == "success"])
        warning = len([r for r in self.test_results if r["status"] == "warning"])
        failed = len([r for r in self.test_results if r["status"] == "failed"])
        error = len([r for r in self.test_results if r["status"] == "error"])
        
        print(f"📈 総テスト数: {total}")
        print(f"✅ 成功: {success} ({success/total*100:.1f}%)")
        print(f"⚠️ 警告: {warning} ({warning/total*100:.1f}%)")
        print(f"❌ 失敗: {failed} ({failed/total*100:.1f}%)")
        print(f"💥 エラー: {error} ({error/total*100:.1f}%)")
        
        # 成功率判定
        success_rate = (success + warning) / total if total > 0 else 0
        
        if success_rate >= 0.9:
            print("\n🎉 統合テスト成功！本番デプロイ準備完了です。")
            return True
        elif success_rate >= 0.7:
            print("\n⚠️ 一部問題がありますが、基本機能は動作します。")
            return True
        else:
            print("\n❌ 重大な問題があります。修正が必要です。")
            return False
    
    def run_integration_tests(self):
        """統合テスト実行"""
        print(f"🧪 資金計画機能統合テスト開始")
        print(f"🌐 テスト対象: {self.base_url}")
        print(f"👤 テストユーザー: {self.test_user_id}")
        print(f"⏰ 開始時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        self.test_line_bot_endpoints()
        self.test_financial_planning_flow()
        self.test_liff_page()
        self.test_financial_calculation_api()
        
        success = self.generate_test_report()
        
        # 詳細レポート保存
        report_filename = f"integration_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_filename, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "test_target": self.base_url,
                "test_user_id": self.test_user_id,
                "results": self.test_results,
                "summary": {
                    "total": len(self.test_results),
                    "success": len([r for r in self.test_results if r["status"] == "success"]),
                    "warning": len([r for r in self.test_results if r["status"] == "warning"]),
                    "failed": len([r for r in self.test_results if r["status"] == "failed"]),
                    "error": len([r for r in self.test_results if r["status"] == "error"]),
                    "overall_success": success
                }
            }, f, indent=2, ensure_ascii=False)
        
        print(f"\n📄 詳細レポート: {report_filename}")
        return success

# ==============================================================================
# LIFF設定ヘルパー
# ==============================================================================
def generate_liff_setup_guide():
    """LIFF設定ガイド生成"""
    
    guide = """
📱 LIFF（LINE Front-end Framework）設定手順

🔧 **LINE Developers Console での設定**

1. **コンソールアクセス**
   https://developers.line.biz/console/

2. **チャンネル選択**
   既存のBotチャンネルを選択

3. **LIFF タブ**
   「LIFF」タブをクリック → 「新規作成」

4. **LIFF アプリ設定**
   ```
   LIFF アプリ名: AI資金診断 - キノエデザイン
   サイズ: Full
   エンドポイントURL: https://your-domain.com/financial/liff-page
   スコープ: ☑ profile ☑ openid
   ボットリンク機能: On
   Scan QR: Off（不要）
   Bluetooth LE: Off（不要）
   ```

5. **LIFF ID 取得**
   作成完了後、LIFF ID をコピー
   例: `liff-1234567890-abcdefgh`

6. **コード内のLIFF ID更新**
   `api/routers/financial_api.py` の以下の行を更新:
   ```javascript
   liff.init({
       liffId: 'liff-1234567890-abcdefgh'  // 👈 ここを更新
   })
   ```

🔗 **LIFF URL の構成**
```
完全なLIFF URL: https://liff.line.me/{LIFF_ID}
エンドポイントURL: https://your-domain.com/financial/liff-page
```

⚙️ **動作確認手順**
1. LINEアプリで「💰 資金計画」をタップ
2. LIFF ページが正常に表示されることを確認
3. フォーム入力が動作することを確認
4. 計算結果がLINEに送信されることを確認

📝 **トラブルシューティング**
- LIFF ページが表示されない → URL・LIFF ID確認
- フォームが動作しない → JavaScript エラーログ確認
- LINEに送信されない → liff.sendMessages() の実装確認
    """
    
    print(guide)
    
    with open("LIFF_SETUP_GUIDE.md", "w", encoding="utf-8") as f:
        f.write(guide)
    
    print("📁 LIFF_SETUP_GUIDE.md に詳細手順を保存しました")

# ==============================================================================
# メイン実行部分
# ==============================================================================
if __name__ == "__main__":
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="資金計画機能セットアップ・テスト")
    parser.add_argument("--mode", choices=["richmenu", "test", "liff-guide", "all"], 
                       default="all", help="実行モード")
    parser.add_argument("--api-url", default="http://localhost:8080", 
                       help="APIベースURL")
    parser.add_argument("--skip-richmenu", action="store_true", 
                       help="リッチメニュー設定をスキップ")
    
    args = parser.parse_args()
    
    success = True
    
    if args.mode in ["richmenu", "all"] and not args.skip_richmenu:
        print("🎨 リッチメニュー設定開始...")
        richmenu_success = main()
        success = success and richmenu_success
        print()
    
    if args.mode in ["liff-guide", "all"]:
        print("📱 LIFF設定ガイド生成...")
        generate_liff_setup_guide()
        print()
    
    if args.mode in ["test", "all"]:
        print("🧪 統合テスト開始...")
        tester = FinancialPlanningIntegrationTester(args.api_url)
        test_success = tester.run_integration_tests()
        success = success and test_success
        print()
    
    if success:
        print("🎉 資金計画機能のセットアップ・テストが完了しました！")
        print("📱 LINEアプリで「💰 資金計画」ボタンをお試しください。")
    else:
        print("⚠️ 一部の処理で問題が発生しました。ログを確認してください。")
        sys.exit(1)