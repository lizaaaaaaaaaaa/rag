#!/usr/bin/env python3
"""
緊急LINE Bot修復スクリプト（現在のサービス用）
python quick_linebot_fix.py
"""

import os
import json
import requests
import time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

# 環境変数
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
API_URL = "https://rag-api-190389115361.asia-northeast1.run.app"

if not LINE_CHANNEL_ACCESS_TOKEN:
    print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
    print("以下のコマンドでSecret Managerから取得してください：")
    print('gcloud secrets versions access latest --secret="LINE_CHANNEL_ACCESS_TOKEN"')
    exit(1)

headers = {
    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

def test_api_status():
    """APIの状態確認"""
    print("🏠 API状態確認...")
    
    endpoints = [
        "/healthz",
        "/line/status",
        "/status"
    ]
    
    api_healthy = True
    for endpoint in endpoints:
        try:
            response = requests.get(f"{API_URL}{endpoint}", timeout=10)
            if response.status_code == 200:
                print(f"✅ {endpoint}: OK")
                if endpoint == "/line/status":
                    data = response.json()
                    print(f"    LINE Bot設定: {data.get('line_bot_configured')}")
                    print(f"    SDK利用可能: {data.get('line_sdk_available')}")
            else:
                print(f"❌ {endpoint}: {response.status_code}")
                api_healthy = False
        except Exception as e:
            print(f"❌ {endpoint}: エラー - {e}")
            api_healthy = False
    
    return api_healthy

def test_line_api():
    """LINE API接続テスト"""
    print("\n🌐 LINE API接続テスト...")
    
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
            return False
            
    except Exception as e:
        print(f"❌ LINE API接続エラー: {e}")
        return False

def check_current_richmenu():
    """現在のリッチメニュー確認"""
    print("\n📱 現在のリッチメニュー確認...")
    
    try:
        response = requests.get(
            "https://api.line.me/v2/bot/richmenu/list",
            headers=headers
        )
        
        if response.status_code == 200:
            menus = response.json().get("richmenus", [])
            print(f"✅ リッチメニュー数: {len(menus)}")
            
            for menu in menus:
                print(f"\nメニュー: {menu['name']}")
                print(f"  ID: {menu['richMenuId']}")
                print(f"  選択状態: {menu['selected']}")
                
                for i, area in enumerate(menu.get('areas', [])):
                    action = area.get('action', {})
                    if action.get('type') == 'message':
                        print(f"  ボタン{i+1}: {action.get('text', '')}")
            
            return len(menus) > 0
        else:
            print(f"❌ リッチメニュー取得失敗: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ リッチメニュー確認エラー: {e}")
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
        "name": "修復済みメニュー",
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
    """Webhookテスト"""
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
            timeout=10
        )
        
        print(f"  ステータス: {response.status_code}")
        if response.status_code in [200, 400]:
            print("  ✅ Webhookエンドポイント応答中")
            return True
        else:
            print(f"  ❌ 予期しないレスポンス: {response.text}")
            return False
    except Exception as e:
        print(f"  ❌ Webhookテストエラー: {e}")
        return False

def main():
    print("🚨 緊急LINE Bot修復開始")
    print(f"実行時刻: {datetime.now()}")
    print("=" * 60)
    
    # 1. API状態確認
    if not test_api_status():
        print("❌ APIに問題があります。先にAPIの修正が必要です。")
        return False
    
    # 2. LINE API接続確認
    if not test_line_api():
        print("❌ LINE APIに接続できません。認証情報を確認してください。")
        return False
    
    # 3. 現在のリッチメニュー確認
    has_menu = check_current_richmenu()
    
    # 4. 既存メニュー削除
    if has_menu:
        delete_all_richmenus()
        time.sleep(2)
    
    # 5. 新しいメニュー作成
    richmenu_id = create_simple_richmenu()
    if not richmenu_id:
        print("❌ リッチメニュー作成に失敗しました")
        return False
    
    time.sleep(2)
    
    # 6. デフォルト設定
    if not set_default_richmenu(richmenu_id):
        print("❌ デフォルト設定に失敗しました")
        return False
    
    time.sleep(2)
    
    # 7. Webhook確認
    webhook_ok = test_webhook()
    
    print("\n" + "=" * 60)
    if webhook_ok:
        print("✅ LINE Bot修復完了！")
        print(f"リッチメニューID: {richmenu_id}")
        print("""
📱 修復されたリッチメニュー:
- AI相談
- AI住まいサイト  
- 資料請求
- 展示場予約
- 資金計画
- チャット相談

🎯 次の確認事項:
1. LINEアプリでリッチメニューが表示されることを確認
2. 各ボタンをタップして応答があることを確認
        """)
        return True
    else:
        print("❌ Webhookに問題があります")
        return False

if __name__ == "__main__":
    success = main()
    if not success:
        print("\n🔧 問題が続く場合:")
        print("1. Cloud Runログを確認:")
        print('   gcloud logging read \'resource.type="cloud_run_revision" AND textPayload:"LINE"\' --limit=20')
        print("2. LINE Developers設定を確認:")
        print("   - Webhook URL: https://rag-api-190389115361.asia-northeast1.run.app/line/webhook")
        print("   - 応答メッセージ: オフ")
        print("   - Webhookの利用: オン")