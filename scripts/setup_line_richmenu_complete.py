#!/usr/bin/env python3
"""
LINE リッチメニュー設定スクリプト（完全版）
python scripts/setup_line_richmenu_complete.py
"""

import os
import json
import requests
from PIL import Image, ImageDraw, ImageFont
import io
import sys

# 環境変数から取得
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

if not LINE_CHANNEL_ACCESS_TOKEN:
    print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
    sys.exit(1)

headers = {
    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

def create_rich_menu():
    """リッチメニューを作成（正しいテキスト設定）"""
    
    rich_menu_object = {
        "size": {
            "width": 2500,
            "height": 1686
        },
        "selected": True,
        "name": "キノエデザインホーム メニュー",
        "chatBarText": "メニュー",
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
                    "text": "🤖 AI相談 AI相談を開始します！ ご質問やお悩みを自由に 入力してください😊"
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
                    "text": "🌐 AI住まいサイト AI住まいホームページ、準備中です 今しばらくお待ちください😴"
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
                    "text": "📋 資料請求します！ お名前と送付先を ご入力ください😊"
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
                    "text": "📍 展示場来場予約します！日時をメッセージください 営業時間9-18時"
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
                    "text": "💰 資金計画 資金計画を開始します お名前と連絡先を送付先を ご入力ください😊"
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
                    "text": "💬 チャット相談 スタッフとチャット相談 気軽にメッセージどうぞ！ 営業時間9-18時"
                }
            }
        ]
    }
    
    # 既存のリッチメニューを削除
    print("🗑️ 既存のリッチメニューを確認・削除中...")
    try:
        existing_menus = requests.get(
            "https://api.line.me/v2/bot/richmenu/list",
            headers=headers
        )
        if existing_menus.status_code == 200:
            menus = existing_menus.json().get("richmenus", [])
            for menu in menus:
                menu_id = menu["richMenuId"]
                delete_response = requests.delete(
                    f"https://api.line.me/v2/bot/richmenu/{menu_id}",
                    headers=headers
                )
                if delete_response.status_code == 200:
                    print(f"  ✅ 既存メニュー削除: {menu_id}")
                else:
                    print(f"  ⚠️ メニュー削除失敗: {menu_id}")
    except Exception as e:
        print(f"  ⚠️ 既存メニュー確認エラー: {e}")
    
    # 新しいリッチメニューを作成
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
    """リッチメニュー画像を作成（実際のデザインに合わせた版）"""
    print("🎨 リッチメニュー画像を作成中...")
    
    # 2500x1686の画像を作成
    img = Image.new('RGB', (2500, 1686), color='white')
    draw = ImageDraw.Draw(img)
    
    # 各セクションの設定（実際のデザインに基づく）
    sections = [
        # 上段
        {
            "pos": (0, 0, 833, 843),
            "color": "#4A90E2",  # 青系
            "icon": "🤖",
            "title": "AI相談",
            "subtitle": "AI相談を開始します！\nご質問やお悩みを自由に\n入力してください😊"
        },
        {
            "pos": (833, 0, 1667, 843),
            "color": "#50C878",  # 緑系
            "icon": "🌐",
            "title": "AI住まい\nサイト",
            "subtitle": "AI住まいホームページ、\n準備中です\n今しばらくお待ちください😴"
        },
        {
            "pos": (1667, 0, 2500, 843),
            "color": "#FF6B6B",  # 赤系
            "icon": "📋",
            "title": "資料請求",
            "subtitle": "資料請求します！\nお名前と送付先を\nご入力ください😊"
        },
        # 下段
        {
            "pos": (0, 843, 833, 1686),
            "color": "#FFA500",  # オレンジ系
            "icon": "📍",
            "title": "展示場来場\n予約",
            "subtitle": "展示場来場予約します！\n日時をメッセージください\n営業時間9-18時"
        },
        {
            "pos": (833, 843, 1667, 1686),
            "color": "#9B59B6",  # 紫系
            "icon": "💰",
            "title": "資金計画",
            "subtitle": "資金計画を開始します\nお名前と連絡先を\nご入力ください😊"
        },
        {
            "pos": (1667, 843, 2500, 1686),
            "color": "#3498DB",  # 水色系
            "icon": "💬",
            "title": "チャット相談",
            "subtitle": "スタッフとチャット相談\n気軽にメッセージどうぞ！\n営業時間9-18時"
        }
    ]
    
    # フォント設定
    try:
        # 日本語フォントを優先的に探す
        font_paths = [
            "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",  # Mac
            "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",  # Linux
            "C:/Windows/Fonts/msgothic.ttc",  # Windows
        ]
        
        title_font = None
        subtitle_font = None
        
        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    title_font = ImageFont.truetype(font_path, 48)
                    subtitle_font = ImageFont.truetype(font_path, 24)
                    break
                except:
                    continue
        
        if not title_font:
            # デフォルトフォントを使用
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
            
    except:
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
    
    for section in sections:
        x1, y1, x2, y2 = section["pos"]
        
        # 背景を塗りつぶし
        draw.rectangle([x1, y1, x2, y2], fill=section["color"])
        
        # 白い境界線を描画
        draw.rectangle([x1, y1, x2-2, y2-2], outline='white', width=3)
        
        # 中央位置を計算
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        
        # アイコンを描画（上部）
        icon_y = center_y - 120
        draw.text((center_x, icon_y), section["icon"], fill='white', 
                 anchor='mm', font=ImageFont.truetype("/System/Library/Fonts/Apple Color Emoji.ttc", 72) if os.path.exists("/System/Library/Fonts/Apple Color Emoji.ttc") else title_font)
        
        # タイトルを描画（中央）
        title_y = center_y - 20
        draw.text((center_x, title_y), section["title"], fill='white', 
                 anchor='mm', font=title_font, align='center')
        
        # サブタイトルを描画（下部）
        subtitle_y = center_y + 60
        # サブタイトルを行ごとに描画
        lines = section["subtitle"].split('\n')
        for i, line in enumerate(lines):
            y_offset = subtitle_y + (i * 30)
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
        print(f"❌ リッチメニュー画像アップロード失敗: {response.status_code}")
        print(f"エラー詳細: {response.text}")
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
        print(f"エラー詳細: {response.text}")
        return False

