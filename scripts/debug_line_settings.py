#!/usr/bin/env python3
"""
LINE Bot設定デバッグスクリプト
python scripts/debug_line_settings.py
"""

import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

# 環境変数から取得
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

if not LINE_CHANNEL_ACCESS_TOKEN:
    print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
    exit(1)

headers = {
    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

def check_bot_info():
    """ボット情報を確認"""
    print("🤖 ボット情報を確認中...")
    
    response = requests.get(
        "https://api.line.me/v2/bot/info",
        headers=headers
    )
    
    if response.status_code == 200:
        info = response.json()
        print(f"✅ ボット名: {info.get('displayName')}")
        print(f"✅ ボットID: {info.get('userId')}")
        print(f"✅ 画像URL: {info.get('pictureUrl')}")
    else:
        print(f"❌ ボット情報取得失敗: {response.status_code}")

def check_webhook_endpoint():
    """Webhookエンドポイントの動作確認"""
    print("\n🌐 Webhookエンドポイントを確認中...")
    
    webhook_url = "https://rag-api-190389115361.asia-northeast1.run.app/line/webhook"
    
    # テストイベントを送信
    test_event = {
        "destination": "test",
        "events": [{
            "type": "message",
            "replyToken": "test-token",
            "source": {"type": "user", "userId": "test-user"},
            "timestamp": int(datetime.now().timestamp() * 1000),
            "message": {
                "type": "text",
                "id": "test-message",
                "text": "🤖 AI相談 AI相談を開始します！ ご質問やお悩みを自由に 入力してください😊"
            }
        }]
    }
    
    try:
        response = requests.post(
            webhook_url,
            json=test_event,
            headers={
                "Content-Type": "application/json",
                "X-Line-Signature": "test-signature"
            }
        )
        
        print(f"Webhook URL: {webhook_url}")
        print(f"レスポンスコード: {response.status_code}")
        print(f"レスポンス: {response.text}")
        
        if response.status_code == 400:
            print("ℹ️ 署名エラーは正常（テスト署名のため）")
        
    except Exception as e:
        print(f"❌ Webhook接続エラー: {e}")

def check_rich_menu():
    """リッチメニューの設定確認"""
    print("\n📱 リッチメニューを確認中...")
    
    # リッチメニューリストを取得
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
            print(f"選択状態: {menu['selected']}")
            
            # エリアのアクションを確認
            print("アクション設定:")
            for i, area in enumerate(menu['areas']):
                action = area['action']
                if action['type'] == 'message':
                    print(f"  エリア{i+1}: {action['text'][:30]}...")
    else:
        print(f"❌ リッチメニュー取得失敗: {response.status_code}")

def send_test_message():
    """テストメッセージを送信（ブロードキャスト）"""
    print("\n📨 テストメッセージ送信...")
    
    # 注意：これは全ユーザーに送信されます
    confirm = input("全ユーザーにテストメッセージを送信しますか？ (y/N): ")
    if confirm.lower() != 'y':
        print("キャンセルしました")
        return
    
    message = {
        "messages": [{
            "type": "text",
            "text": "【テスト】Webhook接続テスト中です。このメッセージが届いた場合、LINE Bot APIは正常に動作しています。"
        }]
    }
    
    response = requests.post(
        "https://api.line.me/v2/bot/message/broadcast",
        headers=headers,
        json=message
    )
    
    if response.status_code == 200:
        print("✅ テストメッセージ送信成功")
    else:
        print(f"❌ メッセージ送信失敗: {response.status_code}")
        print(response.text)

def check_cloud_run_logs():
    """Cloud Runのログ確認コマンドを表示"""
    print("\n📊 Cloud Runログ確認コマンド:")
    print("```")
    print("# 最新のログを確認")
    print("gcloud logging read 'resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"rag-api\" AND textPayload:\"line\"' --limit=50 --format=json")
    print("\n# リアルタイムログ確認")
    print("gcloud alpha logging tail 'resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"rag-api\"'")
    print("```")

def main():
    print("🔍 LINE Bot 設定デバッグ開始...")
    print("=" * 60)
    
    # 1. ボット情報確認
    check_bot_info()
    
    # 2. Webhookエンドポイント確認
    check_webhook_endpoint()
    
    # 3. リッチメニュー確認
    check_rich_menu()
    
    # 4. Cloud Runログコマンド表示
    check_cloud_run_logs()
    
    print("\n" + "=" * 60)
    print("📋 確認事項チェックリスト:")
    print("1. LINE Developers Console:")
    print("   - Webhook URL が正しく設定されているか")
    print("   - Webhookの利用が「オン」になっているか")
    print("   - 応答メッセージが「オフ」になっているか ← 重要！")
    print("\n2. LINE Official Account Manager:")
    print("   - 応答設定 → 詳細設定 → 応答メッセージが「オフ」か")
    print("   - Webhookが「オン」になっているか")
    print("\n3. Cloud Run:")
    print("   - 環境変数が正しく設定されているか")
    print("   - エラーログが出ていないか")
    
    # オプション：テストメッセージ送信
    print("\n")
    send_test_message()

if __name__ == "__main__":
    main()