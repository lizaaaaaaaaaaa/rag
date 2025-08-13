#!/usr/bin/env python3
"""
LINE チャネル完全確認ツール - 正しいチャネルを特定
python line_channel_verifier.py
"""

import requests
import json
from datetime import datetime

def verify_channel_with_oauth(token):
    """OAuth verify エンドポイントでチャネルIDを確認"""
    print(f"\n🔍 チャネルID確認テスト")
    print("-" * 30)
    
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get("https://api.line.me/v2/oauth/verify", headers=headers, timeout=10)
        
        print(f"ステータスコード: {response.status_code}")
        print(f"レスポンス: {response.text}")
        
        if response.status_code == 200:
            verify_info = response.json()
            client_id = verify_info.get('client_id')
            print(f"\n📊 このトークンのチャネル情報:")
            print(f"   クライアントID: {client_id}")
            
            # チャネルタイプを判定
            expected_messaging_api_id = "2007887876"  # あなたのMessaging APIチャネルID
            
            if str(client_id) == expected_messaging_api_id:
                print(f"✅ これは正しいMessaging APIチャネルのトークンです")
                return True, client_id
            else:
                print(f"❌ これは異なるチャネルのトークンです")
                print(f"   期待値: {expected_messaging_api_id}")
                print(f"   実際値: {client_id}")
                print(f"💡 LINE Loginチャネルまたは別のMessaging APIチャネルのトークンです")
                return False, client_id
        else:
            print(f"❌ チャネル確認失敗: {response.status_code}")
            return False, None
            
    except Exception as e:
        print(f"❌ チャネル確認エラー: {e}")
        return False, None

def guide_correct_channel_selection():
    """正しいチャネル選択のガイド"""
    print(f"\n📋 正しいMessaging APIチャネルの特定方法")
    print("=" * 50)
    
    print("🌐 LINE Developers Console にアクセス:")
    print("   https://developers.line.biz/console/")
    print()
    
    print("1️⃣ プロバイダー選択")
    print("   - 該当するプロバイダーを選択")
    print()
    
    print("2️⃣ チャネル一覧で確認すべき項目:")
    print("   📱 チャネル名: 何らかのBot用の名前")
    print("   🏷️ チャネルタイプ: 「Messaging API」")
    print("   🆔 チャネルID: 数字のみ（例：1234567890）")
    print("   ⚠️ 「LINE Login」タイプは除外してください")
    print()
    
    print("3️⃣ 正しいMessaging APIチャネルを見つける方法:")
    print("   - チャネル一覧で複数ある場合は、すべて確認")
    print("   - 各チャネルで「Messaging API設定」タブがあることを確認")
    print("   - 「Bot情報」または「Basic information」で目的と一致するか確認")
    print()
    
    print("4️⃣ チャネルアクセストークン（長期）の正しい取得:")
    print("   ✅ 正しいMessaging APIチャネルを選択")
    print("   ✅ 「Messaging API設定」タブをクリック")
    print("   ✅ 「チャネルアクセストークン（長期）」セクション")
    print("   ✅ 既存のトークンがあれば使用、なければ「Issue」で発行")

def test_token_with_different_endpoints(token):
    """複数のエンドポイントでトークンをテスト"""
    print(f"\n🧪 複数エンドポイントテスト")
    print("-" * 30)
    
    headers = {"Authorization": f"Bearer {token}"}
    
    endpoints = [
        ("Bot Info", "https://api.line.me/v2/bot/info"),
        ("OAuth Verify", "https://api.line.me/v2/oauth/verify"),
        ("Rich Menu List", "https://api.line.me/v2/bot/richmenu/list")
    ]
    
    results = {}
    
    for name, url in endpoints:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            results[name] = {
                "status": response.status_code,
                "response": response.text[:100] + "..." if len(response.text) > 100 else response.text
            }
            print(f"   {name}: HTTP {response.status_code}")
        except Exception as e:
            results[name] = {"status": "ERROR", "response": str(e)}
            print(f"   {name}: エラー - {e}")
    
    return results

def create_new_token_guide():
    """新しいトークン作成の具体的ガイド"""
    print(f"\n🔄 新しいトークン発行の具体的手順")
    print("=" * 40)
    
    print("⚠️ 重要: 以下の手順を順番通りに実行してください")
    print()
    
    print("STEP 1: チャネルの特定")
    print("   1. https://developers.line.biz/console/ にアクセス")
    print("   2. 正しいプロバイダーを選択")
    print("   3. チャネル一覧で「Messaging API」タイプを探す")
    print("   4. チャネル名とIDをメモする")
    print()
    
    print("STEP 2: トークン発行")
    print("   1. 該当するMessaging APIチャネルをクリック")
    print("   2. 「Messaging API設定」タブをクリック")
    print("   3. ページを下にスクロール")
    print("   4. 「チャネルアクセストークン（長期）」セクションを見つける")
    print("   5. 「Issue」ボタンをクリック")
    print("   6. 新しいトークンが表示される（古いトークンは無効になる）")
    print("   7. トークンを安全な場所にコピー")
    print()
    
    print("STEP 3: 即座にテスト")
    print("   1. このスクリプトを再実行")
    print("   2. 新しいトークンを入力")
    print("   3. Bot Info APIが成功することを確認")

def main():
    print("🔧 LINE チャネル完全確認ツール")
    print(f"📅 実行時刻: {datetime.now()}")
    print("=" * 60)
    
    # トークン入力
    print("\n🔐 現在使用しているトークンを入力してください:")
    token = input("トークン: ").strip()
    
    if not token:
        print("❌ トークンが入力されていません")
        return
    
    # 1. OAuth verify でチャネルIDを確認
    is_correct_channel, client_id = verify_channel_with_oauth(token)
    
    # 2. 複数エンドポイントでテスト
    endpoint_results = test_token_with_different_endpoints(token)
    
    # 3. 結果の分析
    print(f"\n📊 分析結果")
    print("=" * 30)
    
    if is_correct_channel:
        print("✅ 正しいMessaging APIチャネルのトークンです")
        print("しかし、Bot Info APIで403エラーが出る場合:")
        print("   1. トークンが古い可能性")
        print("   2. チャネルに問題がある可能性")
        print("   3. 新しいトークンを発行してください")
    else:
        print("❌ 間違ったチャネルのトークンです")
        print(f"このトークンのチャネルID: {client_id}")
        print("正しいMessaging APIチャネルを見つけて、新しいトークンを取得してください")
    
    # 4. ガイド表示
    guide_correct_channel_selection()
    create_new_token_guide()
    
    print(f"\n🎯 次のアクション:")
    if is_correct_channel:
        print("1. 同じチャネルで新しいトークンを発行")
        print("2. 発行後すぐにテスト")
    else:
        print("1. 正しいMessaging APIチャネルを特定")
        print("2. そのチャネルでトークンを発行")
        print("3. 発行後すぐにテスト")
    
    print(f"\n🔄 再テスト:")
    print(f"   python line_channel_verifier.py")

if __name__ == "__main__":
    main()