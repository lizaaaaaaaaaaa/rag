#!/usr/bin/env python3
"""
LINE Bot クイックフィックス - 3分で最も一般的な問題を解決
python line_bot_quick_fix.py
"""

import os
import json
import requests
import subprocess
import time
from datetime import datetime

def get_secret(secret_name: str) -> str:
    """Secret Manager から値を取得"""
    try:
        result = subprocess.run([
            'gcloud', 'secrets', 'versions', 'access', 'latest',
            '--secret', secret_name
        ], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None
    except:
        return None

def main():
    print("🚀 LINE Bot クイックフィックス - 3分で解決")
    print(f"開始時刻: {datetime.now()}")
    print("=" * 60)
    
    # Step 1: Token取得・検証（30秒）
    print("1️⃣ トークン検証中...")
    bot_token = get_secret("LINE_CHANNEL_ACCESS_TOKEN")
    if not bot_token:
        print("❌ トークンが取得できません")
        print("💡 修正: gcloud auth login を実行してください")
        return
    
    headers = {"Authorization": f"Bearer {bot_token}"}
    
    # Bot情報確認
    try:
        response = requests.get("https://api.line.me/v2/bot/info", headers=headers, timeout=10)
        if response.status_code == 200:
            bot_info = response.json()
            print(f"✅ Bot: {bot_info.get('displayName')} (ID: {bot_info.get('userId')})")
        else:
            print(f"❌ トークンエラー: {response.status_code}")
            print("💡 修正: LINE Developers で新しいトークンを発行してください")
            return
    except Exception as e:
        print(f"❌ 接続エラー: {e}")
        return
    
    # Step 2: Cloud Run 強制更新（60秒）
    print("\n2️⃣ Cloud Run 強制更新中...")
    try:
        result = subprocess.run([
            'gcloud', 'run', 'services', 'update', 'rag-api',
            '--region', 'asia-northeast1',
            '--update-secrets', 'LINE_CHANNEL_ACCESS_TOKEN=LINE_CHANNEL_ACCESS_TOKEN:latest,LINE_CHANNEL_SECRET=LINE_CHANNEL_SECRET:latest'
        ], capture_output=True, text=True, timeout=120)
        
        if result.returncode == 0:
            print("✅ Cloud Run 更新成功")
            print("⏳ デプロイ待機中...")
            time.sleep(15)
        else:
            print(f"❌ 更新失敗: {result.stderr}")
            return
    except Exception as e:
        print(f"❌ 更新エラー: {e}")
        return
    
    # Step 3: リッチメニュー削除・再作成（60秒）
    print("\n3️⃣ リッチメニュー修復中...")
    try:
        # 既存メニュー削除
        response = requests.get("https://api.line.me/v2/bot/richmenu/list", headers=headers)
        if response.status_code == 200:
            menus = response.json().get("richmenus", [])
            for menu in menus:
                requests.delete(f"https://api.line.me/v2/bot/richmenu/{menu['richMenuId']}", headers=headers)
                time.sleep(0.5)
        
        # 新メニュー作成
        richmenu_data = {
            "size": {"width": 2500, "height": 1686},
            "selected": True,
            "name": f"QuickFix-{int(time.time())}",
            "chatBarText": "メニュー",
            "areas": [
                {"bounds": {"x": 0, "y": 0, "width": 833, "height": 843}, "action": {"type": "message", "text": "AI相談"}},
                {"bounds": {"x": 833, "y": 0, "width": 834, "height": 843}, "action": {"type": "message", "text": "AI住まいサイト"}},
                {"bounds": {"x": 1667, "y": 0, "width": 833, "height": 843}, "action": {"type": "message", "text": "資料請求"}},
                {"bounds": {"x": 0, "y": 843, "width": 833, "height": 843}, "action": {"type": "message", "text": "展示場予約"}},
                {"bounds": {"x": 833, "y": 843, "width": 834, "height": 843}, "action": {"type": "message", "text": "資金計画"}},
                {"bounds": {"x": 1667, "y": 843, "width": 833, "height": 843}, "action": {"type": "message", "text": "チャット相談"}}
            ]
        }
        
        create_response = requests.post("https://api.line.me/v2/bot/richmenu", headers=headers, json=richmenu_data)
        if create_response.status_code == 200:
            richmenu_id = create_response.json()["richMenuId"]
            print(f"✅ リッチメニュー作成成功: {richmenu_id}")
            
            # デフォルト設定
            default_response = requests.post(f"https://api.line.me/v2/bot/user/all/richmenu/{richmenu_id}", headers=headers)
            if default_response.status_code == 200:
                print("✅ デフォルト設定成功")
            else:
                print(f"⚠️ デフォルト設定警告: {default_response.status_code}")
        else:
            print(f"❌ リッチメニュー作成失敗: {create_response.status_code}")
            return
    except Exception as e:
        print(f"❌ リッチメニューエラー: {e}")
        return
    
    # Step 4: 動作確認（30秒）
    print("\n4️⃣ 動作確認中...")
    try:
        # API確認
        api_response = requests.get("https://rag-api-190389115361.asia-northeast1.run.app/line/status", timeout=10)
        if api_response.status_code == 200:
            status = api_response.json()
            print(f"✅ API応答: {status.get('line_bot_configured', False)}")
        
        # Webhook簡易テスト
        channel_secret = get_secret("LINE_CHANNEL_SECRET")
        if channel_secret:
            import hmac, hashlib, base64
            test_body = '{"events":[],"destination":"test"}'
            signature = base64.b64encode(hmac.new(channel_secret.encode(), test_body.encode(), hashlib.sha256).digest()).decode()
            
            webhook_response = requests.post(
                "https://rag-api-190389115361.asia-northeast1.run.app/line/webhook",
                data=test_body,
                headers={"Content-Type": "application/json", "X-Line-Signature": signature},
                timeout=10
            )
            print(f"✅ Webhook応答: {webhook_response.status_code}")
        
    except Exception as e:
        print(f"⚠️ 確認エラー: {e}")
    
    # 結果表示
    print("\n" + "=" * 60)
    print("🎉 クイックフィックス完了！")
    print(f"完了時刻: {datetime.now()}")
    print("\n📱 次の確認事項:")
    print("1. LINEアプリでリッチメニューが表示されることを確認")
    print("2. 各ボタンを押してメッセージが送信されることを確認")
    print("3. AIからの返答があることを確認")
    
    print("\n⚠️ それでも動作しない場合:")
    print("1. LINE Official Account Manager にアクセス")
    print("   https://manager.line.biz/")
    print("2. 「設定」→「応答設定」で以下を確認:")
    print("   - 応答メッセージ: オフ ← 最重要!")
    print("   - Webhook: オン")
    print("3. 上記設定後、再度テストしてください")
    
    print("\n🔧 詳細診断が必要な場合:")
    print("python line_bot_comprehensive_fix.py")
    print("=" * 60)

if __name__ == "__main__":
    main()