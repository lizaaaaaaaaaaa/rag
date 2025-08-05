#!/usr/bin/env python3
"""
LIFF設定とテスト用スクリプト
python scripts/setup_liff.py
"""

import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class LIFFSetupManager:
    def __init__(self):
        self.line_login_channel_id = os.environ.get("LINE_LOGIN_CHANNEL_ID")
        self.line_login_channel_secret = os.environ.get("LINE_LOGIN_CHANNEL_SECRET")
        self.liff_app_id = os.environ.get("LIFF_APP_ID")
        self.api_base = os.environ.get("API_URL", "https://rag-api-190389115361.asia-northeast1.run.app")
        
    def check_environment(self):
        """環境変数の確認"""
        print("🔍 LIFF環境変数の確認")
        print("=" * 50)
        
        env_vars = {
            "LINE_LOGIN_CHANNEL_ID": self.line_login_channel_id,
            "LINE_LOGIN_CHANNEL_SECRET": self.line_login_channel_secret,
            "LIFF_APP_ID": self.liff_app_id,
            "JWT_SECRET": os.environ.get("JWT_SECRET"),
            "API_URL": self.api_base
        }
        
        for key, value in env_vars.items():
            status = "✅ 設定済み" if value else "❌ 未設定"
            if value and key in ["LINE_LOGIN_CHANNEL_SECRET", "JWT_SECRET"]:
                display_value = f"{value[:10]}..." if len(value) > 10 else value
            else:
                display_value = value or "未設定"
            print(f"  {key}: {status} ({display_value})")
        
        missing_vars = [k for k, v in env_vars.items() if not v]
        if missing_vars:
            print(f"\n❌ 未設定の環境変数: {', '.join(missing_vars)}")
            return False
        else:
            print("\n✅ すべての環境変数が設定されています")
            return True
    
    def test_api_endpoints(self):
        """APIエンドポイントのテスト"""
        print("\n🧪 APIエンドポイントのテスト")
        print("=" * 50)
        
        # LIFF設定取得テスト
        try:
            response = requests.get(f"{self.api_base}/liff/config", timeout=10)
            if response.status_code == 200:
                config = response.json()
                print("✅ LIFF設定取得成功:")
                print(f"  LIFF ID: {config.get('liff_id')}")
                print(f"  API Endpoint: {config.get('api_endpoint')}")
            else:
                print(f"❌ LIFF設定取得失敗: {response.status_code}")
        except Exception as e:
            print(f"❌ LIFF設定取得エラー: {e}")
        
        # メインAPI状態確認
        try:
            response = requests.get(f"{self.api_base}/status", timeout=10)
            if response.status_code == 200:
                status = response.json()
                print("\n✅ メインAPI状態:")
                print(f"  LLM: {'✅' if status.get('llm_loaded') else '❌'}")
                print(f"  VectorStore: {'✅' if status.get('vectorstore_loaded') else '❌'}")
                print(f"  LINE Bot: {'✅' if status.get('line_bot_configured') else '❌'}")
            else:
                print(f"❌ メインAPI状態取得失敗: {response.status_code}")
        except Exception as e:
            print(f"❌ メインAPI状態取得エラー: {e}")
    
    def create_liff_urls(self):
        """LIFF用URLの生成"""
        print("\n🔗 LIFF設定用URL")
        print("=" * 50)
        
        base_url = self.api_base.replace("rag-api", "rag-frontend")  # フロントエンドURL
        
        urls = {
            "LIFF Endpoint URL": f"{base_url}/liff-chat.html",
            "Callback URL (LINE Login)": f"{self.api_base}/liff/callback",
            "API Verify Token": f"{self.api_base}/liff/verify-token",
            "API User Profile": f"{self.api_base}/liff/user-profile",
            "API Config": f"{self.api_base}/liff/config"
        }
        
        print("LINE Developers コンソールでの設定:")
        for name, url in urls.items():
            print(f"  {name}: {url}")
        
        return urls
    
    def generate_test_token(self):
        """テスト用JWTトークンの生成"""
        print("\n🔧 テスト用トークン生成")
        print("=" * 50)
        
        jwt_secret = os.environ.get("JWT_SECRET")
        if not jwt_secret:
            print("❌ JWT_SECRET が設定されていません")
            return None
        
        try:
            import jwt
            from datetime import timedelta
            
            test_payload = {
                "user_id": "test_user_12345",
                "display_name": "テストユーザー",
                "picture_url": "https://via.placeholder.com/150",
                "login_type": "liff",
                "exp": datetime.utcnow() + timedelta(hours=24),
                "iat": datetime.utcnow()
            }
            
            test_token = jwt.encode(test_payload, jwt_secret, algorithm="HS256")
            print("✅ テスト用JWTトークン生成成功")
            print(f"Token: {test_token[:50]}...")
            
            return test_token
            
        except Exception as e:
            print(f"❌ テスト用トークン生成エラー: {e}")
            return None
    
    def test_authenticated_api(self, token):
        """認証付きAPIのテスト"""
        if not token:
            return
            
        print("\n🔐 認証付きAPIテスト")
        print("=" * 50)
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # プロフィール取得テスト
        try:
            response = requests.get(
                f"{self.api_base}/liff/user-profile",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                profile = response.json()
                print("✅ プロフィール取得成功:")
                print(f"  User ID: {profile.get('user_id')}")
                print(f"  Display Name: {profile.get('display_name')}")
                print(f"  Login Type: {profile.get('login_type')}")
            else:
                print(f"❌ プロフィール取得失敗: {response.status_code}")
                
        except Exception as e:
            print(f"❌ プロフィール取得エラー: {e}")
        
        # チャットAPIテスト
        try:
            response = requests.post(
                f"{self.api_base}/chat/",
                headers=headers,
                json={
                    "question": "こんにちは、テストメッセージです",
                    "username": "liff-test-user"
                },
                timeout=30
            )
            
            if response.status_code == 200:
                chat_data = response.json()
                answer = chat_data.get("answer", "回答なし")
                print("\n✅ チャットAPI成功:")
                print(f"  回答: {answer[:100]}...")
            else:
                print(f"❌ チャットAPI失敗: {response.status_code}")
                
        except Exception as e:
            print(f"❌ チャットAPIエラー: {e}")
    
    def show_setup_instructions(self):
        """セットアップ手順の表示"""
        print("\n📋 LIFF設定手順")
        print("=" * 50)
        
        instructions = """
1. LINE Developers コンソールでの設定:
   https://developers.line.biz/console/
   
   a) LINE Login チャネルの作成:
      - チャネル名: RAG AI Chat
      - アプリタイプ: ウェブアプリ
      - チャネル説明: RAG AI チャットボット
   
   b) LIFF アプリの作成:
      - LIFF アプリ名: RAG Chat LIFF
      - サイズ: Full
      - エンドポイントURL: {frontend_url}/liff-chat.html
      - スコープ: profile, openid
      - ボットリンク機能: On (任意)

2. 環境変数の設定:
   - LINE_LOGIN_CHANNEL_ID: LINEログインのチャネルID
   - LINE_LOGIN_CHANNEL_SECRET: LINEログインのチャネルシークレット
   - LIFF_APP_ID: 作成したLIFFアプリのID
   - JWT_SECRET: 強力なランダム文字列

3. デプロイ:
   - gcloud run services update rag-api --set-env-vars...
   - または Cloud Build でデプロイ

4. テスト:
   - フロントエンドページでLIFFログインを確認
   - チャット機能の動作確認
        """.format(
            frontend_url=self.api_base.replace("rag-api", "rag-frontend")
        )
        
        print(instructions)
    
    def run_full_check(self):
        """完全なチェックとテストの実行"""
        print("🚀 LIFF セットアップ確認開始")
        print(f"時刻: {datetime.now()}")
        print("=" * 60)
        
        # 1. 環境変数確認
        env_ok = self.check_environment()
        
        # 2. API エンドポイントテスト
        self.test_api_endpoints()
        
        # 3. URL生成
        self.create_liff_urls()
        
        # 4. テスト用トークン生成とAPIテスト
        if env_ok:
            test_token = self.generate_test_token()
            self.test_authenticated_api(test_token)
        
        # 5. セットアップ手順表示
        self.show_setup_instructions()
        
        print("\n" + "=" * 60)
        print("✅ LIFF セットアップ確認完了")

def main():
    setup_manager = LIFFSetupManager()
    setup_manager.run_full_check()

if __name__ == "__main__":
    main()