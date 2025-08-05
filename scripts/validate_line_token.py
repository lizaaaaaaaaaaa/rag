#!/usr/bin/env python3
"""
LINEアクセストークンの検証スクリプト
python scripts/validate_line_token.py
"""

import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

def check_token_details():
    """トークンの詳細確認"""
    print("🔍 現在のアクセストークン詳細分析")
    print("=" * 60)
    
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    
    if not access_token:
        print("❌ アクセストークンが設定されていません")
        return False
    
    print(f"完全なトークン（最初の50文字）: {access_token[:50]}...")
    print(f"完全なトークン（最後の20文字）: ...{access_token[-20:]}")
    print(f"トークン長: {len(access_token)} 文字")
    
    # 改行文字やスペースの確認
    if '\n' in access_token:
        print("⚠️ トークンに改行文字が含まれています")
    if ' ' in access_token:
        print("⚠️ トークンにスペースが含まれています")
    if access_token != access_token.strip():
        print("⚠️ トークンの前後に余分な文字があります")
    
    return True

def test_token_variations():
    """トークンのバリエーションテスト"""
    print("\n🧪 トークンバリエーションテスト")
    print("=" * 60)
    
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    
    variations = [
        ("元のトークン", access_token),
        ("trim適用", access_token.strip() if access_token else ""),
        ("改行削除", access_token.replace('\n', '').replace('\r', '') if access_token else ""),
    ]
    
    for name, token in variations:
        if not token:
            continue
            
        print(f"\n{name} テスト:")
        print(f"  長さ: {len(token)}")
        
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
            
            print(f"  結果: {response.status_code}")
            
            if response.status_code == 200:
                print("  ✅ 成功！このトークンが正しいです")
                return token
            else:
                error_msg = response.json() if response.headers.get('content-type') == 'application/json' else response.text
                print(f"  ❌ エラー: {error_msg}")
                
        except Exception as e:
            print(f"  ❌ 例外: {e}")
    
    return None

def check_cloud_run_token():
    """実際のCloud Runのトークンを確認"""
    print("\n☁️ Cloud Runの実際のトークン確認")
    print("=" * 60)
    
    try:
        # Cloud Runの実際の環境変数を取得
        import subprocess
        
        result = subprocess.run([
            "gcloud", "run", "services", "describe", "rag-api",
            "--region=asia-northeast1",
            "--format=value(spec.template.spec.template.spec.containers[0].env[?name==\"LINE_CHANNEL_ACCESS_TOKEN\"].value)"
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            cloud_token = result.stdout.strip()
            print(f"Cloud Runのトークン長: {len(cloud_token)}")
            print(f"Cloud Runのトークン（先頭）: {cloud_token[:30]}...")
            
            # ローカルと比較
            local_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
            
            if cloud_token == local_token:
                print("✅ ローカルとCloud Runのトークンが一致")
            else:
                print("❌ ローカルとCloud Runのトークンが不一致")
                print("この不一致が問題の原因の可能性があります")
                
            return cloud_token
        else:
            print(f"❌ gcloudコマンドエラー: {result.stderr}")
            
    except Exception as e:
        print(f"❌ Cloud Run確認エラー: {e}")
    
    return None

def generate_new_token_steps():
    """新しいトークン生成の詳細手順"""
    print("\n🔧 完全な新規トークン生成手順")
    print("=" * 60)
    
    steps = [
        "1. LINE Developersコンソールにログイン",
        "   https://developers.line.biz/console/",
        "",
        "2. 正しいプロバイダーを選択",
        "",
        "3. **Messaging API**チャネルを選択",
        "   （LINEログインチャネルではない）",
        "",
        "4. 「Messaging API設定」タブをクリック",
        "",
        "5. チャネルアクセストークンの欄で：",
        "   a) 既存のトークンがあれば「削除」",
        "   b) 「発行」ボタンをクリック",
        "   c) 新しいトークンが表示されたら即座に全選択してコピー",
        "",
        "6. トークンをテキストエディタに貼り付けて確認：",
        "   - 余分なスペースや改行がないか",
        "   - 172文字程度の長さか",
        "   - Base64文字（A-Z, a-z, 0-9, +, /, =）のみか",
        "",
        "7. Cloud Runに設定：",
        "   gcloud run services update rag-api \\",
        "     --region=asia-northeast1 \\",
        "     --set-env-vars LINE_CHANNEL_ACCESS_TOKEN=新しいトークン",
        "",
        "8. 設定確認：",
        "   python scripts/validate_line_token.py"
    ]
    
    for step in steps:
        print(step)

def check_channel_status():
    """チャネルの状態確認ガイド"""
    print("\n📋 チャネル状態確認ガイド")
    print("=" * 60)
    
    print("LINE Developersコンソールで以下を確認してください：")
    print("")
    print("1. チャネル基本設定：")
    print("   - チャネル種別: Messaging API")
    print("   - チャネルの状態: 公開済み")
    print("   - Basic ID: @から始まる文字列")
    print("")
    print("2. Messaging API設定：")
    print("   - Webhook URL: https://rag-api-190389115361.asia-northeast1.run.app/line/webhook")
    print("   - Webhookの利用: オン")
    print("   - チャネルアクセストークン: 有効期限なし")
    print("")
    print("3. LINE Official Account Manager設定：")
    print("   - 応答メッセージ: オフ")
    print("   - Webhook: オン")
    print("   - あいさつメッセージ: オフ")

def main():
    print("🔍 LINEアクセストークン詳細検証")
    print(f"時刻: {datetime.now()}")
    print("=" * 80)
    
    # 1. トークン詳細確認
    if not check_token_details():
        return
    
    # 2. トークンバリエーションテスト
    valid_token = test_token_variations()
    
    # 3. Cloud Runのトークン確認
    cloud_token = check_cloud_run_token()
    
    # 4. 新しいトークン生成手順
    generate_new_token_steps()
    
    # 5. チャネル状態確認
    check_channel_status()
    
    print("\n" + "=" * 80)
    
    if valid_token:
        print("✅ 有効なトークンが見つかりました")
        print("Cloud Runに正しく設定してください")
    else:
        print("❌ 有効なトークンが見つかりませんでした")
        print("新しいトークンを生成してください")

if __name__ == "__main__":
    main()