#!/usr/bin/env python3
"""
LINE Bot + RAG システムの完全動作テスト
python scripts/complete_system_test.py
"""

import os
import json
import requests
import time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

# 設定
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
API_URL = "https://rag-api-190389115361.asia-northeast1.run.app"

class SystemTester:
    def __init__(self):
        self.results = []
        self.headers = {
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
    
    def test_api_health(self):
        """APIヘルスチェック"""
        print("\n🏥 APIヘルスチェック")
        print("-" * 50)
        
        try:
            response = requests.get(f"{API_URL}/healthz", timeout=10)
            if response.status_code == 200:
                self.results.append(("API Health", "✅ PASS"))
                print("✅ API正常稼働中")
                return True
            else:
                self.results.append(("API Health", "❌ FAIL"))
                print(f"❌ API異常: HTTP {response.status_code}")
                return False
        except Exception as e:
            self.results.append(("API Health", "❌ FAIL"))
            print(f"❌ API接続エラー: {e}")
            return False
    
    def test_line_bot_status(self):
        """LINE Bot状態確認"""
        print("\n🤖 LINE Bot状態確認")
        print("-" * 50)
        
        try:
            response = requests.get(f"{API_URL}/line/status", timeout=10)
            if response.status_code == 200:
                status = response.json()
                
                checks = [
                    ("LINE Bot Configured", status.get("line_bot_configured", False)),
                    ("SDK Available", status.get("line_sdk_available", False)),
                    ("Access Token Set", status.get("channel_access_token_set", False)),
                    ("Channel Secret Set", status.get("channel_secret_set", False))
                ]
                
                all_pass = True
                for check_name, check_result in checks:
                    if check_result:
                        print(f"  ✅ {check_name}")
                    else:
                        print(f"  ❌ {check_name}")
                        all_pass = False
                
                self.results.append(("LINE Bot Status", "✅ PASS" if all_pass else "⚠️ PARTIAL"))
                return all_pass
            else:
                self.results.append(("LINE Bot Status", "❌ FAIL"))
                return False
        except Exception as e:
            print(f"❌ エラー: {e}")
            self.results.append(("LINE Bot Status", "❌ FAIL"))
            return False
    
    def test_rag_system(self):
        """RAGシステムテスト"""
        print("\n📚 RAGシステムテスト")
        print("-" * 50)
        
        try:
            response = requests.get(f"{API_URL}/status", timeout=10)
            if response.status_code == 200:
                status = response.json()
                
                checks = [
                    ("LLM Loaded", status.get("llm_loaded", False)),
                    ("VectorStore Loaded", status.get("vectorstore_loaded", False)),
                    ("RAG Chain Loaded", status.get("rag_chain_loaded", False)),
                    ("OpenAI API Key Set", status.get("openai_api_key_set", False))
                ]
                
                all_pass = True
                for check_name, check_result in checks:
                    if check_result:
                        print(f"  ✅ {check_name}")
                    else:
                        print(f"  ❌ {check_name}")
                        all_pass = False
                
                self.results.append(("RAG System", "✅ PASS" if all_pass else "⚠️ PARTIAL"))
                return all_pass
            else:
                self.results.append(("RAG System", "❌ FAIL"))
                return False
        except Exception as e:
            print(f"❌ エラー: {e}")
            self.results.append(("RAG System", "❌ FAIL"))
            return False
    
    def test_richmenu_messages(self):
        """リッチメニューメッセージ処理テスト"""
        print("\n📱 リッチメニューメッセージ処理テスト")
        print("-" * 50)
        
        test_messages = [
            ("AI相談を開始", "ai_consultation"),
            ("AI住まいサイト", "ai_site"),
            ("資料請求", "document_request"),
            ("展示場予約", "exhibition_reservation"),
            ("資金計画相談", "finance_planning"),
            ("チャット相談", "chat_consultation")
        ]
        
        all_pass = True
        for message, expected_action in test_messages:
            webhook_payload = {
                "destination": "test",
                "events": [{
                    "type": "message",
                    "message": {
                        "type": "text",
                        "id": f"test-{datetime.now().timestamp()}",
                        "text": message
                    },
                    "timestamp": int(datetime.now().timestamp() * 1000),
                    "source": {
                        "type": "user",
                        "userId": "test-user"
                    },
                    "replyToken": f"test-token-{datetime.now().timestamp()}"
                }]
            }
            
            try:
                response = requests.post(
                    f"{API_URL}/line/webhook",
                    json=webhook_payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Line-Signature": "test-signature"
                    },
                    timeout=10
                )
                
                # 署名エラー(400)は正常
                if response.status_code in [200, 400]:
                    print(f"  ✅ {message} → 処理成功")
                else:
                    print(f"  ❌ {message} → エラー (HTTP {response.status_code})")
                    all_pass = False
                    
            except Exception as e:
                print(f"  ❌ {message} → エラー: {e}")
                all_pass = False
        
        self.results.append(("Rich Menu Messages", "✅ PASS" if all_pass else "❌ FAIL"))
        return all_pass
    
    def test_chat_endpoint(self):
        """チャットエンドポイントテスト"""
        print("\n💬 チャットエンドポイントテスト")
        print("-" * 50)
        
        test_queries = [
            "こんにちは",
            "坪単価について教えてください",
            "標準仕様は？"
        ]
        
        all_pass = True
        for query in test_queries:
            try:
                response = requests.post(
                    f"{API_URL}/chat/",
                    json={"question": query, "username": "test-user"},
                    timeout=30
                )
                
                if response.status_code == 200:
                    data = response.json()
                    answer = data.get("answer", "")
                    if answer and len(answer) > 10:
                        print(f"  ✅ '{query}' → 回答取得成功 ({len(answer)}文字)")
                    else:
                        print(f"  ⚠️ '{query}' → 回答が短い")
                        all_pass = False
                else:
                    print(f"  ❌ '{query}' → エラー (HTTP {response.status_code})")
                    all_pass = False
                    
            except Exception as e:
                print(f"  ❌ '{query}' → エラー: {e}")
                all_pass = False
        
        self.results.append(("Chat Endpoint", "✅ PASS" if all_pass else "⚠️ PARTIAL"))
        return all_pass
    
    def test_line_api_connection(self):
        """LINE API接続テスト"""
        print("\n🌐 LINE API接続テスト")
        print("-" * 50)
        
        if not LINE_CHANNEL_ACCESS_TOKEN:
            print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
            self.results.append(("LINE API Connection", "❌ FAIL"))
            return False
        
        try:
            # Bot情報取得
            response = requests.get(
                "https://api.line.me/v2/bot/info",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                bot_info = response.json()
                print(f"  ✅ Bot名: {bot_info.get('displayName', '不明')}")
                print(f"  ✅ Bot ID: {bot_info.get('userId', '不明')}")
                self.results.append(("LINE API Connection", "✅ PASS"))
                return True
            else:
                print(f"  ❌ 接続失敗: HTTP {response.status_code}")
                self.results.append(("LINE API Connection", "❌ FAIL"))
                return False
                
        except Exception as e:
            print(f"❌ エラー: {e}")
            self.results.append(("LINE API Connection", "❌ FAIL"))
            return False
    
    def test_richmenu_setup(self):
        """リッチメニュー設定確認"""
        print("\n📋 リッチメニュー設定確認")
        print("-" * 50)
        
        if not LINE_CHANNEL_ACCESS_TOKEN:
            print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
            self.results.append(("Rich Menu Setup", "❌ FAIL"))
            return False
        
        try:
            response = requests.get(
                "https://api.line.me/v2/bot/richmenu/list",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                menus = response.json().get("richmenus", [])
                
                if len(menus) > 0:
                    print(f"  ✅ リッチメニュー数: {len(menus)}")
                    
                    # デフォルトメニューの確認
                    has_default = False
                    for menu in menus:
                        if menu.get("selected"):
                            has_default = True
                            print(f"  ✅ デフォルトメニュー: {menu['name']}")
                            break
                    
                    if not has_default:
                        print("  ⚠️ デフォルトメニューが設定されていません")
                    
                    self.results.append(("Rich Menu Setup", "✅ PASS" if has_default else "⚠️ PARTIAL"))
                    return has_default
                else:
                    print("  ❌ リッチメニューが設定されていません")
                    self.results.append(("Rich Menu Setup", "❌ FAIL"))
                    return False
            else:
                print(f"  ❌ 取得失敗: HTTP {response.status_code}")
                self.results.append(("Rich Menu Setup", "❌ FAIL"))
                return False
                
        except Exception as e:
            print(f"❌ エラー: {e}")
            self.results.append(("Rich Menu Setup", "❌ FAIL"))
            return False
    
    def print_summary(self):
        """テスト結果サマリー"""
        print("\n" + "=" * 60)
        print("📊 テスト結果サマリー")
        print("=" * 60)
        
        for test_name, result in self.results:
            print(f"{result} {test_name}")
        
        # 全体の判定
        fail_count = sum(1 for _, result in self.results if "FAIL" in result)
        partial_count = sum(1 for _, result in self.results if "PARTIAL" in result)
        
        print("\n" + "-" * 60)
        if fail_count == 0 and partial_count == 0:
            print("🎉 すべてのテストに合格しました！")
            print("✅ システムは完全に動作しています")
        elif fail_count == 0:
            print("⚠️ 一部のテストで問題があります")
            print("詳細を確認して修正してください")
        else:
            print("❌ 重要な問題が見つかりました")
            print("早急に修正が必要です")
        
        # 推奨アクション
        print("\n📝 推奨アクション:")
        if fail_count > 0 or partial_count > 0:
            print("1. リッチメニューの再設定:")
            print("   python scripts/setup_fixed_richmenu.py")
            print("")
            print("2. Cloud Runの再デプロイ:")
            print("   gcloud builds submit --config cloudbuild-optimized.yaml")
            print("")
            print("3. ログの確認:")
            print("   gcloud logging read 'severity>=ERROR' --limit=20")

def main():
    print("🚀 LINE Bot + RAG システム完全動作テスト")
    print(f"実行時刻: {datetime.now()}")
    print("=" * 60)
    
    tester = SystemTester()
    
    # 各テストを実行
    tester.test_api_health()
    time.sleep(1)
    
    tester.test_line_bot_status()
    time.sleep(1)
    
    tester.test_rag_system()
    time.sleep(1)
    
    tester.test_line_api_connection()
    time.sleep(1)
    
    tester.test_richmenu_setup()
    time.sleep(1)
    
    tester.test_richmenu_messages()
    time.sleep(1)
    
    tester.test_chat_endpoint()
    
    # サマリー表示
    tester.print_summary()

if __name__ == "__main__":
    main()