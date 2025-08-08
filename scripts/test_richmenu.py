# テストスクリプト: test_richmenu.py
import requests
import json

webhook_url = "https://rag-api-190389115361.asia-northeast1.run.app/line/webhook"

# テストメッセージ（実際のリッチメニューのテキスト）
test_messages = [
    "🤖 AI相談\nAI相談を開始します！\nご質問やお悩みを自由に\n入力してください😊",
    "📋 資料請求\n資料請求します！\nお名前と送付先を\nご入力ください😊",
    "📍 展示場来場\n予約"
]

for msg in test_messages:
    payload = {
        "destination": "test",
        "events": [{
            "type": "message",
            "message": {"type": "text", "text": msg},
            "source": {"type": "user", "userId": "test-user"},
            "replyToken": "test-token"
        }]
    }
    
    response = requests.post(webhook_url, json=payload)
    print(f"Message: {msg[:30]}...")
    print(f"Status: {response.status_code}")