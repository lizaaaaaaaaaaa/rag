#!/usr/bin/env python3
"""
リッチメニューの動作確認とメッセージテスト
python test_richmenu_response.py
"""

import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

def test_richmenu_messages():
    """リッチメニューメッセージのテスト"""
    print("📱 リッチメニューメッセージテスト")
    print("=" * 60)
    
    api_url = "https://rag-api-190389115361.asia-northeast1.run.app"
    
    # リッチメニューから送信される可能性のあるメッセージパターン
    test_messages = [
        "AI相談を開始",
        "AI相談",
        "🤖 AI相談",
        "資料請求",
        "展示場予約",
        "資金計画",
        "チャット相談"
    ]
    
    for message in test_messages:
        print(f"\nテスト: {message}")
        
        # Webhookペイロードを作成
        webhook_payload = {
            "destination": "test",
            "events": [{
                "type": "message",
                "message": {
                    "type": "text",
                    "id": f"test-{int(datetime.now().timestamp())}",
                    "text": message
                },
                "timestamp": int(datetime.now().timestamp() * 1000),
                "source": {
                    "type": "user",
                    "userId": "test-user-richmenu"
                },
                "replyToken": f"test-reply-{int(datetime.now().timestamp())}"
            }]
        }
        
        try:
            response = requests.post(
                f"{api_url}/line/webhook",
                json=webhook_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Line-Signature": "test-signature"
                },
                timeout=15
            )
            
            print(f"  レスポンス: {response.status_code}")
            
            if response.status_code == 200:
                print("  ✅ Webhook処理成功")
            elif response.status_code == 400:
                print("  ⚠️ 署名エラー（テストなので正常）")
            else:
                print(f"  ❌ エラー: {response.text}")
                
        except Exception as e:
            print(f"  ❌ 接続エラー: {e}")

def check_current_richmenu():
    """現在のリッチメニュー設定確認"""
    print("\n📋 現在のリッチメニュー確認")
    print("=" * 60)
    
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not access_token:
        print("❌ アクセストークンが設定されていません")
        return
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(
            "https://api.line.me/v2/bot/richmenu/list",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            menus = response.json().get("richmenus", [])
            print(f"リッチメニュー数: {len(menus)}")
            
            for menu in menus:
                if menu.get('selected'):
                    print(f"\n✅ アクティブメニュー: {menu['name']}")
                    print("設定されているアクション:")
                    for i, area in enumerate(menu.get('areas', [])):
                        action = area.get('action', {})
                        if action.get('type') == 'message':
                            print(f"  {i+1}. {action.get('text', 'テキストなし')}")
        else:
            print(f"❌ リッチメニュー取得失敗: {response.status_code}")
            print(f"エラー: {response.text}")
            
    except Exception as e:
        print(f"❌ リッチメニュー確認エラー: {e}")

def main():
    print("🔍 リッチメニュー動作確認開始")
    print(f"時刻: {datetime.now()}")
    print("\n")
    
    # 1. 現在のリッチメニュー設定確認
    check_current_richmenu()
    
    # 2. メッセージテスト
    test_richmenu_messages()
    
    print("\n" + "=" * 60)
    print("📋 確認事項:")
    print("1. リッチメニューが正しく設定されているか")
    print("2. メッセージアクションが正しく動作するか")
    print("3. 403エラーが解決されているか")
    
    print("\n💡 問題が続く場合:")
    print("1. LINE Official Account Managerで応答設定を確認")
    print("2. アクセストークンを再生成")
    print("3. Cloud Runサービスを再起動")

if __name__ == "__main__":
    main()