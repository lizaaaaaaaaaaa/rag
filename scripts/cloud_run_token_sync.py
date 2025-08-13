#!/usr/bin/env python3
"""
Cloud Run Secret Manager 同期ツール（Web UI対応版）
python cloud_run_token_sync.py
"""

import requests
import json
import time
from datetime import datetime

class CloudRunTokenSync:
    def __init__(self):
        self.api_url = "https://rag-api-190389115361.asia-northeast1.run.app"
        self.working_token = None
        self.working_secret = None
        
        print("🔄 Cloud Run Secret Manager 同期ツール")
        print(f"📅 実行時刻: {datetime.now()}")
        print("=" * 60)
        print("💡 このツールは、正しいトークンをCloud Runに反映させます")
        print("=" * 60)

    def get_working_credentials(self):
        """動作するトークンとシークレットを取得"""
        print("\n🔑 動作確認済みの認証情報を入力してください")
        print("（先ほどローカルで403エラーが出たものでも構いません）")
        print("-" * 50)
        
        # トークン入力
        self.working_token = input("\n📱 Messaging API チャネルアクセストークン（長期）: ").strip()
        if not self.working_token:
            print("❌ トークンが入力されていません")
            return False
        
        # シークレット入力
        self.working_secret = input("🔒 チャネルシークレット: ").strip()
        if not self.working_secret:
            print("❌ シークレットが入力されていません")
            return False
        
        print(f"\n✅ 認証情報を取得しました")
        print(f"   トークン: {self.working_token[:20]}...")
        print(f"   シークレット: {self.working_secret[:10]}...")
        
        return True

    def test_cloud_run_current_status(self):
        """Cloud Runの現在の状態をテスト"""
        print(f"\n🏠 Cloud Run 現在の状態テスト")
        print("-" * 40)
        
        try:
            # 1. 基本的な生存確認
            response = requests.get(f"{self.api_url}/healthz", timeout=10)
            if response.status_code == 200:
                print("✅ Cloud Run サービス: 正常稼働中")
            else:
                print(f"⚠️ Cloud Run サービス: 異常 (HTTP {response.status_code})")
            
            # 2. LINE Bot状態確認
            response = requests.get(f"{self.api_url}/line/status", timeout=10)
            if response.status_code == 200:
                status = response.json()
                print("✅ LINE Bot API: 応答中")
                print(f"   LINE Bot設定: {status.get('line_bot_configured', False)}")
                print(f"   SDK利用可能: {status.get('line_sdk_available', False)}")
                print(f"   Webhook処理: {status.get('webhook_events_processed', 0)}件")
                return status
            else:
                print(f"❌ LINE Bot API: 異常 (HTTP {response.status_code})")
                return None
                
        except Exception as e:
            print(f"❌ Cloud Run接続エラー: {e}")
            return None

    def test_cloud_run_webhook(self):
        """Cloud Run経由でWebhook機能をテスト"""
        print(f"\n🔗 Cloud Run Webhook機能テスト")
        print("-" * 40)
        
        if not self.working_secret:
            print("❌ シークレットが設定されていません")
            return False
        
        # テストペイロード作成
        test_payload = {
            "destination": "test",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "test", "text": "Cloud Run テスト"},
                "timestamp": int(time.time() * 1000),
                "source": {"type": "user", "userId": "test-user"},
                "replyToken": "test-token"
            }]
        }
        
        try:
            # 正しい署名を生成
            import hmac, hashlib, base64
            body_json = json.dumps(test_payload, separators=(',', ':'))
            signature = base64.b64encode(
                hmac.new(
                    self.working_secret.encode('utf-8'),
                    body_json.encode('utf-8'),
                    hashlib.sha256
                ).digest()
            ).decode('utf-8')
            
            # Webhookテスト実行
            response = requests.post(
                f"{self.api_url}/line/webhook",
                json=test_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Line-Signature": signature
                },
                timeout=15
            )
            
            print(f"Webhook レスポンス: HTTP {response.status_code}")
            if response.status_code in [200, 400]:
                print("✅ Cloud Run Webhook: 正常動作")
                print("💡 これは、Cloud Runの認証情報が正しいことを示しています")
                return True
            elif response.status_code == 403:
                print("❌ Cloud Run Webhook: 署名エラー")
                print("💡 Cloud RunのCHANNEL_SECRETが古い可能性があります")
                return False
            else:
                print(f"⚠️ Cloud Run Webhook: 予期しないレスポンス")
                print(f"   レスポンス: {response.text[:200]}...")
                return False
                
        except Exception as e:
            print(f"❌ Webhook テストエラー: {e}")
            return False

    def test_direct_line_api_from_cloud_run(self):
        """Cloud Run経由でLINE APIにアクセスできるかテスト"""
        print(f"\n📱 Cloud Run → LINE API 接続テスト")
        print("-" * 40)
        
        try:
            # Cloud RunのAPIを使ってLINE APIテストを依頼
            test_url = f"{self.api_url}/line/test"
            response = requests.post(test_url, timeout=15)
            
            if response.status_code == 200:
                result = response.json()
                print("✅ Cloud Run → LINE API: 成功")
                print(f"   テスト結果: {result.get('status', 'unknown')}")
                return True
            else:
                print(f"❌ Cloud Run → LINE API: 失敗 (HTTP {response.status_code})")
                return False
                
        except Exception as e:
            print(f"❌ Cloud Run → LINE API テストエラー: {e}")
            return False

    def provide_secret_manager_update_guide(self):
        """Secret Manager更新のガイド（Web UI版）"""
        print(f"\n🔧 Secret Manager 更新ガイド（Web UI版）")
        print("=" * 50)
        
        print("Google Cloud Console を使用してSecret Managerを更新します：")
        print()
        
        print("🌐 STEP 1: Google Cloud Console にアクセス")
        print("   https://console.cloud.google.com/")
        print("   プロジェクト: rag-cloud-project")
        print()
        
        print("🔐 STEP 2: Secret Manager を開く")
        print("   左メニュー → 「セキュリティ」 → 「Secret Manager」")
        print("   または直接アクセス:")
        print("   https://console.cloud.google.com/security/secret-manager?project=rag-cloud-project")
        print()
        
        print("📝 STEP 3: LINE_CHANNEL_ACCESS_TOKEN を更新")
        print("   1. 「LINE_CHANNEL_ACCESS_TOKEN」をクリック")
        print("   2. 「新しいバージョンを作成」をクリック")
        print("   3. 以下のトークンを貼り付け:")
        print(f"      {self.working_token}")
        print("   4. 「バージョンを作成」をクリック")
        print()
        
        print("🔒 STEP 4: LINE_CHANNEL_SECRET を更新")
        print("   1. 「LINE_CHANNEL_SECRET」をクリック")
        print("   2. 「新しいバージョンを作成」をクリック")
        print("   3. 以下のシークレットを貼り付け:")
        print(f"      {self.working_secret}")
        print("   4. 「バージョンを作成」をクリック")
        print()
        
        print("🚀 STEP 5: Cloud Run サービスを再起動")
        print("   1. Cloud Run コンソールにアクセス:")
        print("   https://console.cloud.google.com/run?project=rag-cloud-project")
        print("   2. 「rag-api」サービスをクリック")
        print("   3. 「編集してデプロイ」をクリック")
        print("   4. 何も変更せずに「デプロイ」をクリック")
        print("   5. 新しいリビジョンが作成され、最新のSecretを参照します")

    def wait_for_manual_update(self):
        """手動更新の完了を待機"""
        print(f"\n⏳ Secret Manager更新完了の確認")
        print("-" * 40)
        
        print("上記の手順でSecret Managerを更新してください。")
        print("更新が完了したら、以下を入力してください：")
        
        while True:
            user_input = input("\nSecret Manager更新が完了しましたか？ (y/N): ").strip().lower()
            if user_input == 'y':
                print("✅ 更新完了を確認しました")
                break
            elif user_input == 'n' or user_input == '':
                print("⏳ 更新が完了するまでお待ちください...")
                continue
            else:
                print("'y' または 'n' を入力してください")

    def verify_final_status(self):
        """最終的な動作確認"""
        print(f"\n🎯 最終動作確認")
        print("-" * 30)
        
        print("Cloud Runサービスの再起動を待っています...")
        time.sleep(10)
        
        # 1. Cloud Run状態確認
        status = self.test_cloud_run_current_status()
        if not status:
            print("❌ Cloud Runの状態確認に失敗しました")
            return False
        
        # 2. Webhook機能確認
        webhook_ok = self.test_cloud_run_webhook()
        
        # 3. 結果判定
        if webhook_ok:
            print(f"\n🎉 修復成功！")
            print("✅ Cloud RunでLINE Botが正常に動作しています")
            print("\n📱 次の確認:")
            print("1. LINEアプリでリッチメニューをタップ")
            print("2. メッセージが送信されて応答があることを確認")
            return True
        else:
            print(f"\n⚠️ まだ問題があります")
            print("以下を確認してください:")
            print("1. Secret Managerの値が正しく保存されているか")
            print("2. Cloud Runの新しいリビジョンがデプロイされているか")
            print("3. 5-10分待ってから再度テスト")
            return False

    def run_sync_process(self):
        """同期プロセスを実行"""
        print("🚀 Cloud Run Secret Manager 同期プロセス開始")
        
        # Step 1: 認証情報取得
        if not self.get_working_credentials():
            print("❌ 認証情報の取得に失敗しました")
            return
        
        # Step 2: Cloud Run現状確認
        current_status = self.test_cloud_run_current_status()
        if not current_status:
            print("❌ Cloud Runに接続できません")
            return
        
        # Step 3: Webhook機能テスト
        webhook_works = self.test_cloud_run_webhook()
        
        if webhook_works:
            print("\n🎉 実は既に正常動作しています！")
            print("Cloud Runの認証情報は最新のようです。")
            print("リッチメニューが反応しない場合、LINE Official Account Manager の設定を確認してください。")
            return
        
        # Step 4: Secret Manager更新ガイド
        self.provide_secret_manager_update_guide()
        
        # Step 5: 手動更新待ち
        self.wait_for_manual_update()
        
        # Step 6: 最終確認
        self.verify_final_status()

def main():
    sync_tool = CloudRunTokenSync()
    sync_tool.run_sync_process()

if __name__ == "__main__":
    main()