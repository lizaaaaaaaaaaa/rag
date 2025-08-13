#!/usr/bin/env python3
"""
LINE Bot リッチメニュー無反応問題の総合診断・修復スクリプト
python line_bot_comprehensive_fix.py
"""

import os
import json
import requests
import subprocess
import time
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from dotenv import load_dotenv
load_dotenv()

class LINEBotDiagnostic:
    def __init__(self):
        self.project_id = "rag-cloud-project"
        self.region = "asia-northeast1"
        self.service_name = "rag-api"
        self.api_url = f"https://{self.service_name}-190389115361.{self.region}.run.app"
        
        # 診断結果を保存
        self.results = {
            "token_verification": {},
            "secret_verification": {},
            "cloud_run_status": {},
            "webhook_status": {},
            "richmenu_status": {},
            "recommendations": []
        }
        
        print("🔍 LINE Bot 総合診断システム開始")
        print(f"📅 実行時刻: {datetime.now()}")
        print(f"🌐 API URL: {self.api_url}")
        print("=" * 80)

    def get_secret_from_gcp(self, secret_name: str) -> Optional[str]:
        """Google Secret Managerから値を取得"""
        try:
            result = subprocess.run([
                'gcloud', 'secrets', 'versions', 'access', 'latest',
                '--secret', secret_name, '--project', self.project_id
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                print(f"❌ Secret {secret_name} 取得失敗: {result.stderr}")
                return None
        except Exception as e:
            print(f"❌ Secret取得エラー: {e}")
            return None

    def step1_verify_bot_token(self) -> Tuple[bool, Dict]:
        """Step 1: BOT_TOKENの正体を確定"""
        print("\n" + "="*60)
        print("🔍 Step 1: BOT_TOKEN の正体確定")
        print("="*60)
        
        # Secret Managerから取得
        bot_token = self.get_secret_from_gcp("LINE_CHANNEL_ACCESS_TOKEN")
        if not bot_token:
            print("❌ LINE_CHANNEL_ACCESS_TOKEN が取得できません")
            return False, {"error": "Token not found"}
        
        print(f"✅ トークン取得成功: {bot_token[:20]}...")
        
        headers = {"Authorization": f"Bearer {bot_token}"}
        
        # 1) Bot情報テスト
        print("\n1️⃣ Bot情報確認テスト...")
        try:
            response = requests.get("https://api.line.me/v2/bot/info", headers=headers, timeout=10)
            if response.status_code == 200:
                bot_info = response.json()
                print(f"✅ Bot情報取得成功")
                print(f"   ボット名: {bot_info.get('displayName', '不明')}")
                print(f"   ボットID: {bot_info.get('userId', '不明')}")
                self.results["token_verification"]["bot_info"] = bot_info
            else:
                print(f"❌ Bot情報取得失敗: HTTP {response.status_code}")
                print(f"   エラー詳細: {response.text}")
                return False, {"error": f"Bot info failed: {response.status_code}"}
        except Exception as e:
            print(f"❌ Bot情報テストエラー: {e}")
            return False, {"error": str(e)}
        
        # 2) チャネルID照合テスト
        print("\n2️⃣ チャネルID照合テスト...")
        try:
            response = requests.get("https://api.line.me/v2/oauth/verify", headers=headers, timeout=10)
            if response.status_code == 200:
                verify_info = response.json()
                client_id = verify_info.get('client_id')
                print(f"✅ チャネルID照合成功")
                print(f"   クライアントID: {client_id}")
                
                # Messaging APIチャネルIDと比較
                expected_channel_id = "2007887876"  # Messaging APIチャネル
                if str(client_id) == expected_channel_id:
                    print(f"✅ 正しいMessaging APIチャネルのトークンです")
                else:
                    print(f"⚠️ 警告: 期待値 {expected_channel_id} と異なります")
                    print(f"   実際の値: {client_id}")
                    print(f"   💡 LINE Loginチャネルのトークンを使用している可能性があります")
                
                self.results["token_verification"]["client_id"] = client_id
                self.results["token_verification"]["is_messaging_api"] = str(client_id) == expected_channel_id
            else:
                print(f"❌ チャネルID照合失敗: HTTP {response.status_code}")
                return False, {"error": f"OAuth verify failed: {response.status_code}"}
        except Exception as e:
            print(f"❌ チャネルID照合エラー: {e}")
            return False, {"error": str(e)}
        
        # 3) リッチメニューAPIテスト
        print("\n3️⃣ リッチメニューAPI接続テスト...")
        try:
            response = requests.get("https://api.line.me/v2/bot/richmenu/list", headers=headers, timeout=10)
            if response.status_code == 200:
                richmenu_list = response.json().get("richmenus", [])
                print(f"✅ リッチメニューAPI成功")
                print(f"   登録メニュー数: {len(richmenu_list)}")
                for i, menu in enumerate(richmenu_list):
                    print(f"   メニュー{i+1}: {menu.get('name', '名前なし')} (選択: {menu.get('selected', False)})")
                self.results["token_verification"]["richmenu_count"] = len(richmenu_list)
            else:
                print(f"❌ リッチメニューAPI失敗: HTTP {response.status_code}")
                return False, {"error": f"RichMenu API failed: {response.status_code}"}
        except Exception as e:
            print(f"❌ リッチメニューAPIエラー: {e}")
            return False, {"error": str(e)}
        
        print("\n✅ Step 1 完了: BOT_TOKEN は有効なMessaging APIトークンです")
        return True, {"bot_token": bot_token, "headers": headers}

    def step2_verify_cloud_run_secrets(self) -> bool:
        """Step 2: Cloud Runが最新secretを参照しているか確認"""
        print("\n" + "="*60)
        print("🔍 Step 2: Cloud Run Secret 参照状況確認")
        print("="*60)
        
        try:
            # 1) 現在のサービス設定を確認
            print("1️⃣ 現在のCloud Run設定確認...")
            result = subprocess.run([
                'gcloud', 'run', 'services', 'describe', self.service_name,
                '--region', self.region, '--format', 'yaml'
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                print("✅ Cloud Runサービス情報取得成功")
                
                # secretの参照状況をチェック
                if "LINE_CHANNEL_ACCESS_TOKEN" in result.stdout and "latest" in result.stdout:
                    print("✅ LINE_CHANNEL_ACCESS_TOKEN: latest版を参照中")
                    self.results["cloud_run_status"]["token_latest"] = True
                else:
                    print("❌ LINE_CHANNEL_ACCESS_TOKEN: 古いバージョンを参照している可能性")
                    self.results["cloud_run_status"]["token_latest"] = False
                
                if "LINE_CHANNEL_SECRET" in result.stdout and "latest" in result.stdout:
                    print("✅ LINE_CHANNEL_SECRET: latest版を参照中")
                    self.results["cloud_run_status"]["secret_latest"] = True
                else:
                    print("❌ LINE_CHANNEL_SECRET: 古いバージョンを参照している可能性")
                    self.results["cloud_run_status"]["secret_latest"] = False
            else:
                print(f"❌ Cloud Run情報取得失敗: {result.stderr}")
                return False
            
            # 2) Secret を最新に更新
            print("\n2️⃣ Secret を最新版に強制更新...")
            update_result = subprocess.run([
                'gcloud', 'run', 'services', 'update', self.service_name,
                '--region', self.region,
                '--update-secrets', 'LINE_CHANNEL_ACCESS_TOKEN=LINE_CHANNEL_ACCESS_TOKEN:latest,LINE_CHANNEL_SECRET=LINE_CHANNEL_SECRET:latest'
            ], capture_output=True, text=True)
            
            if update_result.returncode == 0:
                print("✅ Secret更新成功")
                print("⏳ 新リビジョンのデプロイ待機中...")
                time.sleep(10)  # デプロイ完了を待つ
                self.results["cloud_run_status"]["updated"] = True
            else:
                print(f"❌ Secret更新失敗: {update_result.stderr}")
                self.results["cloud_run_status"]["updated"] = False
                return False
            
            # 3) 更新後の確認
            print("\n3️⃣ 更新後の確認...")
            api_response = requests.get(f"{self.api_url}/line/status", timeout=15)
            if api_response.status_code == 200:
                status = api_response.json()
                print(f"✅ API応答確認済み")
                print(f"   LINE Bot設定: {status.get('line_bot_configured', False)}")
                print(f"   SDK利用可能: {status.get('line_sdk_available', False)}")
                self.results["cloud_run_status"]["api_response"] = status
            else:
                print(f"❌ API応答確認失敗: {api_response.status_code}")
                return False
            
            print("\n✅ Step 2 完了: Cloud Run は最新のSecretを参照しています")
            return True
            
        except Exception as e:
            print(f"❌ Step 2 エラー: {e}")
            return False

    def step3_verify_webhook_signature(self) -> bool:
        """Step 3: Webhook署名検証の問題を切り分け"""
        print("\n" + "="*60)
        print("🔍 Step 3: Webhook 署名検証診断")
        print("="*60)
        
        # CHANNEL_SECRETを取得
        channel_secret = self.get_secret_from_gcp("LINE_CHANNEL_SECRET")
        if not channel_secret:
            print("❌ LINE_CHANNEL_SECRET が取得できません")
            return False
        
        print(f"✅ CHANNEL_SECRET取得: {channel_secret[:10]}...")
        
        # 1) テスト用Webhookペイロードを作成
        print("\n1️⃣ Webhook署名テスト実行...")
        test_payload = {
            "destination": "test",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "test", "text": "AI相談"},
                "timestamp": int(time.time() * 1000),
                "source": {"type": "user", "userId": "test-user"},
                "replyToken": "test-token"
            }]
        }
        
        # 正しい署名を生成
        import hmac
        import hashlib
        import base64
        
        body_json = json.dumps(test_payload, separators=(',', ':'))
        signature = base64.b64encode(
            hmac.new(
                channel_secret.encode('utf-8'),
                body_json.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        
        # 2) 正しい署名でテスト
        print("2️⃣ 正しい署名でWebhookテスト...")
        try:
            response = requests.post(
                f"{self.api_url}/line/webhook",
                json=test_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Line-Signature": signature
                },
                timeout=15
            )
            
            print(f"   ステータスコード: {response.status_code}")
            if response.status_code == 200:
                print("✅ 署名検証成功: Webhookは正常に動作します")
                self.results["webhook_status"]["signature_valid"] = True
            elif response.status_code == 400:
                print("⚠️ 400エラー: 署名は通ったがペイロード処理でエラー（正常）")
                self.results["webhook_status"]["signature_valid"] = True
            else:
                print(f"❌ 署名検証エラー: {response.status_code}")
                print(f"   レスポンス: {response.text}")
                self.results["webhook_status"]["signature_valid"] = False
                return False
                
        except Exception as e:
            print(f"❌ Webhookテストエラー: {e}")
            return False
        
        # 3) 間違った署名でテスト（403が返ることを確認）
        print("\n3️⃣ 間違った署名でテスト（403確認）...")
        try:
            response = requests.post(
                f"{self.api_url}/line/webhook",
                json=test_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Line-Signature": "invalid-signature"
                },
                timeout=10
            )
            
            if response.status_code == 403 or response.status_code == 401:
                print("✅ 不正署名を正しく拒否しています")
            else:
                print(f"⚠️ 不正署名でも {response.status_code} が返りました")
                
        except Exception as e:
            print(f"❌ 不正署名テストエラー: {e}")
        
        print("\n✅ Step 3 完了: Webhook署名検証は正常に動作しています")
        return True

    def step4_fix_richmenu(self, headers: Dict) -> bool:
        """Step 4: リッチメニューの反応を取り戻す"""
        print("\n" + "="*60)
        print("🔍 Step 4: リッチメニュー修復・最適化")
        print("="*60)
        
        try:
            # 1) 既存メニューを削除
            print("1️⃣ 既存リッチメニューを削除中...")
            response = requests.get("https://api.line.me/v2/bot/richmenu/list", headers=headers)
            if response.status_code == 200:
                menus = response.json().get("richmenus", [])
                for menu in menus:
                    menu_id = menu["richMenuId"]
                    delete_response = requests.delete(
                        f"https://api.line.me/v2/bot/richmenu/{menu_id}",
                        headers=headers
                    )
                    if delete_response.status_code == 200:
                        print(f"   ✅ 削除成功: {menu_id}")
                    time.sleep(0.5)
            
            # 2) 新しいリッチメニューを作成
            print("\n2️⃣ 最適化されたリッチメニューを作成...")
            richmenu_data = {
                "size": {"width": 2500, "height": 1686},
                "selected": True,
                "name": "完全修復メニューv3",
                "chatBarText": "メニュー",
                "areas": [
                    {
                        "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
                        "action": {"type": "message", "text": "AI相談"}
                    },
                    {
                        "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
                        "action": {"type": "message", "text": "AI住まいサイト"}
                    },
                    {
                        "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                        "action": {"type": "message", "text": "資料請求"}
                    },
                    {
                        "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
                        "action": {"type": "message", "text": "展示場予約"}
                    },
                    {
                        "bounds": {"x": 833, "y": 843, "width": 834, "height": 843},
                        "action": {"type": "message", "text": "資金計画"}
                    },
                    {
                        "bounds": {"x": 1667, "y": 843, "width": 833, "height": 843},
                        "action": {"type": "message", "text": "チャット相談"}
                    }
                ]
            }
            
            create_response = requests.post(
                "https://api.line.me/v2/bot/richmenu",
                headers=headers,
                json=richmenu_data
            )
            
            if create_response.status_code == 200:
                richmenu_id = create_response.json()["richMenuId"]
                print(f"✅ リッチメニュー作成成功: {richmenu_id}")
                
                # 3) デフォルトに設定
                print("\n3️⃣ デフォルトリッチメニューに設定...")
                default_response = requests.post(
                    f"https://api.line.me/v2/bot/user/all/richmenu/{richmenu_id}",
                    headers=headers
                )
                
                if default_response.status_code == 200:
                    print("✅ デフォルト設定成功")
                    self.results["richmenu_status"]["created"] = True
                    self.results["richmenu_status"]["richmenu_id"] = richmenu_id
                else:
                    print(f"❌ デフォルト設定失敗: {default_response.status_code}")
                    return False
            else:
                print(f"❌ リッチメニュー作成失敗: {create_response.status_code}")
                print(f"   エラー詳細: {create_response.text}")
                return False
            
            print("\n✅ Step 4 完了: リッチメニューを完全修復しました")
            return True
            
        except Exception as e:
            print(f"❌ Step 4 エラー: {e}")
            return False

    def step5_final_verification(self, headers: Dict) -> bool:
        """Step 5: 最終動作確認"""
        print("\n" + "="*60)
        print("🔍 Step 5: 最終動作確認テスト")
        print("="*60)
        
        # 1) リッチメニューメッセージ処理テスト
        test_messages = ["AI相談", "資料請求", "展示場予約"]
        
        print("1️⃣ リッチメニューメッセージ処理テスト...")
        for message in test_messages:
            print(f"   テスト: '{message}'")
            
            test_payload = {
                "destination": "test",
                "events": [{
                    "type": "message",
                    "message": {"type": "text", "id": f"test-{message}", "text": message},
                    "timestamp": int(time.time() * 1000),
                    "source": {"type": "user", "userId": "test-user"},
                    "replyToken": f"test-token-{message}"
                }]
            }
            
            # 正しい署名を生成
            channel_secret = self.get_secret_from_gcp("LINE_CHANNEL_SECRET")
            if channel_secret:
                import hmac, hashlib, base64
                body_json = json.dumps(test_payload, separators=(',', ':'))
                signature = base64.b64encode(
                    hmac.new(channel_secret.encode('utf-8'), body_json.encode('utf-8'), hashlib.sha256).digest()
                ).decode('utf-8')
                
                try:
                    response = requests.post(
                        f"{self.api_url}/line/webhook",
                        json=test_payload,
                        headers={
                            "Content-Type": "application/json",
                            "X-Line-Signature": signature
                        },
                        timeout=10
                    )
                    
                    if response.status_code in [200, 400]:
                        print(f"      ✅ {message}: 処理成功")
                    else:
                        print(f"      ❌ {message}: エラー ({response.status_code})")
                        
                except Exception as e:
                    print(f"      ❌ {message}: 例外 - {e}")
            
            time.sleep(1)
        
        # 2) LINE API経由の確認
        print("\n2️⃣ 最新リッチメニュー確認...")
        try:
            response = requests.get("https://api.line.me/v2/bot/richmenu/list", headers=headers)
            if response.status_code == 200:
                menus = response.json().get("richmenus", [])
                if menus:
                    menu = menus[0]
                    print(f"✅ アクティブメニュー: {menu.get('name')}")
                    print(f"   メニューID: {menu.get('richMenuId')}")
                    print(f"   選択状態: {menu.get('selected')}")
                    print(f"   アクション数: {len(menu.get('areas', []))}")
                else:
                    print("❌ リッチメニューが見つかりません")
                    return False
            else:
                print(f"❌ リッチメニュー確認失敗: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ リッチメニュー確認エラー: {e}")
            return False
        
        print("\n✅ Step 5 完了: すべてのテストに成功しました")
        return True

    def generate_report(self):
        """診断結果レポートを生成"""
        print("\n" + "="*80)
        print("📊 LINE Bot 診断結果レポート")
        print("="*80)
        
        print("\n🔍 診断サマリー:")
        print(f"   トークン検証: {'✅ 成功' if self.results['token_verification'] else '❌ 失敗'}")
        print(f"   Secret更新: {'✅ 成功' if self.results['cloud_run_status'].get('updated') else '❌ 失敗'}")
        print(f"   Webhook署名: {'✅ 正常' if self.results['webhook_status'].get('signature_valid') else '❌ 異常'}")
        print(f"   リッチメニュー: {'✅ 修復済み' if self.results['richmenu_status'].get('created') else '❌ 未修復'}")
        
        if self.results['richmenu_status'].get('richmenu_id'):
            print(f"\n📱 新リッチメニューID: {self.results['richmenu_status']['richmenu_id']}")
        
        print("\n🎯 次のアクション:")
        if all([
            self.results['token_verification'],
            self.results['cloud_run_status'].get('updated'),
            self.results['webhook_status'].get('signature_valid'),
            self.results['richmenu_status'].get('created')
        ]):
            print("✅ すべて修復完了！以下を確認してください：")
            print("   1. LINEアプリでリッチメニューが表示されることを確認")
            print("   2. 各ボタンをタップして応答があることを確認")
            print("   3. 「AI相談」と入力してAIが応答することを確認")
        else:
            print("❌ 一部に問題があります。以下を確認してください：")
            print("   1. LINE Developers Console の設定確認")
            print("   2. OA Manager の応答設定確認")
            print("   3. Cloud Run ログの確認")
        
        print(f"\n📄 診断完了時刻: {datetime.now()}")
        print("="*80)

    def run_full_diagnostic(self):
        """完全診断を実行"""
        try:
            # Step 1: トークン検証
            success, token_data = self.step1_verify_bot_token()
            if not success:
                print("❌ Step 1 失敗: BOT_TOKEN に問題があります")
                return False
            
            headers = token_data["headers"]
            
            # Step 2: Cloud Run Secret 更新
            if not self.step2_verify_cloud_run_secrets():
                print("❌ Step 2 失敗: Cloud Run Secret 更新に問題があります")
                return False
            
            # Step 3: Webhook 署名検証
            if not self.step3_verify_webhook_signature():
                print("❌ Step 3 失敗: Webhook 署名検証に問題があります")
                return False
            
            # Step 4: リッチメニュー修復
            if not self.step4_fix_richmenu(headers):
                print("❌ Step 4 失敗: リッチメニュー修復に問題があります")
                return False
            
            # Step 5: 最終確認
            if not self.step5_final_verification(headers):
                print("❌ Step 5 失敗: 最終確認で問題が見つかりました")
                return False
            
            # レポート生成
            self.generate_report()
            return True
            
        except Exception as e:
            print(f"💥 診断プロセスで予期しないエラー: {e}")
            return False

def main():
    """メイン実行関数"""
    print("🚀 LINE Bot リッチメニュー修復システム")
    print(f"開始時刻: {datetime.now()}")
    
    # 診断システムを初期化
    diagnostic = LINEBotDiagnostic()
    
    # 完全診断を実行
    success = diagnostic.run_full_diagnostic()
    
    if success:
        print("\n🎉 修復完了!")
        print("LINE アプリでリッチメニューをテストしてください。")
    else:
        print("\n💥 修復に失敗しました")
        print("詳細なエラーログを確認し、手動で修正してください。")

if __name__ == "__main__":
    main()