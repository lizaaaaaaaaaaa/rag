#!/usr/bin/env python3
"""
LIFF対応リッチメニュー設定スクリプト
python scripts/setup_richmenu_with_liff.py
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
LIFF_ID = os.environ.get("LIFF_ID")
API_URL = "https://rag-api-190389115361.asia-northeast1.run.app"

if not LINE_CHANNEL_ACCESS_TOKEN:
    print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
    sys.exit(1)

if not LIFF_ID:
    print("❌ LIFF_ID が設定されていません")
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

def create_liff_rich_menu():
    """LIFF対応のリッチメニューを作成"""
    
    rich_menu_object = {
        "size": {
            "width": 2500,
            "height": 1686
        },
        "selected": True,
        "name": "キノエデザインホーム LIFF メニュー",
        "chatBarText": "メニュー",
        "areas": [
            # 1. AI相談（LIFF起動）
            {
                "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
                "action": {
                    "type": "uri",
                    "uri": f"https://liff.line.me/{LIFF_ID}"
                }
            },
            # 2. AI住まいサイト（メッセージ）
            {
                "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
                "action": {
                    "type": "message",
                    "text": "🌐 AI住まいサイト\n準備中です。今しばらくお待ちください😴"
                }
            },
            # 3. 資料請求（メッセージ）
            {
                "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                "action": {
                    "type": "message", 
                    "text": "📋 資料請求\nお名前と送付先をご入力ください😊"
                }
            },
            # 4. 展示場予約（メッセージ）
            {
                "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
                "action": {
                    "type": "message",
                    "text": "📍 展示場来場予約\n日時をメッセージください\n営業時間9-18時"
                }
            },
            # 5. 資金計画（LIFF起動 - 別機能）
            {
                "bounds": {"x": 833, "y": 843, "width": 834, "height": 843},
                "action": {
                    "type": "uri",
                    "uri": f"https://liff.line.me/{LIFF_ID}?mode=finance"
                }
            },
            # 6. チャット相談（メッセージ）
            {
                "bounds": {"x": 1667, "y": 843, "width": 833, "height": 843},
                "action": {
                    "type": "message",
                    "text": "💬 チャット相談\n気軽にメッセージどうぞ！\n営業時間9-18時"
                }
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
        print(f"✅ LIFF対応リッチメニュー作成成功: {richmenu_id}")
        return richmenu_id
    else:
        print(f"❌ 作成失敗: {response.text}")
        return None

def create_liff_richmenu_image():
    """LIFF対応リッチメニュー画像を作成"""
    print("🎨 LIFF対応リッチメニュー画像を作成中...")
    
    # 2500x1686の画像を作成
    img = Image.new('RGB', (2500, 1686), color='white')
    draw = ImageDraw.Draw(img)
    
    # 各セクションの設定
    sections = [
        # 上段
        {
            "pos": (0, 0, 833, 843),
            "color": "#FF6B6B",  # 赤系（LIFF）
            "icon": "🤖",
            "title": "AI相談",
            "subtitle": "LIFF\nアプリで\n相談開始",
            "is_liff": True
        },
        {
            "pos": (833, 0, 1667, 843),
            "color": "#50C878",  # 緑系
            "icon": "🌐",
            "title": "AI住まい\nサイト",
            "subtitle": "準備中です\n今しばらく\nお待ちください😴",
            "is_liff": False
        },
        {
            "pos": (1667, 0, 2500, 843),
            "color": "#4A90E2",  # 青系
            "icon": "📋",
            "title": "資料請求",
            "subtitle": "お名前と\n送付先を\nご入力ください😊",
            "is_liff": False
        },
        # 下段
        {
            "pos": (0, 843, 833, 1686),
            "color": "#FFA500",  # オレンジ系
            "icon": "📍",
            "title": "展示場来場\n予約",
            "subtitle": "日時を\nメッセージ\nください",
            "is_liff": False
        },
        {
            "pos": (833, 843, 1667, 1686),
            "color": "#9B59B6",  # 紫系（LIFF）
            "icon": "💰",
            "title": "資金計画",
            "subtitle": "LIFF\nアプリで\n計算開始",
            "is_liff": True
        },
        {
            "pos": (1667, 843, 2500, 1686),
            "color": "#3498DB",  # 水色系
            "icon": "💬",
            "title": "チャット相談",
            "subtitle": "気軽に\nメッセージ\nどうぞ！",
            "is_liff": False
        }
    ]
    
    # フォント設定
    try:
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
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
            
    except:
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
    
    for section in sections:
        x1, y1, x2, y2 = section["pos"]
        
        # 背景を塗りつぶし
        draw.rectangle([x1, y1, x2, y2], fill=section["color"])
        
        # LIFF アプリの場合は特別な枠線
        if section["is_liff"]:
            # 金色の枠線でLIFFアプリを強調
            draw.rectangle([x1, y1, x2-2, y2-2], outline='#FFD700', width=6)
            # LIFF マークを追加
            draw.text((x1+20, y1+20), "LIFF", fill='#FFD700', font=subtitle_font)
        else:
            # 通常の白い境界線
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
        lines = section["subtitle"].split('\n')
        for i, line in enumerate(lines):
            y_offset = subtitle_y + (i * 30)
            draw.text((center_x, y_offset), line, fill='white', 
                     anchor='mm', font=subtitle_font)
    
    # バイト列に変換
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    print("✅ LIFF対応リッチメニュー画像作成完了")
    return img_byte_arr

def upload_richmenu_image(richmenu_id):
    """リッチメニュー画像をアップロード"""
    print("📤 リッチメニュー画像をアップロード中...")
    
    image_data = create_liff_richmenu_image()
    
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

def verify_liff_setup():
    """LIFF設定の確認"""
    print("\n📝 LIFF設定の確認...")
    
    # LIFF アプリの確認（実際のAPIは制限があるため、設定確認のみ）
    print(f"✅ LIFF ID: {LIFF_ID}")
    print(f"✅ LIFF URL: https://liff.line.me/{LIFF_ID}")
    print(f"✅ API URL: {API_URL}")
    
    # リッチメニューの設定確認
    response = requests.get(
        "https://api.line.me/v2/bot/richmenu/list",
        headers=headers
    )
    
    if response.status_code == 200:
        menus = response.json().get("richmenus", [])
        for menu in menus:
            if menu.get("selected"):
                print(f"✅ アクティブなリッチメニュー: {menu['name']}")
                
                # LIFF URIの確認
                liff_count = 0
                for area in menu.get("areas", []):
                    action = area.get("action", {})
                    if action.get("type") == "uri" and "liff.line.me" in action.get("uri", ""):
                        liff_count += 1
                
                print(f"✅ LIFF URIボタン数: {liff_count}")

def main():
    print("🚀 LIFF対応リッチメニュー設定開始...")
    print("=" * 60)
    
    print(f"📋 設定情報:")
    print(f"  LIFF ID: {LIFF_ID}")
    print(f"  API URL: {API_URL}")
    print(f"  LIFF URL: https://liff.line.me/{LIFF_ID}")
    print()
    
    # 1. 既存メニュー削除
    delete_existing_richmenus()
    
    # 2. LIFF対応メニュー作成
    richmenu_id = create_liff_rich_menu()
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
    
    # 5. 設定確認
    verify_liff_setup()
    
    print("\n" + "=" * 60)
    print("✅ LIFF対応リッチメニュー設定完了！")
    print(f"リッチメニューID: {richmenu_id}")
    
    print(f"""
🎉 設定完了！LIFF対応機能:

📱 リッチメニューボタン設定:
1. AI相談 → LIFF アプリ起動 ({LIFF_ID})
2. AI住まいサイト → メッセージ送信
3. 資料請求 → メッセージ送信  
4. 展示場予約 → メッセージ送信
5. 資金計画 → LIFF アプリ起動（資金計画モード）
6. チャット相談 → メッセージ送信

🔗 LIFF アプリURL:
https://liff.line.me/{LIFF_ID}

⚠️ 次のステップ:
1. LINE Developers でLIFFアプリのエンドポイントURLを設定:
   → {API_URL}/liff
   
2. LINEログインのコールバックURLを設定:
   → {API_URL}/line-login/callback
   
3. 動作確認:
   - リッチメニューの「AI相談」をタップ
   - LIFFアプリが起動することを確認
   - ログイン機能が正常に動作することを確認
""")

if __name__ == "__main__":
    main()