#!/usr/bin/env python3
"""
LINE認証情報確認・修正スクリプト
python fix_line_credentials.py
"""

import os
import requests
import json
import subprocess
from datetime import datetime

def get_secret_from_gcp(secret_name):
    """Google Secret Managerから値を取得"""
    try:
        result = subprocess.run([
            'gcloud', 'secrets', 'versions', 'access', 'latest',
            '--secret', secret_name
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            print(f"❌ Secret {secret_name} 取得失敗: {result.stderr}")
            return None
    except Exception as e:
        print(f"❌ Secret取得エラー: {e}")
        return None

def test_line_token(token):
    """LINE tokenのテスト"""
    print(f"🧪 LINE token テスト中...")
    
    headers = {
        "Authorization": f"Bearer {token}",
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
            print(f"✅ LINE token 有効")
            print(f"  ボット名: {bot_info.get('displayName', '不明')}")
            print(f"  ボットID: {bot_info.get('userId', '不明')}")
            return True
        else:
            print(f"❌ LINE token 無効: {response.status_code}")
            print(f"  エラー詳細: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ LINE API テストエラー: {e}")
        return False

def check_line_developers_console():
    """LINE Developers Consoleの確認指示"""
    print("\n📋 LINE Developers Console 確認事項:")
    print("1. https://developers.line.biz/console/ にアクセス")
    print("2. 該当のチャネルを選択")
    print("3. 「Messaging API」タブを確認")
    print("4. 「Channel access token」が有効期限内か確認")
    print("5. 必要に応じて「Issue」ボタンで新しいトークンを発行")
    print("6. 新しいトークンをSecret Managerに更新")

def update_secret_manager_token():
    """Secret Managerのトークンを更新"""
    print("\n🔄 Secret Manager トークン更新手順:")
    
    new_token = input("新しいLINE_CHANNEL_ACCESS_TOKENを入力してください: ").strip()
    
    if not new_token:
        print("❌ トークンが入力されていません")
        return False
    
    if not new_token.startswith(('eyJ', 'sk-')):
        print("⚠️ トークンの形式が正しくない可能性があります")
        confirm = input("続行しますか？ (y/N): ")
        if confirm.lower() != 'y':
            return False
    
    # トークンをテスト
    if test_line_token(new_token):
        # Secret Managerに保存
        try:
            cmd = [
                'gcloud', 'secrets', 'versions', 'add', 'LINE_CHANNEL_ACCESS_TOKEN',
                '--data-file=-'
            ]
            
            result = subprocess.run(
                cmd,
                input=new_token,
                text=True,
                capture_output=True
            )
            
            if result.returncode == 0:
                print("✅ Secret Manager更新成功")
                return True
            else:
                print(f"❌ Secret Manager更新失敗: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Secret Manager更新エラー: {e}")
            return False
    else:
        print("❌ 新しいトークンが無効です")
        return False

def check_line_webhook_settings():
    """LINE Webhook設定の確認"""
    print("\n📱 LINE Webhook設定確認:")
    print("1. LINE Official Account Manager (https://manager.line.biz/) にアクセス")
    print("2. 該当のアカウントを選択")
    print("3. 「設定」→「応答設定」")
    print("4. 以下の設定を確認:")
    print("   - 応答メッセージ: オフ")
    print("   - あいさつメッセージ: オフ")
    print("   - Webhook: オン")
    print("")
    print("5. LINE Developers Console で:")
    print("   - Webhook URL: https://rag-api-190389115361.asia-northeast1.run.app/line/webhook")
    print("   - Webhookの利用: オン")

def main():
    print("🔧 LINE認証情報確認・修正")
    print(f"実行時刻: {datetime.now()}")
    print("=" * 60)
    
    # 1. 現在のSecret Manager値を確認
    print("📋 現在のSecret Manager値を確認中...")
    
    current_token = get_secret_from_gcp("LINE_CHANNEL_ACCESS_TOKEN")
    current_secret = get_secret_from_gcp("LINE_CHANNEL_SECRET")
    
    if current_token:
        print(f"✅ LINE_CHANNEL_ACCESS_TOKEN: {current_token[:20]}...")
    else:
        print("❌ LINE_CHANNEL_ACCESS_TOKEN: 取得失敗")
    
    if current_secret:
        print(f"✅ LINE_CHANNEL_SECRET: {current_secret[:10]}...")
    else:
        print("❌ LINE_CHANNEL_SECRET: 取得失敗")
    
    # 2. トークンテスト
    if current_token:
        token_valid = test_line_token(current_token)
        
        if not token_valid:
            print("\n❌ 現在のトークンが無効です")
            
            # 修正オプション
            print("\n🔧 修正オプション:")
            print("1. LINE Developers Consoleで新しいトークンを発行")
            print("2. Secret Managerを更新")
            
            choice = input("\n修正を実行しますか？ (y/N): ")
            if choice.lower() == 'y':
                check_line_developers_console()
                print("\n" + "="*40)
                update_token = input("新しいトークンを今すぐ更新しますか？ (y/N): ")
                if update_token.lower() == 'y':
                    if update_secret_manager_token():
                        print("\n✅ トークン更新完了！")
                        print("次のステップ:")
                        print("1. Cloud Runサービスを再起動:")
                        print("   gcloud run services update rag-api --region=asia-northeast1")
                        print("2. リッチメニュー修復を再実行:")
                        print("   python scripts/quick_linebot_fix.py")
                    else:
                        print("\n❌ トークン更新失敗")
        else:
            print("✅ トークンは有効です")
            print("他の設定を確認してください")
    
    # 3. その他の設定確認
    check_line_webhook_settings()
    
    print("\n" + "=" * 60)
    print("🎯 推奨次ステップ:")
    print("1. 上記の設定を確認・修正")
    print("2. Cloud Runサービス再起動:")
    print("   gcloud run services update rag-api --region=asia-northeast1")
    print("3. リッチメニュー修復を再実行:")
    print("   python scripts/quick_linebot_fix.py")

if __name__ == "__main__":
    main()