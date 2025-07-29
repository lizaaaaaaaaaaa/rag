#!/usr/bin/env python3
"""
リッチメニューの動作をテストするスクリプト
python scripts/test_richmenu_functions.py
"""

import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

# APIエンドポイント
API_URL = "https://rag-api-190389115361.asia-northeast1.run.app"

def test_webhook_with_richmenu_messages():
    """リッチメニューのメッセージをシミュレート"""
    print("🧪 リッチメニューメッセージのテスト")
    print("=" * 60)
    
    # テストメッセージ（実際のリッチメニューから送信されるもの）
    test_messages = [
        {
            "name": "AI相談",
            "text": "🤖 AI相談 AI相談を開始します！ ご質問やお悩みを自由に 入力してください😊"
        },
        {
            "name": "AI住まいサイト",
            "text": "🌐 AI住まいサイト AI住まいホームページ、準備中です 今しばらくお待ちください😴"
        },
        {
            "name": "資料請求",
            "text": "📋 資料請求します！ お名前と送付先を ご入力ください😊"
        },
        {
            "name": "展示場予約",
            "text": "📍 展示場来場予約します！日時をメッセージください 営業時間9-18時"
        },
        {
            "name": "資金計画",
            "text": "💰 資金計画 資金計画を開始します お名前と連絡先を送付先を ご入力ください😊"
        },
        {
            "name": "チャット相談",
            "text": "💬 チャット相談 スタッフとチャット相談 気軽にメッセージどうぞ！ 営業時間9-18時"
        }
    ]
    
    for msg in test_messages:
        print(f"\nテスト: {msg['name']}")
        print(f"メッセージ: {msg['text'][:50]}...")
        
        # Webhookペイロードを作成
        webhook_payload = {
            "destination": "test",
            "events": [{
                "type": "message",
                "message": {
                    "type": "text",
                    "id": f"test-{datetime.now().timestamp()}",
                    "text": msg['text']
                },
                "timestamp": int(datetime.now().timestamp() * 1000),
                "source": {
                    "type": "user",
                    "userId": "test-user"
                },
                "replyToken": f"test-reply-token-{datetime.now().timestamp()}"
            }]
        }
        
        try:
            # WebhookエンドポイントにPOST
            response = requests.post(
                f"{API_URL}/line/webhook",
                json=webhook_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Line-Signature": "test-signature"  # テスト用
                },
                timeout=10
            )
            
            print(f"  レスポンス: {response.status_code}")
            
            if response.status_code == 400:
                print("  → 署名エラー（テストなので正常）")
            elif response.status_code == 200:
                print("  → 処理成功")
            else:
                print(f"  → エラー: {response.text}")
                
        except Exception as e:
            print(f"  → エラー: {e}")

def check_api_status():
    """APIの状態を確認"""
    print("\n\n" + "=" * 60)
    print("🔍 API状態確認")
    print("=" * 60)
    
    try:
        # LINE Bot status
        response = requests.get(f"{API_URL}/line/status", timeout=5)
        if response.status_code == 200:
            status = response.json()
            print("✅ LINE Bot API Status:")
            for key, value in status.items():
                print(f"  - {key}: {value}")
        else:
            print(f"❌ LINE Bot API Status取得失敗: {response.status_code}")
            
        # Main API status
        response = requests.get(f"{API_URL}/status", timeout=5)
        if response.status_code == 200:
            status = response.json()
            print("\n✅ Main API Status:")
            for key, value in status.items():
                print(f"  - {key}: {value}")
                
    except Exception as e:
        print(f"❌ API接続エラー: {e}")

def test_direct_chat():
    """通常のチャット機能をテスト"""
    print("\n\n" + "=" * 60)
    print("💬 通常チャット機能テスト")
    print("=" * 60)
    
    test_queries = [
        "こんにちは",
        "住宅の坪単価を教えてください",
        "展示場の場所はどこですか？"
    ]
    
    for query in test_queries:
        print(f"\nクエリ: {query}")
        
        try:
            response = requests.post(
                f"{API_URL}/chat/",
                json={
                    "question": query,
                    "username": "test-user"
                },
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                answer = data.get("answer", "回答なし")
                print(f"回答: {answer[:100]}...")
            else:
                print(f"エラー: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"エラー: {e}")

def show_troubleshooting():
    """トラブルシューティング情報を表示"""
    print("\n\n" + "=" * 60)
    print("🔧 トラブルシューティング")
    print("=" * 60)
    
    print("\n1. リッチメニューが反応しない場合:")
    print("   - LINE Developersコンソールでメッセージアクションの内容を確認")
    print("   - Cloud Runのログで受信したメッセージを確認")
    print("   - line_bot.pyの判定ロジックが正しいか確認")
    
    print("\n2. エラーが発生する場合:")
    print("   - LINE Bot SDKのバージョンを確認 (3.5.0)")
    print("   - 環境変数が正しく設定されているか確認")
    print("   - Cloud Runのメモリ/CPUリソースが十分か確認")
    
    print("\n3. ログコマンド:")
    print("   # エラーログを確認")
    print('   gcloud logging read \'severity>=ERROR AND resource.labels.service_name="rag-api"\' --limit=20')
    print("\n   # LINE関連のすべてのログ")
    print('   gcloud logging read \'textPayload:"LINE" AND resource.labels.service_name="rag-api"\' --limit=50')

def main():
    print("🚀 リッチメニュー動作テスト開始")
    print(f"時刻: {datetime.now()}")
    print(f"API URL: {API_URL}\n")
    
    # API状態確認
    check_api_status()
    
    # リッチメニューメッセージのテスト
    test_webhook_with_richmenu_messages()
    
    # 通常チャット機能のテスト
    test_direct_chat()
    
    # トラブルシューティング情報
    show_troubleshooting()
    
    print("\n\n✅ テスト完了")

if __name__ == "__main__":
    main()