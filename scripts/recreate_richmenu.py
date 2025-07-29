#!/usr/bin/env python3
"""
リッチメニューを再作成するスクリプト（画像のテキストに基づいた修正版）
python scripts/recreate_richmenu.py
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

def delete_all_richmenus():
    """既存のリッチメニューをすべて削除"""
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
            else:
                print(f"❌ 削除失敗: {menu_id}")

def create_rich_menu():
    """画像に基づいた正確なリッチメニューを作成"""
    
    rich_menu_object = {
        "size": {
            "width": 2500,
            "height": 1686
        },
        "selected": True,
        "name": "キノエデザインホーム AIメニュー",
        "chatBarText": "メニュー▼",
        "areas": [
            # A: AI相談（左上）
            {
                "bounds": {
                    "x": 0,
                    "y": 0,
                    "width": 833,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "text": "A：テスト・ 💬AIとお話"
                }
            },
            # B: AI住まいサイト（中央上）
            {
                "bounds": {
                    "x": 833,
                    "y": 0,
                    "width": 834,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "text": "B：テスト・ 🏢AI住まいサイト AI住まいホームページ。 準備中です 今しばらくお待ちください😴"
                }
            },
            # C: 資料請求（右上）
            {
                "bounds": {
                    "x": 1667,
                    "y": 0,
                    "width": 833,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "text": "C：テスト・ 📋資料請求します！ おるも和歌付き をご入力ください😊"
                }
            },
            # D: 展示場来場予約（左下）
            {
                "bounds": {
                    "x": 0,
                    "y": 843,
                    "width": 833,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "text": "D：テスト・ 📍展示場来場 予約手続き を メッセージください"
                }
            },
            # E: 資金計画（中央下）
            {
                "bounds": {
                    "x": 833,
                    "y": 843,
                    "width": 834,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "text": "E：テスト・ 💰資金計画 AI金融相談スタート！ 年収・自己資金など 調査にお間にします😊"
                }
            },
            # F: チャット相談（右下）
            {
                "bounds": {
                    "x": 1667,
                    "y": 843,
                    "width": 833,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "text": "F：チャット相談 スタッフとチャット相談 気転にメッセージどうぞ！ 営業時間9-18時"
                }
            }
        ]
    }
    
    print("📋 新しいリッチメニューを作成中...")
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
        print(f"エラー詳細: {response.text}")
        return None

def create_richmenu_image():
    """リッチメニュー画像を作成（画像に合わせたデザイン）"""
    print("🎨 リッチメニュー画像を作成中...")
    
    # 2500x1686の画像を作成
    img = Image.new('RGB', (2500, 1686), color='#f0f0f0')
    draw = ImageDraw.Draw(img)
    
    # 各セクションの設定（画像に基づく）
    sections = [
        # 上段
        {
            "pos": (0, 0, 833, 843),
            "bg_color": "#FFE5E5",  # 薄いピンク
            "text_color": "#FF1493",  # 濃いピンク
            "icon": "🤖",
            "label": "AI相談",
            "main_text": "AIとお話"
        },
        {
            "pos": (833, 0, 1667, 843),
            "bg_color": "#E5F5FF",  # 薄い青
            "text_color": "#0080FF",  # 青
            "icon": "🌐",
            "label": "AI住まい\nサイト",
            "main_text": ""
        },
        {
            "pos": (1667, 0, 2500, 843),
            "bg_color": "#FFE5CC",  # 薄いオレンジ
            "text_color": "#FF8C00",  # オレンジ
            "icon": "📋",
            "label": "資料請求",
            "main_text": ""
        },
        # 下段
        {
            "pos": (0, 843, 833, 1686),
            "bg_color": "#E5FFE5",  # 薄い緑
            "text_color": "#228B22",  # 緑
            "icon": "📍",
            "label": "展示場来場\n予約",
            "main_text": ""
        },
        {
            "pos": (833, 843, 1667, 1686),
            "bg_color": "#FFFFE5",  # 薄い黄色
            "text_color": "#FFD700",  # 金色
            "icon": "💰",
            "label": "資金計画",
            "main_text": ""
        },
        {
            "pos": (1667, 843, 2500, 1686),
            "bg_color": "#FFE5FF",  # 薄い紫
            "text_color": "#9370DB",  # 紫
            "icon": "💬",
            "label": "チャット相談",
            "main_text": ""
        }
    ]
    
    # フォント設定
    try:
        icon_font = ImageFont.truetype("/System/Library/Fonts/Apple Color Emoji.ttc", 100) if os.path.exists("/System/Library/Fonts/Apple Color Emoji.ttc") else ImageFont.load_default()
        label_font = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 36) if os.path.exists("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc") else ImageFont.load_default()
    except:
        icon_font = ImageFont.load_default()
        label_font = ImageFont.load_default()
    
    for section in sections:
        x1, y1, x2, y2 = section["pos"]
        
        # 背景を塗りつぶし
        draw.rectangle([x1, y1, x2, y2], fill=section["bg_color"])
        
        # 白い境界線
        draw.rectangle([x1, y1, x2-2, y2-2], outline='white', width=4)
        
        # 中央位置を計算
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        
        # アイコンを描画
        icon_y = center_y - 80
        draw.text((center_x, icon_y), section["icon"], fill=section["text_color"], 
                 anchor='mm', font=icon_font)
        
        # ラベルを描画
        label_y = center_y + 30
        lines = section["label"].split('\n')
        for i, line in enumerate(lines):
            y_offset = label_y + (i * 40)
            draw.text((center_x, y_offset), line, fill=section["text_color"], 
                     anchor='mm', font=label_font)
    
    # バイト列に変換
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    print("✅ リッチメニュー画像作成完了")
    return img_byte_arr

def upload_richmenu_image(richmenu_id):
    """リッチメニュー画像をアップロード"""
    print("📤 リッチメニュー画像をアップロード中...")
    
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
        print(f"❌ リッチメニュー画像アップロード失敗: {response.status_code}")
        return False

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
        print(f"❌ デフォルトリッチメニュー設定失敗: {response.status_code}")
        return False

def main():
    print("🚀 リッチメニュー再作成開始...")
    print("=" * 60)
    
    # 1. 既存のメニューを削除
    delete_all_richmenus()
    
    # 2. 新しいメニューを作成
    richmenu_id = create_rich_menu()
    if not richmenu_id:
        print("❌ リッチメニュー作成に失敗しました")
        return
    
    # 3. 画像をアップロード
    if not upload_richmenu_image(richmenu_id):
        print("❌ 画像アップロードに失敗しました")
        return
    
    # 4. デフォルトに設定
    if not set_default_richmenu(richmenu_id):
        print("❌ デフォルト設定に失敗しました")
        return
    
    print("\n" + "=" * 60)
    print("✅ リッチメニュー再作成完了！")
    print(f"リッチメニューID: {richmenu_id}")
    print("\n設定されたアクションテキスト:")
    print("A: A：テスト・ 💬AIとお話")
    print("B: B：テスト・ 🏢AI住まいサイト AI住まいホームページ。 準備中です 今しばらくお待ちください😴")
    print("C: C：テスト・ 📋資料請求します！ おるも和歌付き をご入力ください😊")
    print("D: D：テスト・ 📍展示場来場 予約手続き を メッセージください")
    print("E: E：テスト・ 💰資金計画 AI金融相談スタート！ 年収・自己資金など 調査にお間にします😊")
    print("F: F：チャット相談 スタッフとチャット相談 気転にメッセージどうぞ！ 営業時間9-18時")

if __name__ == "__main__":
    main()