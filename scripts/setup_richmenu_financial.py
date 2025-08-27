# scripts/setup_richmenu_financial.py - リッチメニューセットアップスクリプト（指定文面対応修正版）
# 資金計画対応リッチメニューセットアップスクリプト

import os
import json
import requests
import time
from datetime import datetime
from typing import Dict, Any, Optional

class LineRichMenuManager:
    """LINE リッチメニュー管理クラス（指定文面対応版）"""
    
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
    
    def create_specified_richmenu(self) -> Optional[str]:
        """🔧 指定文面対応リッチメニューを作成"""
        
        # 🆕 指定文面対応統合リッチメニュー定義
        richmenu_data = {
            "size": {
                "width": 2500,
                "height": 1686
            },
            "selected": True,
            "name": "キノエデザイン指定文面対応メニュー",  # 🔧 メニュー名更新
            "chatBarText": "メニュー",
            "areas": [
                {
                    # 🔧 AI相談ボタン（指定文面対応）
                    "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
                    "action": {"type": "message", "text": "🤖 AI相談"}
                },
                {
                    # 🔧 AI住まいサイトボタン（指定文面対応）
                    "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
                    "action": {"type": "message", "text": "🌐 AI住まいサイト"}
                },
                {
                    # 🔧 資料請求ボタン（指定文面対応）
                    "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                    "action": {"type": "message", "text": "📄 資料請求"}
                },
                {
                    # 🔧 展示場来場予約ボタン（指定文面対応）
                    "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
                    "action": {"type": "message", "text": "📍 展示場来場　予約"}
                },
                {
                    # 🔧 資金計画ボタン（指定文面対応）
                    "bounds": {"x": 833, "y": 843, "width": 834, "height": 843},
                    "action": {"type": "message", "text": "💰 資金計画"}
                },
                {
                    # 🔧 チャット相談ボタン（指定文面対応）
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
                print(f"✅ 指定文面対応リッチメニュー作成成功: {richmenu_id}")
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
    """🔧 指定文面対応リッチメニュー画像テンプレート作成（説明）"""
    template_info = """
🎨 リッチメニュー画像作成ガイド（指定文面対応版）

📐 **画像仕様**
- サイズ: 2500 x 1686 ピクセル
- フォーマット: PNG または JPEG
- ファイルサイズ: 1MB以下

🗂️ **レイアウト（6ボタン - 指定文面対応）**
┌─────────────────┬─────────────────┬─────────────────┐
│   🤖 AI相談     │  🌐 AI住まいサイト │    📄 資料請求    │
│   (833x843)     │    (834x843)    │   (833x843)     │
├─────────────────┼─────────────────┼─────────────────┤
│ 📍 展示場来場予約  │   💰 資金計画      │   💬 チャット相談   │
│   (833x843)     │    (834x843)    │   (833x843)     │
└─────────────────┴─────────────────┴─────────────────┘

🎯 **ボタン配置座標（指定文面対応）**
1. 🤖 AI相談: (0, 0, 833, 843)
2. 🌐 AI住まいサイト: (833, 0, 834, 843)  
3. 📄 資料請求: (1667, 0, 833, 843)
4. 📍 展示場来場予約: (0, 843, 833, 843)
5. 💰 資金計画: (833, 843, 834, 843)
6. 💬 チャット相談: (1667, 843, 833, 843)

📝 **ボタンテキスト（押下時送信文字列）**
- 🤖 AI相談 → "🤖 AI相談"
- 🌐 AI住まいサイト → "🌐 AI住まいサイト"
- 📄 資料請求 → "📄 資料請求"
- 📍 展示場来場予約 → "📍 展示場来場　予約"
- 💰 資金計画 → "💰 資金計画"
- 💬 チャット相談 → "💬 チャット相談"

🎨 **デザイン推奨**
- キノエデザインのブランドカラーを使用
- 各ボタンの境界線を明確に
- 絵文字を効果的に配置（視認性向上）
- 「📍 展示場来場予約」「💰 資金計画」を目立たせる

📁 **ファイル保存**
- ファイル名: richmenu_specified_design.png
- 保存場所: ./assets/richmenu/ 

⚠️ **重要事項**
- ボタンの座標とアクションテキストは厳密に一致させてください
- 指定文面との整合性を保つため、ボタン表示とアクション文字列を統一
- 画像のボタン表示テキストは日本語でも問題ありません
    """
    
    print(template_info)
    
    # 画像ディレクトリ作成
    os.makedirs("assets/richmenu", exist_ok=True)
    
    with open("assets/richmenu/README_specified.md", "w", encoding="utf-8") as f:
        f.write(template_info)
    
    print("📁 assets/richmenu/README_specified.md に詳細を保存しました")

def main():
    """メイン実行関数（指定文面対応版）"""
    print("🎨 LINE リッチメニュー指定文面対応セットアップ")
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
    
    # 4. 🔧 新しいリッチメニュー作成（指定文面対応）
    print("\n🆕 指定文面対応リッチメニュー作成...")
    richmenu_id = manager.create_specified_richmenu()
    
    if not richmenu_id:
        print("❌ リッチメニュー作成失敗")
        return False
    
    # 5. 🔧 画像について案内（指定文面対応）
    print("\n🎨 リッチメニュー画像について...")
    create_richmenu_image_template()
    
    image_path = "assets/richmenu/richmenu_specified_design.png"
    
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
        print("🎉 指定文面対応リッチメニュー設定完了！")
        print(f"📱 リッチメニューID: {richmenu_id}")
        print("📲 LINEアプリでリッチメニューを確認してください")
        print("\n✅ 期待される動作:")
        print("   🤖 AI相談 → AI住まい相談開始案内")
        print("   🌐 AI住まいサイト → サイト案内とURL提供")
        print("   📄 資料請求 → 資料提供とアンケート案内")
        print("   📍 展示場来場予約 → 予約URL案内")
        print("   💰 資金計画 → AI資金診断案内")
        print("   💬 チャット相談 → スタッフ対応案内")
        return True
    else:
        print("❌ デフォルト設定失敗")
        return False

# ==============================================================================
# 統合テスト実行クラス（指定文面対応版）
# ==============================================================================
class SpecifiedContentIntegrationTester:
    """指定文面対応統合テストクラス"""
    
    def __init__(self, api_base_url: str = "http://localhost:8080"):
        self.base_url = api_base_url
        self.test_user_id = f"test_user_{int(time.time())}"
        self.test_results = []
        
        # 🔧 指定文面テストケース
        self.specified_test_cases = [
            ("🤖 AI相談", "AI住まい相談開始案内", "🤖 AI住まい相談を開始します！"),
            ("🌐 AI住まいサイト", "サイト案内", "🌐 AI住まいサイトのご案内"),
            ("📄 資料請求", "資料提供案内", "📋ありがとうございます！こちらからご覧いただけます。"),
            ("📍 展示場来場　予約", "予約URL案内", "📍 展示場のご来場予約につきましては"),
            ("💰 資金計画", "資金診断案内", "💬 AI資金診断のご案内"),
            ("💬 チャット相談", "スタッフ対応案内", "💬 スタッフとのご相談")
        ]
    
    def test_specified_responses(self):
        """🔧 指定文面応答テスト"""
        print("📝 指定文面応答テスト")
        print("-" * 40)
        
        for button_text, description, expected_start in self.specified_test_cases:
            try:
                print(f"\n🧪 テスト: {button_text} ({description})")
                
                # API呼び出し
                test_data = {
                    "question": button_text,
                    "username": self.test_user_id,
                    "platform": "line"
                }
                
                response = requests.post(
                    f"{self.base_url}/chat",
                    json=test_data,
                    timeout=15
                )
                
                if response.status_code == 200:
                    result = response.json()
                    answer = result.get("answer", "")
                    
                    # 指定文面との一致チェック
                    if answer.startswith(expected_start):
                        print(f"   ✅ 指定文面確認: OK")
                        print(f"   📄 応答内容: {answer[:100]}...")
                        self.test_results.append({
                            "button": button_text, 
                            "status": "success",
                            "content_match": True
                        })
                    else:
                        print(f"   ❌ 指定文面不一致")
                        print(f"   📄 期待: {expected_start}")
                        print(f"   📄 実際: {answer[:100]}...")
                        self.test_results.append({
                            "button": button_text,
                            "status": "content_mismatch",
                            "expected": expected_start,
                            "actual": answer[:100]
                        })
                else:
                    print(f"   ❌ API呼び出し失敗: {response.status_code}")
                    self.test_results.append({
                        "button": button_text,
                        "status": "api_error",
                        "status_code": response.status_code
                    })
                    
                time.sleep(1)  # API制限対策
                
            except Exception as e:
                print(f"   💥 テストエラー: {e}")
                self.test_results.append({
                    "button": button_text,
                    "status": "error",
                    "error": str(e)
                })
    
    def test_follow_event(self):
        """友だち追加イベントテスト（シミュレーション）"""
        print("\n👥 友だち追加イベントテスト")
        print("-" * 40)
        
        # 実際のfollowイベントはLINE側からのWebhookなのでシミュレーション
        expected_welcome = "こんにちは！キノエデザインです。"
        print(f"📄 期待される歓迎メッセージ: {expected_welcome}")
        print("ℹ️ 実際のテストは LINE Developers Console の webhook テストで実行してください")
        
        self.test_results.append({
            "test": "follow_event",
            "status": "simulation",
            "note": "Webhook経由で実際のテストが必要"
        })
    
    def generate_test_report(self):
        """🔧 指定文面テストレポート生成"""
        print("\n📊 指定文面テスト結果サマリー")
        print("=" * 60)
        
        total = len([r for r in self.test_results if "button" in r])
        success = len([r for r in self.test_results if r.get("status") == "success"])
        content_match = len([r for r in self.test_results if r.get("content_match", False)])
        
        print(f"📈 総テスト数: {total}")
        print(f"✅ API成功: {success} ({success/total*100:.1f}%)")
        print(f"📝 指定文面一致: {content_match} ({content_match/total*100:.1f}%)")
        
        # 不一致の詳細表示
        mismatches = [r for r in self.test_results if r.get("status") == "content_mismatch"]
        if mismatches:
            print(f"\n❌ 文面不一致の詳細:")
            for mismatch in mismatches:
                print(f"   ボタン: {mismatch['button']}")
                print(f"   期待: {mismatch['expected']}")
                print(f"   実際: {mismatch['actual']}")
        
        # 成功率判定
        success_rate = content_match / total if total > 0 else 0
        
        if success_rate >= 0.9:
            print("\n🎉 指定文面テスト成功！本番デプロイ準備完了です。")
            return True
        elif success_rate >= 0.7:
            print("\n⚠️ 一部文面に問題がありますが、基本機能は動作します。")
            return True
        else:
            print("\n❌ 指定文面との一致率が低すぎます。修正が必要です。")
            return False
    
    def run_integration_tests(self):
        """🔧 指定文面統合テスト実行"""
        print(f"🧪 指定文面対応統合テスト開始")
        print(f"🌐 テスト対象: {self.base_url}")
        print(f"👤 テストユーザー: {self.test_user_id}")
        print(f"⏰ 開始時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        self.test_specified_responses()
        self.test_follow_event()
        
        success = self.generate_test_report()
        
        # 詳細レポート保存
        report_filename = f"specified_content_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_filename, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "test_target": self.base_url,
                "test_user_id": self.test_user_id,
                "test_cases": self.specified_test_cases,
                "results": self.test_results,
                "summary": {
                    "total_tests": len([r for r in self.test_results if "button" in r]),
                    "content_matches": len([r for r in self.test_results if r.get("content_match", False)]),
                    "overall_success": success
                }
            }, f, indent=2, ensure_ascii=False)
        
        print(f"\n📄 詳細レポート: {report_filename}")
        return success

# ==============================================================================
# LIFF設定ヘルパー（指定文面対応版）
# ==============================================================================
def generate_liff_setup_guide():
    """LIFF設定ガイド生成（指定文面対応版）"""
    
    guide = """
📱 LIFF（LINE Front-end Framework）設定手順（指定文面対応版）

🔧 **LINE Developers Console での設定**

1. **コンソールアクセス**
   https://developers.line.biz/console/

2. **チャンネル選択**
   既存のBotチャンネルを選択

3. **LIFF タブ**
   「LIFF」タブをクリック → 「新規作成」

4. **LIFF アプリ設定（資金計画用）**
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

🔗 **動作確認手順（指定文面対応）**
1. LINEアプリで「💰 資金計画」をタップ
2. "💰 資金計画" というメッセージが送信される
3. "💬 AI資金診断のご案内" で始まる応答が返る
4. 必要に応じてLIFF ページが表示される

📝 **指定文面チェックポイント**
- ボタン押下時の送信テキストが絵文字付きになっているか
- 応答内容が指定文面と完全一致しているか
- プライバシーポリシー等のURLが正しく含まれているか
    """
    
    print(guide)
    
    with open("LIFF_SETUP_GUIDE_SPECIFIED.md", "w", encoding="utf-8") as f:
        f.write(guide)
    
    print("📁 LIFF_SETUP_GUIDE_SPECIFIED.md に詳細手順を保存しました")

# ==============================================================================
# メイン実行部分
# ==============================================================================
if __name__ == "__main__":
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="指定文面対応リッチメニューセットアップ・テスト")
    parser.add_argument("--mode", choices=["richmenu", "test", "liff-guide", "all"], 
                       default="all", help="実行モード")
    parser.add_argument("--api-url", default="http://localhost:8080", 
                       help="APIベースURL")
    parser.add_argument("--skip-richmenu", action="store_true", 
                       help="リッチメニュー設定をスキップ")
    
    args = parser.parse_args()
    
    success = True
    
    if args.mode in ["richmenu", "all"] and not args.skip_richmenu:
        print("🎨 指定文面対応リッチメニュー設定開始...")
        richmenu_success = main()
        success = success and richmenu_success
        print()
    
    if args.mode in ["liff-guide", "all"]:
        print("📱 LIFF設定ガイド生成...")
        generate_liff_setup_guide()
        print()
    
    if args.mode in ["test", "all"]:
        print("🧪 指定文面統合テスト開始...")
        tester = SpecifiedContentIntegrationTester(args.api_url)
        test_success = tester.run_integration_tests()
        success = success and test_success
        print()
    
    if success:
        print("🎉 指定文面対応リッチメニューのセットアップ・テストが完了しました！")
        print("📱 LINEアプリで各ボタンをお試しください。")
        print("📝 指定文面通りに応答されることを確認してください。")
    else:
        print("⚠️ 一部の処理で問題が発生しました。ログを確認してください。")
        sys.exit(1)