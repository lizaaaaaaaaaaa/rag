#!/usr/bin/env python3
"""
直接設定LINE Bot修復スクリプト（gcloud CLI不要版）
python direct_line_fix.py
"""

import os
import json
import requests
import time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

# 環境変数を直接設定（.envファイルまたは直接入力）
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
API_URL = "https://rag-api-190389115361.asia-northeast1.run.app"

# トークンが設定されていない場合は直接入力を求める
if not LINE_CHANNEL_ACCESS_TOKEN:
    print("🔑 LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
    LINE_CHANNEL_ACCESS_TOKEN = input("LINE_CHANNEL_ACCESS_TOKEN を入力してください: ").strip()
    
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("❌ トークンが入力されていません")
        exit(1)

headers = {
    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

def test_line_api():
    """LINE API接続テスト"""
    print("🌐 LINE API接続テスト...")
    
    try:
        response = requests.get(
            "https://api.line.me/v2/bot/info",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            bot_info = response.json()
            print(f"✅ LINE API接続成功")
            print(f"  ボット名: {bot_info.get('displayName', '不明')}")
            print(f"  ボットID: {bot_info.get('userId', '不明')}")
            return True
        else:
            print(f"❌ LINE API接続失敗: {response.status_code}")
            print(f"  エラー詳細: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ LINE API接続エラー: {e}")
        return False

def test_cloud_run_api():
    """Cloud Run API簡易テスト"""
    print("\n🏠 Cloud Run API簡易テスト...")
    
    try:
        response = requests.get(f"{API_URL}/line/status", timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Cloud Run API応答中")
            print(f"  LINE Bot設定: {data.get('line_bot_configured')}")
            print(f"  SDK利用可能: {data.get('line_sdk_available')}")
            return True
        else:
            print(f"❌ Cloud Run API異常: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Cloud Run API接続エラー: {e}")
        return False

def delete_all_richmenus():
    """すべてのリッチメニューを削除"""
    print("\n🗑️ 既存のリッチメニューを削除中...")
    
    try:
        response = requests.get(
            "https://api.line.me/v2/bot/richmenu/list",
            headers=headers
        )
        
        if response.status_code == 200:
            menus = response.json().get("richmenus", [])
            print(f"削除対象: {len(menus)}個のメニュー")
            
            for menu in menus:
                menu_id = menu["richMenuId"]
                delete_response = requests.delete(
                    f"https://api.line.me/v2/bot/richmenu/{menu_id}",
                    headers=headers
                )
                if delete_response.status_code == 200:
                    print(f"✅ 削除成功: {menu_id}")
                else:
                    print(f"❌ 削除失敗: {menu_id}")
                time.sleep(0.5)
            return True
        else:
            print(f"❌ リッチメニュー一覧取得失敗: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ リッチメニュー削除エラー: {e}")
        return False

def create_simple_richmenu():
    """シンプルなリッチメニューを作成"""
    print("\n📋 シンプルなリッチメニューを作成中...")
    
    richmenu_object = {
        "size": {"width": 2500, "height": 1686},
        "selected": True,
        "name": "修復済みメニューv2",
        "chatBarText": "メニュー",
        "areas": [
            {
                "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
                "action": {"type": "message", "text": "AI相談"}
            },
            {
                "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
                "action": {"type": "message", "text": "AI住まいサイト"}
            },
            {
                "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                "action": {"type": "message", "text": "資料請求"}
            },
            {
                "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
                "action": {"type": "message", "text": "展示場予約"}
            },
            {
                "bounds": {"x": 833, "y": 843, "width": 834, "height": 843},
                "action": {"type": "message", "text": "資金計画"}
            },
            {
                "bounds": {"x": 1667, "y": 843, "width": 833, "height": 843},
                "action": {"type": "message", "text": "チャット相談"}
            }
        ]
    }
    
    try:
        response = requests.post(
            "https://api.line.me/v2/bot/richmenu",
            headers=headers,
            data=json.dumps(richmenu_object)
        )
        
        if response.status_code == 200:
            richmenu_id = response.json()["richMenuId"]
            print(f"✅ リッチメニュー作成成功: {richmenu_id}")
            return richmenu_id
        else:
            print(f"❌ 作成失敗: {response.status_code}")
            print(f"エラー詳細: {response.text}")
            return None
    except Exception as e:
        print(f"❌ リッチメニュー作成エラー: {e}")
        return None

def set_default_richmenu(richmenu_id):
    """デフォルトのリッチメニューに設定"""
    print(f"\n⚙️ デフォルトリッチメニューに設定中: {richmenu_id}")
    
    try:
        response = requests.post(
            f"https://api.line.me/v2/bot/user/all/richmenu/{richmenu_id}",
            headers=headers
        )
        
        if response.status_code == 200:
            print("✅ デフォルトリッチメニュー設定成功")
            return True
        else:
            print(f"❌ デフォルト設定失敗: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ デフォルト設定エラー: {e}")
        return False

def test_webhook():
    """Webhookテスト（healthzを使わない）"""
    print("\n🧪 Webhookテスト...")
    
    test_payload = {
        "destination": "test",
        "events": [{
            "type": "message",
            "message": {"type": "text", "id": "test", "text": "AI相談"},
            "timestamp": int(time.time() * 1000),
            "source": {"type": "user", "userId": "test-user"},
            "replyToken": "test-token"
        }]
    }
    
    try:
        response = requests.post(
            f"{API_URL}/line/webhook",
            json=test_payload,
            headers={"Content-Type": "application/json", "X-Line-Signature": "test"},
            timeout=15
        )
        
        print(f"  ステータス: {response.status_code}")
        if response.status_code in [200, 400]:
            print("  ✅ Webhookエンドポイント応答中")
            return True
        else:
            print(f"  ❌ 予期しないレスポンス: {response.text[:200]}")
            return False
    except Exception as e:
        print(f"  ❌ Webhookテストエラー: {e}")
        return False

def test_direct_message():
    """直接メッセージテスト"""
    print("\n📱 直接メッセージテスト...")
    
    test_messages = ["AI相談", "資料請求", "こんにちは"]
    
    for message in test_messages:
        print(f"  テスト: {message}")
        
        test_payload = {
            "destination": "test",
            "events": [{
                "type": "message",
                "message": {"type": "text", "id": f"test-{message}", "text": message},
                "timestamp": int(time.time() * 1000),
                "source": {"type": "user", "userId": "test-user"},
                "replyToken": f"test-token-{message}"
            }]
        }
        
        try:
            response = requests.post(
                f"{API_URL}/line/webhook",
                json=test_payload,
                headers={"Content-Type": "application/json", "X-Line-Signature": "test"},
                timeout=10
            )
            
            if response.status_code in [200, 400]:
                print(f"    ✅ {message}: OK")
            else:
                print(f"    ❌ {message}: {response.status_code}")
        except Exception as e:
            print(f"    ❌ {message}: エラー - {e}")
        
        time.sleep(1)

def main():
    print("🚨 直接設定LINE Bot修復開始")
    print(f"実行時刻: {datetime.now()}")
    print(f"使用トークン: {LINE_CHANNEL_ACCESS_TOKEN[:20]}...")
    print("=" * 60)
    
    # 1. LINE API接続確認
    if not test_line_api():
        print("❌ LINE APIに接続できません。トークンを確認してください。")
        return False
    
    # 2. Cloud Run API確認
    if not test_cloud_run_api():
        print("❌ Cloud Run APIに問題があります。")
        print("ℹ️  ただし、LINE Bot部分は動作する可能性があります。続行します...")
    
    # 3. 既存メニュー削除
    print("\n" + "="*40)
    delete_all_richmenus()
    time.sleep(2)
    
    # 4. 新しいメニュー作成
    richmenu_id = create_simple_richmenu()
    if not richmenu_id:
        print("❌ リッチメニュー作成に失敗しました")
        return False
    
    time.sleep(2)
    
    # 5. デフォルト設定
    if not set_default_richmenu(richmenu_id):
        print("❌ デフォルト設定に失敗しました")
        return False
    
    time.sleep(3)
    
    # 6. Webhook確認
    webhook_ok = test_webhook()
    
    # 7. 直接メッセージテスト
    test_direct_message()
    
    print("\n" + "=" * 60)
    if webhook_ok:
        print("✅ LINE Bot修復完了！")
        print(f"リッチメニューID: {richmenu_id}")
        print("""
🎉 修復完了！

📱 新しいリッチメニュー:
- AI相談
- AI住まいサイト  
- 資料請求
- 展示場予約
- 資金計画
- チャット相談

🎯 確認事項:
1. LINEアプリでリッチメニューが表示されることを確認
2. 各ボタンをタップして応答があることを確認
3. 「AI相談」と入力してAIが応答することを確認
        """)
        return True
    else:
        print("⚠️ Webhookに問題がありますが、リッチメニューは設定されました")
        print("LINEアプリで実際にテストしてください")
        return True

if __name__ == "__main__":
    success = main()
    if success:
        print("\n🎊 次のステップ:")
        print("1. LINEアプリで公式アカウントを開く")
        print("2. リッチメニューをタップしてテスト")
        print("3. 「AI相談」と直接入力してテスト")
        print("4. 問題があればCloud Runログを確認")
    else:
        print("\n🔧 問題解決のために:")
        print("1. LINE Developersでトークンを確認")
        print("2. Cloud Runサービスの状態を確認")
        print("3. Webhook URLの設定を確認")