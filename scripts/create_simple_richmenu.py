#!/usr/bin/env python3
"""
シンプルなリッチメニューを作成するスクリプト
python scripts/create_simple_richmenu.py
"""

import os
import json
import requests
from PIL import Image, ImageDraw, ImageFont
import io
import sys
from dotenv import load_dotenv
load_dotenv()

# 環境変数から取得
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
                print(f"  ✅ 削除成功: {menu_id}")

def create_simple_richmenu():
    """シンプルなリッチメニューを作成"""
    
    rich_menu_object = {
        "size": {
            "width": 2500,
            "height": 1686
        },
        "selected": True,
        "name": "キノエデザインホーム シンプルメニュー",
        "chatBarText": "メニュー",
        "areas": [
            # AI相談（左上）
            {
                "bounds": {
                    "x": 0,
                    "y": 0,
                    "width": 833,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "text": "AI相談"
                }
            },
            # AI住まいサイト（中央上）
            {
                "bounds": {
                    "x": 833,
                    "y": 0,
                    "width": 834,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "text": "AI住まいサイト"
                }
            },
            # 資料請求（右上）
            {
                "bounds": {
                    "x": 1667,
                    "y": 0,
                    "width": 833,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "text": "資料請求"
                }
            },
            # 展示場予約（左下）
            {
                "bounds": {
                    "x": 0,
                    "y": 843,
                    "width": 833,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "text": "展示場予約"
                }
            },
            # 資金計画（中央下）
            {
                "bounds": {
                    "x": 833,
                    "y": 843,
                    "width": 834,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "text": "資金計画"
                }
            },
            # チャット相談（右下）
            {
                "bounds": {
                    "x": 1667,
                    "y": 843,
                    "width": 833,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "text": "チャット相談"
                }
            }
        ]
    }
    
    print("📋 シンプルなリッチメニューを作成中...")
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
        print(f"❌ リッチメニュー作成失敗: {response.status_code}")
        return None

def create_simple_image():
    """シンプルなリッチメニュー画像を作成"""
    print("🎨 リッチメニュー画像を作成中...")
    
    img = Image.new('RGB', (2500, 1686), color='white')
    draw = ImageDraw.Draw(img)
    
    # 各セクションの設定
    sections = [
        # 上段
        {"pos": (0, 0, 833, 843), "color": "#FF6B6B", "text": "AI相談", "emoji": "🤖"},
        {"pos": (833, 0, 1667, 843), "color": "#4ECDC4", "text": "AI住まい\nサイト", "emoji": "🌐"},
        {"pos": (1667, 0, 2500, 843), "color": "#45B7D1", "text": "資料請求", "emoji": "📋"},
        # 下段
        {"pos": (0, 843, 833, 1686), "color": "#96CEB4", "text": "展示場\n予約", "emoji": "📍"},
        {"pos": (833, 843, 1667, 1686), "color": "#FECA57", "text": "資金計画", "emoji": "💰"},
        {"pos": (1667, 843, 2500, 1686), "color": "#48C9B0", "text": "チャット\n相談", "emoji": "💬"}
    ]
    
    font_large = ImageFont.load_default()
    
    for section in sections:
        x1, y1, x2, y2 = section["pos"]
        
        # 背景を塗りつぶし
        draw.rectangle([x1, y1, x2, y2], fill=section["color"])
        
        # 境界線
        draw.rectangle([x1, y1, x2-1, y2-1], outline='white', width=3)
        
        # 中央配置
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        
        # 絵文字（上部）
        draw.text((center_x, center_y - 60), section["emoji"], 
                 fill='white', anchor='mm', font=font_large)
        
        # テキスト（下部）
        draw.text((center_x, center_y + 30), section["text"], 
                 fill='white', anchor='mm', font=font_large)
    
    # バイト列に変換
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    print("✅ 画像作成完了")
    return img_byte_arr

def upload_image(richmenu_id):
    """画像をアップロード"""
    print("📤 画像をアップロード中...")
    
    image_data = create_simple_image()
    
    headers_image = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "image/png"
    }
    
    response = requests.post(
        f"https://api-data.line.me/v2/bot/richmenu/{richmenu_id}/content",
        headers=headers_image,
        data=image_data.read()
    )
    
    if response.status_code == 200:
        print("✅ 画像アップロード成功")
        return True
    else:
        print(f"❌ 画像アップロード失敗: {response.status_code}")
        return False

def set_default(richmenu_id):
    """デフォルトに設定"""
    print("⚙️ デフォルトに設定中...")
    
    response = requests.post(
        f"https://api.line.me/v2/bot/user/all/richmenu/{richmenu_id}",
        headers=headers
    )
    
    if response.status_code == 200:
        print("✅ デフォルト設定成功")
        return True
    else:
        print(f"❌ デフォルト設定失敗: {response.status_code}")
        return False

def main():
    print("🚀 シンプルなリッチメニュー作成開始...")
    print("=" * 60)
    
    # 1. 既存削除
    delete_existing_richmenus()
    
    # 2. 新規作成
    richmenu_id = create_simple_richmenu()
    if not richmenu_id:
        print("❌ 作成失敗")
        return
    
    # 3. 画像アップロード
    if not upload_image(richmenu_id):
        print("❌ 画像アップロード失敗")
        return
    
    # 4. デフォルト設定
    if not set_default(richmenu_id):
        print("❌ デフォルト設定失敗")
        return
    
    print("\n" + "=" * 60)
    print("✅ シンプルなリッチメニュー作成完了！")
    print(f"リッチメニューID: {richmenu_id}")
    
    print("\n📝 設定されたメッセージ:")
    print("• AI相談")
    print("• AI住まいサイト") 
    print("• 資料請求")
    print("• 展示場予約")
    print("• 資金計画")
    print("• チャット相談")
    
    print("\n🧪 テスト方法:")
    print("1. LINE公式アカウントでリッチメニューを確認")
    print("2. 各ボタンをタップして応答を確認")
    print("3. ログで処理状況を確認:")
    print("   gcloud logs read rag-api --limit=20")

if __name__ == "__main__":
    main()