#!/usr/bin/env python3
"""
LINE Token 詳細デバッガー - トークンの問題を特定
python line_token_debugger.py
"""

import requests
import json
from datetime import datetime

def debug_line_token():
    print("🔍 LINE Token 詳細デバッガー")
    print(f"📅 実行時刻: {datetime.now()}")
    print("=" * 60)
    
    # トークン入力
    print("\n🔐 Messaging API チャネルアクセストークン（長期）を入力してください:")
    token = input("トークン: ").strip()
    
    if not token:
        print("❌ トークンが入力されていません")
        return
    
    print(f"\n📊 トークン情報:")
    print(f"   長さ: {len(token)} 文字")
    print(f"   開始: {token[:20]}...")
    print(f"   終了: ...{token[-20:]}")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1) Bot Info API 詳細テスト
    print(f"\n1️⃣ Bot Info API 詳細テスト")
    print("-" * 30)
    
    try:
        response = requests.get(
            "https://api.line.me/v2/bot/info", 
            headers=headers, 
            timeout=15
        )
        
        print(f"ステータスコード: {response.status_code}")
        print(f"レスポンスヘッダー: {dict(response.headers)}")
        print(f"レスポンス本文: {response.text}")
        
        if response.status_code == 200:
            bot_info = response.json()
            print(f"\n✅ 成功！ Bot情報:")
            print(f"   ボット名: {bot_info.get('displayName')}")
            print(f"   ボットID: {bot_info.get('userId')}")
            print(f"   プレミアムID: {bot_info.get('premiumId', 'なし')}")
            return True
        else:
            print(f"\n❌ 失敗: {response.status_code}")
            
            # エラーパターン別の詳細説明
            if response.status_code == 401:
                print("📋 401エラーの可能性:")
                print("   1. トークンが無効または期限切れ")
                print("   2. トークンの形式が間違っている")
                print("   3. まだアクティベーションされていない")
                
            elif response.status_code == 403:
                print("📋 403エラーの可能性:")
                print("   1. LINE Loginのトークンを使用している")
                print("   2. 権限が不足している")
                print("   3. チャネルが無効化されている")
                
            elif response.status_code == 429:
                print("📋 429エラー:")
                print("   レート制限に達しています。少し待ってから再試行してください")
                
            return False
            
    except requests.exceptions.Timeout:
        print("❌ タイムアウト: LINE APIサーバーに接続できません")
        return False
    except requests.exceptions.ConnectionError:
        print("❌ 接続エラー: インターネット接続を確認してください")
        return False
    except Exception as e:
        print(f"❌ 予期しないエラー: {e}")
        return False

def check_channel_settings():
    print(f"\n2️⃣ LINE Developers Console 設定確認ガイド")
    print("-" * 50)
    
    print("以下の設定を確認してください：")
    print()
    print("🌐 LINE Developers Console")
    print("   https://developers.line.biz/console/")
    print()
    print("1️⃣ 正しいプロバイダーを選択")
    print("   - 複数のプロバイダーがある場合は注意")
    print()
    print("2️⃣ Messaging APIチャネルを選択")
    print("   - チャネル一覧で「Messaging API」タイプを確認")
    print("   - ❌ 「LINE Login」ではない")
    print()
    print("3️⃣ Messaging API設定タブで確認")
    print("   ✅ チャネルの基本設定")
    print("      - 公開/非公開: どちらでもOK")
    print("      - チャネルの状態: 有効")
    print()
    print("   ✅ チャネルアクセストークン（長期）")
    print("      - 発行済み、有効期限内")
    print("      - 「Issue」ボタンで新しいトークン発行可能")
    print()
    print("   ✅ Webhook設定")
    print("      - Webhook URL: https://rag-api-190389115361.asia-northeast1.run.app/line/webhook")
    print("      - Webhookの利用: オン")

def generate_new_token_guide():
    print(f"\n3️⃣ 新しいトークン発行ガイド")
    print("-" * 30)
    
    print("現在のトークンに問題がある場合：")
    print()
    print("1️⃣ LINE Developers Console にアクセス")
    print("   https://developers.line.biz/console/")
    print()
    print("2️⃣ Messaging APIチャネル → Messaging API設定")
    print()
    print("3️⃣ チャネルアクセストークン（長期）セクション")
    print("   - 「Issue」ボタンをクリック")
    print("   - 新しいトークンが生成される")
    print("   - ⚠️ 古いトークンは無効になります")
    print()
    print("4️⃣ 新しいトークンをコピー")
    print("   - すぐにテストして動作確認")
    print()
    print("5️⃣ Secret Managerに新しいトークンを保存")
    print("   （後でCloud Runに反映するため）")

def test_basic_connectivity():
    print(f"\n4️⃣ 基本的な接続テスト")
    print("-" * 30)
    
    print("LINE API サーバーへの基本接続確認...")
    
    try:
        # LINE APIサーバーへの基本接続
        response = requests.get("https://api.line.me/", timeout=10)
        print(f"✅ LINE APIサーバー接続: OK (HTTP {response.status_code})")
        
        # 認証なしでアクセスできるエンドポイントのテスト
        response = requests.get("https://api.line.me/v2/bot/info", timeout=10)
        if response.status_code == 401:
            print(f"✅ Bot Info API エンドポイント: 到達可能 (認証エラーは正常)")
        else:
            print(f"⚠️ Bot Info API エンドポイント: 予期しないレスポンス ({response.status_code})")
            
    except Exception as e:
        print(f"❌ 基本接続エラー: {e}")
        print("インターネット接続またはファイアウォール設定を確認してください")

def main():
    # トークンのデバッグテスト
    token_success = debug_line_token()
    
    # 設定確認ガイド
    check_channel_settings()
    
    # 基本接続テスト
    test_basic_connectivity()
    
    # 新しいトークン発行ガイド
    if not token_success:
        generate_new_token_guide()
    
    print(f"\n" + "=" * 60)
    print("📊 デバッグ結果サマリー")
    print("=" * 60)
    
    if token_success:
        print("✅ トークンは正常に動作しています！")
        print("他の問題の可能性:")
        print("   - Cloud RunのSecret Manager設定")
        print("   - LINE Official Account Manager設定")
        print("   - Webhook設定")
    else:
        print("❌ トークンに問題があります")
        print("推奨アクション:")
        print("   1. 上記の設定確認ガイドに従って確認")
        print("   2. 新しいトークンを発行")
        print("   3. 発行後すぐにこのスクリプトで再テスト")
    
    print(f"\n🔄 再テストする場合:")
    print(f"   python line_token_debugger.py")
    print("=" * 60)

if __name__ == "__main__":
    main()