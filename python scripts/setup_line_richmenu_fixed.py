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
    """リッチメニューを作成（AI相談メッセージを修正）"""
    
    rich_menu_object = {
        "size": {
            "width": 2500,
            "height": 1686
        },
        "selected": True,
        "name": "RAG AI Chat Menu",
        "chatBarText": "メニュー",
        "areas": [
            # AI相談ボタン（左上）- メッセージを修正
            {
                "bounds": {
                    "x": 0,
                    "y": 0,
                    "width": 833,
                    "height": 843
                },
                "action": {
                    "type": "message",
                    "text": "AI相談を開始"  # この文字列が重要
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
                    "uri": "https://leafy-kitsune-eb4566.netlify.app"  # 実際のWebサイトURL
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
    """リッチメニュー画像を作成（改良版）"""
    print("🎨 リッチメニュー画像を作成中...")
    
    # 2500x1686の画像を作成
    img = Image.new('RGB', (2500, 1686), color='white')
    draw = ImageDraw.Draw(img)
    
    # 各セクションの色とテキスト
    sections = [
        # 上段
        {"pos": (0, 0, 833, 843), "color": "#FF6B6B", "text": "AI相談", "emoji": "🤖"},
        {"pos": (833, 0, 1667, 843), "color": "#4ECDC4", "text": "AI住まい\nサイト", "emoji": "🌐"},
        {"pos": (1667, 0, 2500, 843), "color": "#45B7D1", "text": "資料請求", "emoji": "📋"},
        # 下段
        {"pos": (0, 843, 833, 1686), "color": "#96CEB4", "text": "展示場来場\n予約", "emoji": "📍"},
        {"pos": (833, 843, 1667, 1686), "color": "#FECA57", "text": "資金計画", "emoji": "💰"},
        {"pos": (1667, 843, 2500, 1686), "color": "#48C9B0", "text": "チャット相談", "emoji": "💬"}
    ]
    
    # フォント設定（デフォルトフォントを使用）
    try:
        # 大きいフォントサイズを試す
        font_large = ImageFont.load_default()
        font_emoji = ImageFont.load_default()
    except:
        font_large = ImageFont.load_default()
        font_emoji = ImageFont.load_default()
    
    for section in sections:
        x1, y1, x2, y2 = section["pos"]
        
        # 背景を塗りつぶし
        draw.rectangle([x1, y1, x2, y2], fill=section["color"])
        
        # 境界線を描画
        draw.rectangle([x1, y1, x2-1, y2-1], outline='white', width=3)
        
        # テキストの中央配置を計算
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        
        # 絵文字を上部に配置
        emoji_y = center_y - 80
        draw.text((center_x, emoji_y), section["emoji"], fill='white', 
                 anchor='mm', font=font_emoji)
        
        # テキストを下部に配置
        text_y = center_y + 40
        draw.text((center_x, text_y), section["text"], fill='white', 
                 anchor='mm', font=font_large)
    
    # タイトルを上部に追加
    draw.text((1250, 50), "キノエデザインホーム", fill='#333333', 
             anchor='mm', font=font_large)
    
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

def verify_webhook_settings():
    """Webhook設定の確認"""
    print("🔍 Webhook設定を確認中...")
    
    expected_webhook = "https://rag-api-190389115361.asia-northeast1.run.app/line/webhook"
    
    print(f"期待するWebhook URL: {expected_webhook}")
    print("\n⚠️ 以下を LINE Developers コンソールで確認してください:")
    print("1. Messaging API設定 > Webhook URL が正しく設定されているか")
    print("2. Webhookの利用 が「有効」になっているか")
    print("3. 自動応答メッセージ が「無効」になっているか")
    print("4. あいさつメッセージ が「無効」になっているか")

def test_ai_consultation():
    """AI相談機能のテスト"""
    print("\n🧪 AI相談機能をテスト中...")
    
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
            print(f"  - アクセストークン設定: {status.get('channel_access_token_set')}")
            print(f"  - チャネルシークレット設定: {status.get('channel_secret_set')}")
        else:
            print(f"❌ API接続失敗: {status_response.status_code}")
            
    except Exception as e:
        print(f"❌ API接続エラー: {e}")

def main():
    print("🚀 LINE リッチメニュー設定開始...")
    print("=" * 60)
    
    # 1. Webhook設定確認
    verify_webhook_settings()
    
    print("\n" + "=" * 60)
    
    # 2. リッチメニュー作成
    richmenu_id = create_rich_menu()
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
    
    # 5. API接続テスト
    test_ai_consultation()
    
    print("\n" + "=" * 60)
    print("✅ リッチメニュー設定完了！")
    print(f"リッチメニューID: {richmenu_id}")
    
    print(f"""
🎉 設定完了！以下の手順でテストしてください:

1. LINE公式アカウントを友だち追加
2. トーク画面下部にリッチメニューが表示されることを確認
3. 「AI相談」ボタンをタップ
4. 「AI相談を開始します！🤖」というメッセージが表示される
5. 質問を入力してRAGチャットボットが応答することを確認

⚠️ 問題がある場合の確認点:
- LINE Developers コンソールでWebhook設定を確認
- Cloud Runでの環境変数設定を確認
- ログを確認: gcloud logs read rag-api --limit=50
""")

if __name__ == "__main__":
    main()