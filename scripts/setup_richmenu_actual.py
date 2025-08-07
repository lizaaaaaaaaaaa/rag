#!/usr/bin/env python3
"""
実際の値でLIFF対応リッチメニュー設定
python setup_richmenu_actual.py
"""

import os
import json
import requests
from dotenv import load_dotenv
load_dotenv()

# 実際の値を設定
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LIFF_ID = "2007887876-vMNe74eX"
API_URL = "https://rag-api-190389115361.asia-northeast1.run.app"

if not LINE_CHANNEL_ACCESS_TOKEN:
    print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
    print("環境変数を設定してください：")
    print("export LINE_CHANNEL_ACCESS_TOKEN='your-messaging-api-token'")
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
    else:
        print(f"⚠️ リッチメニュー一覧取得失敗: {response.status_code}")

def create_liff_rich_menu():
    """LIFF対応のリッチメニューを作成"""
    
    rich_menu_object = {
        "size": {
            "width": 2500,
            "height": 1686
        },
        "selected": True,
        "name": "キノエデザインホーム LIFF メニュー v2",
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
                    "text": "🌐 AI住まいサイト 準備中です。今しばらくお待ちください😴"
                }
            },
            # 3. 資料請求（メッセージ）
            {
                "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                "action": {
                    "type": "message", 
                    "text": "📋 資料請求 お名前と送付先をご入力ください😊"
                }
            },
            # 4. 展示場予約（メッセージ）
            {
                "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
                "action": {
                    "type": "message",
                    "text": "📍 展示場来場予約 日時をメッセージください 営業時間9-18時"
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
                    "text": "💬 チャット相談 気軽にメッセージどうぞ！ 営業時間9-18時"
                }
            }
        ]
    }
    
    print("📋 LIFF対応リッチメニューを作成中...")
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
        print(f"❌ 作成失敗: {response.status_code}")
        print(f"エラー詳細: {response.text}")
        return None

def upload_simple_richmenu_image(richmenu_id):
    """シンプルなリッチメニュー画像をアップロード"""
    print("📤 リッチメニュー画像をアップロード中...")
    
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
        
        # 2500x1686の画像を作成
        img = Image.new('RGB', (2500, 1686), color='white')
        draw = ImageDraw.Draw(img)
        
        # 各セクションの設定
        sections = [
            # 上段
            {"pos": (0, 0, 833, 843), "color": "#FF6B6B", "text": "AI相談\n(LIFF)", "is_liff": True},
            {"pos": (833, 0, 1667, 843), "color": "#50C878", "text": "AI住まい\nサイト", "is_liff": False},
            {"pos": (1667, 0, 2500, 843), "color": "#4A90E2", "text": "資料請求", "is_liff": False},
            # 下段
            {"pos": (0, 843, 833, 1686), "color": "#FFA500", "text": "展示場\n予約", "is_liff": False},
            {"pos": (833, 843, 1667, 1686), "color": "#9B59B6", "text": "資金計画\n(LIFF)", "is_liff": True},
            {"pos": (1667, 843, 2500, 1686), "color": "#3498DB", "text": "チャット\n相談", "is_liff": False}
        ]
        
        # フォント設定
        try:
            font = ImageFont.truetype("arial.ttf", 48)
        except:
            font = ImageFont.load_default()
        
        for section in sections:
            x1, y1, x2, y2 = section["pos"]
            
            # 背景を塗りつぶし
            draw.rectangle([x1, y1, x2, y2], fill=section["color"])
            
            # LIFF アプリの場合は特別な枠線
            if section["is_liff"]:
                draw.rectangle([x1, y1, x2-2, y2-2], outline='#FFD700', width=6)
            else:
                draw.rectangle([x1, y1, x2-2, y2-2], outline='white', width=3)
            
            # テキストを描画
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2
            
            # マルチライン対応
            lines = section["text"].split('\n')
            total_height = len(lines) * 60
            start_y = center_y - total_height // 2
            
            for i, line in enumerate(lines):
                y_pos = start_y + (i * 60)
                draw.text((center_x, y_pos), line, fill='white', 
                         anchor='mm', font=font)
        
        # バイト列に変換
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        
        # アップロード
        headers_image = {
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "image/png"
        }
        
        response = requests.post(
            f"https://api-data.line.me/v2/bot/richmenu/{richmenu_id}/content",
            headers=headers_image,
            data=img_byte_arr.read()
        )
        
        if response.status_code == 200:
            print("✅ リッチメニュー画像アップロード成功")
            return True
        else:
            print(f"❌ 画像アップロード失敗: {response.status_code}")
            return False
            
    except ImportError:
        print("⚠️ PIL (Pillow) がインストールされていません")
        print("pip install Pillow でインストールしてください")
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
    print("🚀 LIFF対応リッチメニュー設定開始...")
    print("=" * 60)
    
    print(f"📋 設定情報:")
    print(f"  LIFF ID: {LIFF_ID}")
    print(f"  LIFF URL: https://liff.line.me/{LIFF_ID}")
    print(f"  API URL: {API_URL}")
    print()
    
    # 1. 既存メニュー削除
    delete_existing_richmenus()
    
    # 2. LIFF対応メニュー作成
    richmenu_id = create_liff_rich_menu()
    if not richmenu_id:
        print("❌ リッチメニュー作成に失敗しました")
        return
    
    # 3. 画像アップロード
    if not upload_simple_richmenu_image(richmenu_id):
        print("❌ 画像アップロードに失敗しました")
        return
    
    # 4. デフォルト設定
    if not set_default_richmenu(richmenu_id):
        print("❌ デフォルト設定に失敗しました")
        return
    
    print("\n" + "=" * 60)
    print("✅ LIFF対応リッチメニュー設定完了！")
    print(f"リッチメニューID: {richmenu_id}")
    
    print(f"""
🎉 設定完了！機能一覧:

📱 リッチメニューボタン:
1. AI相談 → LIFF アプリ起動
2. AI住まいサイト → メッセージ送信
3. 資料請求 → メッセージ送信  
4. 展示場予約 → メッセージ送信
5. 資金計画 → LIFF アプリ起動（資金計画モード）
6. チャット相談 → メッセージ送信

🔗 LIFF URL: https://liff.line.me/{LIFF_ID}

✅ 次の確認事項:
1. LINE公式アカウントを友だち追加
2. リッチメニューの「AI相談」をタップ
3. LIFFアプリが起動することを確認
4. メッセージボタンが正常に動作することを確認
""")

if __name__ == "__main__":
    main()