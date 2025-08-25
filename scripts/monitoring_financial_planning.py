# scripts/monitoring_financial_planning.py
# 資金計画機能運用監視スクリプト

import os
import json
import time
import requests
import schedule
from datetime import datetime, timedelta
from typing import Dict, Any, List
import smtplib
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart

class FinancialPlanningMonitor:
    """資金計画機能監視クラス"""
    
    def __init__(self, api_base_url: str, alert_email: str = None):
        self.api_base_url = api_base_url.rstrip('/')
        self.alert_email = alert_email
        self.monitoring_log = []
        self.alert_thresholds = {
            "response_time_ms": 5000,      # 5秒以上で警告
            "error_rate_percent": 5,       # エラー率5%以上で警告  
            "active_sessions": 100,        # 100セッション以上で警告
            "memory_usage_mb": 1800,       # 1.8GB以上で警告
            "cpu_usage_percent": 80        # CPU使用率80%以上で警告
        }
    
    def check_api_health(self) -> Dict[str, Any]:
        """API ヘルスチェック"""
        try:
            start_time = time.time()
            response = requests.get(f"{self.api_base_url}/healthz", timeout=10)
            response_time = (time.time() - start_time) * 1000
            
            if response.status_code == 200:
                health_data = response.json()
                
                check_result = {
                    "timestamp": datetime.now().isoformat(),
                    "status": "healthy",
                    "response_time_ms": response_time,
                    "details": health_data,
                    "alerts": []
                }
                
                # 応答時間チェック
                if response_time > self.alert_thresholds["response_time_ms"]:
                    check_result["alerts"].append({
                        "type": "high_response_time",
                        "value": response_time,
                        "threshold": self.alert_thresholds["response_time_ms"]
                    })
                
                return check_result
            else:
                return {
                    "timestamp": datetime.now().isoformat(),
                    "status": "unhealthy",
                    "response_time_ms": response_time,
                    "status_code": response.status_code,
                    "alerts": [{"type": "api_down", "status_code": response.status_code}]
                }
                
        except Exception as e:
            return {
                "timestamp": datetime.now().isoformat(),
                "status": "error",
                "error": str(e),
                "alerts": [{"type": "api_unreachable", "error": str(e)}]
            }
    
    def check_financial_sessions(self) -> Dict[str, Any]:
        """資金計画セッション状態チェック"""
        try:
            response = requests.get(f"{self.api_base_url}/financial/sessions", timeout=10)
            
            if response.status_code == 200:
                sessions_data = response.json()
                active_sessions = sessions_data.get("active_sessions", 0)
                
                session_check = {
                    "timestamp": datetime.now().isoformat(),
                    "active_sessions": active_sessions,
                    "sessions_details": sessions_data.get("sessions", []),
                    "alerts": []
                }
                
                # セッション数チェック
                if active_sessions > self.alert_thresholds["active_sessions"]:
                    session_check["alerts"].append({
                        "type": "high_session_count",
                        "value": active_sessions,
                        "threshold": self.alert_thresholds["active_sessions"]
                    })
                
                # 長時間セッション検出
                long_sessions = []
                for session in sessions_data.get("sessions", []):
                    created_at = datetime.fromisoformat(session["created_at"].replace('Z', '+00:00'))
                    duration = datetime.now() - created_at.replace(tzinfo=None)
                    
                    if duration > timedelta(hours=1):  # 1時間以上
                        long_sessions.append({
                            "user_id": session["user_id"],
                            "duration_hours": duration.total_seconds() / 3600,
                            "completion_rate": session["completion_rate"]
                        })
                
                if long_sessions:
                    session_check["alerts"].append({
                        "type": "long_running_sessions",
                        "sessions": long_sessions
                    })
                
                return session_check
            else:
                return {
                    "timestamp": datetime.now().isoformat(),
                    "status": "error",
                    "status_code": response.status_code,
                    "alerts": [{"type": "session_api_error", "status_code": response.status_code}]
                }
                
        except Exception as e:
            return {
                "timestamp": datetime.now().isoformat(),
                "status": "error",
                "error": str(e),
                "alerts": [{"type": "session_check_error", "error": str(e)}]
            }
    
    def check_line_bot_performance(self) -> Dict[str, Any]:
        """LINE Bot パフォーマンスチェック"""
        try:
            response = requests.get(f"{self.api_base_url}/line/performance", timeout=10)
            
            if response.status_code == 200:
                perf_data = response.json()
                
                performance_check = {
                    "timestamp": datetime.now().isoformat(),
                    "routing_stats": perf_data.get("line_smart_integrated_financial_stats", {}),
                    "system_info": perf_data.get("system_info", {}),
                    "alerts": []
                }
                
                # 統計データから異常検出
                stats = perf_data.get("line_smart_integrated_financial_stats", {})
                
                # 資金計画利用率チェック
                financial_rate = stats.get("financial_rate", 0)
                if financial_rate > 50:  # 50%以上で高利用率アラート
                    performance_check["alerts"].append({
                        "type": "high_financial_usage",
                        "value": financial_rate,
                        "threshold": 50
                    })
                
                # 平均応答時間チェック
                avg_time = stats.get("avg_processing_time_ms", 0)
                if avg_time > self.alert_thresholds["response_time_ms"]:
                    performance_check["alerts"].append({
                        "type": "slow_processing",
                        "value": avg_time,
                        "threshold": self.alert_thresholds["response_time_ms"]
                    })
                
                return performance_check
            else:
                return {
                    "timestamp": datetime.now().isoformat(),
                    "status": "error",
                    "status_code": response.status_code,
                    "alerts": [{"type": "performance_api_error", "status_code": response.status_code}]
                }
                
        except Exception as e:
            return {
                "timestamp": datetime.now().isoformat(),
                "status": "error", 
                "error": str(e),
                "alerts": [{"type": "performance_check_error", "error": str(e)}]
            }
    
    def run_comprehensive_check(self) -> Dict[str, Any]:
        """総合監視チェック実行"""
        print(f"🔍 資金計画機能総合監視チェック - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 各種チェック実行
        api_health = self.check_api_health()
        session_status = self.check_financial_sessions()
        line_performance = self.check_line_bot_performance()
        
        # 総合結果
        comprehensive_result = {
            "timestamp": datetime.now().isoformat(),
            "overall_status": "healthy",
            "checks": {
                "api_health": api_health,
                "financial_sessions": session_status,
                "line_bot_performance": line_performance
            },
            "total_alerts": 0,
            "critical_alerts": []
        }
        
        # アラート集計
        all_alerts = []
        for check_name, check_result in comprehensive_result["checks"].items():
            alerts = check_result.get("alerts", [])
            for alert in alerts:
                alert["source"] = check_name
                all_alerts.append(alert)
        
        comprehensive_result["total_alerts"] = len(all_alerts)
        
        # 重要アラートフィルタリング
        critical_types = ["api_down", "api_unreachable", "high_session_count", "high_financial_usage"]
        critical_alerts = [alert for alert in all_alerts if alert["type"] in critical_types]
        comprehensive_result["critical_alerts"] = critical_alerts
        
        # 総合ステータス判定
        if len(critical_alerts) > 0:
            comprehensive_result["overall_status"] = "critical"
        elif len(all_alerts) > 3:
            comprehensive_result["overall_status"] = "warning"
        
        # ログ記録
        self.monitoring_log.append(comprehensive_result)
        
        # 結果出力
        status_emoji = {
            "healthy": "✅",
            "warning": "⚠️", 
            "critical": "🚨"
        }
        
        print(f"{status_emoji[comprehensive_result['overall_status']]} 総合ステータス: {comprehensive_result['overall_status'].upper()}")
        print(f"📊 総アラート数: {len(all_alerts)}")
        
        if critical_alerts:
            print("🚨 重要アラート:")
            for alert in critical_alerts:
                print(f"   - {alert['type']}: {alert.get('value', 'N/A')}")
        
        # アラート通知
        if len(critical_alerts) > 0 and self.alert_email:
            self.send_alert_email(comprehensive_result)
        
        return comprehensive_result
    
    def send_alert_email(self, check_result: Dict[str, Any]):
        """アラートメール送信"""
        try:
            subject = f"🚨 資金計画機能アラート - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            body = f"""
資金計画機能で重要なアラートが発生しました。

⏰ 検出時刻: {check_result['timestamp']}
🎯 総合ステータス: {check_result['overall_status']}
📊 総アラート数: {check_result['total_alerts']}

🚨 重要アラート:
"""
            
            for alert in check_result["critical_alerts"]:
                body += f"- {alert['type']}: {alert.get('value', 'N/A')} (ソース: {alert['source']})\n"
            
            body += f"""

🔗 確認URL:
- API ステータス: {self.api_base_url}/healthz
- パフォーマンス: {self.api_base_url}/line/performance  
- セッション状況: {self.api_base_url}/financial/sessions

このアラートは自動送信されました。
            """
            
            # メール送信（実装は環境に応じて調整）
            print(f"📧 アラートメール準備完了: {subject}")
            print("   （実際の送信は SMTP 設定が必要です）")
            
        except Exception as e:
            print(f"❌ アラートメール送信エラー: {e}")
    
    def cleanup_old_sessions(self):
        """古いセッションのクリーンアップ"""
        try:
            print("🧹 古いセッションクリーンアップ開始...")
            
            response = requests.post(f"{self.api_base_url}/financial/sessions/clear-all")
            
            if response.status_code == 200:
                result = response.json()
                cleared_count = result.get("cleared_sessions", 0)
                print(f"✅ セッションクリーンアップ完了: {cleared_count}件削除")
                return True
            else:
                print(f"❌ セッションクリーンアップ失敗: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"💥 セッションクリーンアップエラー: {e}")
            return False
    
    def generate_daily_report(self):
        """日次レポート生成"""
        try:
            print("📊 日次レポート生成開始...")
            
            # 各種統計取得
            health_check = self.check_api_health()
            session_status = self.check_financial_sessions()
            line_performance = self.check_line_bot_performance()
            
            # レポートデータ構築
            daily_report = {
                "report_date": datetime.now().strftime('%Y-%m-%d'),
                "generation_time": datetime.now().isoformat(),
                "summary": {
                    "api_status": health_check.get("status", "unknown"),
                    "total_sessions_today": session_status.get("active_sessions", 0),
                    "response_time_avg": health_check.get("response_time_ms", 0),
                    "financial_usage_rate": line_performance.get("routing_stats", {}).get("financial_rate", 0)
                },
                "detailed_metrics": {
                    "api_health": health_check,
                    "session_management": session_status,
                    "line_bot_performance": line_performance
                },
                "recommendations": []
            }
            
            # 推奨事項生成
            recommendations = []
            
            if daily_report["summary"]["response_time_avg"] > 3000:
                recommendations.append("応答時間が遅いため、RAGキャッシュの最適化を検討してください")
            
            if daily_report["summary"]["total_sessions_today"] > 50:
                recommendations.append("資金計画の利用が活発です。リソース増強を検討してください")
            
            if daily_report["summary"]["financial_usage_rate"] > 30:
                recommendations.append("資金計画機能の利用率が高いため、専用インスタンスの検討をお勧めします")
            
            daily_report["recommendations"] = recommendations
            
            # レポートファイル保存
            report_filename = f"daily_report_{datetime.now().strftime('%Y%m%d')}.json"
            with open(report_filename, "w", encoding="utf-8") as f:
                json.dump(daily_report, f, indent=2, ensure_ascii=False)
            
            print(f"✅ 日次レポート生成完了: {report_filename}")
            
            # コンソール出力
            print("\n📈 本日の統計サマリー:")
            print(f"   API状態: {daily_report['summary']['api_status']}")
            print(f"   アクティブセッション: {daily_report['summary']['total_sessions_today']}件")
            print(f"   平均応答時間: {daily_report['summary']['response_time_avg']:.1f}ms")
            print(f"   資金計画利用率: {daily_report['summary']['financial_usage_rate']:.1f}%")
            
            if recommendations:
                print("\n💡 推奨事項:")
                for rec in recommendations:
                    print(f"   - {rec}")
            
            return daily_report
            
        except Exception as e:
            print(f"❌ 日次レポート生成エラー: {e}")
            return None

def setup_monitoring_schedule():
    """監視スケジュール設定"""
    api_url = os.getenv("API_BASE_URL", "https://rag-api-190389115361.asia-northeast1.run.app")
    alert_email = os.getenv("ALERT_EMAIL")
    
    monitor = FinancialPlanningMonitor(api_url, alert_email)
    
    # スケジュール設定
    schedule.every(5).minutes.do(lambda: monitor.run_comprehensive_check())
    schedule.every().hour.do(lambda: monitor.cleanup_old_sessions())
    schedule.every().day.at("09:00").do(lambda: monitor.generate_daily_report())
    
    print("⏰ 監視スケジュール設定完了:")
    print("   - 5分毎: 総合ヘルスチェック")
    print("   - 1時間毎: セッションクリーンアップ")
    print("   - 毎日9:00: 日次レポート生成")
    
    # 監視開始
    print("🚀 監視開始...")
    while True:
        schedule.run_pending()
        time.sleep(60)  # 1分間隔でチェック

# ==============================================================================
# Cloud Run 監視用スクリプト
# ==============================================================================
class CloudRunMonitor:
    """Cloud Run サービス監視"""
    
    def __init__(self, project_id: str, service_name: str = "rag-api", region: str = "asia-northeast1"):
        self.project_id = project_id
        self.service_name = service_name
        self.region = region
    
    def get_service_metrics(self) -> Dict[str, Any]:
        """Cloud Run サービスメトリクス取得"""
        try:
            # gcloud コマンドでメトリクス取得
            import subprocess
            
            # CPU使用率
            cpu_cmd = f"""
            gcloud monitoring metrics list \
              --project {self.project_id} \
              --filter "metric.type=run.googleapis.com/container/cpu/utilizations" \
              --format="value(metric.type)"
            """
            
            # メモリ使用率  
            memory_cmd = f"""
            gcloud monitoring metrics list \
              --project {self.project_id} \
              --filter "metric.type=run.googleapis.com/container/memory/utilizations" \
              --format="value(metric.type)"
            """
            
            # リクエスト数
            requests_cmd = f"""
            gcloud monitoring metrics list \
              --project {self.project_id} \
              --filter "metric.type=run.googleapis.com/request_count" \
              --format="value(metric.type)"
            """
            
            metrics = {
                "timestamp": datetime.now().isoformat(),
                "service": f"{self.service_name} ({self.region})",
                "metrics_available": True,
                "note": "実際のメトリクス取得にはCloud Monitoring APIを使用してください"
            }
            
            return metrics
            
        except Exception as e:
            return {
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
                "metrics_available": False
            }

# ==============================================================================
# 動作確認テストスイート
# ==============================================================================
class FinancialPlanningValidationSuite:
    """資金計画機能動作確認テストスイート"""
    
    def __init__(self, api_base_url: str):
        self.base_url = api_base_url
        self.validation_results = []
    
    def validate_richmenu_responses(self):
        """リッチメニュー応答検証"""
        print("📱 リッチメニュー応答検証")
        print("-" * 40)
        
        richmenu_actions = [
            ("🤖 AI相談", "AI相談応答"),
            ("🌐 AI住まいサイト", "住まいサイト案内"),
            ("📋 資料請求", "資料請求案内"),
            ("📍 展示場来場予約", "展示場予約案内"),
            ("💰 資金計画", "資金計画開始"),  # 🆕 重要
            ("💬 チャット相談", "チャット相談案内")
        ]
        
        for action_text, description in richmenu_actions:
            try:
                test_data = {
                    "question": action_text,
                    "username": f"validation_user_{int(time.time())}",
                    "platform": "line"
                }
                
                response = requests.post(
                    f"{self.base_url}/chat",
                    json=test_data,
                    timeout=10
                )
                
                if response.status_code == 200:
                    result = response.json()
                    answer = result.get("answer", "")
                    
                    # 応答内容の検証
                    if len(answer) > 20 and answer.endswith(('。', '！', '？')):
                        print(f"✅ {description}: 適切な応答 ({len(answer)}文字)")
                        
                        # 資金計画特有の内容チェック
                        if action_text == "💰 資金計画":
                            required_elements = ["年収", "返済額", "借入期間", "家族構成", "その他負担"]
                            missing_elements = [elem for elem in required_elements if elem not in answer]
                            
                            if not missing_elements:
                                print(f"   ✅ 必要要素全て含有")
                                self.validation_results.append({"test": description, "status": "success"})
                            else:
                                print(f"   ⚠️ 不足要素: {missing_elements}")
                                self.validation_results.append({"test": description, "status": "warning"})
                        else:
                            self.validation_results.append({"test": description, "status": "success"})
                    else:
                        print(f"❌ {description}: 不適切な応答 - {answer[:50]}...")
                        self.validation_results.append({"test": description, "status": "failed"})
                else:
                    print(f"❌ {description}: API呼び出し失敗 ({response.status_code})")
                    self.validation_results.append({"test": description, "status": "failed"})
                    
                time.sleep(0.5)  # レート制限対策
                
            except Exception as e:
                print(f"💥 {description}: {e}")
                self.validation_results.append({"test": description, "status": "error"})
    
    def validate_financial_edge_cases(self):
        """資金計画エッジケース検証"""
        print("\n💰 資金計画エッジケース検証")
        print("-" * 40)
        
        edge_cases = [
            {
                "name": "極端な高所得",
                "data": {
                    "annual_income": 15000000,  # 1500万円
                    "monthly_payment": 200000,  # 20万円
                    "loan_period": 30,
                    "family_composition": "大人2名",
                    "other_expenses": 0
                },
                "expected_behavior": "計算成功・適切な上限設定"
            },
            {
                "name": "極端な低所得",
                "data": {
                    "annual_income": 2000000,   # 200万円
                    "monthly_payment": 50000,   # 5万円
                    "loan_period": 40,
                    "family_composition": "大人1名",
                    "other_expenses": 0
                },
                "expected_behavior": "計算成功・現実的な提案"
            },
            {
                "name": "不整合な入力",
                "data": {
                    "annual_income": 3000000,   # 300万円
                    "monthly_payment": 200000,  # 20万円（年収に対して高すぎ）
                    "loan_period": 35,
                    "family_composition": "大人2名・お子さま3名",
                    "other_expenses": 100000    # 10万円
                },
                "expected_behavior": "警告またはリスク高評価"
            }
        ]
        
        for case in edge_cases:
            try:
                print(f"\n🧪 {case['name']}テスト...")
                
                response = requests.post(
                    f"{self.base_url}/financial/calculate",
                    json=case["data"],
                    timeout=15
                )
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if result.get("success"):
                        calc = result["calculation"]
                        
                        print(f"   ✅ 計算成功")
                        print(f"   💰 結果: {calc['affordable_budget_min']}万〜{calc['affordable_budget_max']}万円")
                        print(f"   🎯 リスク: {calc['risk_level']}")
                        
                        # 妥当性チェック
                        if calc['affordable_budget_min'] > 0 and calc['affordable_budget_max'] > calc['affordable_budget_min']:
                            print(f"   ✅ 結果の妥当性: OK")
                            self.validation_results.append({"test": case['name'], "status": "success"})
                        else:
                            print(f"   ⚠️ 結果の妥当性: 要確認")
                            self.validation_results.append({"test": case['name'], "status": "warning"})
                    else:
                        print(f"   ❌ 計算失敗: {result}")
                        self.validation_results.append({"test": case['name'], "status": "failed"})
                else:
                    print(f"   ❌ API呼び出し失敗: {response.status_code}")
                    self.validation_results.append({"test": case['name'], "status": "failed"})
                    
            except Exception as e:
                print(f"   💥 エラー: {e}")
                self.validation_results.append({"test": case['name'], "status": "error"})
    
    def validate_liff_functionality(self):
        """LIFF機能検証"""
        print("\n📱 LIFF機能検証")
        print("-" * 40)
        
        try:
            # LIFF ページアクセス
            response = requests.get(f"{self.base_url}/financial/liff-page", timeout=10)
            
            if response.status_code == 200:
                content = response.text
                
                # JavaScript機能チェック
                js_functions = [
                    "liff.init",
                    "updateProgress",
                    "formatResult", 
                    "addEventListener",
                    "fetch('/financial/calculate'"
                ]
                
                missing_functions = []
                for func in js_functions:
                    if func not in content:
                        missing_functions.append(func)
                
                if not missing_functions:
                    print("✅ LIFF JavaScript機能: 全て実装済み")
                    self.validation_results.append({"test": "liff_js_functions", "status": "success"})
                else:
                    print(f"⚠️ LIFF JavaScript機能: 不足 - {missing_functions}")
                    self.validation_results.append({"test": "liff_js_functions", "status": "warning"})
                
                # CSS スタイルチェック
                css_elements = [".container", ".btn", ".input", ".progress-bar", ".result"]
                missing_styles = [elem for elem in css_elements if elem not in content]
                
                if not missing_styles:
                    print("✅ LIFF CSS スタイル: 完全")
                    self.validation_results.append({"test": "liff_css_styles", "status": "success"})
                else:
                    print(f"⚠️ LIFF CSS スタイル: 不足 - {missing_styles}")
                    self.validation_results.append({"test": "liff_css_styles", "status": "warning"})
                    
            else:
                print(f"❌ LIFF ページアクセス失敗: {response.status_code}")
                self.validation_results.append({"test": "liff_page_access", "status": "failed"})
                
        except Exception as e:
            print(f"💥 LIFF検証エラー: {e}")
            self.validation_results.append({"test": "liff_validation", "status": "error"})
    
    def run_full_validation(self) -> bool:
        """完全検証実行"""
        print("🔍 資金計画機能完全検証開始")
        print("=" * 60)
        
        self.validate_richmenu_responses()
        self.validate_financial_edge_cases()
        self.validate_liff_functionality()
        
        # 結果サマリー
        total = len(self.validation_results)
        success = len([r for r in self.validation_results if r["status"] == "success"])
        warning = len([r for r in self.validation_results if r["status"] == "warning"])
        failed = len([r for r in self.validation_results if r["status"] == "failed"])
        error = len([r for r in self.validation_results if r["status"] == "error"])
        
        print(f"\n📊 検証結果サマリー")
        print("=" * 40)
        print(f"📈 総検証数: {total}")
        print(f"✅ 成功: {success} ({success/total*100:.1f}%)")
        print(f"⚠️ 警告: {warning} ({warning/total*100:.1f}%)")
        print(f"❌ 失敗: {failed} ({failed/total*100:.1f}%)")
        print(f"💥 エラー: {error} ({error/total*100:.1f}%)")
        
        # 合格判定
        pass_rate = (success + warning) / total if total > 0 else 0
        
        if pass_rate >= 0.9:
            print("\n🎉 検証合格！本番運用開始可能です。")
            return True
        elif pass_rate >= 0.7:
            print("\n⚠️ 部分合格。警告事項を確認の上、運用開始してください。")
            return True
        else:
            print("\n❌ 検証不合格。問題を修正してから再検証してください。")
            return False

# ==============================================================================
# デプロイ後確認スクリプト
# ==============================================================================
def post_deployment_verification(service_url: str):
    """デプロイ後確認"""
    print("🚀 デプロイ後確認開始")
    print("=" * 50)
    
    # 1. 基本接続確認
    print("1️⃣ 基本接続確認...")
    try:
        response = requests.get(f"{service_url}/healthz", timeout=15)
        if response.status_code == 200:
            health = response.json()
            print(f"✅ API接続: OK")
            print(f"   バージョン: {health.get('version', 'N/A')}")
            print(f"   稼働時間: {health.get('uptime', 0):.2f}秒")
        else:
            print(f"❌ API接続: {response.status_code}")
            return False
    except Exception as e:
        print(f"💥 接続エラー: {e}")
        return False
    
    # 2. LINE Bot設定確認
    print("\n2️⃣ LINE Bot設定確認...")
    try:
        response = requests.get(f"{service_url}/line/debug", timeout=10)
        if response.status_code == 200:
            debug_info = response.json()
            
            checks = [
                ("line_sdk_available", "LINE SDK"),
                ("line_bot_api_initialized", "LINE Bot API"),
                ("handler_initialized", "ハンドラー"),
                ("financial_planning", "資金計画機能")
            ]
            
            for key, description in checks:
                value = debug_info.get(key, False)
                if isinstance(value, dict):
                    value = value.get("handler_initialized", False)
                
                status = "✅" if value else "❌"
                print(f"   {status} {description}: {value}")
        else:
            print(f"❌ LINE Bot設定確認失敗: {response.status_code}")
    except Exception as e:
        print(f"💥 LINE Bot確認エラー: {e}")
    
    # 3. 資金計画機能確認
    print("\n3️⃣ 資金計画機能確認...")
    try:
        response = requests.get(f"{service_url}/financial/settings", timeout=10)
        if response.status_code == 200:
            settings = response.json()
            print(f"✅ 資金計画設定: OK")
            
            params = settings.get("calculation_parameters", {})
            print(f"   金利: {params.get('default_interest_rate', 'N/A')}%")
            print(f"   頭金率: {params.get('default_down_payment_rate', 'N/A')*100:.1f}%")
            print(f"   年収倍率: {params.get('income_multiplier_safe', 'N/A')}倍")
        else:
            print(f"❌ 資金計画設定確認失敗: {response.status_code}")
    except Exception as e:
        print(f"💥 資金計画確認エラー: {e}")
    
    # 4. LIFF ページ確認
    print("\n4️⃣ LIFF ページ確認...")
    try:
        response = requests.get(f"{service_url}/financial/liff-page", timeout=10)
        if response.status_code == 200:
            print(f"✅ LIFF ページ: アクセス可能 ({len(response.text):,} bytes)")
        else:
            print(f"❌ LIFF ページ: アクセス失敗 ({response.status_code})")
    except Exception as e:
        print(f"💥 LIFF ページ確認エラー: {e}")
    
    # 5. 最終テスト実行
    print("\n5️⃣ 最終統合テスト...")
    validator = FinancialPlanningValidationSuite(service_url)
    validation_success = validator.run_full_validation()
    
    if validation_success:
        print("\n🎉 デプロイ後確認完了！本番運用開始可能です。")
        
        print("\n📋 次のステップ:")
        print("1. LINE Developers Console で Webhook URL を更新")
        print(f"   URL: {service_url}/line/webhook")
        print("2. リッチメニュー画像をアップロード")
        print("3. LINEアプリでテスト実行")
        print("4. 監視アラート設定")
        
        return True
    else:
        print("\n❌ 検証に問題があります。修正後に再確認してください。")
        return False

# ==============================================================================
# メイン実行関数
# ==============================================================================
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="資金計画機能運用管理")
    parser.add_argument("command", choices=[
        "setup-richmenu", "monitor", "validate", "post-deploy", "daily-report"
    ], help="実行コマンド")
    parser.add_argument("--api-url", default="http://localhost:8080", help="API URL")
    parser.add_argument("--service-url", help="本番サービスURL")
    
    args = parser.parse_args()
    
    if args.command == "setup-richmenu":
        print("🎨 リッチメニューセットアップ実行...")
        success = main()  # リッチメニュー設定関数
        return success
    
    elif args.command == "monitor":
        print("🔍 監視開始...")
        monitor = FinancialPlanningMonitor(args.api_url)
        result = monitor.run_comprehensive_check()
        return result["overall_status"] != "critical"
    
    elif args.command == "validate":
        print("✅ 動作確認テスト実行...")
        validator = FinancialPlanningValidationSuite(args.api_url)
        return validator.run_full_validation()
    
    elif args.command == "post-deploy":
        service_url = args.service_url or args.api_url
        print(f"🚀 デプロイ後確認実行: {service_url}")
        return post_deployment_verification(service_url)
    
    elif args.command == "daily-report":
        print("📊 日次レポート生成...")
        monitor = FinancialPlanningMonitor(args.api_url)
        report = monitor.generate_daily_report()
        return report is not None
    
    return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)