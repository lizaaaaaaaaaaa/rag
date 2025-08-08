#!/usr/bin/env python3
"""
リッチメニュー文字化け修正版セットアップスクリプト
python scripts/setup_fixed_richmenu.py
"""

import os
import json
import requests
from PIL import Image, ImageDraw, ImageFont
import io
from dotenv import load_dotenv
load_dotenv()

# 環境変数から取得
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LIFF_ID = os.environ.get("LIFF_ID", "2007887876-vMNe74eX")

if not LINE_CHANNEL_ACCESS_TOKEN:
    print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
    exit(1)

headers = {
    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

def delete_all_richmenus():
    """すべてのリッチメニューを削除"""
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

def create_fixed_rich_menu():
    """修正版リッチメニューを作成（テキストは横書き）"""
    
    rich_menu_object = {
        "size": {
            "width": 2500,
            "height": 1686
        },
        "selected": True,
        "name": "キノエデザインRAGメニュー（修正版）",
        "chatBarText": "メニュー",
        "areas": [
            # A：AI相談（メッセージ送信）
            {
                "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
                "action": {
                    "type": "message",
                    "text": "AI相談を開始"
                }
            },
            # B：AIによいサイト（メッセージ送信）
            {
                "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
                "action": {
                    "type": "message",
                    "text": "AI住まいサイト"
                }
            },
            # C：資料請求（メッセージ送信）
            {
                "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                "action": {
                    "type": "message",
                    "text": "資料請求"
                }
            },
            # D：展示場予約（メッセージ送信）
            {
                "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
                "action": {
                    "type": "message",
                    "text": "展示場予約"
                }
            },
            # E：資金計画（メッセージ送信）
            {
                "bounds": {"x": 833, "y": 843, "width": 834, "height": 843},
                "action": {
                    "type": "message",
                    "text": "資金計画相談"
                }
            },
            # F：チャット相談（メッセージ送信）
            {
                "bounds": {"x": 1667, "y": 843, "width": 833, "height": 843},
                "action": {
                    "type": "message",
                    "text": "チャット相談"
                }
            }
        ]
    }
    
    print("📋 修正版リッチメニューを作成中...")
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
        print(f"❌ 作成失敗: {response.status_code}")
        print(f"エラー詳細: {response.text}")
        return None

