# scripts/check_line_webhook.py - LINE Webhook設定確認スクリプト

import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

def check_line_webhook_config():
    """LINE Webhook設定を確認"""
    
    print("🔍 LINE Webhook設定確認を開始...")
    print("=" * 50)
    
    # 環境変数確認
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    channel_secret = os.environ.get("LINE_CHANNEL_SECRET")
    
    print(f"📋 環境変数確認:")
    print(f"  - LINE_CHANNEL_ACCESS_TOKEN: {'✅ 設定済み' if access_token else '❌ 未設定'}")
    print(f"  - LINE_CHANNEL_SECRET: {'✅ 設定済み' if channel_secret else '❌ 未設定'}")
    
    if not access_token:
        print("\n❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
        return False
    
    if not channel_secret:
        print("\n❌ LINE_CHANNEL_SECRET が設定されていません")
        return False
    
    print("\n🌐 Webhook URL確認:")
    expected_webhook_url = "https://rag-api-190389115361.asia-northeast1.run.app/line/webhook"
    print(f"  期待するWebhook URL: {expected_webhook_url}")
    
    # LINE Messaging API 設定情報を取得
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        # Webhook情報を取得（実際のAPIエンドポイントは限定的）
        print("\n📡 LINE API接続テスト:")
        
        # ボット情報を取得してAPI接続を確認
        response = requests.get(
            "https://api.line.me/v2/bot/info",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            bot_info = response.json()
            print(f"  ✅ LINE API接続成功")
            print(f"  ボット名: {bot_info.get('displayName', '不明')}")
            print(f"  ボットID: {bot_info.get('userId', '不明')}")
        else:
            print(f"  ❌ LINE API接続失敗: {response.status_code}")
            print(f"  エラー内容: {response.text}")
            return False
            
    except Exception as e:
        print(f"  ❌ LINE API接続エラー: {e}")
        return False
    
    # 自分のAPIエンドポイントの確認
    print("\n🏠 自身のAPIエンドポイント確認:")
    try:
        api_response = requests.get(
            "https://rag-api-190389115361.asia-northeast1.run.app/line/status",
            timeout=10
        )
        
        if api_response.status_code == 200:
            status_info = api_response.json()
            print("  ✅ 自身のAPI接続成功")
            print(f"  LINE Bot設定済み: {status_info.get('line_bot_configured')}")
            print(f"  LINE SDK利用可能: {status_info.get('line_sdk_available')}")
        else:
            print(f"  ❌ 自身のAPI接続失敗: {api_response.status_code}")
            
    except Exception as e:
        print(f"  ❌ 自身のAPI接続エラー: {e}")
    
    print("\n📝 設定確認チェックリスト:")
    print("  1. LINE Developersコンソールでの設定確認:")
    print("     - Webhook URL: https://rag-api-190389115361.asia-northeast1.run.app/line/webhook")
    print("     - Webhookの利用: 有効")
    print("     - Webhookの再送: 有効（推奨）")
    print("     - 自動応答メッセージ: 無効")
    print("     - Greeting messages: 無効")
    
    print("\n  2. Cloud Runでの環境変数確認:")
    print("     - LINE_CHANNEL_ACCESS_TOKEN: 設定済み")
    print("     - LINE_CHANNEL_SECRET: 設定済み")
    
    print("\n  3. リッチメニューの設定確認:")
    print("     - 'AI相談を開始' のメッセージアクションが設定されているか")
    
    return True

def test_webhook_endpoint():
    """Webhookエンドポイントのテスト"""
    print("\n🧪 Webhookエンドポイントテスト:")
    
    test_payload = {
        "destination": "test",
        "events": [
            {
                "type": "message",
                "message": {
                    "type": "text",
                    "id": "test",
                    "text": "テストメッセージ"
                },
                "timestamp": int(datetime.now().timestamp() * 1000),
                "source": {
                    "type": "user",
                    "userId": "test-user"
                },
                "replyToken": "test-reply-token"
            }
        ]
    }
    
    try:
        response = requests.post(
            "https://rag-api-190389115361.asia-northeast1.run.app/line/webhook",
            json=test_payload,
            headers={
                "Content-Type": "application/json",
                "X-Line-Signature": "test-signature"
            },
            timeout=10
        )
        
        print(f"  レスポンスステータス: {response.status_code}")
        print(f"  レスポンス内容: {response.text}")
        
        if response.status_code == 400:
            print("  ℹ️ 署名エラーは正常（テスト署名のため）")
        elif response.status_code == 200:
            print("  ✅ Webhookエンドポイント正常")
        else:
            print("  ⚠️ 予期しないレスポンス")
            
    except Exception as e:
        print(f"  ❌ Webhookテストエラー: {e}")

if __name__ == "__main__":
    success = check_line_webhook_config()
    if success:
        test_webhook_endpoint()
        
    print("\n" + "=" * 50)
    print("✅ 確認完了")
    print("\n💡 問題がある場合の対処法:")
    print("1. LINE Developersコンソールでの設定を再確認")
    print("2. Cloud RunでのWebhook URL設定を確認")
    print("3. 環境変数の設定を確認")
    print("4. リッチメニューの設定を確認")