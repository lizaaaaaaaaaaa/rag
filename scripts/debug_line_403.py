#!/usr/bin/env python3
"""
LINE 403エラーの診断スクリプト
python debug_line_403.py
"""

import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

def check_line_credentials():
    """LINE認証情報の確認"""
    print("🔑 LINE認証情報の確認")
    print("=" * 60)
    
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    channel_secret = os.environ.get("LINE_CHANNEL_SECRET")
    
    print(f"ACCESS_TOKEN設定: {'✅' if access_token else '❌'}")
    print(f"CHANNEL_SECRET設定: {'✅' if channel_secret else '❌'}")
    
    if access_token:
        print(f"ACCESS_TOKEN長: {len(access_token)} 文字")
        print(f"ACCESS_TOKEN先頭: {access_token[:20]}...")
    
    return access_token, channel_secret

def test_line_api_connection(access_token):
    """LINE API接続テスト"""
    print("\n🧪 LINE API接続テスト")
    print("=" * 60)
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # 1. ボット情報取得テスト
    try:
        response = requests.get(
            "https://api.line.me/v2/bot/info",
            headers=headers,
            timeout=10
        )
        
        print(f"ボット情報取得: {response.status_code}")
        if response.status_code == 200:
            info = response.json()
            print(f"  ボット名: {info.get('displayName')}")
            print(f"  ボットID: {info.get('userId')}")
            print("  ✅ アクセストークンは有効")
        elif response.status_code == 401:
            print("  ❌ アクセストークンが無効または期限切れ")
            return False
        elif response.status_code == 403:
            print("  ❌ アクセス権限がない（403エラー）")
            return False
        else:
            print(f"  ⚠️ 予期しないレスポンス: {response.text}")
            
    except Exception as e:
        print(f"  ❌ API接続エラー: {e}")
        return False
    
    # 2. リッチメニュー取得テスト
    try:
        response = requests.get(
            "https://api.line.me/v2/bot/richmenu/list",
            headers=headers,
            timeout=10
        )
        
        print(f"リッチメニュー取得: {response.status_code}")
        if response.status_code == 200:
            menus = response.json().get("richmenus", [])
            print(f"  リッチメニュー数: {len(menus)}")
        else:
            print(f"  ⚠️ リッチメニュー取得失敗: {response.text}")
            
    except Exception as e:
        print(f"  ❌ リッチメニューAPI接続エラー: {e}")
    
    return True

def check_webhook_response_capability(access_token):
    """Webhook応答機能のテスト"""
    print("\n📡 Webhook応答機能テスト")
    print("=" * 60)
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # テスト用ブロードキャストメッセージ（実際には送信しない）
    test_message = {
        "messages": [
            {
                "type": "text",
                "text": "【テスト】このメッセージは送信されません - APIアクセス確認のみ"
            }
        ]
    }
    
    # dry-run的な確認（実際には送信しない）
    print("⚠️ 実際のメッセージ送信はスキップします")
    print("API権限確認のみ実行中...")
    
    return True

def check_cloud_run_environment():
    """Cloud Run環境の確認"""
    print("\n☁️ Cloud Run環境確認")
    print("=" * 60)
    
    api_url = "https://rag-api-190389115361.asia-northeast1.run.app"
    
    try:
        # ステータス確認
        response = requests.get(f"{api_url}/line/status", timeout=10)
        if response.status_code == 200:
            status = response.json()
            print("✅ LINE Bot API確認:")
            for key, value in status.items():
                print(f"  {key}: {value}")
        else:
            print(f"❌ Cloud Run接続失敗: {response.status_code}")
            
        # デバッグ情報確認
        response = requests.get(f"{api_url}/debug/env", timeout=10)
        if response.status_code == 200:
            debug = response.json()
            print("\n🔍 環境変数確認:")
            print(f"  LINE_CHANNEL_ACCESS_TOKEN_SET: {debug.get('line_channel_access_token_set')}")
            print(f"  LINE_CHANNEL_SECRET_SET: {debug.get('line_channel_secret_set')}")
            
    except Exception as e:
        print(f"❌ Cloud Run確認エラー: {e}")

def show_solutions():
    """解決策の表示"""
    print("\n🔧 解決策")
    print("=" * 60)
    
    solutions = [
        {
            "問題": "403 Forbidden エラー",
            "解決策": [
                "1. LINE Developersでアクセストークンを再生成",
                "2. 応答メッセージを「オフ」に設定",
                "3. LINE Official Account Managerで応答設定を確認"
            ]
        },
        {
            "問題": "アクセストークン無効",
            "解決策": [
                "1. LINE Developersコンソールでトークンを再発行",
                "2. Cloud Runの環境変数を更新",
                "3. サービスを再デプロイ"
            ]
        },
        {
            "問題": "自動応答との競合",
            "解決策": [
                "1. LINE Official Account Manager → 応答設定",
                "2. 応答メッセージ: オフ",
                "3. Webhook: オン",
                "4. あいさつメッセージ: オフ"
            ]
        }
    ]
    
    for solution in solutions:
        print(f"\n問題: {solution['問題']}")
        for step in solution['解決策']:
            print(f"  {step}")

def main():
    print("🚨 LINE 403エラー診断開始")
    print(f"時刻: {datetime.now()}")
    print("=" * 80)
    
    # 1. 認証情報確認
    access_token, channel_secret = check_line_credentials()
    
    if not access_token:
        print("\n❌ アクセストークンが設定されていません")
        print("環境変数を確認してください")
        return
    
    # 2. LINE API接続テスト
    api_ok = test_line_api_connection(access_token)
    
    # 3. Webhook応答機能テスト
    check_webhook_response_capability(access_token)
    
    # 4. Cloud Run環境確認
    check_cloud_run_environment()
    
    # 5. 解決策表示
    show_solutions()
    
    print("\n" + "=" * 80)
    if api_ok:
        print("✅ 基本的なAPI接続は成功しています")
        print("応答設定の問題の可能性が高いです")
    else:
        print("❌ API接続に問題があります")
        print("アクセストークンの再生成が必要です")

if __name__ == "__main__":
    main()