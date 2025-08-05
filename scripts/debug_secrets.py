#!/usr/bin/env python3
"""
Secret Manager設定確認スクリプト
python debug_secrets.py
"""

import os
import requests
from google.cloud import secretmanager

def debug_line_secrets():
    """LINE Bot関連のSecret Manager設定を確認"""
    print("🔍 LINE Bot Secret Manager確認")
    print("=" * 50)
    
    # 環境変数の確認
    env_vars = {
        "LINE_CHANNEL_ACCESS_TOKEN": os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"),
        "LINE_CHANNEL_SECRET": os.environ.get("LINE_CHANNEL_SECRET"),
        "ENV": os.environ.get("ENV"),
        "GOOGLE_CLOUD_PROJECT": os.environ.get("GOOGLE_CLOUD_PROJECT")
    }
    
    print("\n📋 環境変数:")
    for key, value in env_vars.items():
        if value:
            if "TOKEN" in key or "SECRET" in key:
                print(f"  ✅ {key}: {value[:15]}...")
            else:
                print(f"  ✅ {key}: {value}")
        else:
            print(f"  ❌ {key}: 未設定")
    
    # Secret Managerから直接取得を試行
    if env_vars["ENV"] == "production":
        print("\n🔐 Secret Manager確認:")
        try:
            project_id = env_vars["GOOGLE_CLOUD_PROJECT"] or "rag-cloud-project"
            client = secretmanager.SecretManagerServiceClient()
            
            secrets_to_check = [
                "LINE_CHANNEL_ACCESS_TOKEN",
                "LINE_CHANNEL_SECRET"
            ]
            
            for secret_name in secrets_to_check:
                try:
                    secret_path = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
                    response = client.access_secret_version(request={"name": secret_path})
                    secret_value = response.payload.data.decode("UTF-8")
                    print(f"  ✅ {secret_name}: {secret_value[:15]}... (Secret Manager)")
                except Exception as e:
                    print(f"  ❌ {secret_name}: {e}")
                    
        except Exception as e:
            print(f"  ❌ Secret Manager接続エラー: {e}")

def test_line_api_connection():
    """LINE APIへの接続テスト"""
    print("\n🌐 LINE API接続テスト")
    print("=" * 50)
    
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not access_token:
        print("❌ ACCESS_TOKEN が設定されていません")
        return False
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        # ボット情報取得
        response = requests.get(
            "https://api.line.me/v2/bot/info",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            bot_info = response.json()
            print(f"✅ LINE API接続成功")
            print(f"  ボット名: {bot_info.get('displayName', '不明')}")
            print(f"  ボットID: {bot_info.get('userId', '不明')}")
            return True
        else:
            print(f"❌ LINE API接続失敗: {response.status_code}")
            print(f"  エラー詳細: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ LINE API接続エラー: {e}")
        return False

def test_webhook_endpoint():
    """自分のWebhookエンドポイントのテスト"""
    print("\n🔗 Webhookエンドポイントテスト")
    print("=" * 50)
    
    webhook_url = "https://rag-api-190389115361.asia-northeast1.run.app/line/status"
    
    try:
        response = requests.get(webhook_url, timeout=10)
        
        if response.status_code == 200:
            status = response.json()
            print("✅ Webhook エンドポイント正常")
            print(f"  LINE Bot設定: {status.get('line_bot_configured')}")
            print(f"  SDK利用可能: {status.get('line_sdk_available')}")
            print(f"  アクセストークン: {status.get('channel_access_token_set')}")
            print(f"  チャネルシークレット: {status.get('channel_secret_set')}")
            print(f"  API準備完了: {status.get('api_client_ready')}")
            print(f"  Handler準備完了: {status.get('handler_ready')}")
            
            return status.get('line_bot_configured', False)
        else:
            print(f"❌ Webhook接続失敗: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Webhook接続エラー: {e}")
        return False

def main():
    print("🚀 LINE Bot設定診断開始")
    print(f"実行時刻: {datetime.now()}")
    print()
    
    # 1. Secret設定確認
    debug_line_secrets()
    
    # 2. LINE API接続確認
    line_api_ok = test_line_api_connection()
    
    # 3. Webhook確認
    webhook_ok = test_webhook_endpoint()
    
    print("\n" + "=" * 50)
    print("📊 診断結果サマリー")
    print("=" * 50)
    print(f"LINE API接続: {'✅ OK' if line_api_ok else '❌ NG'}")
    print(f"Webhook設定: {'✅ OK' if webhook_ok else '❌ NG'}")
    
    if line_api_ok and webhook_ok:
        print("\n✅ すべて正常です！リッチメニューが機能するはずです。")
    else:
        print("\n❌ 問題が検出されました。以下を確認してください:")
        if not line_api_ok:
            print("  - Secret ManagerのLINE_CHANNEL_ACCESS_TOKEN")
            print("  - Secret ManagerのLINE_CHANNEL_SECRET")
        if not webhook_ok:
            print("  - Cloud Runサービスの起動状態")
            print("  - 環境変数の設定")

if __name__ == "__main__":
    from datetime import datetime
    main()