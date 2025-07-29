#!/usr/bin/env python3
"""
自然な回答生成のテストスクリプト
python scripts/test_natural_response.py
"""

import requests
import json
import time
from datetime import datetime

# APIエンドポイント
API_URL = "https://rag-api-190389115361.asia-northeast1.run.app"

def test_natural_responses():
    """自然な回答生成をテスト"""
    print("🧪 自然な回答生成テスト開始")
    print("=" * 60)
    print(f"時刻: {datetime.now()}")
    print(f"API URL: {API_URL}")
    print()

    # テストケース
    test_cases = [
        {
            "name": "住宅仕様に関する質問",
            "question": "住宅の標準仕様について教えてください"
        },
        {
            "name": "人気設備に関する質問", 
            "question": "最近人気の設備や間取りは何ですか？"
        },
        {
            "name": "価格に関する質問",
            "question": "坪単価はいくらですか？"
        },
        {
            "name": "一般的な挨拶",
            "question": "こんにちは"
        },
        {
            "name": "建築に関する基本的な質問",
            "question": "ZEH住宅とは何ですか？"
        }
    ]

    for i, test_case in enumerate(test_cases, 1):
        print(f"\n【テスト {i}】{test_case['name']}")
        print(f"質問: {test_case['question']}")
        print("-" * 40)

        try:
            # APIリクエスト送信
            response = requests.post(
                f"{API_URL}/chat/",
                json={
                    "question": test_case['question'],
                    "username": "test-user"
                },
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                answer = data.get("answer", "回答なし")
                
                print(f"✅ レスポンス取得成功")
                print(f"回答: {answer}")
                
                # 問題のあるパターンをチェック
                issues = []
                
                if "関連文書が見つかりました" in answer:
                    issues.append("デバッグ情報が含まれている")
                
                if "【質問】" in answer or "【回答】" in answer:
                    issues.append("不要な構造化情報が含まれている")
                
                if "出典:" in answer or ".pdf" in answer:
                    issues.append("出典情報が含まれている")
                
                # 縦書き文字の検出（連続する改行で単一文字）
                lines = answer.split('\n')
                single_char_lines = [line for line in lines if len(line.strip()) == 1]
                if len(single_char_lines) > 3:
                    issues.append("縦書き文字が含まれている可能性")
                
                if issues:
                    print(f"⚠️ 問題点: {', '.join(issues)}")
                else:
                    print("✅ 自然な回答が生成されています")
                    
            else:
                print(f"❌ APIエラー: {response.status_code}")
                print(f"エラー内容: {response.text}")

        except Exception as e:
            print(f"❌ リクエストエラー: {e}")

        # 次のリクエストまで少し待機
        time.sleep(1)

    print("\n" + "=" * 60)
    print("✅ テスト完了")

def test_line_integration():
    """LINE Botとの統合テスト"""
    print("\n\n🔗 LINE Bot統合テスト")
    print("=" * 60)

    # LINE Botのメッセージ形式をシミュレート
    line_messages = [
        "AI相談を開始",
        "住宅の標準仕様について教えてください",
        "最近人気の設備は何ですか？"
    ]

    for message in line_messages:
        print(f"\nLINEメッセージ: {message}")
        print("-" * 30)

        try:
            # Webhookペイロードを作成
            webhook_payload = {
                "destination": "test",
                "events": [{
                    "type": "message",
                    "message": {
                        "type": "text",
                        "id": f"test-{int(time.time())}",
                        "text": message
                    },
                    "timestamp": int(time.time() * 1000),
                    "source": {
                        "type": "user",
                        "userId": "test-user"
                    },
                    "replyToken": f"test-reply-{int(time.time())}"
                }]
            }

            response = requests.post(
                f"{API_URL}/line/webhook",
                json=webhook_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Line-Signature": "test-signature"
                },
                timeout=10
            )

            print(f"Webhookレスポンス: {response.status_code}")
            
            if response.status_code == 400:
                print("✅ 署名エラー（テストなので正常）")
            elif response.status_code == 200:
                print("✅ Webhook処理成功")
            else:
                print(f"⚠️ 予期しないレスポンス: {response.text}")

        except Exception as e:
            print(f"❌ Webhookテストエラー: {e}")

def show_deployment_checklist():
    """デプロイ後の確認チェックリスト"""
    print("\n\n📋 デプロイ後確認チェックリスト")
    print("=" * 60)

    checklist = [
        "✅ 修正されたコードがCloud Runにデプロイされているか",
        "✅ 環境変数が正しく設定されているか",
        "✅ rag/prompt_template.txt が更新されているか",
        "✅ チャットAPIが自然な回答を返すか",
        "✅ LINE Botが正常に動作するか",
        "✅ 縦書き文字の問題が解決されているか",
        "✅ デバッグ情報が表示されないか",
        "✅ 出典情報が非表示になっているか"
    ]

    for item in checklist:
        print(f"  {item}")

    print(f"\n💡 問題がある場合の対処法:")
    print("1. Cloud Buildログを確認")
    print("2. Cloud Runのログを確認")
    print("3. 環境変数の設定を再確認")
    print("4. 必要に応じて再デプロイを実行")

if __name__ == "__main__":
    test_natural_responses()
    test_line_integration()
    show_deployment_checklist()