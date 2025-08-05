#!/usr/bin/env python3
"""
LINE Bot問題診断スクリプト
python debug_line_issue.py
"""

import os
import requests
import json
from datetime import datetime

def check_environment():
    """環境変数の確認"""
    print("🔍 環境変数確認")
    print("=" * 50)
    
    env_vars = [
        "LINE_CHANNEL_ACCESS_TOKEN",
        "LINE_CHANNEL_SECRET", 
        "OPENAI_API_KEY",
        "ENV"
    ]
    
    for var in env_vars:
        value = os.environ.get(var)
        if value:
            print(f"✅ {var}: 設定済み ({value[:10]}...)")
        else:
            print(f"❌ {var}: 未設定")

def test_api_endpoint():
    """APIエンドポイントのテスト"""
    print("\n🌐 APIエンドポイント確認")
    print("=" * 50)
    
    endpoints = [
        ("ヘルスチェック", "https://rag-api-190389115361.asia-northeast1.run.app/healthz"),
        ("LINE Bot状態", "https://rag-api-190389115361.asia-northeast1.run.app/line/status"),
        ("システム状態", "https://rag-api-190389115361.asia-northeast1.run.app/status")
    ]
    
    for name, url in endpoints:
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                print(f"✅ {name}: OK")
                if "line" in url.lower():
                    data = response.json()
                    print(f"   LINE Bot設定: {data.get('line_bot_configured')}")
                    print(f"   SDK利用可能: {data.get('line_sdk_available')}")
            else:
                print(f"❌ {name}: エラー {response.status_code}")
        except Exception as e:
            print(f"❌ {name}: 接続エラー {e}")

def test_webhook():
    """Webhookのテスト"""
    print("\n📡 Webhook テスト")
    print("=" * 50)
    
    webhook_url = "https://rag-api-190389115361.asia-northeast1.run.app/line/webhook"
    
    test_payload = {
        "destination": "test",
        "events": [{
            "type": "message",
            "message": {
                "type": "text",
                "id": "test-message",
                "text": "AI相談を開始"
            },
            "timestamp": int(datetime.now().timestamp() * 1000),
            "source": {
                "type": "user",
                "userId": "test-user"
            },
            "replyToken": "test-reply-token"
        }]
    }
    
    try:
        response = requests.post(
            webhook_url,
            json=test_payload,
            headers={
                "Content-Type": "application/json",
                "X-Line-Signature": "test-signature"
            },
            timeout=10
        )
        
        print(f"Webhook URL: {webhook_url}")
        print(f"ステータス: {response.status_code}")
        print(f"レスポンス: {response.text}")
        
        if response.status_code == 400:
            print("ℹ️ 署名エラーは正常（テスト署名のため）")
        elif response.status_code == 200:
            print("✅ Webhook正常動作")
        elif response.status_code == 503:
            print("❌ サービス利用不可 - 環境変数を確認してください")
        
    except Exception as e:
        print(f"❌ Webhook接続エラー: {e}")

def check_logs():
    """ログ確認のコマンドを表示"""
    print("\n📊 ログ確認コマンド")
    print("=" * 50)
    
    commands = [
        ("最新のLINE関連ログ", 
         'gcloud logging read \'resource.type="cloud_run_revision" AND resource.labels.service_name="rag-api" AND textPayload:"LINE"\' --limit=20'),
        ("エラーログ", 
         'gcloud logging read \'resource.type="cloud_run_revision" AND resource.labels.service_name="rag-api" AND severity>=ERROR\' --limit=10'),
        ("リアルタイムログ", 
         'gcloud alpha logging tail \'resource.type="cloud_run_revision" AND resource.labels.service_name="rag-api"\'')
    ]
    
    for name, command in commands:
        print(f"\n{name}:")
        print(f"```\n{command}\n```")

def main():
    print("🚀 LINE Bot問題診断開始")
    print(f"時刻: {datetime.now()}")
    print()
    
    check_environment()
    test_api_endpoint()
    test_webhook()
    check_logs()
    
    print("\n" + "=" * 50)
    print("📋 推奨対処手順:")
    print("1. 環境変数が未設定の場合 → Secret Managerに設定")
    print("2. APIエラーが続く場合 → Cloud Runを再デプロイ")
    print("3. Webhook 503エラー → LINE Bot初期化エラーを確認")
    print("4. リッチメニューが反応しない → メッセージ判定ロジックを確認")

if __name__ == "__main__":
    main()