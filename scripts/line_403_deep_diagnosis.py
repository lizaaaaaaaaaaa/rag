#!/usr/bin/env python3
"""
LINE API 403エラー詳細診断スクリプト
トークン再発行しても403が続く場合の原因特定
"""

import os
import requests
import json
import base64
from datetime import datetime
from dotenv import load_dotenv

class LINEDeepDiagnostic:
    def __init__(self):
        print("🔍 LINE API 403エラー詳細診断")
        print("=" * 60)
        print(f"📅 実行時刻: {datetime.now()}")
        
        # .envファイルを明示的に読み込み
        load_dotenv()
        
        self.line_token = None
        self.line_secret = None
        self.channel_id = None
        
    def check_environment_variables(self):
        """環境変数の詳細チェック"""
        print("\n🔧 1. 環境変数詳細チェック")
        print("-" * 40)
        
        # 各種環境変数をチェック
        env_vars = {
            "LINE_CHANNEL_ACCESS_TOKEN": os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"),
            "LINE_CHANNEL_SECRET": os.environ.get("LINE_CHANNEL_SECRET"),
            "LINE_CHANNEL_ID": os.environ.get("LINE_CHANNEL_ID"),
            "LINE_LOGIN_CHANNEL_ID": os.environ.get("LINE_LOGIN_CHANNEL_ID"),
            "LINE_LOGIN_CHANNEL_SECRET": os.environ.get("LINE_LOGIN_CHANNEL_SECRET")
        }
        
        for key, value in env_vars.items():
            if value:
                print(f"✅ {key}: 設定済み (長さ: {len(value)} 文字)")
                print(f"   プレビュー: {value[:20]}{'...' if len(value) > 20 else ''}")
                
                # トークンの形式チェック
                if "ACCESS_TOKEN" in key:
                    self.line_token = value
                    if value.startswith("Bearer "):
                        print(f"   ⚠️ 警告: 'Bearer 'プレフィックスが含まれています")
                        self.line_token = value.replace("Bearer ", "")
                    
                elif "CHANNEL_SECRET" in key and "LOGIN" not in key:
                    self.line_secret = value
                    if len(value) != 32:
                        print(f"   ⚠️ 警告: Channel Secretは通常32文字です (現在: {len(value)}文字)")
                
                elif key == "LINE_CHANNEL_ID":
                    self.channel_id = value
            else:
                print(f"❌ {key}: 未設定")
        
        # .envファイルの確認
        print(f"\n📄 .envファイル確認:")
        if os.path.exists(".env"):
            print("✅ .envファイル存在")
            with open(".env", "r", encoding="utf-8") as f:
                lines = f.readlines()
                line_count = 0
                for line in lines:
                    if line.strip() and not line.startswith("#"):
                        line_count += 1
                        if "LINE_CHANNEL_ACCESS_TOKEN" in line:
                            print(f"   📝 ACCESS_TOKEN設定行を発見")
                print(f"   設定行数: {line_count}")
        else:
            print("❌ .envファイルが見つかりません")
        
        return bool(self.line_token)
    
    def check_token_format(self):
        """トークン形式の詳細チェック"""
        print("\n🔧 2. トークン形式詳細チェック")
        print("-" * 40)
        
        if not self.line_token:
            print("❌ アクセストークンが見つかりません")
            return False
        
        # トークンの基本情報
        print(f"📏 トークン長: {len(self.line_token)} 文字")
        print(f"🔤 文字種類分析:")
        
        has_upper = any(c.isupper() for c in self.line_token)
        has_lower = any(c.islower() for c in self.line_token)
        has_digit = any(c.isdigit() for c in self.line_token)
        has_special = any(c in "+-/=" for c in self.line_token)
        
        print(f"   大文字: {'✅' if has_upper else '❌'}")
        print(f"   小文字: {'✅' if has_lower else '❌'}")
        print(f"   数字: {'✅' if has_digit else '❌'}")
        print(f"   記号(+/-/=): {'✅' if has_special else '❌'}")
        
        # Base64エンコーディングチェック
        try:
            decoded = base64.b64decode(self.line_token + "==")
            print(f"📦 Base64デコード: 可能 ({len(decoded)} bytes)")
        except:
            print(f"📦 Base64デコード: 不可")
        
        # 改行・空白文字チェック
        if "\n" in self.line_token or "\r" in self.line_token:
            print("⚠️ 警告: トークンに改行文字が含まれています")
        if " " in self.line_token:
            print("⚠️ 警告: トークンに空白文字が含まれています")
        
        # Channel Secretの確認
        if self.line_secret:
            print(f"\n🔐 Channel Secret:")
            print(f"   長さ: {len(self.line_secret)} 文字")
            print(f"   16進数チェック: {'✅' if all(c in '0123456789abcdef' for c in self.line_secret.lower()) else '❌'}")
        
        return True
    
    def test_different_endpoints(self):
        """複数のエンドポイントでテスト"""
        print("\n🔧 3. 複数エンドポイントテスト")
        print("-" * 40)
        
        if not self.line_token:
            print("❌ トークンがありません")
            return
        
        endpoints = [
            ("Bot Info", "https://api.line.me/v2/bot/info"),
            ("Rich Menu List", "https://api.line.me/v2/bot/richmenu/list"),
            ("Bot Settings", "https://api.line.me/v2/bot/followersdetail"),
        ]
        
        headers = {
            "Authorization": f"Bearer {self.line_token}",
            "User-Agent": "LINE-Bot-SDK-Python/Diagnostic"
        }
        
        for name, url in endpoints:
            try:
                print(f"\n🧪 {name} テスト:")
                print(f"   URL: {url}")
                
                response = requests.get(url, headers=headers, timeout=10)
                print(f"   ステータス: {response.status_code}")
                
                if response.status_code == 200:
                    print(f"   ✅ 成功!")
                    try:
                        data = response.json()
                        if "displayName" in data:
                            print(f"   Bot名: {data['displayName']}")
                        if "userId" in data:
                            print(f"   Bot ID: {data['userId']}")
                    except:
                        pass
                else:
                    print(f"   ❌ 失敗: {response.text}")
                    
            except Exception as e:
                print(f"   ❌ エラー: {e}")
    
    def check_channel_settings(self):
        """チャンネル設定の推測"""
        print("\n🔧 4. チャンネル設定推測")
        print("-" * 40)
        
        if not self.line_token:
            print("❌ トークンがありません")
            return
        
        # Webhook URLのテスト（推測）
        webhook_urls = [
            "https://rag-api-190389115361.asia-northeast1.run.app/line/webhook",
            "https://rag-api-190389115361.asia-northeast1.run.app/api/line/webhook",
            "https://rag-api-190389115361.asia-northeast1.run.app/webhook"
        ]
        
        print("🌐 想定Webhook URL到達性テスト:")
        for url in webhook_urls:
            try:
                response = requests.get(url.replace("/webhook", "/status"), timeout=5)
                print(f"   {url}: {'✅' if response.status_code < 500 else '❌'} (HTTP {response.status_code})")
            except:
                print(f"   {url}: ❌ 到達不可")
        
        # トークンからチャンネル情報を推測
        print(f"\n🔍 トークン分析:")
        if len(self.line_token) > 100:
            print("   ✅ 長期トークンの可能性")
        else:
            print("   ⚠️ 短期トークンまたは異常")
        
        # Base64パターン分析
        if self.line_token.endswith("="):
            print("   ✅ Base64エンコーディングパターン")
        else:
            print("   ⚠️ 非Base64パターン")
    
    def test_manual_curl_command(self):
        """手動確認用のcurlコマンド生成"""
        print("\n🔧 5. 手動確認コマンド生成")
        print("-" * 40)
        
        if not self.line_token:
            print("❌ トークンがありません")
            return
        
        # セキュアなトークン表示（最初と最後のみ）
        masked_token = f"{self.line_token[:10]}...{self.line_token[-10:]}"
        
        print("📋 手動確認用コマンド:")
        print(f"curl -X GET \\")
        print(f'  -H "Authorization: Bearer YOUR_ACTUAL_TOKEN" \\')
        print(f"  https://api.line.me/v2/bot/info")
        
        print(f"\n⚠️ トークンマスク済み表示: {masked_token}")
        print("実際のトークンに置き換えて実行してください")
        
        # PowerShell版も提供
        print(f"\n💻 PowerShell版:")
        print(f'$headers = @{{ "Authorization" = "Bearer YOUR_ACTUAL_TOKEN" }}')
        print(f'Invoke-RestMethod -Uri "https://api.line.me/v2/bot/info" -Headers $headers')
    
    def analyze_403_causes(self):
        """403エラーの原因分析"""
        print("\n🔧 6. 403エラー原因分析")
        print("-" * 40)
        
        possible_causes = [
            {
                "原因": "間違ったチャンネルタイプ",
                "説明": "LINE LoginチャンネルとMessaging APIチャンネルを混同",
                "確認方法": "LINE Developersコンソールでチャンネルタイプを確認"
            },
            {
                "原因": "チャンネル機能無効",
                "説明": "Messaging API機能が無効化されている",
                "確認方法": "Messaging API設定で「Use webhook」が有効か確認"
            },
            {
                "原因": "アカウント制限",
                "説明": "開発者アカウントまたはBotアカウントが制限されている",
                "確認方法": "LINE Developersコンソールでアカウント状態確認"
            },
            {
                "原因": "リージョン制限",
                "説明": "日本以外のアカウントでの制限",
                "確認方法": "アカウントの国・地域設定を確認"
            },
            {
                "原因": "プロバイダー権限",
                "説明": "プロバイダーへのアクセス権限がない",
                "確認方法": "プロバイダー設定で権限を確認"
            }
        ]
        
        for i, cause in enumerate(possible_causes, 1):
            print(f"{i}. {cause['原因']}")
            print(f"   説明: {cause['説明']}")
            print(f"   確認: {cause['確認方法']}")
            print()
    
    def provide_next_steps(self):
        """次の確認ステップ"""
        print("\n💡 次の確認ステップ")
        print("=" * 50)
        
        steps = [
            "LINE Developersコンソールに再ログイン",
            "正しいプロバイダーを選択していることを確認",
            "Messaging APIチャンネル（LINE Loginではない）を確認",
            "チャンネルの基本設定でChannel access tokenを確認",
            "Messaging API設定で「Use webhook」が有効か確認",
            "一時的に新しいテスト用チャンネルを作成して比較",
            "LINE公式アカウントの状態を確認",
            "ブラウザのキャッシュをクリアしてコンソール再アクセス"
        ]
        
        for i, step in enumerate(steps, 1):
            print(f"{i}. {step}")
        
        print(f"\n🆘 それでも解決しない場合:")
        print("- LINE開発者サポートに問い合わせ")
        print("- 異なるLINEアカウントで新規チャンネル作成を試行")
        print("- 企業アカウントの場合、管理者権限を確認")
    
    def run_full_diagnosis(self):
        """完全診断の実行"""
        # 環境変数チェック
        if not self.check_environment_variables():
            print("\n❌ 環境変数が正しく設定されていません")
            return False
        
        # トークン形式チェック
        self.check_token_format()
        
        # エンドポイントテスト
        self.test_different_endpoints()
        
        # チャンネル設定チェック
        self.check_channel_settings()
        
        # 手動確認コマンド
        self.test_manual_curl_command()
        
        # 原因分析
        self.analyze_403_causes()
        
        # 次のステップ
        self.provide_next_steps()
        
        return True

def main():
    diagnostic = LINEDeepDiagnostic()
    diagnostic.run_full_diagnosis()

if __name__ == "__main__":
    main()