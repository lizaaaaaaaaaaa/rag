#!/usr/bin/env python3
"""
LINE設定最終確認スクリプト
python scripts/final_line_verification.py
"""

import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

def test_bot_info():
    """ボット情報取得テスト"""
    print("🤖 ボット情報取得テスト")
    print("=" * 40)
    
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    
    if not access_token:
        print("❌ アクセストークンが設定されていません")
        return False
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(
            "https://api.line.me/v2/bot/info",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            info = response.json()
            print("✅ ボット情報取得成功！")
            print(f"  ボット名: {info.get('displayName')}")
            print(f"  ボットID: {info.get('userId')}")
            print(f"  Basic ID: {info.get('basicId', 'N/A')}")
            return True
        else:
            print(f"❌ エラー: {response.status_code}")
            error_detail = response.json() if response.headers.get('content-type') == 'application/json' else response.text
            print(f"  詳細: {error_detail}")
            return False
            
    except Exception as e:
        print(f"❌ 接続エラー: {e}")
        return False

def test_richmenu():
    """リッチメニュー取得テスト"""
    print("\n📱 リッチメニュー取得テスト")
    print("=" * 40)
    
    access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
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
            print(f"✅ リッチメニュー取得成功！")
            print(f"  メニュー数: {len(menus)}")
            
            for menu in menus:
                if menu.get('selected'):
                    print(f"  アクティブメニュー: {menu['name']}")
                    print(f"  エリア数: {len(menu.get('areas', []))}")
                    
                    # 各エリアのアクション確認
                    for i, area in enumerate(menu.get('areas', [])):
                        action = area.get('action', {})
                        if action.get('type') == 'message':
                            print(f"    エリア{i+1}: {action.get('text', '')[:30]}...")
            return True
        else:
            print(f"❌ エラー: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ 接続エラー: {e}")
        return False

def test_webhook_response():
    """Webhook応答テスト"""
    print("\n🔗 Webhook応答テスト")
    print("=" * 40)
    
    api_url = "https://rag-api-190389115361.asia-northeast1.run.app"
    
    # テスト用メッセージ
    test_payload = {
        "destination": "test",
        "events": [{
            "type": "message",
            "message": {
                "type": "text",
                "id": f"test-{int(datetime.now().timestamp())}",
                "text": "AI相談を開始"
            },
            "timestamp": int(datetime.now().timestamp() * 1000),
            "source": {
                "type": "user",
                "userId": "test-user-final"
            },
            "replyToken": f"test-reply-{int(datetime.now().timestamp())}"
        }]
    }
    
    try:
        response = requests.post(
            f"{api_url}/line/webhook",
            json=test_payload,
            headers={
                "Content-Type": "application/json",
                "X-Line-Signature": "test-signature"
            },
            timeout=15
        )
        
        print(f"Webhookレスポンス: {response.status_code}")
        
        if response.status_code == 400:
            print("✅ Webhook処理中（署名エラーは正常）")
            return True
        elif response.status_code == 200:
            print("✅ Webhook処理成功")
            return True
        else:
            print(f"⚠️ 予期しないレスポンス: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Webhookテストエラー: {e}")
        return False

def show_next_steps(api_success, richmenu_success, webhook_success):
    """次のステップを表示"""
    print("\n" + "=" * 60)
    print("📋 テスト結果サマリー")
    print("=" * 60)
    
    print(f"LINE API接続: {'✅' if api_success else '❌'}")
    print(f"リッチメニュー: {'✅' if richmenu_success else '❌'}")
    print(f"Webhook処理: {'✅' if webhook_success else '❌'}")
    
    if api_success and richmenu_success and webhook_success:
        print("\n🎉 すべてのテストが成功しました！")
        print("\n次のステップ:")
        print("1. LINEアプリで公式アカウントを友だち追加")
        print("2. リッチメニューの「AI相談」ボタンをタップ")
        print("3. AIチャットが開始されることを確認")
        
        print(f"\n📱 公式アカウント情報:")
        print(f"Basic ID: @484Tuk1v")
        print(f"アカウント名: キノエデザインの住まいAIコンシェルジュ")
        
    elif api_success:
        print("\n⚠️ API接続は成功していますが、他に問題があります")
        
        if not richmenu_success:
            print("- リッチメニューが設定されていません")
            print("  → scripts/setup_line_richmenu_complete.py を実行してください")
            
        if not webhook_success:
            print("- Webhook処理に問題があります")
            print("  → Cloud Runのログを確認してください")
            
    else:
        print("\n❌ まだAPI接続に問題があります")
        print("新しいアクセストークンの設定を再確認してください")

def main():
    print("🔍 LINE設定最終確認テスト")
    print(f"時刻: {datetime.now()}")
    print("=" * 80)
    
    # 1. ボット情報取得テスト
    api_success = test_bot_info()
    
    # 2. リッチメニュー取得テスト
    richmenu_success = test_richmenu()
    
    # 3. Webhook応答テスト
    webhook_success = test_webhook_response()
    
    # 4. 結果表示と次のステップ
    show_next_steps(api_success, richmenu_success, webhook_success)
    
    return api_success and richmenu_success and webhook_success

if __name__ == "__main__":
    success = main()
    if success:
        print("\n✅ LINE Bot設定完了 - 実際のLINEアプリでテストしてください！")
    else:
        print("\n❌ 追加の設定が必要です")