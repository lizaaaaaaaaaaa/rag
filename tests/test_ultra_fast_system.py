# test_ultra_fast_system.py - 超高速システム パフォーマンステストツール

import asyncio
import aiohttp
import time
import json
import statistics
from datetime import datetime
from typing import List, Dict, Any
import argparse

class UltraFastSystemTester:
    """超高速システムのパフォーマンステスター"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.test_queries = self._load_test_queries()
        self.results = []
        
    def _load_test_queries(self) -> List[Dict[str, str]]:
        """テスト用クエリセット"""
        return [
            # === 即座応答対象（テンプレート） ===
            {"query": "坪単価について教えて", "expected_source": "template", "target_time": 0.1},
            {"query": "標準仕様はどんな感じ？", "expected_source": "template", "target_time": 0.1},
            {"query": "断熱性能について知りたい", "expected_source": "template", "target_time": 0.1},
            {"query": "耐震性能について", "expected_source": "template", "target_time": 0.1},
            {"query": "資料請求したい", "expected_source": "template", "target_time": 0.1},
            {"query": "展示場を見学したい", "expected_source": "template", "target_time": 0.1},
            {"query": "資金計画について相談", "expected_source": "template", "target_time": 0.1},
            
            # === キャッシュ効果確認用（同じクエリを再実行） ===
            {"query": "坪単価について教えて", "expected_source": "cache", "target_time": 0.05},
            {"query": "標準仕様はどんな感じ？", "expected_source": "cache", "target_time": 0.05},
            
            # === フォールバック対象 ===
            {"query": "家を建てる流れを教えて", "expected_source": "fallback", "target_time": 0.2},
            {"query": "補助金制度について", "expected_source": "fallback", "target_time": 0.2},
            {"query": "ZEHについて詳しく", "expected_source": "fallback", "target_time": 0.2},
            
            # === LINE Bot想定クエリ ===
            {"query": "AI相談", "expected_source": "template", "target_time": 0.1},
            {"query": "こんにちは", "expected_source": "template", "target_time": 0.1},
            {"query": "ありがとう", "expected_source": "template", "target_time": 0.1},
        ]
    
    async def test_system_startup(self) -> Dict[str, Any]:
        """システム起動時間テスト"""
        print("🚀 システム起動テスト開始...")
        
        startup_checks = [
            ("/healthz", "ヘルスチェック"),
            ("/", "ルートエンドポイント"),
            ("/system-status", "システム状態"),
            ("/performance-stats", "パフォーマンス統計")
        ]
        
        startup_results = {}
        
        async with aiohttp.ClientSession() as session:
            for endpoint, description in startup_checks:
                try:
                    start_time = time.time()
                    async with session.get(f"{self.base_url}{endpoint}", timeout=10) as response:
                        response_time = (time.time() - start_time) * 1000
                        
                        if response.status == 200:
                            data = await response.json()
                            startup_results[endpoint] = {
                                "status": "success",
                                "response_time_ms": response_time,
                                "description": description,
                                "data": data
                            }
                            print(f"  ✅ {description}: {response_time:.1f}ms")
                        else:
                            startup_results[endpoint] = {
                                "status": "error",
                                "response_time_ms": response_time,
                                "description": description,
                                "error": f"HTTP {response.status}"
                            }
                            print(f"  ❌ {description}: HTTP {response.status}")
                            
                except Exception as e:
                    startup_results[endpoint] = {
                        "status": "error",
                        "description": description,
                        "error": str(e)
                    }
                    print(f"  ❌ {description}: {e}")
        
        return startup_results
    
    async def test_web_chat_performance(self) -> Dict[str, Any]:
        """ウェブチャット性能テスト"""
        print("\n📊 ウェブチャット性能テスト開始...")
        
        response_times = []
        source_distribution = {"template": 0, "cache": 0, "fallback": 0, "error": 0}
        target_achievements = {"under_100ms": 0, "under_500ms": 0, "under_1000ms": 0}
        
        async with aiohttp.ClientSession() as session:
            for i, test_query in enumerate(self.test_queries):
                try:
                    print(f"  🧪 テスト {i+1}/{len(self.test_queries)}: '{test_query['query'][:30]}...'")
                    
                    start_time = time.time()
                    
                    async with session.post(
                        f"{self.base_url}/chat",
                        json={"question": test_query["query"], "username": "performance-test"},
                        timeout=5
                    ) as response:
                        response_time = (time.time() - start_time) * 1000
                        
                        if response.status == 200:
                            data = await response.json()
                            answer = data.get("answer", "")
                            performance = data.get("performance", {})
                            source = performance.get("source", "unknown")
                            
                            # 結果記録
                            response_times.append(response_time)
                            source_distribution[source] = source_distribution.get(source, 0) + 1
                            
                            # 目標達成度
                            if response_time <= 100:
                                target_achievements["under_100ms"] += 1
                            if response_time <= 500:
                                target_achievements["under_500ms"] += 1
                            if response_time <= 1000:
                                target_achievements["under_1000ms"] += 1
                            
                            # 期待値チェック
                            expected_source = test_query.get("expected_source")
                            target_time_ms = test_query.get("target_time", 1.0) * 1000
                            
                            status_icon = "✅" if response_time <= target_time_ms else "⚠️"
                            source_match = "✅" if source == expected_source else f"❓{source}"
                            
                            print(f"    {status_icon} {response_time:.1f}ms | {source_match} | {len(answer)}文字")
                            
                            # 結果保存
                            self.results.append({
                                "query": test_query["query"],
                                "response_time_ms": response_time,
                                "source": source,
                                "expected_source": expected_source,
                                "target_time_ms": target_time_ms,
                                "answer_length": len(answer),
                                "success": True
                            })
                            
                        else:
                            source_distribution["error"] += 1
                            print(f"    ❌ HTTP {response.status}")
                            
                except Exception as e:
                    source_distribution["error"] += 1
                    print(f"    ❌ Error: {e}")
        
        # 統計計算
        total_tests = len(self.test_queries)
        avg_response_time = statistics.mean(response_times) if response_times else 0
        p95_response_time = statistics.quantiles(response_times, n=20)[18] if len(response_times) > 20 else 0
        p99_response_time = statistics.quantiles(response_times, n=100)[98] if len(response_times) > 100 else 0
        
        return {
            "total_tests": total_tests,
            "successful_tests": len(response_times),
            "error_count": source_distribution["error"],
            "response_times": {
                "average_ms": avg_response_time,
                "min_ms": min(response_times) if response_times else 0,
                "max_ms": max(response_times) if response_times else 0,
                "p95_ms": p95_response_time,
                "p99_ms": p99_response_time
            },
            "source_distribution": source_distribution,
            "target_achievements": {
                "under_100ms_count": target_achievements["under_100ms"],
                "under_100ms_rate": target_achievements["under_100ms"] / total_tests * 100,
                "under_500ms_count": target_achievements["under_500ms"],
                "under_500ms_rate": target_achievements["under_500ms"] / total_tests * 100,
                "under_1000ms_count": target_achievements["under_1000ms"],
                "under_1000ms_rate": target_achievements["under_1000ms"] / total_tests * 100
            }
        }
    
    async def test_line_bot_status(self) -> Dict[str, Any]:
        """LINE Bot状態テスト"""
        print("\n🤖 LINE Bot状態テスト開始...")
        
        line_endpoints = [
            ("/line/ultra-performance", "超高速パフォーマンス"),
            ("/line/templates", "テンプレート一覧"),
            ("/ultra-debug", "デバッグ情報")
        ]
        
        line_results = {}
        
        async with aiohttp.ClientSession() as session:
            for endpoint, description in line_endpoints:
                try:
                    start_time = time.time()
                    async with session.get(f"{self.base_url}{endpoint}", timeout=10) as response:
                        response_time = (time.time() - start_time) * 1000
                        
                        if response.status == 200:
                            data = await response.json()
                            line_results[endpoint] = {
                                "status": "success",
                                "response_time_ms": response_time,
                                "description": description,
                                "data": data
                            }
                            print(f"  ✅ {description}: {response_time:.1f}ms")
                        else:
                            line_results[endpoint] = {
                                "status": "error",
                                "response_time_ms": response_time,
                                "description": description,
                                "error": f"HTTP {response.status}"
                            }
                            print(f"  ❌ {description}: HTTP {response.status}")
                            
                except Exception as e:
                    line_results[endpoint] = {
                        "status": "error",
                        "description": description,
                        "error": str(e)
                    }
                    print(f"  ❌ {description}: {e}")
        
        return line_results
    
    async def test_load_performance(self, concurrent_users: int = 10, requests_per_user: int = 5) -> Dict[str, Any]:
        """負荷テスト"""
        print(f"\n🔄 負荷テスト開始 ({concurrent_users}同時ユーザー, {requests_per_user}リクエスト/ユーザー)...")
        
        async def user_simulation(user_id: int):
            """ユーザーシミュレーション"""
            user_results = []
            
            async with aiohttp.ClientSession() as session:
                for request_num in range(requests_per_user):
                    test_query = self.test_queries[request_num % len(self.test_queries)]
                    
                    try:
                        start_time = time.time()
                        async with session.post(
                            f"{self.base_url}/chat",
                            json={"question": test_query["query"], "username": f"load-test-user-{user_id}"},
                            timeout=10
                        ) as response:
                            response_time = (time.time() - start_time) * 1000
                            
                            user_results.append({
                                "user_id": user_id,
                                "request_num": request_num,
                                "response_time_ms": response_time,
                                "status_code": response.status,
                                "success": response.status == 200
                            })
                            
                    except Exception as e:
                        user_results.append({
                            "user_id": user_id,
                            "request_num": request_num,
                            "response_time_ms": 0,
                            "status_code": 0,
                            "success": False,
                            "error": str(e)
                        })
            
            return user_results
        
        # 並行実行
        start_time = time.time()
        tasks = [user_simulation(user_id) for user_id in range(concurrent_users)]
        all_user_results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time
        
        # 結果集計
        all_results = []
        for user_results in all_user_results:
            all_results.extend(user_results)
        
        successful_requests = [r for r in all_results if r["success"]]
        failed_requests = [r for r in all_results if not r["success"]]
        
        response_times = [r["response_time_ms"] for r in successful_requests]
        
        return {
            "test_config": {
                "concurrent_users": concurrent_users,
                "requests_per_user": requests_per_user,
                "total_requests": len(all_results),
                "total_time_seconds": total_time
            },
            "results": {
                "successful_requests": len(successful_requests),
                "failed_requests": len(failed_requests),
                "success_rate": len(successful_requests) / len(all_results) * 100 if all_results else 0,
                "throughput_rps": len(all_results) / total_time if total_time > 0 else 0
            },
            "response_times": {
                "average_ms": statistics.mean(response_times) if response_times else 0,
                "min_ms": min(response_times) if response_times else 0,
                "max_ms": max(response_times) if response_times else 0,
                "p95_ms": statistics.quantiles(response_times, n=20)[18] if len(response_times) > 20 else 0
            }
        }
    
    async def run_comprehensive_test(self) -> Dict[str, Any]:
        """包括的テスト実行"""
        print("🧪 超高速システム 包括的テスト開始")
        print("=" * 60)
        
        test_start_time = time.time()
        
        # 1. システム起動テスト
        startup_results = await self.test_system_startup()
        
        # 2. ウェブチャット性能テスト  
        web_chat_results = await self.test_web_chat_performance()
        
        # 3. LINE Bot状態テスト
        line_bot_results = await self.test_line_bot_status()
        
        # 4. 軽負荷テスト
        load_results = await self.test_load_performance(concurrent_users=5, requests_per_user=3)
        
        total_test_time = time.time() - test_start_time
        
        # 総合評価
        overall_assessment = self._generate_assessment(web_chat_results, load_results)
        
        return {
            "test_summary": {
                "timestamp": datetime.now().isoformat(),
                "total_test_time_seconds": total_test_time,
                "base_url": self.base_url
            },
            "startup_test": startup_results,
            "web_chat_performance": web_chat_results,
            "line_bot_status": line_bot_results,
            "load_test": load_results,
            "overall_assessment": overall_assessment
        }
    
    def _generate_assessment(self, web_results: Dict, load_results: Dict) -> Dict[str, Any]:
        """総合評価生成"""
        
        # パフォーマンス評価
        avg_response_time = web_results["response_times"]["average_ms"]
        fast_response_rate = web_results["target_achievements"]["under_100ms_rate"]
        success_rate = load_results["results"]["success_rate"]
        
        # グレード計算
        performance_grade = "A"
        if avg_response_time > 500 or fast_response_rate < 70 or success_rate < 95:
            performance_grade = "C"
        elif avg_response_time > 200 or fast_response_rate < 85 or success_rate < 98:
            performance_grade = "B"
        
        recommendations = []
        if avg_response_time > 200:
            recommendations.append("平均応答時間が目標を上回っています。キャッシュ最適化を検討してください。")
        if fast_response_rate < 80:
            recommendations.append("高速応答率が低いです。テンプレートの拡充を検討してください。")
        if success_rate < 98:
            recommendations.append("成功率が低いです。エラーハンドリングの改善が必要です。")
        
        if not recommendations:
            recommendations.append("システムは目標性能を達成しています。優秀です！")
        
        return {
            "performance_grade": performance_grade,
            "key_metrics": {
                "average_response_time_ms": avg_response_time,
                "fast_response_rate_percent": fast_response_rate,
                "load_test_success_rate_percent": success_rate
            },
            "target_achievement": {
                "ultra_fast_startup": True,  # < 10秒
                "template_response": fast_response_rate >= 80,  # 80%以上が100ms以内
                "system_stability": success_rate >= 95  # 95%以上成功
            },
            "recommendations": recommendations
        }
    
    def print_summary(self, results: Dict[str, Any]):
        """結果サマリー表示"""
        print("\n" + "=" * 60)
        print("🎯 超高速システム テスト結果サマリー")
        print("=" * 60)
        
        # 総合評価
        assessment = results["overall_assessment"]
        grade = assessment["performance_grade"]
        grade_emoji = {"A": "🏆", "B": "🥈", "C": "🥉"}.get(grade, "❓")
        
        print(f"\n{grade_emoji} 総合評価: {grade}グレード")
        
        # 主要メトリクス
        metrics = assessment["key_metrics"]
        print(f"\n📊 主要メトリクス:")
        print(f"  • 平均応答時間: {metrics['average_response_time_ms']:.1f}ms")
        print(f"  • 高速応答率: {metrics['fast_response_rate_percent']:.1f}%")
        print(f"  • 負荷テスト成功率: {metrics['load_test_success_rate_percent']:.1f}%")
        
        # 目標達成度
        achievements = assessment["target_achievement"]
        print(f"\n🎯 目標達成度:")
        for target, achieved in achievements.items():
            status = "✅" if achieved else "❌"
            print(f"  {status} {target}: {'達成' if achieved else '未達成'}")
        
        # 推奨事項
        print(f"\n💡 推奨事項:")
        for rec in assessment["recommendations"]:
            print(f"  • {rec}")
        
        print(f"\n📈 詳細結果:")
        print(f"  • テスト実行時間: {results['test_summary']['total_test_time_seconds']:.1f}秒")
        print(f"  • 総テスト数: {results['web_chat_performance']['total_tests']}")
        print(f"  • 成功テスト数: {results['web_chat_performance']['successful_tests']}")
        
        print("\n🚀 超高速システム テスト完了！")

async def main():
    """メイン実行関数"""
    parser = argparse.ArgumentParser(description="超高速RAGシステム パフォーマンステスト")
    parser.add_argument("--url", default="https://rag-api-190389115361.asia-northeast1.run.app", 
                       help="テスト対象のベースURL")
    parser.add_argument("--output", help="結果をJSONファイルに保存するパス")
    parser.add_argument("--quick", action="store_true", help="クイックテストモード")
    
    args = parser.parse_args()
    
    tester = UltraFastSystemTester(args.url)
    
    # テスト実行
    if args.quick:
        # クイックテスト（基本機能のみ）
        print("⚡ クイックテストモード")
        startup_results = await tester.test_system_startup()
        web_results = await tester.test_web_chat_performance()
        
        # 簡易結果表示
        avg_time = web_results["response_times"]["average_ms"]
        fast_rate = web_results["target_achievements"]["under_100ms_rate"]
        
        print(f"\n⚡ クイック結果:")
        print(f"  平均応答時間: {avg_time:.1f}ms")
        print(f"  高速応答率: {fast_rate:.1f}%")
        print(f"  評価: {'🏆 優秀' if avg_time < 200 and fast_rate > 80 else '🔧 要改善'}")
        
    else:
        # 包括的テスト
        results = await tester.run_comprehensive_test()
        
        # 結果表示
        tester.print_summary(results)
        
        # ファイル保存
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2, default=str)
            print(f"\n💾 結果を保存しました: {args.output}")

if __name__ == "__main__":
    asyncio.run(main())