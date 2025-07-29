#!/usr/bin/env python3
"""
現在のリッチメニューの設定を確認するスクリプト
python scripts/verify_richmenu.py
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

def check_current_richmenu():
    """現在のリッチメニュー設定を確認"""
    print("📱 現在のリッチメニュー設定を確認中...")
    print("=" * 60)
    
    # リッチメニューリストを取得
    response = requests.get(
        "https://api.line.me/v2/bot/richmenu/list",
        headers=headers
    )
    
    if response.status_code == 200:
        menus = response.json().get("richmenus", [])
        print(f"✅ リッチメニュー数: {len(menus)}")
        
        for menu in menus:
            print(f"\nメニューID: {menu['richMenuId']}")
            print(f"メニュー名: {menu['name']}")
            print(f"デフォルト設定: {menu['selected']}")
            print("\n各エリアのアクション:")
            
            for i, area in enumerate(menu['areas']):
                action = area['action']
                if action['type'] == 'message':
                    print(f"\nエリア{i+1}:")
                    print(f"  メッセージ: {action['text']}")
                    print(f"  文字数: {len(action['text'])}")
                    
                    # メッセージの内容を解析
                    if "AI相談" in action['text']:
                        print("  → AI相談ボタン")
                    elif "AI住まいサイト" in action['text']:
                        print("  → AI住まいサイトボタン")
                    elif "資料請求" in action['text']:
                        print("  → 資料請求ボタン")
                    elif "展示場" in action['text']:
                        print("  → 展示場予約ボタン")
                    elif "資金計画" in action['text']:
                        print("  → 資金計画ボタン")
                    elif "チャット相談" in action['text']:
                        print("  → チャット相談ボタン")
                        
    else:
        print(f"❌ リッチメニュー取得失敗: {response.status_code}")
        print(f"エラー詳細: {response.text}")

def test_message_processing():
    """メッセージ処理のテスト"""
    print("\n\n" + "=" * 60)
    print("📝 メッセージ処理の推奨パターン")
    print("=" * 60)
    
    print("\n部分一致での判定を推奨します:")
    print("例：")
    print('  if "AI相談" in message_text and ("開始" in message_text or "お話" in message_text):')
    print('  if "資料請求" in message_text and ("入力" in message_text or "送付先" in message_text):')
    print("\nこれにより、リッチメニューのテキストが少し変わっても対応できます。")

def check_webhook_logs():
    """ログ確認のコマンドを表示"""
    print("\n\n" + "=" * 60)
    print("📊 ログ確認コマンド")
    print("=" * 60)
    
    print("\n最新のLINE関連ログを確認:")
    print("```")
    print('gcloud logging read \'resource.type="cloud_run_revision" AND resource.labels.service_name="rag-api" AND textPayload:"LINE"\' --limit=50 --format=json')
    print("```")
    
    print("\nリアルタイムログ確認:")
    print("```")
    print('gcloud alpha logging tail \'resource.type="cloud_run_revision" AND resource.labels.service_name="rag-api" AND textPayload:"LINE"\'')
    print("```")

def main():
    print("🔍 LINE リッチメニュー設定確認")
    print("現在時刻:", os.popen('date').read().strip())
    print("\n")
    
    # 現在の設定を確認
    check_current_richmenu()
    
    # 推奨パターンを表示
    test_message_processing()
    
    # ログ確認方法を表示
    check_webhook_logs()
    
    print("\n\n" + "=" * 60)
    print("✅ 確認完了")
    print("\n対処方法:")
    print("1. line_bot.pyの判定ロジックを部分一致に変更")
    print("2. リッチメニューのテキストを再設定（必要に応じて）")
    print("3. ログを確認してエラーの詳細を特定")

if __name__ == "__main__":
    main()