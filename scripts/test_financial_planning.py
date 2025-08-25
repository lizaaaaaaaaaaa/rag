# scripts/test_financial_planning.py
# 資金計画機能テストスクリプト

import asyncio
import json
import requests
import time
from datetime import datetime

class FinancialPlanningTester:
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.test_results = []
    
    def test_api_endpoints(self):
        """API エンドポイントのテスト"""
        print("🧪 API エンドポイントテスト開始")
        print("=" * 50)
        
        endpoints = [
            ("/healthz", "GET", "ヘルスチェック"),
            ("/financial/liff-page", "GET", "LIFF ページ"),
            ("/financial/settings", "GET", "資金計画設定"),
            ("/financial/sessions", "GET", "セッション一覧"),
            ("/line/debug", "GET", "LINE Bot デバッグ"),
            ("/line/performance", "GET", "パフォーマンス統計")
        ]
        
        for endpoint, method, description in endpoints:
            try:
                url = f"{self.base_url}{endpoint}"
                response = requests.get(url, timeout=10)
                
                if response.status_code == 200:
                    print(f"✅ {description}: {response.status_code}")
                    self.test_results.append({"test": description, "status": "success"})
                else:
                    print(f"❌ {description}: {response.status_code}")
                    self.test_results.append({"test": description, "status": "failed"})
                    
            except Exception as e:
                print(f"💥 {description}: {str(e)}")
                self.test_results.append({"test": description, "status": "error", "error": str(e)})
    
    def test_financial_calculation(self):
        """資金計算テスト"""
        print("\n💰 資金計算テスト開始")
        print("=" * 50)
        
        test_data = {
            "annual_income": 6000000,   # 600万円
            "monthly_payment": 80000,   # 8万円
            "loan_period": 35,          # 35年
            "family_composition": "大人2名・お子さま1名",
            "other_expenses": 30000     # 3万円
        }
        
        try:
            url = f"{self.base_url}/financial/calculate"
            response = requests.post(url, json=test_data, timeout=15)
            
            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    calc = result["calculation"]
                    print(f"✅ 計算成功:")
                    print(f"   購入可能額: {calc['affordable_budget_min']}万〜{calc['affordable_budget_max']}万円")
                    print(f"   推奨返済額: {calc['monthly_payment_suggestion']:,}円")
                    print(f"   最大借入額: {calc['max_loan_amount']}万円")
                    
                    # 結果の妥当性チェック
                    if 2000 <= calc['affordable_budget_min'] <= 4000:
                        print("✅ 計算結果の妥当性確認")
                        self.test_results.append({"test": "financial_calculation", "status": "success"})
                    else:
                        print("⚠️ 計算結果が期待値から外れています")
                        self.test_results.append({"test": "financial_calculation", "status": "warning"})
                else:
                    print(f"❌ 計算失敗: {result}")
                    self.test_results.append({"test": "financial_calculation", "status": "failed"})
            else:
                print(f"❌ API呼び出し失敗: {response.status_code}")
                self.test_results.append({"test": "financial_calculation", "status": "failed"})
                
        except Exception as e:
            print(f"💥 計算テストエラー: {str(e)}")
            self.test_results.append({"test": "financial_calculation", "status": "error", "error": str(e)})
    
    def test_session_management(self):
        """セッション管理テスト"""
        print("\n📝 セッション管理テスト開始")
        print("=" * 50)
        
        try:
            # セッション一覧取得
            response = requests.get(f"{self.base_url}/financial/sessions")
            if response.status_code == 200:
                sessions = response.json()
                print(f"✅ セッション一覧取得成功: {sessions['active_sessions']}件")
                self.test_results.append({"test": "session_list", "status": "success"})
            else:
                print(f"❌ セッション一覧取得失敗: {response.status_code}")
                self.test_results.append({"test": "session_list", "status": "failed"})
            
            # セッション全クリア
            response = requests.post(f"{self.base_url}/financial/sessions/clear-all")
            if response.status_code == 200:
                result = response.json()
                print(f"✅ セッション全クリア成功: {result['cleared_sessions']}件クリア")
                self.test_results.append({"test": "session_clear", "status": "success"})
            else:
                print(f"❌ セッション全クリア失敗: {response.status_code}")
                self.test_results.append({"test": "session_clear", "status": "failed"})
                
        except Exception as e:
            print(f"💥 セッション管理テストエラー: {str(e)}")
            self.test_results.append({"test": "session_management", "status": "error", "error": str(e)})
    
    def generate_test_report(self):
        """テストレポート生成"""
        print("\n📊 テスト結果サマリー")
        print("=" * 50)
        
        total_tests = len(self.test_results)
        success_tests = len([r for r in self.test_results if r["status"] == "success"])
        failed_tests = len([r for r in self.test_results if r["status"] == "failed"])
        error_tests = len([r for r in self.test_results if r["status"] == "error"])
        
        print(f"総テスト数: {total_tests}")
        print(f"成功: {success_tests} ({success_tests/total_tests*100:.1f}%)")
        print(f"失敗: {failed_tests} ({failed_tests/total_tests*100:.1f}%)")
        print(f"エラー: {error_tests} ({error_tests/total_tests*100:.1f}%)")
        
        if failed_tests == 0 and error_tests == 0:
            print("\n🎉 全てのテストが成功しました！")
            return True
        else:
            print("\n⚠️ 一部のテストが失敗しました。ログを確認してください。")
            return False
    
    def run_all_tests(self):
        """全テスト実行"""
        print(f"🧪 資金計画機能総合テスト開始")
        print(f"🌐 テスト対象: {self.base_url}")
        print(f"⏰ 開始時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        self.test_api_endpoints()
        self.test_financial_calculation()
        self.test_session_management()
        
        success = self.generate_test_report()
        
        # テストレポートファイル出力
        with open(f"test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", "w") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "base_url": self.base_url,
                "results": self.test_results,
                "summary": {
                    "total": len(self.test_results),
                    "success": len([r for r in self.test_results if r["status"] == "success"]),
                    "failed": len([r for r in self.test_results if r["status"] == "failed"]),
                    "error": len([r for r in self.test_results if r["status"] == "error"]),
                    "overall_success": success
                }
            }, f, indent=2, ensure_ascii=False)
        
        return success

if __name__ == "__main__":
    import sys
    
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
    tester = FinancialPlanningTester(base_url)
    
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)