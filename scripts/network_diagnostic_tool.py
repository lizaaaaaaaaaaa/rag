#!/usr/bin/env python3
"""
ネットワーク診断ツール - LINE API接続問題の詳細調査
python network_diagnostic_tool.py
"""

import requests
import socket
import os
import sys
import json
import urllib.request
import urllib.parse
from datetime import datetime
import time

class NetworkDiagnostic:
    def __init__(self):
        self.line_token = None
        print("🌐 ネットワーク診断ツール - LINE API接続問題解決")
        print(f"📅 実行時刻: {datetime.now()}")
        print("=" * 70)

    def get_token_input(self):
        """トークン入力"""
        print("\n🔐 Messaging APIトークンを入力してください:")
        self.line_token = input("トークン: ").strip()
        return bool(self.line_token)

    def check_basic_network(self):
        """基本的なネットワーク接続確認"""
        print("\n🔍 1. 基本ネットワーク接続確認")
        print("-" * 40)
        
        # DNS解決テスト
        print("📡 DNS解決テスト...")
        try:
            ip = socket.gethostbyname("api.line.me")
            print(f"✅ api.line.me → {ip}")
        except Exception as e:
            print(f"❌ DNS解決失敗: {e}")
            return False
        
        # 基本HTTP接続テスト
        print("\n🌐 基本HTTP接続テスト...")
        test_urls = [
            "https://httpbin.org/get",
            "https://google.com",
            "https://api.line.me/"
        ]
        
        for url in test_urls:
            try:
                response = requests.get(url, timeout=10)
                print(f"✅ {url} → HTTP {response.status_code}")
            except requests.exceptions.ProxyError as e:
                print(f"❌ {url} → プロキシエラー: {e}")
                return False
            except requests.exceptions.SSLError as e:
                print(f"❌ {url} → SSL証明書エラー: {e}")
                return False
            except requests.exceptions.ConnectionError as e:
                print(f"❌ {url} → 接続エラー: {e}")
                return False
            except Exception as e:
                print(f"❌ {url} → エラー: {e}")
                return False
        
        return True

    def check_proxy_settings(self):
        """プロキシ設定確認"""
        print("\n🔍 2. プロキシ設定確認")
        print("-" * 40)
        
        # 環境変数のプロキシ設定
        proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']
        proxy_found = False
        
        for var in proxy_vars:
            value = os.environ.get(var)
            if value:
                print(f"⚠️ {var}: {value}")
                proxy_found = True
        
        if not proxy_found:
            print("✅ 環境変数にプロキシ設定なし")
        
        # requestsのプロキシ設定確認
        session = requests.Session()
        if session.proxies:
            print(f"⚠️ Requestsプロキシ: {session.proxies}")
        else:
            print("✅ Requestsプロキシなし")
        
        return not proxy_found

    def check_firewall_corporate(self):
        """企業ファイアウォール・制限確認"""
        print("\n🔍 3. 企業ファイアウォール・制限確認")
        print("-" * 40)
        
        # 異なるポートでの接続テスト
        ports_to_test = [80, 443, 8080, 8443]
        
        for port in ports_to_test:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex(("api.line.me", port))
                sock.close()
                
                if result == 0:
                    print(f"✅ ポート {port}: 接続可能")
                else:
                    print(f"❌ ポート {port}: 接続不可")
            except Exception as e:
                print(f"❌ ポート {port}: エラー - {e}")
        
        # 外部IPアドレス確認
        print(f"\n📍 外部IPアドレス確認...")
        try:
            response = requests.get("https://httpbin.org/ip", timeout=10)
            if response.status_code == 200:
                ip_info = response.json()
                print(f"✅ 外部IP: {ip_info.get('origin')}")
            else:
                print(f"❌ IP確認失敗: {response.status_code}")
        except Exception as e:
            print(f"❌ IP確認エラー: {e}")

    def test_line_api_with_details(self):
        """LINE API詳細テスト"""
        print("\n🔍 4. LINE API詳細接続テスト")
        print("-" * 40)
        
        if not self.line_token:
            print("❌ トークンが設定されていません")
            return False
        
        # 詳細なリクエスト情報を記録
        import requests.adapters
        
        # カスタムアダプターで詳細ログ
        class VerboseHTTPAdapter(requests.adapters.HTTPAdapter):
            def send(self, request, **kwargs):
                print(f"📤 リクエスト詳細:")
                print(f"   URL: {request.url}")
                print(f"   メソッド: {request.method}")
                print(f"   ヘッダー: {dict(request.headers)}")
                
                response = super().send(request, **kwargs)
                
                print(f"📥 レスポンス詳細:")
                print(f"   ステータス: {response.status_code}")
                print(f"   ヘッダー: {dict(response.headers)}")
                print(f"   本文: {response.text}")
                
                return response
        
        session = requests.Session()
        session.mount("https://", VerboseHTTPAdapter())
        
        headers = {"Authorization": f"Bearer {self.line_token}"}
        
        try:
            print("🚀 LINE Bot Info API テスト開始...")
            response = session.get(
                "https://api.line.me/v2/bot/info",
                headers=headers,
                timeout=15
            )
            
            if response.status_code == 200:
                print("✅ 成功！")
                return True
            else:
                print(f"❌ 失敗: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ 例外エラー: {e}")
            return False

    def test_different_user_agents(self):
        """異なるUser-Agentでのテスト"""
        print("\n🔍 5. User-Agent変更テスト")
        print("-" * 40)
        
        user_agents = [
            "python-requests/2.31.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "curl/7.68.0",
            "LINE-Bot-SDK-Python/1.0"
        ]
        
        for ua in user_agents:
            print(f"🔍 User-Agent: {ua[:50]}...")
            
            try:
                headers = {
                    "Authorization": f"Bearer {self.line_token}",
                    "User-Agent": ua
                }
                
                response = requests.get(
                    "https://api.line.me/v2/bot/info",
                    headers=headers,
                    timeout=10
                )
                
                print(f"   結果: HTTP {response.status_code}")
                
                if response.status_code == 200:
                    print("   ✅ このUser-Agentで成功！")
                    return True
                    
            except Exception as e:
                print(f"   ❌ エラー: {e}")
        
        return False

    def test_alternative_endpoints(self):
        """代替エンドポイントテスト"""
        print("\n🔍 6. 代替エンドポイント・方法テスト")
        print("-" * 40)
        
        # urllib を使用したテスト
        print("📡 urllib使用テスト...")
        try:
            req = urllib.request.Request(
                "https://api.line.me/v2/bot/info",
                headers={"Authorization": f"Bearer {self.line_token}"}
            )
            
            with urllib.request.urlopen(req, timeout=10) as response:
                print(f"✅ urllib成功: HTTP {response.status}")
                return True
                
        except urllib.error.HTTPError as e:
            print(f"❌ urllib HTTPエラー: {e.code} {e.reason}")
        except Exception as e:
            print(f"❌ urllib エラー: {e}")
        
        # 異なるSSL設定でのテスト
        print("\n🔒 SSL検証無効化テスト（診断目的のみ）...")
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            response = requests.get(
                "https://api.line.me/v2/bot/info",
                headers={"Authorization": f"Bearer {self.line_token}"},
                verify=False,
                timeout=10
            )
            
            print(f"✅ SSL検証無し成功: HTTP {response.status_code}")
            print("⚠️ SSL証明書に問題がある可能性があります")
            return True
            
        except Exception as e:
            print(f"❌ SSL無効化でも失敗: {e}")
        
        return False

    def provide_solutions(self):
        """解決策の提案"""
        print("\n💡 解決策とワークアラウンド")
        print("=" * 50)
        
        print("🔧 1. プロキシ経由での接続設定")
        print("   企業ネットワークの場合、以下の設定を試してください：")
        print()
        print("   # 環境変数でプロキシ設定")
        print("   export HTTP_PROXY=http://proxy.company.com:8080")
        print("   export HTTPS_PROXY=https://proxy.company.com:8080")
        print()
        print("   # Pythonコード内でプロキシ設定")
        print("   proxies = {")
        print("       'http': 'http://proxy.company.com:8080',")
        print("       'https': 'https://proxy.company.com:8080'")
        print("   }")
        print("   requests.get(url, proxies=proxies)")
        print()
        
        print("🔧 2. Cloud Run経由での回避策")
        print("   ローカル環境に制限がある場合、Cloud Runを経由：")
        print()
        print("   # Cloud Run上でLINE APIを呼び出すエンドポイントを作成")
        print("   GET /proxy/line-api?endpoint=bot/info")
        print()
        
        print("🔧 3. 代替実行環境")
        print("   - Google Cloud Shell（ブラウザ内ターミナル）")
        print("   - GitHub Codespaces")
        print("   - Replit")
        print("   - 個人のネットワーク環境")
        print()
        
        print("🔧 4. 企業IT部門への確認事項")
        print("   - api.line.me へのHTTPS接続許可")
        print("   - 外部API呼び出しの制限確認")
        print("   - プロキシ設定の詳細")

    def create_proxy_workaround_script(self):
        """プロキシ回避スクリプトの生成"""
        print("\n🛠️ プロキシ回避スクリプト生成")
        print("-" * 30)
        
        script_content = '''#!/usr/bin/env python3
"""
プロキシ環境対応 LINE API テストスクリプト
"""

import requests
import os

# プロキシ設定（企業環境に応じて変更）
PROXIES = {
    'http': 'http://proxy.company.com:8080',
    'https': 'https://proxy.company.com:8080'
}

# LINE Bot Token
LINE_TOKEN = "YOUR_LINE_TOKEN_HERE"

def test_with_proxy():
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    
    try:
        response = requests.get(
            "https://api.line.me/v2/bot/info",
            headers=headers,
            proxies=PROXIES,
            timeout=15
        )
        
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_with_proxy()
'''
        
        with open("line_proxy_test.py", "w", encoding="utf-8") as f:
            f.write(script_content)
        
        print("📄 line_proxy_test.py を生成しました")
        print("企業プロキシ設定を編集して実行してください")

    def run_full_diagnostic(self):
        """完全診断実行"""
        # トークン入力
        if not self.get_token_input():
            print("❌ トークンが入力されていません")
            return
        
        # 各種診断実行
        basic_ok = self.check_basic_network()
        proxy_ok = self.check_proxy_settings()
        
        if basic_ok:
            self.check_firewall_corporate()
            line_api_ok = self.test_line_api_with_details()
            
            if not line_api_ok:
                ua_ok = self.test_different_user_agents()
                if not ua_ok:
                    alt_ok = self.test_alternative_endpoints()
        
        # 解決策提案
        self.provide_solutions()
        self.create_proxy_workaround_script()
        
        print(f"\n📊 診断完了")
        print("=" * 30)
        print("次のステップ:")
        print("1. 上記の解決策を試行")
        print("2. IT部門にネットワーク制限を確認")
        print("3. Cloud Shell等の代替環境で実行")

def main():
    diagnostic = NetworkDiagnostic()
    diagnostic.run_full_diagnostic()

if __name__ == "__main__":
    main()