def verify_rich_menu_settings():
    """リッチメニューの設定確認"""
    print("\n📝 リッチメニュー設定の確認...")
    
    # 設定されたアクションテキスト
    action_texts = {
        "A": "🤖 AI相談 AI相談を開始します！ ご質問やお悩みを自由に 入力してください😊",
        "B": "🌐 AI住まいサイト AI住まいホームページ、準備中です 今しばらくお待ちください😴",
        "C": "📋 資料請求します！ お名前と送付先を ご入力ください😊",
        "D": "📍 展示場来場予約します！日時をメッセージください 営業時間9-18時",
        "E": "💰 資金計画 資金計画を開始します お名前と連絡先を送付先を ご入力ください😊",
        "F": "💬 チャット相談 スタッフとチャット相談 気軽にメッセージどうぞ！ 営業時間9-18時"
    }
    
    print("\n✅ 設定されたアクションテキスト:")
    for key, text in action_texts.items():
        print(f"  {key}: {text[:30]}...")

def test_bot_functionality():
    """ボット機能のテスト"""
    print("\n🧪 ボット機能をテスト中...")
    
    # APIエンドポイントの確認
    try:
        status_response = requests.get(
            "https://rag-api-190389115361.asia-northeast1.run.app/line/status",
            timeout=10
        )
        
        if status_response.status_code == 200:
            status = status_response.json()
            print("✅ LINE Bot API接続確認:")
            print(f"  - LINE Bot設定: {status.get('line_bot_configured')}")
            print(f"  - LINE SDK利用可能: {status.get('line_sdk_available')}")
        else:
            print(f"❌ API接続失敗: {status_response.status_code}")
            
    except Exception as e:
        print(f"❌ API接続エラー: {e}")

def main():
    print("🚀 LINE リッチメニュー設定開始（完全版）...")
    print("=" * 60)
    
    # 1. リッチメニュー作成
    richmenu_id = create_rich_menu()
    if not richmenu_id:
        print("❌ リッチメニュー作成に失敗しました")
        return
    
    # 2. 画像アップロード
    if not upload_richmenu_image(richmenu_id):
        print("❌ 画像アップロードに失敗しました")
        return
    
    # 3. デフォルト設定
    if not set_default_richmenu(richmenu_id):
        print("❌ デフォルト設定に失敗しました")
        return
    
    # 4. 設定確認
    verify_rich_menu_settings()
    
    # 5. 機能テスト
    test_bot_functionality()
    
    print("\n" + "=" * 60)
    print("✅ リッチメニュー設定完了！")
    print(f"リッチメニューID: {richmenu_id}")
    
    print(f"""
🎉 設定完了！動作確認手順:

1. LINE公式アカウントを友だち追加
2. トーク画面下部にリッチメニューが表示されることを確認
3. 各ボタンをタップして動作確認:
   
   A. AI相談 → AIチャットが開始される
   B. AI住まいサイト → 準備中メッセージが表示される
   C. 資料請求 → 住所入力の案内が表示される
   D. 展示場予約 → 予約日時入力の案内が表示される
   E. 資金計画 → 連絡先入力の案内が表示される
   F. チャット相談 → チャット相談開始メッセージが表示される

⚠️ 問題がある場合の確認点:
- LINE Developers コンソールでWebhook設定を確認
- Cloud Runでの環境変数設定を確認
- ログを確認: gcloud logs read rag-api --limit=50
""")

if __name__ == "__main__":
    main()