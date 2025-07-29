#!/usr/bin/env python3
"""
現在のリッチメニューのテキストを正確に確認するスクリプト
python scripts/debug_richmenu_texts.py
"""

import os
import requests
import json
from dotenv import load_dotenv
load_dotenv()

# 環境変数から取得
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

if not LINE_CHANNEL_ACCESS_TOKEN:
    print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
    exit(1)

headers = {
    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

def check_rich_menu_texts():
    """現在のリッチメニューのアクションテキストを確認"""
    print("📱 現在のリッチメニュー設定を確認中...")
    
    # リッチメニューリストを取得
    response = requests.get(
        "https://api.line.me/v2/bot/richmenu/list",
        headers=headers
    )
    
    if response.status_code == 200:
        menus = response.json().get("richmenus", [])
        print(f"✅ リッチメニュー数: {len(menus)}")
        
        for menu in menus:
            print(f"\n========================================")
            print(f"メニューID: {menu['richMenuId']}")
            print(f"メニュー名: {menu['name']}")
            print(f"選択状態: {menu['selected']}")
            print(f"\n各エリアのアクションテキスト（完全版）:")
            print("========================================")
            
            for i, area in enumerate(menu['areas']):
                action = area['action']
                if action['type'] == 'message':
                    print(f"\nエリア{i+1}:")
                    print(f"テキスト: 「{action['text']}」")
                    print(f"文字数: {len(action['text'])}")
                    print(f"16進ダンプ: {action['text'].encode('utf-8').hex()}")
                elif action['type'] == 'uri':
                    print(f"\nエリア{i+1}:")
                    print(f"URI: {action['uri']}")
            
            print("\n========================================")
            
            # 現在のデフォルトリッチメニューを確認
            if menu['selected']:
                print(f"✅ これがデフォルトのリッチメニューです")
    else:
        print(f"❌ リッチメニュー取得失敗: {response.status_code}")
        print(f"エラー詳細: {response.text}")

def test_message_matching():
    """メッセージマッチングのテスト"""
    print("\n📝 メッセージマッチングテスト")
    print("========================================")
    
    # 画像から読み取れるテキスト（推測）
    test_texts = [
        "A：テスト・ 💬AIとお話",
        "B：テスト・ 🏢AI住まいサイト AI住まいホームページ。 準備中です 今しばらくお待ちください😴",
        "C：テスト・ 📋資料請求します！ おるも和歌付き をご入力ください😊",
        "D：テスト・ 📍展示場来場 予約手続き を メッセージください",
        "E：テスト・ 💰資金計画 AI金融相談スタート！ 年収・自己資金など 調査にお間にします😊",
        "F：チャット相談 スタッフとチャット相談 気転にメッセージどうぞ！ 営業時間9-18時"
    ]
    
    for text in test_texts:
        print(f"\nテストテキスト: 「{text}」")
        print(f"文字数: {len(text)}")

if __name__ == "__main__":
    check_rich_menu_texts()
    test_message_matching()