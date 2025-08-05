#!/usr/bin/env python3
"""
チャネル状態詳細診断スクリプト
python scripts/deep_channel_diagnosis.py
"""

import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

def test_different_endpoints():
    """様々なエンドポイントで詳細テスト"""
    print("🧪 詳細エンドポイント診断")
    print("=" * 60)
    
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    
    if not access_token:
        print("❌ アクセストークンが設定されていません")
        return
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # 様々なエンドポイントをテスト
    endpoints = [
        ("ボット情報", "GET", "https://api.line.me/v2/bot/info", None),
        ("チャネル情報", "GET", "https://api.line.me/v2/bot/channel/info", None),
        ("リッチメニュー一覧", "GET", "https://api.line.me/v2/bot/richmenu/list", None),
        ("Webhook情報", "GET", "https://api.line.me/v2/bot/channel/webhook/endpoint", None),
        ("Webhook テスト", "POST", "https://api.line.me/v2/bot/channel/webhook/test", {"text": "test"}),
    ]
    
    for name, method, url, data in endpoints:
        try:
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=10)
            else:
                response = requests.post(url, headers=headers, json=data, timeout=10)
            
            print(f"\n{name}:")
            print(f"  ステータス: {response.status_code}")
            
            if response.status_code == 200:
                print("  ✅ 成功")
                try:
                    result = response.json()
                    if name == "ボット情報" and "displayName" in result:
                        print(f"    ボット名: {result['displayName']}")
                        print(f"    ユーザーID: {result['userId']}")
                    elif name == "リッチメニュー一覧":
                        menus = result.get("richmenus", [])
                        print(f"    メニュー数: {len(menus)}")
                except:
                    pass
            elif response.status_code == 403:
                error_detail = response.json() if response.headers.get('content-type') == 'application/json' else response.text
                print(f"  ❌ 403エラー: {error_detail}")
            elif response.status_code == 401:
                print("  ❌ 401: 認証エラー（トークンが無効）")
            elif response.status_code == 400:
                error_detail = response.json() if response.headers.get('content-type') == 'application/json' else response.text
                print(f"  ⚠️ 400エラー: {error_detail}")
            else:
                print(f"  ⚠️ その他のエラー: {response.text}")
                
        except Exception as e:
            print(f"  ❌ 接続エラー: {e}")

def check_token_validity():
    """トークンの有効性をより詳細にチェック"""
    print("\n🔍 トークン有効性詳細チェック")
    print("=" * 60)
    
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    
    print(f"トークン情報:")
    print(f"  長さ: {len(access_token)} 文字")
    print(f"  先頭10文字: {access_token[:10]}")
    print(f"  末尾10文字: {access_token[-10:]}")
    
    # 文字セットチェック
    import string
    valid_chars = set(string.ascii_letters + string.digits + '+/=')
    token_chars = set(access_token)
    invalid_chars = token_chars - valid_chars
    
    if invalid_chars:
        print(f"  ⚠️ 不正な文字が含まれています: {invalid_chars}")
    else:
        print("  ✅ 文字セットは正常")
    
    # Base64チェック
    try:
        import base64
        decoded = base64.b64decode(access_token + '==')
        print("  ✅ Base64デコード可能")
    except Exception as e:
        print(f"  ⚠️ Base64デコードエラー: {e}")

def test_curl_command():
    """curl相当のテスト"""
    print("\n🖥️ curl相当テスト")
    print("=" * 60)
    
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    
    print("実行可能なcurlコマンド:")
    print(f"curl -v -X GET \\")
    print(f"  -H 'Authorization: Bearer {access_token}' \\")
    print(f"  -H 'Content-Type: application/json' \\")
    print(f"  'https://api.line.me/v2/bot/info'")
    
    print(f"\nWindows PowerShellの場合:")
    print(f'curl -Method GET -Uri "https://api.line.me/v2/bot/info" -Headers @{{"Authorization"="Bearer {access_token}"; "Content-Type"="application/json"}}')

def check_common_issues():
    """よくある問題をチェック"""
    print("\n🔧 よくある問題のチェック")
    print("=" * 60)
    
    issues_to_check = [
        "1. チャネルの承認状態",
        "   → LINE Developersコンソールでチャネルが「承認済み」になっているか",
        "",
        "2. プロバイダーの権限",
        "   → プロバイダーに適切な権限が設定されているか",
        "",
        "3. チャネルの有効期限",
        "   → チャネルアクセストークンに有効期限が設定されていないか",
        "",
        "4. APIの利用制限",
        "   → プランやAPIの利用制限に引っかかっていないか",
        "",
        "5. 地域制限",
        "   → 特定の地域からのアクセス制限がかかっていないか",
        "",
        "6. チャネル削除状態",
        "   → チャネルが削除済みまたは停止状態になっていないか",
        "",
        "7. 複数トークンの競合",
        "   → 複数のトークンが発行されていて古いものを使用していないか"
    ]
    
    for issue in issues_to_check:
        print(issue)

def suggest_solutions():
    """解決策の提案"""
    print("\n💡 推奨解決策")
    print("=" * 60)
    
    solutions = [
        {
            "問題": "チャネルが未承認状態",
            "解決策": [
                "1. LINE Developersコンソール → チャネル基本設定",
                "2. 「アプリケーション審査を開始する」ボタンがあれば実行",
                "3. 必要な情報を入力して承認申請"
            ]
        },
        {
            "問題": "プロバイダー権限の問題",
            "解決策": [
                "1. プロバイダー設定を確認",
                "2. 管理者権限があるアカウントでログイン",
                "3. 必要に応じて新しいプロバイダーを作成"
            ]
        },
        {
            "問題": "トークンの重複・競合",
            "解決策": [
                "1. 既存のトークンをすべて削除",
                "2. 完全に新しいトークンを1つだけ生成",
                "3. そのトークンのみを使用"
            ]
        },
        {
            "問題": "チャネル自体の問題",
            "解決策": [
                "1. 新しいMessaging APIチャネルを作成",
                "2. そのチャネルでトークンを生成",
                "3. すべての設定を新しいチャネルで実行"
            ]
        }
    ]
    
    for solution in solutions:
        print(f"\n問題: {solution['問題']}")
        for step in solution['解決策']:
            print(f"  {step}")

def main():
    print("🔍 チャネル状態詳細診断")
    print(f"時刻: {datetime.now()}")
    print("=" * 80)
    
    # 1. 様々なエンドポイントテスト
    test_different_endpoints()
    
    # 2. トークン有効性チェック
    check_token_validity()
    
    # 3. curl相当テスト
    test_curl_command()
    
    # 4. よくある問題チェック
    check_common_issues()
    
    # 5. 解決策提案
    suggest_solutions()
    
    print("\n" + "=" * 80)
    print("🚨 次に確認すべき重要事項:")
    print("1. LINE Developersコンソールでチャネルの「承認状態」を確認")
    print("2. プロバイダーの権限設定を確認")
    print("3. 完全に新しいチャネルの作成を検討")
    print("4. LINEサポートへの問い合わせも検討")

if __name__ == "__main__":
    main()