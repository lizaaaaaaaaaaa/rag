#!/usr/bin/env python3
"""
LINE リッチメニュー設定スクリプト
python scripts/setup_line_richmenu.py
"""

import os
import json
import requests
from PIL import Image, ImageDraw, ImageFont
import io

# 環境変数から取得
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

if not LINE_CHANNEL_ACCESS_TOKEN:
    print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
    exit(1)

headers = {
    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

# リッチメニューの作成
def create_rich_menu():
    """リッチメニューを作成"""
    
    rich_menu_object = {
        "size": {
            "width": 2500,
            "height": 1686
        },
        "selected": True,
        "name": "RAG Chat Menu",
        "chatBarText": "メニュー",
        "areas": [
            # AI相談ボタン（左上）
            {
                "bounds": {
                    "x": 0,
                    "y": 0,
                    "width": 833,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "text": "AI相談を開始"
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
                    "type": "uri",
                    "uri": "https://your-website.com"
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
            # 展示場来場予約（左下）
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
                    "text": "資金計画相談"
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
    
    # リッチメニューを作成
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
        print(f"❌ リッチメニュー作成失敗: {response.text}")
        return None

def create_richmenu_image():
    """リッチメニュー画像を作成（簡易版）"""
    # 2500x1686の画像を作成
    img = Image.new('RGB', (2500, 1686), color='white')
    draw = ImageDraw.Draw(img)
    
    # グリッド線を描画
    # 垂直線
    draw.line([(833, 0), (833, 1686)], fill='gray', width=2)
    draw.line([(1667, 0), (1667, 1686)], fill='gray', width=2)
    
    # 水平線
    draw.line([(0, 843), (2500, 843)], fill='gray', width=2)
    
    # テキストを追加（フォントがない場合は省略）
    menu_items = [
        ("AI相談", 416, 421),
        ("AI住まい\nサイト", 1250, 421),
        ("資料請求", 2083, 421),
        ("展示場来場\n予約", 416, 1264),
        ("資金計画", 1250, 1264),
        ("チャット相談", 2083, 1264)
    ]
    
    # 各メニューアイテムに背景色を追加
    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FECA57', '#48C9B0']
    
    for i, (text, x, y) in enumerate(menu_items):
        # 背景を塗りつぶし
        left = (i % 3) * 833
        top = (i // 3) * 843
        draw.rectangle([left, top, left + 833, top + 843], fill=colors[i])
        
        # テキストを描画（中央寄せ）
        draw.text((x, y), text, fill='white', anchor='mm')
    
    # バイト列に変換
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    return img_byte_arr

def upload_richmenu_image(richmenu_id):
    """リッチメニュー画像をアップロード"""
    image_data = create_richmenu_image()
    
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
        print("✅ リッチメニュー画像アップロード成功")
        return True
    else:
        print(f"❌ リッチメニュー画像アップロード失敗: {response.text}")
        return False

def set_default_richmenu(richmenu_id):
    """デフォルトのリッチメニューに設定"""
    response = requests.post(
        f"https://api.line.me/v2/bot/user/all/richmenu/{richmenu_id}",
        headers=headers
    )
    
    if response.status_code == 200:
        print("✅ デフォルトリッチメニュー設定成功")
        return True
    else:
        print(f"❌ デフォルトリッチメニュー設定失敗: {response.text}")
        return False

def main():
    print("🚀 LINE リッチメニュー設定開始...")
    
    # 1. リッチメニュー作成
    richmenu_id = create_rich_menu()
    if not richmenu_id:
        return
    
    # 2. 画像アップロード
    if not upload_richmenu_image(richmenu_id):
        return
    
    # 3. デフォルト設定
    if not set_default_richmenu(richmenu_id):
        return
    
    print(f"""
✅ リッチメニュー設定完了！
リッチメニューID: {richmenu_id}

テスト方法:
1. LINE公式アカウントを友だち追加
2. トーク画面下部にリッチメニューが表示されることを確認
3. 「AI相談」ボタンをタップ
4. 「AI相談を開始」というメッセージが送信される
5. RAGチャットボットが応答することを確認
""")

if __name__ == "__main__":
    main()