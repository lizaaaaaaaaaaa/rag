#!/usr/bin/env python3
# scripts/line_bot_diagnostics.py - LINE Bot 完全診断・修復スクリプト

import os
import sys
import json
import time
import requests
import hmac
import hashlib
import base64
from datetime import datetime
from typing import Dict, Any, Optional

def normalize_credential(value: Any) -> str:
    """認証情報を安全にstring型に変換"""
    if value is None:
        return ""
    
    # bytes型の場合はデコード
    if isinstance(value, bytes):
        try:
            value = value.decode('utf-8')
        except UnicodeDecodeError:
            print(f"❌ Failed to decode credential from bytes")
            return ""
    
    # 文字列に変換
    credential_str = str(value).strip()
    
    # 不要なプレフィックス・サフィックスを削除
    if credential_str.startswith('Bearer '):
        credential_str = credential_str[7:].strip()
    
    if credential_str.startswith("b'") and credential_str.endswith("'"):
        credential_str = credential_str[2:-1]
    
    return credential_str

class LineBotDiagnostics:
    def __init__(self):
        self.api_base_url = "https://rag-api-190389115361.asia-northeast1.run.app"
        self.line_api_base = "https://api.line.me/v2"
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "tests": {},
            "issues": [],
            "recommendations": [],
            "summary": {}
        }
        
        # 環境変数読み込み
        self.load_credentials()
    
    def load_credentials(self):
        """認証情報の読み込みと正規化"""
        print("🔑 Loading and normalizing credentials...")
        
        # 生の認証情報取得
        raw_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        raw_secret = os.environ.get("LINE_CHANNEL_SECRET", "")
        
        # 正規化処理
        self.access_token = normalize_credential(raw_token)
        self.channel_secret = normalize_credential(raw_secret)
        
        print(f"   Raw token type: {type(raw_token)} -> Normalized length: {len(self.access_token)}")
        print(f"   Raw secret type: {type(raw_secret)} -> Normalized length: {len(self.channel_secret)}")
        
        # 基本検証
        if not self.access_token:
            self.results["issues"].append("LINE_CHANNEL_ACCESS_TOKEN not found or empty after normalization")
        elif len(self.access_token) < 100:
            self.results["issues"].append("LINE_CHANNEL_ACCESS_TOKEN seems too short")
            
        if not self.channel_secret:
            self.results["issues"].append("LINE_CHANNEL_SECRET not found or empty after normalization")
        elif len(self.channel_secret) < 20:
            self.results["issues"].append("LINE_CHANNEL_SECRET seems too short")
    
    def test_line_api_connection(self) -> bool:
        """LINE API接続テスト"""
        print("🌐 Testing LINE API connection...")
        
        try:
            if not self.access_token:
                print("   ❌ No access token available")
                self.results["tests"]["line_api_connection"] = {
                    "status": "failed",
                    "error": "No access token"
                }
                return False
            
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(
                f"{self.line_api_base}/bot/info",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                bot_info = response.json()
                print(f"   ✅ Connection successful!")
                print(f"   Bot Name: {bot_info.get('displayName', 'Unknown')}")
                print(f"   Bot ID: {bot_info.get('userId', 'Unknown')}")
                
                self.results["tests"]["line_api_connection"] = {
                    "status": "success",
                    "bot_info": bot_info
                }
                return True
            else:
                print(f"   ❌ API connection failed: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
                
                self.results["tests"]["line_api_connection"] = {
                    "status": "failed",
                    "http_status": response.status_code,
                    "response": response.text
                }
                self.results["issues"].append(f"LINE API returned HTTP {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Request failed: {e}")
            self.results["tests"]["line_api_connection"] = {
                "status": "error",
                "error": str(e)
            }
            self.results["issues"].append(f"LINE API request error: {e}")
            return False
    
    def test_webhook_endpoint(self) -> bool:
        """Webhook エンドポイントテスト"""
        print("🔗 Testing webhook endpoint...")
        
        test_endpoints = [
            f"{self.api_base_url}/line/status",
            f"{self.api_base_url}/line/health",
            f"{self.api_base_url}/healthz"
        ]
        
        success_count = 0
        results = {}
        
        for endpoint in test_endpoints:
            try:
                response = requests.get(endpoint, timeout=10)
                if response.status_code == 200:
                    print(f"   ✅ {endpoint} - OK")
                    results[endpoint] = {"status": "success", "http_status": 200}
                    success_count += 1
                else:
                    print(f"   ⚠️ {endpoint} - HTTP {response.status_code}")
                    results[endpoint] = {"status": "warning", "http_status": response.status_code}
            except Exception as e:
                print(f"   ❌ {endpoint} - Error: {e}")
                results[endpoint] = {"status": "error", "error": str(e)}
        
        self.results["tests"]["webhook_endpoints"] = results
        
        if success_count > 0:
            print(f"   ✅ {success_count}/{len(test_endpoints)} endpoints accessible")
            return True
        else:
            print("   ❌ No endpoints accessible")
            self.results["issues"].append("No webhook endpoints accessible")
            return False
    
    def test_signature_generation(self) -> bool:
        """署名生成テスト"""
        print("🔐 Testing signature generation...")
        
        try:
            if not self.channel_secret:
                print("   ❌ No channel secret available")
                return False
            
            test_body = '{"events":[],"destination":"test"}'
            
            hash_obj = hmac.new(
                self.channel_secret.encode('utf-8'),
                test_body.encode('utf-8'),
                hashlib.sha256
            )
            signature = base64.b64encode(hash_obj.digest()).decode('utf-8')
            
            print(f"   ✅ Signature generated successfully")
            print(f"   Test body: {test_body}")
            print(f"   Signature: {signature[:20]}...")
            
            self.results["tests"]["signature_generation"] = {
                "status": "success",
                "signature_preview": signature[:20] + "...",
                "body_length": len(test_body)
            }
            return True
            
        except Exception as e:
            print(f"   ❌ Signature generation failed: {e}")
            self.results["tests"]["signature_generation"] = {
                "status": "error",
                "error": str(e)
            }
            self.results["issues"].append(f"Signature generation error: {e}")
            return False
    
    def test_cloud_run_service(self) -> bool:
        """Cloud Run サービステスト"""
        print("☁️ Testing Cloud Run service...")
        
        try:
            diagnostic_url = f"{self.api_base_url}/line-bot-diagnostics"
            response = requests.get(diagnostic_url, timeout=15)
            
            if response.status_code == 200:
                diagnostics = response.json()
                overall_status = diagnostics.get("overall_status", "unknown")
                
                print(f"   ✅ Cloud Run diagnostics accessible")
                print(f"   Overall Status: {overall_status}")
                
                # 詳細結果の表示
                diagnostic_results = diagnostics.get("diagnostics", {})
                for key, value in diagnostic_results.items():
                    status = "✅" if value else "❌"
                    print(f"   {status} {key}: {value}")
                
                self.results["tests"]["cloud_run_service"] = {
                    "status": "success",
                    "overall_status": overall_status,
                    "diagnostics": diagnostic_results
                }
                
                return overall_status == "healthy"
            else:
                print(f"   ❌ Diagnostics endpoint failed: HTTP {response.status_code}")
                self.results["tests"]["cloud_run_service"] = {
                    "status": "failed",
                    "http_status": response.status_code
                }
                return False
                
        except Exception as e:
            print(f"   ❌ Cloud Run service test failed: {e}")
            self.results["tests"]["cloud_run_service"] = {
                "status": "error",
                "error": str(e)
            }
            return False
    
    def test_richmenu_functionality(self) -> bool:
        """リッチメニュー機能テスト"""
        print("🎛️ Testing rich menu functionality...")
        
        try:
            if not self.access_token:
                print("   ❌ No access token for rich menu test")
                return False
            
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            # リッチメニュー一覧取得
            response = requests.get(
                f"{self.line_api_base}/bot/richmenu/list",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                richmenus = response.json().get("richmenus", [])
                print(f"   ✅ Rich menu list accessible")
                print(f"   Found {len(richmenus)} rich menus")
                
                self.results["tests"]["richmenu_functionality"] = {
                    "status": "success",
                    "menu_count": len(richmenus),
                    "menus": [menu.get("richMenuId") for menu in richmenus]
                }
                
                if len(richmenus) == 0:
                    self.results["recommendations"].append("No rich menus found - consider creating one")
                
                return True
            else:
                print(f"   ❌ Rich menu access failed: HTTP {response.status_code}")
                self.results["tests"]["richmenu_functionality"] = {
                    "status": "failed",
                    "http_status": response.status_code,
                    "response": response.text
                }
                return False
                
        except Exception as e:
            print(f"   ❌ Rich menu test failed: {e}")
            self.results["tests"]["richmenu_functionality"] = {
                "status": "error",
                "error": str(e)
            }
            return False
    
    def run_comprehensive_diagnostics(self):
        """包括的診断の実行"""
        print("🏥 Starting comprehensive LINE Bot diagnostics...")
        print("=" * 60)
        
        # テスト実行
        tests = [
            ("Credential Loading & Normalization", lambda: bool(self.access_token and self.channel_secret)),
            ("LINE API Connection", self.test_line_api_connection),
            ("Webhook Endpoints", self.test_webhook_endpoint),
            ("Signature Generation", self.test_signature_generation),
            ("Cloud Run Service", self.test_cloud_run_service),
            ("Rich Menu Functionality", self.test_richmenu_functionality)
        ]
        
        passed_tests = 0
        total_tests = len(tests)
        
        for test_name, test_func in tests:
            print(f"\n🧪 Running: {test_name}")
            print("-" * 40)
            
            try:
                result = test_func()
                if result:
                    passed_tests += 1
                    print(f"   ✅ {test_name}: PASSED")
                else:
                    print(f"   ❌ {test_name}: FAILED")
            except Exception as e:
                print(f"   💥 {test_name}: ERROR - {e}")
                self.results["issues"].append(f"{test_name} crashed: {e}")
        
        # サマリー生成
        self.results["summary"] = {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": total_tests - passed_tests,
            "success_rate": (passed_tests / total_tests) * 100,
            "overall_status": "healthy" if passed_tests == total_tests else "needs_attention"
        }
        
        print("\n" + "=" * 60)
        print("📊 DIAGNOSTIC SUMMARY")
        print("=" * 60)
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed_tests}")
        print(f"Failed: {total_tests - passed_tests}")
        print(f"Success Rate: {self.results['summary']['success_rate']:.1f}%")
        print(f"Overall Status: {self.results['summary']['overall_status'].upper()}")
        
        # 問題とレコメンデーション
        if self.results["issues"]:
            print(f"\n🚨 ISSUES DETECTED ({len(self.results['issues'])}):")
            for i, issue in enumerate(self.results["issues"], 1):
                print(f"   {i}. {issue}")
        
        if self.results["recommendations"]:
            print(f"\n💡 RECOMMENDATIONS ({len(self.results['recommendations'])}):")
            for i, rec in enumerate(self.results["recommendations"], 1):
                print(f"   {i}. {rec}")
        
        # 緊急修復アクション
        if passed_tests < total_tests:
            print(f"\n🔧 IMMEDIATE ACTIONS:")
            print("   1. Check Secret Manager configuration")
            print("   2. Verify LINE Developers Console settings")
            print("   3. Confirm Cloud Run deployment status")
            print("   4. Test manual message sending")
            
            if not self.access_token:
                print("   🚨 CRITICAL: Fix LINE_CHANNEL_ACCESS_TOKEN immediately")
            if not self.channel_secret:
                print("   🚨 CRITICAL: Fix LINE_CHANNEL_SECRET immediately")
        
        print("\n" + "=" * 60)
        return self.results

def main():
    """メイン実行関数"""
    print("🤖 LINE Bot Comprehensive Diagnostics Tool")
    print("Version: 2.1.0")
    print("=" * 60)
    
    # 診断実行
    diagnostics = LineBotDiagnostics()
    results = diagnostics.run_comprehensive_diagnostics()
    
    # 結果をJSONファイルに保存
    output_file = f"line_bot_diagnostics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n📄 Detailed results saved to: {output_file}")
    except Exception as e:
        print(f"\n⚠️ Failed to save results: {e}")
    
    # 終了コード設定
    exit_code = 0 if results["summary"]["overall_status"] == "healthy" else 1
    print(f"\n🏁 Diagnostics completed with exit code: {exit_code}")
    sys.exit(exit_code)

if __name__ == "__main__":
    main()