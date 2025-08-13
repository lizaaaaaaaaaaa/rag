#!/usr/bin/env python3
"""
LINE Bot 直接API修復スクリプト（ローカル環境・gcloud不要版）
Windows環境対応、TOKEN直接入力方式
python line_bot_direct_api_fix.py
"""

import os
import json
import requests
import time
import hmac
import hashlib
import base64
from datetime import datetime
from typing import Dict, Any, Optional

class DirectAPILineBotFixer:
    def __init__(self):
        self.api_url = "https://rag-api-190389115361.asia-northeast1.run.app"
        self.line_bot_token = None
        self.line_channel_secret = None
        
        print("🔧 LINE Bot 直接API修復システム（Windows対応版）")
        print(f"📅 実行時刻: {datetime.now()}")
        print("=" * 70)
        print("ℹ️  このツールはローカル環境のgcloudコマンドを使用せず、")
        print("   直接APIで診断・修復を行います。")
        print("=" * 70)

    def get_tokens_from_user(self) -> bool:
        """ユーザーからトークンを直接入力してもらう"""
        print("\n🔑 LINE認証情報の入力")
        print("=" * 40)
        print("以下の情報を入力してください：")
        print("1. LINE Developers Console にアクセス")
        print("   https://developers.line.biz/console/")
        print("2. Messaging APIチャネルを選択")
        print("3. 必要な情報をコピーして入力")
        
        print("\n📋 必要な情報:")
        print("   - チャネルアクセストークン（長期）")
        print("   - チャネルシークレット")
        
        print("\n" + "-" * 40)
        
        # チャネルアクセストークンの入力
        while not self.line_bot_token:
            token_input = input("\n🔐 チャネルアクセストークン（長期）を入力してください: ").strip()
            if token_input:
                if self.validate_token_format(token_input):
                    self.line_bot_token = token_input
                    print("✅ トークン形式OK")
                else:
                    print("❌ トークン形式が不正です。正しいトークンを入力してください。")
            else:
                print("❌ トークンが入力されていません。")
        
        # チャネルシークレットの入力
        while not self.line_channel_secret:
            secret_input = input("\n🔒 チャネルシークレットを入力してください: ").strip()
            if secret_input:
                if len(secret_input) >= 20:  # 基本的な長さチェック
                    self.line_channel_secret = secret_input
                    print("✅ シークレット形式OK")
                else:
                    print("❌ シークレットが短すぎます。正しいシークレットを入力してください。")
            else:
                print("❌ シークレットが入力されていません。")
        
        return True

    def validate_token_format(self, token: str) -> bool:
        """トークンの基本的な形式チェック"""
        # LINE Bot トークンの基本的な特徴をチェック
        if len(token) < 100:  # 短すぎる
            return False
        if not any(c.isalpha() for c in token):  # 文字が含まれていない
            return False
        if not any(c.isdigit() for c in token):  # 数字が含まれていない
            return False
        return True

    def test_line_api_connection(self) -> bool:
        """LINE API接続テスト"""
        print("\n🌐 LINE API接続テスト")
        print("=" * 30)
        
        headers = {"Authorization": f"Bearer {self.line_bot_token}"}
        
        try:
            # 1) Bot情報取得テスト
            print("1️⃣ Bot情報取得テスト...")
            response = requests.get("https://api.line.me/v2/bot/info", headers=headers, timeout=10)
            
            if response.status_code == 200:
                bot_info = response.json()
                print(f"✅ Bot情報取得成功")
                print(f"   ボット名: {bot_info.get('displayName', '不明')}")
                print(f"   ボットID: {bot_info.get('userId', '不明')}")
                return True
            elif response.status_code == 401:
                print("❌ 認証エラー: トークンが無効です")
                print("💡 LINE Developers Console で新しいトークンを発行してください")
                return False
            elif response.status_code == 403:
                print("❌ 権限エラー: Messaging APIの権限がありません")
                print("💡 LINE Loginのトークンではなく、Messaging APIのトークンを使用してください")
                return False
            else:
                print(f"❌ 予期しないエラー: HTTP {response.status_code}")
                print(f"   レスポンス: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ 接続エラー: {e}")
            return False

    def test_oauth_verify(self) -> Dict[str, Any]:
        """チャネルID確認テスト"""
        print("\n🔍 チャネルID確認テスト")
        print("=" * 30)
        
        headers = {"Authorization": f"Bearer {self.line_bot_token}"}
        
        try:
            response = requests.get("https://api.line.me/v2/oauth/verify", headers=headers, timeout=10)
            
            if response.status_code == 200:
                verify_info = response.json()
                client_id = verify_info.get('client_id')
                print(f"✅ チャネルID確認成功")
                print(f"   クライアントID: {client_id}")
                
                # 期待されるMessaging APIチャネルIDと比較
                expected_channel_id = "2007887876"
                if str(client_id) == expected_channel_id:
                    print(f"✅ 正しいMessaging APIチャネルのトークンです")
                    return {"success": True, "client_id": client_id, "is_correct": True}
                else:
                    print(f"⚠️ 警告: 期待値 {expected_channel_id} と異なります")
                    print(f"💡 LINE Loginチャネルのトークンを使用している可能性があります")
                    return {"success": True, "client_id": client_id, "is_correct": False}
            else:
                print(f"❌ チャネルID確認失敗: HTTP {response.status_code}")
                return {"success": False, "error": response.status_code}
                
        except Exception as e:
            print(f"❌ チャネルID確認エラー: {e}")
            return {"success": False, "error": str(e)}

    def test_webhook_signature(self) -> bool:
        """Webhook署名検証テスト"""
        print("\n🔐 Webhook署名検証テスト")
        print("=" * 30)
        
        # テスト用ペイロード
        test_payload = {
            "destination": "test",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": "test", "text": "テスト"},
                "timestamp": int(time.time() * 1000),
                "source": {"type": "user", "userId": "test-user"},
                "replyToken": "test-token"
            }]
        }
        
        try:
            # 正しい署名を生成
            body_json = json.dumps(test_payload, separators=(',', ':'))
            signature = base64.b64encode(
                hmac.new(
                    self.line_channel_secret.encode('utf-8'),
                    body_json.encode('utf-8'),
                    hashlib.sha256
                ).digest()
            ).decode('utf-8')
            
            print("1️⃣ 正しい署名でWebhookテスト...")
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
            if response.status_code in [200, 400]:
                print("✅ 署名検証成功: Webhookは正常に動作します")
                return True
            else:
                print(f"❌ 署名検証エラー: {response.status_code}")
                print(f"   レスポンス: {response.text[:200]}...")
                return False
                
        except Exception as e:
            print(f"❌ Webhookテストエラー: {e}")
            return False

    def fix_richmenu(self) -> bool:
        """リッチメニューの修復"""
        print("\n📱 リッチメニュー修復")
        print("=" * 30)
        
        headers = {"Authorization": f"Bearer {self.line_bot_token}"}
        
        try:
            # 1) 既存メニューの削除
            print("1️⃣ 既存リッチメニュー削除中...")
            response = requests.get("https://api.line.me/v2/bot/richmenu/list", headers=headers)
            
            if response.status_code == 200:
                menus = response.json().get("richmenus", [])
                print(f"   削除対象: {len(menus)}個のメニュー")
                
                for menu in menus:
                    menu_id = menu["richMenuId"]
                    delete_response = requests.delete(
                        f"https://api.line.me/v2/bot/richmenu/{menu_id}",
                        headers=headers
                    )
                    if delete_response.status_code == 200:
                        print(f"   ✅ 削除成功: {menu_id[:20]}...")
                    time.sleep(0.5)
            
            # 2) 新しいリッチメニューの作成
            print("\n2️⃣ 新しいリッチメニュー作成中...")
            richmenu_data = {
                "size": {"width": 2500, "height": 1686},
                "selected": True,
                "name": f"DirectAPI修復メニュー_{int(time.time())}",
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
                print(f"✅ リッチメニュー作成成功")
                print(f"   メニューID: {richmenu_id}")
                
                # 3) デフォルト設定
                print("\n3️⃣ デフォルト設定中...")
                default_response = requests.post(
                    f"https://api.line.me/v2/bot/user/all/richmenu/{richmenu_id}",
                    headers=headers
                )
                
                if default_response.status_code == 200:
                    print("✅ デフォルト設定成功")
                    return True
                else:
                    print(f"❌ デフォルト設定失敗: {default_response.status_code}")
                    return False
            else:
                print(f"❌ リッチメニュー作成失敗: {create_response.status_code}")
                print(f"   エラー詳細: {create_response.text}")
                return False
                
        except Exception as e:
            print(f"❌ リッチメニュー修復エラー: {e}")
            return False

    def test_message_processing(self) -> bool:
        """メッセージ処理テスト"""
        print("\n💬 メッセージ処理テスト")
        print("=" * 30)
        
        test_messages = ["AI相談", "資料請求", "こんにちは"]
        success_count = 0
        
        for message in test_messages:
            print(f"   テスト: '{message}'")
            
            # テストペイロード作成
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
            
            try:
                # 署名生成
                body_json = json.dumps(test_payload, separators=(',', ':'))
                signature = base64.b64encode(
                    hmac.new(
                        self.line_channel_secret.encode('utf-8'),
                        body_json.encode('utf-8'),
                        hashlib.sha256
                    ).digest()
                ).decode('utf-8')
                
                # Webhook送信
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
                    success_count += 1
                else:
                    print(f"      ❌ {message}: エラー ({response.status_code})")
                    
            except Exception as e:
                print(f"      ❌ {message}: 例外 - {e}")
            
            time.sleep(1)
        
        print(f"\n📊 処理結果: {success_count}/{len(test_messages)} 成功")
        return success_count == len(test_messages)

    def run_comprehensive_fix(self):
        """包括的修復を実行"""
        print("🚀 LINE Bot 包括的修復開始")
        
        # Step 1: トークン入力
        if not self.get_tokens_from_user():
            print("❌ トークン入力に失敗しました")
            return False
        
        # Step 2: LINE API接続テスト
        if not self.test_line_api_connection():
            print("❌ LINE API接続に失敗しました")
            return False
        
        # Step 3: チャネルID確認
        oauth_result = self.test_oauth_verify()
        if not oauth_result.get("success"):
            print("❌ チャネルID確認に失敗しました")
            return False
        
        if not oauth_result.get("is_correct"):
            print("⚠️ 警告: 正しくないチャネルのトークンを使用している可能性があります")
            continue_choice = input("続行しますか？ (y/N): ")
            if continue_choice.lower() != 'y':
                return False
        
        # Step 4: Webhook署名テスト
        if not self.test_webhook_signature():
            print("❌ Webhook署名検証に失敗しました")
            return False
        
        # Step 5: リッチメニュー修復
        if not self.fix_richmenu():
            print("❌ リッチメニュー修復に失敗しました")
            return False
        
        # Step 6: メッセージ処理テスト
        message_test_success = self.test_message_processing()
        
        # 結果表示
        print("\n" + "=" * 70)
        if message_test_success:
            print("🎉 修復完了！すべてのテストに成功しました")
            print("\n📱 次の確認事項:")
            print("1. LINEアプリでリッチメニューが表示されることを確認")
            print("2. 各ボタンをタップして応答があることを確認")
            print("3. 「AI相談」と入力してAIが応答することを確認")
        else:
            print("⚠️ 修復完了しましたが、一部のテストで問題がありました")
            print("\n📋 確認事項:")
            print("1. LINE Official Account Manager で以下を確認:")
            print("   https://manager.line.biz/")
            print("   - 応答メッセージ: オフ（最重要！）")
            print("   - Webhook: オン")
            print("2. 実際のLINEアプリでテストしてください")
        
        print(f"\n📅 修復完了時刻: {datetime.now()}")
        print("=" * 70)
        
        return True

def main():
    """メイン実行関数"""
    try:
        fixer = DirectAPILineBotFixer()
        fixer.run_comprehensive_fix()
    except KeyboardInterrupt:
        print("\n\n❌ ユーザーによって中断されました")
    except Exception as e:
        print(f"\n💥 予期しないエラー: {e}")
        print("手動で修正を行ってください。")

if __name__ == "__main__":
    main()