def create_richmenu_image():
    """正しい日本語表示のリッチメニュー画像を作成"""
    print("🎨 リッチメニュー画像を作成中...")
    
    # 2500x1686の画像を作成
    img = Image.new('RGB', (2500, 1686), color='white')
    draw = ImageDraw.Draw(img)
    
    # 各セクションの設定（横書きテキスト）
    sections = [
        # 上段
        {
            "pos": (0, 0, 833, 843),
            "color": "#06C755",  # LINE緑
            "icon": "🤖",
            "title": "AI相談",
            "subtitle": "AIが質問に\nお答えします",
            "label": "A"
        },
        {
            "pos": (833, 0, 1667, 843),
            "color": "#00B900",  # 濃い緑
            "icon": "🏠",
            "title": "AI住まいサイト",
            "subtitle": "住まい情報を\nAIがご案内",
            "label": "B"
        },
        {
            "pos": (1667, 0, 2500, 843),
            "color": "#4A90E2",  # 青
            "icon": "📋",
            "title": "資料請求",
            "subtitle": "カタログを\nお送りします",
            "label": "C"
        },
        # 下段
        {
            "pos": (0, 843, 833, 1686),
            "color": "#FFA500",  # オレンジ
            "icon": "📍",
            "title": "展示場予約",
            "subtitle": "見学のご予約を\n承ります",
            "label": "D"
        },
        {
            "pos": (833, 843, 1667, 1686),
            "color": "#9B59B6",  # 紫
            "icon": "💰",
            "title": "資金計画",
            "subtitle": "ローン計算\nシミュレーション",
            "label": "E"
        },
        {
            "pos": (1667, 843, 2500, 1686),
            "color": "#3498DB",  # 水色
            "icon": "💬",
            "title": "チャット相談",
            "subtitle": "スタッフが\nお答えします",
            "label": "F"
        }
    ]
    
    # 日本語フォントの設定
    try:
        # 各OS用のフォントパス
        font_paths = [
            # Windows
            "C:/Windows/Fonts/msgothic.ttc",
            "C:/Windows/Fonts/meiryo.ttc",
            # Mac
            "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            # Linux
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        ]
        
        title_font = None
        subtitle_font = None
        
        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    title_font = ImageFont.truetype(font_path, 56)
                    subtitle_font = ImageFont.truetype(font_path, 32)
                    icon_font = ImageFont.truetype(font_path, 80)
                    break
                except:
                    continue
        
        if not title_font:
            # フォントが見つからない場合はデフォルト
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
            icon_font = ImageFont.load_default()
            print("⚠️ 日本語フォントが見つかりません。デフォルトフォントを使用します。")
            
    except Exception as e:
        print(f"フォント読み込みエラー: {e}")
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        icon_font = ImageFont.load_default()
    
    for section in sections:
        x1, y1, x2, y2 = section["pos"]
        
        # 背景を塗りつぶし
        draw.rectangle([x1, y1, x2, y2], fill=section["color"])
        
        # 白い境界線
        draw.rectangle([x1, y1, x2-3, y2-3], outline='white', width=3)
        
        # ラベル（左上）
        draw.text((x1+20, y1+20), section["label"], fill='white', font=subtitle_font)
        
        # 中央位置を計算
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        
        # アイコンを描画（上部中央）
        icon_y = center_y - 100
        # 絵文字の代わりにテキストで表示
        draw.text((center_x, icon_y), section["icon"], fill='white', 
                 anchor='mm', font=icon_font)
        
        # タイトルを描画（中央）
        title_y = center_y
        draw.text((center_x, title_y), section["title"], fill='white', 
                 anchor='mm', font=title_font)
        
        # サブタイトルを描画（下部）
        subtitle_lines = section["subtitle"].split('\n')
        subtitle_y = center_y + 80
        for i, line in enumerate(subtitle_lines):
            y_offset = subtitle_y + (i * 40)
            draw.text((center_x, y_offset), line, fill='white', 
                     anchor='mm', font=subtitle_font)
    
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
        print(f"❌ 画像アップロード失敗: {response.status_code}")
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
        print(f"❌ デフォルト設定失敗: {response.status_code}")
        return False

def test_message_detection():
    """メッセージ検出のテスト"""
    print("\n🧪 メッセージ検出テスト")
    print("=" * 60)
    
    test_messages = [
        "AI相談を開始",
        "AI住まいサイト", 
        "資料請求",
        "展示場予約",
        "資金計画相談",
        "チャット相談"
    ]
    
    for msg in test_messages:
        print(f"テストメッセージ: 「{msg}」")
        # ここでAPIにテストリクエストを送ることも可能

def main():
    print("🚀 リッチメニュー修正版セットアップ開始...")
    print("=" * 60)
    
    # 1. 既存メニューをすべて削除
    delete_all_richmenus()
    
    # 2. 修正版メニュー作成
    richmenu_id = create_fixed_rich_menu()
    if not richmenu_id:
        print("❌ リッチメニュー作成に失敗しました")
        return
    
    # 3. 画像アップロード
    if not upload_richmenu_image(richmenu_id):
        print("❌ 画像アップロードに失敗しました")
        return
    
    # 4. デフォルト設定
    if not set_default_richmenu(richmenu_id):
        print("❌ デフォルト設定に失敗しました")
        return
    
    # 5. メッセージテスト
    test_message_detection()
    
    print("\n" + "=" * 60)
    print("✅ リッチメニュー修正版設定完了！")
    print(f"リッチメニューID: {richmenu_id}")
    
    print("""
📱 設定されたメッセージアクション:
A. AI相談 → "AI相談を開始"
B. AI住まいサイト → "AI住まいサイト"
C. 資料請求 → "資料請求"
D. 展示場予約 → "展示場予約"
E. 資金計画 → "資金計画相談"
F. チャット相談 → "チャット相談"

✅ 次の確認事項:
1. LINEアプリでリッチメニューが正しく表示されることを確認
2. 各ボタンをタップして正常に動作することを確認
3. Cloud Runのログで処理が正常に行われていることを確認
""")

if __name__ == "__main__":
    main()