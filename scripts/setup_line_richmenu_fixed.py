#!/usr/bin/env python3
"""
LINE リッチメニュー設定スクリプト（修正版）
python scripts/setup_line_richmenu_fixed.py
"""

import os
import json
import requests
from PIL import Image, ImageDraw, ImageFont
import io
import sys
from dotenv import load_dotenv
load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

if not LINE_CHANNEL_ACCESS_TOKEN:
    print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
    sys.exit(1)

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

def create_rich_menu():
    """シンプルなメッセージのリッチメニューを作成"""
    
    rich_menu_object = {
        "size": {
            "width": 2500,
            "height": 1686
        },
        "selected": True,
        "name": "キノエデザインホーム メニュー",
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
    
    response = requests.post(
        "https://api.line.me/v2/bot/richmenu",
        headers=headers,
        data=json.dumps(rich_menu_object)
    )
    
    if response.status_code == 200:
        richmenu_id = response.json()["richMenuId"]
        print(f"✅ リッチメニュー作成成功: {richmenu_id}")
        return richmenu_id
    else:
        print(f"❌ 作成失敗: {response.text}")
        return None

# 以下、画像作成とアップロード関数は既存のものを使用

def main():
    print("🚀 リッチメニュー修正開始...")
    
    # 1. 既存メニュー削除
    delete_existing_richmenus()
    
    # 2. 新規作成
    richmenu_id = create_rich_menu()
    if not richmenu_id:
        return
    
    # 3. 画像アップロード（既存の関数を使用）
    # 4. デフォルト設定（既存の関数を使用）
    
    print("✅ 完了！")

if __name__ == "__main__":
    main()