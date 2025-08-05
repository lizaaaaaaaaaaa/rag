#!/usr/bin/env python3
"""
LINE 403エラーの詳細診断スクリプト
python scripts/deep_line_diagnosis.py
"""

import os
import requests
import json
import base64
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

def check_token_format():
    """アクセストークンの形式をチェック"""
    print("🔍 アクセストークン詳細チェック")
    print("=" * 60)
    
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    
    if not access_token:
        print("❌ アクセストークンが設定されていません")
        return False
    
    print(f"トークン長: {len(access_token)} 文字")
    print(f"先頭: {access_token[:20]}...")
    print(f"末尾: ...{access_token[-20:]}")
    
    # チャネルアクセストークンの一般的な特徴をチェック
    expected_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/=')
    token_chars = set(access_token)
    
    print(f"文字種チェック: {'✅' if token_chars.issubset(expected_chars) else '❌'}")
    
    # Base64エンコードされているかチェック
    try:
        decoded = base64.b64decode(access_token + '==')  # パディング追加
        print("✅ Base64形式のトークンです")
    except:
        print("⚠️ Base64形式ではないようです（これは正常かもしれません）")
    
    return True

def check_multiple_channels():
    """複数チャネルの確認"""
    print("\n🔍 チャネル設定の確認")
    print("=" * 60)
    
    print("確認事項:")
    print("1. 正しいMessaging APIチャネルからトークンを取得しましたか？")
    print("2. LINEログインチャネルのトークンではありませんか？")
    print("3. チャネルが削除・無効化されていませんか？")
    print("4. チャネルの権限設定は正しいですか？")
    
    # 環境変数の詳細確認
    print(f"\n現在の設定:")
    print(f"LINE_CHANNEL_ACCESS_TOKEN長: {len(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', ''))}")
    print(f"LINE_CHANNEL_SECRET長: {len(os.environ.get('LINE_CHANNEL_SECRET', ''))}")

def test_with_different_endpoints():
    """異なるエンドポイントでのテスト"""
    print("\n🧪 複数エンドポイントでのテスト")
    print("=" * 60)
    
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    
    if not access_token:
        return
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # 複数のエンドポイントでテスト
    endpoints = [
        ("ボット情報", "https://api.line.me/v2/bot/info"),
        ("フォロワー統計", "https://api.line.me/v2/bot/insight/followers"),
        ("リッチメニュー一覧", "https://api.line.me/v2/bot/richmenu/list"),
    ]
    
    for name, url in endpoints:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"{name}: {response.status_code}")
            
            if response.status_code == 403:
                error_detail = response.json() if response.headers.get('content-type') == 'application/json' else response.text
                print(f"  エラー詳細: {error_detail}")
            elif response.status_code == 200:
                print("  ✅ 成功")
            
        except Exception as e:
            print(f"{name}: エラー - {e}")

def check_cloud_run_env():
    """Cloud Runの環境変数を詳細確認"""
    print("\n☁️ Cloud Run環境変数詳細確認")
    print("=" * 60)
    
    api_url = "https://rag-api-190389115361.asia-northeast1.run.app"
    
    try:
        # デバッグエンドポイント
        response = requests.get(f"{api_url}/debug/env", timeout=10)
        
        if response.status_code == 200:
            debug_info = response.json()
            print("Cloud Run環境変数:")
            for key, value in debug_info.items():
                if 'line' in key.lower():
                    print(f"  {key}: {value}")
        
        # 環境変数の長さをチェック
        response2 = requests.get(f"{api_url}/line/status", timeout=10)
        if response2.status_code == 200:
            status = response2.json()
            print(f"\nLINE Bot設定状況:")
            for key, value in status.items():
                print(f"  {key}: {value}")
                
    except Exception as e:
        print(f"❌ Cloud Run確認エラー: {e}")

