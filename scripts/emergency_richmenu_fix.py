# scripts/emergency_richmenu_fix.py (新規作成)
#!/usr/bin/env python3
"""
緊急復旧用リッチメニュー設定スクリプト
既存のLIFF URIアクションをpostback/messageアクションに変更
"""

import os
import json
import requests
from dotenv import load_dotenv
load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

if not LINE_CHANNEL_ACCESS_TOKEN:
    print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
    exit(1)

headers = {
    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

def delete_existing_richmenus():
    """既存のリッチメニューを削除"""
    print("🗑️ 既存のリッチメニューを削除中...")
    
    response = requests.get(
        "https://api.line.me/v2/bot/richmenu/list",
        headers=headers
    )
    
    if response.status_code == 200:
        menus = response.json().get("richmenus", [])
        for menu in menus:
            menu_id = menu["richMenuId"]
            delete_response = requests.delete(
                f"https://api.line.me/v2/bot/richmenu/{menu_id}",
                headers=headers
            )
            if delete_response.status_code == 200:
                print(f"✅ 削除成功: {menu_id}")

def create_emergency_richmenu():
    """緊急復旧用リッチメニューを作成（postback/messageアクション）"""
    
    # ★ LIFF URIの代わりにpostback/messageアクションを使用
    emergency_richmenu = {
        "size": {
            "width": 2500,
            "height": 1686
        },
        "selected": True,
        "name": "緊急復旧メニュー（postback版）",
        "chatBarText": "メニュー",
        "areas": [
            # A：AI相談（postbackアクション）
            {
                "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
                "action": {
                    "type": "postback",
                    "data": "action=ai_consultation&source=richmenu",
                    "displayText": "AI相談を開始します"
                }
            },
            # B：AI住まいサイト（messageアクション）
            {
                "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
                "action": {
                    "type": "message",
                    "text": "AI住まいサイト"
                }
            },
            # C：資料請求（postbackアクション）
            {
                "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                "action": {
                    "type": "postback",
                    "data": "action=document_request&source=richmenu",
                    "displayText": "資料請求"
                }
            },
            # D：展示場予約（messageアクション）
            {
                "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
                "action": {
                    "type": "message",
                    "text": "展示場予約"
                }
            },
            # E：資金計画（postbackアクション）
            {
                "bounds": {"x": 833, "y": 843, "width": 834, "height": 843},
                "action": {
                    "type": "postback",
                    "data": "action=finance_planning&source=richmenu",
                    "displayText": "資金計画相談"
                }
            },
            # F：チャット相談（messageアクション）
            {
                "bounds": {"x": 1667, "y": 843, "width": 833, "height": 843},
                "action": {
                    "type": "message",
                    "text": "チャット相談"
                }
            }
        ]
    }
    
    print("📋 緊急復旧用リッチメニューを作成中...")
    response = requests.post(
        "https://api.line.me/v2/bot/richmenu",
        headers=headers,
        data=json.dumps(emergency_richmenu)
    )
    
    if response.status_code == 200:
        richmenu_id = response.json()["richMenuId"]
        print(f"✅ 緊急復旧メニュー作成成功: {richmenu_id}")
        return richmenu_id
    else:
        print(f"❌ 作成失敗: {response.status_code}")
        print(f"エラー詳細: {response.text}")
        return None

def set_default_richmenu(richmenu_id):
    """デフォルトのリッチメニューに設定"""
    print("⚙️ デフォルトリッチメニューに設定中...")
    
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

def main():
    print("🚀 緊急復旧用リッチメニュー設定開始...")
    print("=" * 60)
    
    # 1. 既存メニュー削除
    delete_existing_richmenus()
    
    # 2. 緊急復旧メニュー作成
    richmenu_id = create_emergency_richmenu()
    if not richmenu_id:
        print("❌ リッチメニュー作成に失敗しました")
        return
    
    # 3. デフォルト設定
    if not set_default_richmenu(richmenu_id):
        print("❌ デフォルト設定に失敗しました")
        return
    
    print("\n" + "=" * 60)
    print("✅ 緊急復旧完了！")
    print(f"リッチメニューID: {richmenu_id}")
    print("""
📱 設定されたアクション:
A. AI相談 → postback: "action=ai_consultation&source=richmenu"
B. AI住まいサイト → message: "AI住まいサイト"
C. 資料請求 → postback: "action=document_request&source=richmenu"
D. 展示場予約 → message: "展示場予約"
E. 資金計画 → postback: "action=finance_planning&source=richmenu"
F. チャット相談 → message: "チャット相談"

✅ 次のステップ:
1. LINEアプリでリッチメニューが表示されることを確認
2. 各ボタンをタップして反応があることを確認
3. api/routers/line_bot.py でpostbackイベント処理を確認
""")

if __name__ == "__main__":
    main()