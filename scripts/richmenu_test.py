#!/usr/bin/env python3
"""
リッチメニューの動作を確認するスクリプト
python richmenu_test.py
"""

import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

# 環境変数の確認
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
API_URL = "https://rag-api-190389115361.asia-northeast1.run.app"

if not LINE_CHANNEL_ACCESS_TOKEN:
    print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
    print("export LINE_CHANNEL_ACCESS_TOKEN='your-token-here' を実行してください")
    exit(1)

headers = {
    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

def check_rich_menu():
    """現在のリッチメニュー設定を確認"""
    print("📱 リッチメニュー設定を確認中...")
    
    response = requests.get(
        "https://api.line.me/v2/bot/richmenu/list",
        headers=headers
    )
    
    if response.status_code == 200:
        menus = response.json().get("richmenus", [])
        print(f"✅ リッチメニュー数: {len(menus)}")
        
        for menu in menus:
            print(f"\nメニューID: {menu['richMenuId']}")
            print(f"メニュー名: {menu['name']}")
            print(f"デフォルト設定: {menu['selected']}")
            
            print("\n各ボタンのメッセージ:")
            for i, area in enumerate(menu['areas']):
                action = area['action']
                if action['type'] == 'message':
                    print(f"  ボタン{i+1}: {action['text'][:30]}...")
        return True
    else:
        print(f"❌ リッチメニュー取得失敗: {response.status_code}")
        return False

def test_api_endpoint():
    """APIエンドポイントの動作確認"""
    print("\n🔍 APIエンドポイントを確認中...")
    
    try:
        # LINE Bot状態確認
        response = requests.get(f"{API_URL}/line/status", timeout=10)
        if response.status_code == 200:
            status = response.json()
            print("✅ LINE Bot API状態:")
            print(f"  - 設定済み: {status.get('line_bot_configured')}")
            print(f"  - SDK利用可能: {status.get('line_sdk_available')}")
            return True
        else:
            print(f"❌ API接続失敗: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ API接続エラー: {e}")
        return False

def simulate_richmenu_messages():
    """リッチメニューのメッセージをシミュレート"""
    print("\n🧪 リッチメニューメッセージのシミュレーション")
    
    test_messages = [
        ("AI相談", "🤖 AI相談 AI相談を開始します！ ご質問やお悩みを自由に 入力してください😊"),
        ("資料請求", "📋 資料請求します！ お名前と送付先を ご入力ください😊"),
        ("展示場予約", "📍 展示場来場予約します！日時をメッセージください 営業時間9-18時"),
    ]
    
    for name, message in test_messages:
        print(f"\n📨 {name}ボタンのテスト:")
        
        webhook_payload = {
            "destination": "test",
            "events": [{
                "type": "message",
                "message": {
                    "type": "text",
                    "id": f"test-{datetime.now().timestamp()}",
                    "text": message
                },
                "timestamp": int(datetime.now().timestamp() * 1000),
                "source": {
                    "type": "user",
                    "userId": "test-user"
                },
                "replyToken": f"test-token-{datetime.now().timestamp()}"
            }]
        }
        
        try:
            response = requests.post(
                f"{API_URL}/line/webhook",
                json=webhook_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Line-Signature": "test-signature"
                },
                timeout=10
            )
            
            if response.status_code == 400:
                print("  ✅ Webhookエンドポイント動作中（署名エラーは正常）")
            elif response.status_code == 200:
                print("  ✅ メッセージ処理成功")
            else:
                print(f"  ❌ エラー: {response.status_code}")
        except Exception as e:
            print(f"  ❌ 接続エラー: {e}")

def show_troubleshooting():
    """トラブルシューティング情報"""
    print("\n" + "="*60)
    print("🔧 トラブルシューティング")
    print("="*60)
    
    print("\n1. リッチメニューが表示されない場合:")
    print("   - LINE公式アカウントを一度ブロックして再度友達追加")
    print("   - リッチメニューがデフォルトに設定されているか確認")
    
    print("\n2. ボタンが反応しない場合:")
    print("   - Cloud Runのログを確認")
    print("   - line_bot.pyのメッセージ判定ロジックを確認")
    
    print("\n3. エラーが発生する場合のログ確認コマンド:")
    print('   gcloud logging read \'textPayload:"LINE" AND severity>=ERROR\' --limit=20')

def main():
    print("🚀 LINEリッチメニュー動作確認開始")
    print(f"時刻: {datetime.now()}")
    print("="*60)
    
    # リッチメニュー確認
    if not check_rich_menu():
        print("\n❌ リッチメニューが設定されていません")
        print("scripts/setup_line_richmenu_complete.py を実行してください")
        return
    
    # API確認
    if not test_api_endpoint():
        print("\n❌ APIが正常に動作していません")
        return
    
    # メッセージシミュレーション
    simulate_richmenu_messages()
    
    # トラブルシューティング
    show_troubleshooting()
    
    print("\n✅ 確認完了")

if __name__ == "__main__":
    main()