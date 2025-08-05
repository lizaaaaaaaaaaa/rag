#!/usr/bin/env python3
"""
LINEログイン機能のテストスクリプト
python scripts/test_line_login.py
"""

import os
import requests
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class LineLoginTester:
    def __init__(self):
        self.api_base = os.environ.get("API_URL", "https://rag-api-190389115361.asia-northeast1.run.app")
        self.line_login_channel_id = os.environ.get("LINE_LOGIN_CHANNEL_ID")
        self.line_login_channel_secret = os.environ.get("LINE_LOGIN_CHANNEL_SECRET")
    
    def check_environment(self):
        """環境変数の確認"""
        print("🔍 LINEログイン環境設定確認")
        print("=" * 60)
        
        env_vars = {
            "LINE_LOGIN_CHANNEL_ID": self.line_login_channel_id,
            "LINE_LOGIN_CHANNEL_SECRET": self.line_login_channel_secret,
            "JWT_SECRET": os.environ.get("JWT_SECRET"),
            "API_URL": self.api_base,
            "FRONTEND_URL": os.environ.get("FRONTEND_URL")
        }
        
        all_set = True
        for key, value in env_vars.items():
            if value:
                if key in ["LINE_LOGIN_CHANNEL_SECRET", "JWT_SECRET"]:
                    display_value = f"{value[:10]}***"
                else:
                    display_value = value
                print(f"  ✅ {key}: {display_value}")
            else:
                print(f"  ❌ {key}: 未設定")
                all_set = False
        
        return all_set
    
    def test_api_endpoints(self):
        """APIエンドポイントのテスト"""
        print("\n🧪 APIエンドポイント テスト")
        print("=" * 60)
        
        endpoints = [
            ("/line-login/status", "GET", "ステータス確認"),
            ("/line-login/login-page", "GET", "ログインページ"),
            ("/debug/line-login", "GET", "デバッグ情報")
        ]
        
        for endpoint, method, description in endpoints:
            try:
                url = f"{self.api_base}{endpoint}"
                response = requests.get(url, timeout=10)
                
                if response.status_code == 200:
                    print(f"  ✅ {description}: {response.status_code}")
                    if endpoint == "/line-login/status":
                        data = response.json()
                        print(f"     - コールバックURL: {data.get('callback_url')}")
                        print(f"     - 認証URL: {data.get('auth_url')}")
                else:
                    print(f"  ❌ {description}: {response.status_code}")
                    
            except Exception as e:
                print(f"  ❌ {description}: エラー - {e}")
    
    def show_urls_for_line_developers(self):
        """LINE Developers コンソール用URLの表示"""
        print("\n🔗 LINE Developers コンソール設定用URL")
        print("=" * 60)
        
        urls = {
            "コールバックURL": f"{self.api_base}/line-login/callback",
            "認証開始URL": f"{self.api_base}/line-login/auth",
            "ログインページ": f"{self.api_base}/line-login/login-page",
            "ユーザー情報API": f"{self.api_base}/line-login/user-info",
            "チャットページ": f"{self.api_base.replace('rag-api', 'rag-frontend')}/chat.html"
        }
        
        for name, url in urls.items():
            print(f"  {name}:")
            print(f"    {url}")
        
        print(f"\n📋 LINE Developers コンソールでの設定:")
        print(f"  1. LINEログイン設定 > コールバックURL:")
        print(f"     {urls['コールバックURL']}")
        print(f"  2. スコープ: profile openid email")
        print(f"  3. ウェブアプリでLINEログインを利用する: 有効")
    
    def test_authentication_flow(self):
        """認証フローのテスト（手動）"""
        print("\n🔐 認証フロー テストガイド")
        print("=" * 60)
        
        steps = [
            "1. ブラウザで以下のURLにアクセス:",
            f"   {self.api_base}/line-login/login-page",
            "",
            "2. 「LINEでログイン」ボタンをクリック",
            "",
            "3. LINEログイン画面で認証",
            "",
            "4. コールバック処理でトークンが生成される",
            "",
            "5. チャットページで認証済み状態を確認",
            "",
            "期待される動作:",
            "- ログイン成功後、JWTトークンが発行される",
            "- ユーザー情報が正しく表示される",
            "- チャット機能が認証付きで動作する"
        ]
        
        for step in steps:
            print(f"  {step}")
    
    def validate_callback_url(self):
        """コールバックURLの妥当性確認"""
        print("\n✅ コールバックURL 妥当性確認")
        print("=" * 60)
        
        callback_url = f"{self.api_base}/line-login/callback"
        
        # URLの形式チェック
        checks = [
            ("HTTPS使用", callback_url.startswith("https://")),
            ("正しいドメイン", "rag-api-" in callback_url),
            ("正しいパス", "/line-login/callback" in callback_url)
        ]
        
        for check_name, is_valid in checks:
            status = "✅" if is_valid else "❌"
            print(f"  {status} {check_name}: {is_valid}")
        
        print(f"\n設定すべきコールバックURL:")
        print(f"  {callback_url}")
    
    def test_jwt_token_creation(self):
        """JWTトークン生成のテスト"""
        print("\n🔑 JWTトークン生成 テスト")
        print("=" * 60)
        
        jwt_secret = os.environ.get("JWT_SECRET")
        if not jwt_secret:
            print("  ❌ JWT_SECRET が設定されていません")
            return
        
        try:
            import jwt
            from datetime import timedelta
            
            # テスト用ペイロード
            test_payload = {
                "user_id": "test_line_user_12345",
                "display_name": "テスト太郎",
                "picture_url": "https://example.com/avatar.jpg",
                "login_type": "line_oauth",
                "exp": datetime.utcnow() + timedelta(hours=24),
                "iat": datetime.utcnow()
            }
            
            # トークン生成
            token = jwt.encode(test_payload, jwt_secret, algorithm="HS256")
            print(f"  ✅ JWTトークン生成成功")
            print(f"     トークン長: {len(token)} 文字")
            
            # トークン検証
            decoded = jwt.decode(token, jwt_secret, algorithms=["HS256"])
            print(f"  ✅ JWTトークン検証成功")
            print(f"     ユーザーID: {decoded['user_id']}")
            print(f"     表示名: {decoded['display_name']}")
            
        except ImportError:
            print("  ❌ PyJWT ライブラリが見つかりません")
        except Exception as e:
            print(f"  ❌ JWTトークンテストエラー: {e}")
    
    def show_troubleshooting_guide(self):
        """トラブルシューティングガイド"""
        print("\n🔧 トラブルシューティング")
        print("=" * 60)
        
        common_issues = [
            {
                "問題": "コールバックURL不一致エラー",
                "原因": "LINE Developers設定とAPIのURLが異なる",
                "解決策": "コールバックURLを正確に設定し直す"
            },
            {
                "問題": "invalid_client エラー",
                "原因": "Channel IDまたはSecretが間違っている",
                "解決策": "環境変数を再確認し、正しい値を設定"
            },
            {
                "問題": "JWTトークンエラー",
                "原因": "JWT_SECRETが設定されていない",
                "解決策": "強力なランダム文字列をJWT_SECRETに設定"
            },
            {
                "問題": "CORS エラー",
                "原因": "フロントエンドからAPIへのアクセスが拒否",
                "解決策": "APIサーバーのCORS設定を確認"
            }
        ]
        
        for issue in common_issues:
            print(f"\n  問題: {issue['問題']}")
            print(f"  原因: {issue['原因']}")
            print(f"  解決策: {issue['解決策']}")
        
        print(f"\nログ確認コマンド:")
        print(f"  gcloud logging read 'textPayload:\"line-login\"' --limit=20")
    
    def run_full_test(self):
        """完全テストの実行"""
        print("🚀 LINEログイン 完全テスト開始")
        print(f"時刻: {datetime.now()}")
        print("=" * 80)
        
        # 1. 環境設定確認
        env_ok = self.check_environment()
        
        # 2. APIエンドポイントテスト
        self.test_api_endpoints()
        
        # 3. URL表示
        self.show_urls_for_line_developers()
        
        # 4. コールバックURL妥当性確認
        self.validate_callback_url()
        
        # 5. JWTトークンテスト
        if env_ok:
            self.test_jwt_token_creation()
        
        # 6. 認証フローテストガイド
        self.test_authentication_flow()
        
        # 7. トラブルシューティング
        self.show_troubleshooting_guide()
        
        print("\n" + "=" * 80)
        print("✅ LINEログイン テスト完了")
        
        if not env_ok:
            print("\n⚠️  環境変数の設定を完了してから再度テストしてください")

def main():
    tester = LineLoginTester()
    tester.run_full_test()

if __name__ == "__main__":
    main()