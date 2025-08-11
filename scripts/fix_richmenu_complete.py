# fix_richmenu_complete.py
import os
import json
import requests
from dotenv import load_dotenv
load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

headers = {
    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

# 1. 既存のリッチメニューを全削除
def delete_all_menus():
    response = requests.get(
        "https://api.line.me/v2/bot/richmenu/list",
        headers=headers
    )
    if response.status_code == 200:
        menus = response.json().get("richmenus", [])
        for menu in menus:
            requests.delete(
                f"https://api.line.me/v2/bot/richmenu/{menu['richMenuId']}",
                headers=headers
            )
        print(f"✅ {len(menus)}個のメニューを削除")

# 2. シンプルなメッセージアクションメニューを作成
def create_simple_menu():
    menu_object = {
        "size": {"width": 2500, "height": 1686},
        "selected": True,
        "name": "Simple RAG Menu",
        "chatBarText": "メニュー",
        "areas": [
            {
                "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
                "action": {
                    "type": "message",
                    "text": "AI相談"  # シンプルなテキスト
                }
            },
            {
                "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
                "action": {
                    "type": "message",
                    "text": "資料請求"
                }
            },
            {
                "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                "action": {
                    "type": "message",
                    "text": "展示場予約"
                }
            },
            {
                "bounds": {"x": 0, "y": 843, "width": 833, "height": 1686},
                "action": {
                    "type": "message",
                    "text": "資金計画"
                }
            },
            {
                "bounds": {"x": 833, "y": 843, "width": 834, "height": 1686},
                "action": {
                    "type": "message",
                    "text": "チャット相談"
                }
            },
            {
                "bounds": {"x": 1667, "y": 843, "width": 833, "height": 1686},
                "action": {
                    "type": "message",
                    "text": "ヘルプ"
                }
            }
        ]
    }
    
    response = requests.post(
        "https://api.line.me/v2/bot/richmenu",
        headers=headers,
        data=json.dumps(menu_object)
    )
    
    if response.status_code == 200:
        return response.json()["richMenuId"]
    else:
        print(f"❌ エラー: {response.text}")
        return None

# 3. デフォルトに設定
def set_default(menu_id):
    response = requests.post(
        f"https://api.line.me/v2/bot/user/all/richmenu/{menu_id}",
        headers=headers
    )
    return response.status_code == 200

# 実行
delete_all_menus()
menu_id = create_simple_menu()
if menu_id:
    print(f"✅ メニュー作成: {menu_id}")
    if set_default(menu_id):
        print("✅ デフォルト設定完了")