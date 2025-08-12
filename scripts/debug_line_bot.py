#!/usr/bin/env python3
"""
LINE Bot 詳細デバッグスクリプト
python debug_line_bot.py
"""

import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
API_URL = "https://rag-api-190389115361.asia-northeast1.run.app"

def check_line_api_connection():
    """LINE API接続確認"""
    print("🌐 LINE API接続確認")
    print("-" * 50)
    
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
        return False
    
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
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

def check_cloud_run_api():
    """Cloud Run API確認"""
    print("\n🏠 Cloud Run API確認")
    print("-" * 50)
    
    endpoints = [
        "/healthz",
        "/line/status", 
        "/system-health",
        "/status"
    ]
    
    for endpoint in endpoints:
        try:
            response = requests.get(f"{API_URL}{endpoint}", timeout=10)
            if response.status_code == 200:
                print(f"✅ {endpoint}: OK")
                if endpoint == "/line/status":
                    data = response.json()
                    print(f"    LINE Bot設定: {data.get('line_bot_configured')}")
                    print(f"    SDK利用可能: {data.get('line_sdk_available')}")
            else:
                print(f"❌ {endpoint}: {response.status_code}")
        except Exception as e:
            print(f"❌ {endpoint}: エラー - {e}")

def check_richmenu_status():
    """リッチメニュー状態確認"""
    print("\n📱 リッチメニュー状態確認")
    print("-" * 50)
    
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("❌ トークンが設定されていません")
        return
    
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(
            "https://api.line.me/v2/bot/richmenu/list",
            headers=headers
        )
        
        if response.status_code == 200:
            menus = response.json().get("richmenus", [])
            print(f"✅ リッチメニュー数: {len(menus)}")
            
            for i, menu in enumerate(menus):
                print(f"\nメニュー {i+1}:")
                print(f"  ID: {menu['richMenuId']}")
                print(f"  名前: {menu['name']}")
                print(f"  選択状態: {menu['selected']}")
                print(f"  エリア数: {len(menu.get('areas', []))}")
                
                for j, area in enumerate(menu.get('areas', [])):
                    action = area.get('action', {})
                    if action.get('type') == 'message':
                        print(f"    エリア{j+1}: {action.get('text', '')}")
        else:
            print(f"❌ リッチメニュー取得失敗: {response.status_code}")
            
    except Exception as e:
        print(f"❌ リッチメニュー確認エラー: {e}")

def test_webhook_manually():
    """手動Webhookテスト"""
    print("\n🧪 手動Webhookテスト")
    print("-" * 50)
    
    test_payloads = [
        {
            "name": "AI相談メッセージ",
            "payload": {
                "destination": "test",
                "events": [{
                    "type": "message",
                    "message": {
                        "type": "text",
                        "id": "test-message-1",
                        "text": "AI相談"
                    },
                    "timestamp": int(datetime.now().timestamp() * 1000),
                    "source": {
                        "type": "user",
                        "userId": "test-user-1"
                    },
                    "replyToken": "test-reply-token-1"
                }]
            }
        },
        {
            "name": "資料請求メッセージ",
            "payload": {
                "destination": "test",
                "events": [{
                    "type": "message",
                    "message": {
                        "type": "text",
                        "id": "test-message-2",
                        "text": "資料請求"
                    },
                    "timestamp": int(datetime.now().timestamp() * 1000),
                    "source": {
                        "type": "user",
                        "userId": "test-user-2"
                    },
                    "replyToken": "test-reply-token-2"
                }]
            }
        }
    ]
    
    webhook_url = f"{API_URL}/line/webhook"
    
    for test in test_payloads:
        print(f"\n📨 テスト: {test['name']}")
        
        try:
            response = requests.post(
                webhook_url,
                json=test['payload'],
                headers={
                    "Content-Type": "application/json",
                    "X-Line-Signature": "test-signature"
                },
                timeout=15
            )
            
            print(f"  ステータス: {response.status_code}")
            print(f"  レスポンス: {response.text[:200]}...")
            
            if response.status_code in [200, 400]:
                print("  ✅ エンドポイントは応答しています")
            else:
                print(f"  ❌ 予期しないステータス: {response.status_code}")
                
        except Exception as e:
            print(f"  ❌ テストエラー: {e}")

def check_environment_variables():
    """環境変数確認"""
    print("\n🔧 環境変数確認")
    print("-" * 50)
    
    env_vars = [
        "LINE_CHANNEL_ACCESS_TOKEN",
        "LINE_CHANNEL_SECRET",
        "OPENAI_API_KEY",
        "GCS_BUCKET_NAME",
        "ENV"
    ]
    
    for var in env_vars:
        value = os.environ.get(var)
        if value:
            if "TOKEN" in var or "SECRET" in var or "KEY" in var:
                print(f"✅ {var}: {value[:10]}...")
            else:
                print(f"✅ {var}: {value}")
        else:
            print(f"❌ {var}: 未設定")

def get_cloud_run_logs():
    """Cloud Runログ取得コマンドを表示"""
    print("\n📊 Cloud Runログ確認コマンド")
    print("-" * 50)
    
    commands = [
        "# 最新のエラーログ",
        'gcloud logging read \'resource.type="cloud_run_revision" AND resource.labels.service_name="rag-api" AND severity>=ERROR\' --limit=20',
        "",
        "# LINE関連ログ", 
        'gcloud logging read \'resource.type="cloud_run_revision" AND resource.labels.service_name="rag-api" AND textPayload:"LINE"\' --limit=20',
        "",
        "# Webhookログ",
        'gcloud logging read \'resource.type="cloud_run_revision" AND resource.labels.service_name="rag-api" AND textPayload:"webhook"\' --limit=20',
        "",
        "# リアルタイムログ監視",
        'gcloud alpha logging tail \'resource.type="cloud_run_revision" AND resource.labels.service_name="rag-api"\''
    ]
    
    for cmd in commands:
        print(cmd)

def main():
    print("🔍 LINE Bot 詳細デバッグ開始")
    print(f"実行時刻: {datetime.now()}")
    print("=" * 60)
    
    # 各種確認を実行
    line_ok = check_line_api_connection()
    check_cloud_run_api()
    check_richmenu_status()
    check_environment_variables()
    test_webhook_manually()
    get_cloud_run_logs()
    
    print("\n" + "=" * 60)
    print("📋 デバッグ結果サマリー")
    print("=" * 60)
    
    if line_ok:
        print("✅ LINE API接続: 正常")
    else:
        print("❌ LINE API接続: 問題あり")
    
    print("\n💡 次のアクション:")
    print("1. 上記のCloud Runログコマンドを実行してエラー詳細を確認")
    print("2. エラーがあれば緊急修復スクリプトを実行")
    print("3. それでも解決しない場合はCloud Runサービスを再起動")
    
    print("\n🚨 緊急時のコマンド:")
    print("# 緊急修復")
    print("python emergency_fix_richmenu.py")
    print("")
    print("# サービス再デプロイ")
    print("gcloud builds submit --config cloudbuild.yaml")
    print("")
    print("# Cloud Runサービス再起動")
    print("gcloud run services update rag-api --region=asia-northeast1")

if __name__ == "__main__":
    main()