def generate_fresh_token_commands():
    """新しいトークン設定のコマンド生成"""
    print("\n🔧 トークン再設定手順")
    print("=" * 60)
    
    print("1. LINE Developersコンソールでの確認事項:")
    print("   - 正しいMessaging APIチャネルを選択しているか")
    print("   - チャネルが「公開済み」状態か")
    print("   - Webhookが有効になっているか")
    
    print("\n2. 新しいトークン生成:")
    print("   a) LINE Developers → チャネル選択")
    print("   b) Messaging API設定タブ")
    print("   c) チャネルアクセストークン → 再発行")
    print("   d) 新しいトークンを即座にコピー")
    
    print("\n3. Cloud Run更新コマンド:")
    print("   gcloud run services update rag-api \\")
    print("     --region=asia-northeast1 \\")
    print("     --set-env-vars LINE_CHANNEL_ACCESS_TOKEN=新しいトークン")
    
    print("\n4. 確認コマンド:")
    print("   gcloud run services describe rag-api \\")
    print("     --region=asia-northeast1 \\")
    print("     --format='value(spec.template.spec.template.spec.containers[0].env[?name==\"LINE_CHANNEL_ACCESS_TOKEN\"].value)'")

def check_line_developers_console():
    """LINE Developersコンソールの設定確認ガイド"""
    print("\n📋 LINE Developersコンソール確認ガイド")
    print("=" * 60)
    
    checklist = [
        "✅ 正しいMessaging APIチャネルを使用しているか（LINEログインではない）",
        "✅ チャネルの状態が「公開済み」になっているか",
        "✅ Webhook URLが正しく設定されているか",
        "✅ Webhookの利用が「オン」になっているか",
        "✅ チャネルアクセストークンが最新のものか",
        "✅ プロバイダーが正しく設定されているか",
        "✅ チャネルに適切な権限が付与されているか"
    ]
    
    print("確認事項:")
    for item in checklist:
        print(f"  {item}")
    
    print(f"\n🔗 確認URL:")
    print("LINE Developers: https://developers.line.biz/console/")
    print("LINE Official Account Manager: https://manager.line.biz/")

def test_manual_api_call():
    """手動でのAPI呼び出しテスト"""
    print("\n🔧 手動API呼び出しテスト用情報")
    print("=" * 60)
    
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    
    if access_token:
        print("curlコマンドでのテスト:")
        print(f'curl -X GET \\')
        print(f'  -H "Authorization: Bearer {access_token[:20]}..." \\')
        print(f'  -H "Content-Type: application/json" \\')
        print(f'  "https://api.line.me/v2/bot/info"')
        
        print(f"\n期待される成功レスポンス例:")
        print('{"userId":"U...","displayName":"ボット名","pictureUrl":"..."}')
        
        print(f"\n現在のエラーレスポンス:")
        print('{"message":"Access to this API denied due to authorization error"}')

def main():
    print("🔍 LINE 403エラー詳細診断")
    print(f"時刻: {datetime.now()}")
    print("=" * 80)
    
    # 1. トークン形式チェック
    check_token_format()
    
    # 2. チャネル設定確認
    check_multiple_channels()
    
    # 3. 複数エンドポイントテスト
    test_with_different_endpoints()
    
    # 4. Cloud Run環境確認
    check_cloud_run_env()
    
    # 5. 新しいトークン設定手順
    generate_fresh_token_commands()
    
    # 6. LINE Developersコンソール確認
    check_line_developers_console()
    
    # 7. 手動テスト用情報
    test_manual_api_call()
    
    print("\n" + "=" * 80)
    print("🚨 最優先で確認すべき事項:")
    print("1. 正しいMessaging APIチャネルからトークンを取得しているか")
    print("2. LINEログインチャネルのトークンを誤って使用していないか")
    print("3. チャネルが削除・無効化されていないか")
    print("4. トークンをコピーする際に余分な文字が含まれていないか")

if __name__ == "__main__":
    main()