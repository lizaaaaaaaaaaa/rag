# benchmark/speed_optimization_test_suite.py - 速度最適化ベンチマーク・テストスイート

import asyncio
import time
import statistics
import json
import csv
import requests
import concurrent.futures
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class BenchmarkResult:
    """ベンチマーク結果データクラス"""
    test_name: str
    query: str
    response_time: float
    response_length: int
    source: str
    success: bool
    optimization_applied: str
    platform: str
    timestamp: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_name": self.test_name,
            "query": self.query,
            "response_time": self.response_time,
            "response_length": self.response_length,
            "source": self.source,
            "success": self.success,
            "optimization_applied": self.optimization_applied,
            "platform": self.platform,
            "timestamp": self.timestamp.isoformat()
        }

class SpeedOptimizationBenchmark:
    """速度最適化ベンチマーククラス"""
    
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.results: List[BenchmarkResult] = []
        
        # 🚀 テストケース定義（実際の使用パターンに基づく）
        self.test_cases = {
            # 高頻度質問（テンプレート対象）
            "high_frequency": [
                "坪単価について教えて",
                "標準仕様はどんな感じ？",
                "断熱性能について",
                "耐震性能は？",
                "補助金について",
                "資料請求",
                "展示場見学",
                "価格",
                "費用はいくら",
                "AI相談"
            ],
            
            # LINE専用（リッチメニュー）
            "line_specific": [
                "🤖 AI相談",
                "🌐 AI住まいサイト", 
                "📋 資料請求",
                "📍 展示場来場予約",
                "💰 資金計画",
                "💬 チャット相談",
                "ai相談",
                "資金計画"
            ],
            
            # 中複雑度質問（RAG候補）
            "medium_complexity": [
                "家を建てる際に最初に何から始めればいいでしょうか",
                "土地探しのポイントを教えてください", 
                "住宅ローンの組み方について詳しく",
                "間取りを考える際の注意点"
            ],
            
            # 高複雑度質問（RAG対象）
            "high_complexity": [
                "長期優良住宅認定を取得する場合のメリットとデメリットを詳しく比較してください",
                "ZEH住宅と一般住宅の光熱費の違いを具体的な数値で教えてください",
                "耐震等級3と耐震等級2の違いについて構造計算の観点から詳しく説明してください"
            ],
            
            # アンチハルチネーション対象
            "anti_hallucination": [
                "兵庫県の2024年度ZEH補助金について教えてください",
                "加東市のこどもエコすまい支援事業の最新情報",
                "現在実施中の住宅ローン控除制度について"
            ],
            
            # エラーケース
            "edge_cases": [
                "",  # 空文字
                "あ",  # 単文字
                "？？？",  # 記号のみ
                "a" * 1000,  # 超長文
                "存在しない専門用語について"
            ]
        }
        
        # パフォーマンス目標
        self.performance_targets = {
            "template_response_max": 0.5,      # 500ms以下
            "rag_response_max": 6.0,           # 6秒以下
            "cache_response_max": 0.2,         # 200ms以下
            "line_response_max": 2.0,          # 2秒以下
            "template_hit_rate_min": 0.80,     # 80%以上
            "success_rate_min": 0.95,          # 95%以上
            "rag_usage_max": 0.10              # 10%以下
        }
    
    async def run_comprehensive_benchmark(self, iterations: int = 3, concurrent: int = 1) -> Dict[str, Any]:
        """包括的ベンチマーク実行"""
        logger.info(f"🚀 Starting comprehensive speed optimization benchmark")
        logger.info(f"   - Iterations per test: {iterations}")
        logger.info(f"   - Concurrent requests: {concurrent}")
        
        benchmark_start = time.time()
        
        # 1. Web API ベンチマーク
        web_results = await self._run_web_benchmark(iterations, concurrent)
        
        # 2. 統合システム ベンチマーク
        unified_results = await self._run_unified_benchmark(iterations, concurrent)
        
        # 3. プラットフォーム別ベンチマーク
        platform_results = await self._run_platform_benchmark(iterations)
        
        # 4. 負荷テスト
        load_test_results = await self._run_load_test()
        
        # 5. 結果分析
        analysis = self._analyze_results()
        
        total_time = time.time() - benchmark_start
        
        return {
            "benchmark_summary": {
                "total_time": total_time,
                "total_tests": len(self.results),
                "timestamp": datetime.now().isoformat()
            },
            "web_api_results": web_results,
            "unified_api_results": unified_results,
            "platform_results": platform_results,
            "load_test_results": load_test_results,
            "performance_analysis": analysis,
            "recommendations": self._generate_recommendations(analysis),
            "raw_results": [r.to_dict() for r in self.results]
        }
    
    async def _run_web_benchmark(self, iterations: int, concurrent: int) -> Dict[str, Any]:
        """Web API ベンチマーク"""
        logger.info("📊 Running Web API benchmark...")
        
        web_results = []
        
        for category, queries in self.test_cases.items():
            logger.info(f"   Testing {category} queries...")
            
            for query in queries:
                # 複数回実行
                times = []
                sources = []
                successes = []
                
                for _ in range(iterations):
                    if concurrent > 1:
                        # 並行実行
                        tasks = [self._test_web_api(query) for _ in range(concurrent)]
                        results = await asyncio.gather(*tasks)
                        for result in results:
                            times.append(result['response_time'])
                            sources.append(result['source'])
                            successes.append(result['success'])
                            self.results.append(BenchmarkResult(
                                test_name=f"web_{category}",
                                query=query,
                                response_time=result['response_time'],
                                response_length=result['response_length'],
                                source=result['source'],
                                success=result['success'],
                                optimization_applied="web_optimized",
                                platform="web",
                                timestamp=datetime.now()
                            ))
                    else:
                        # 逐次実行
                        result = await self._test_web_api(query)
                        times.append(result['response_time'])
                        sources.append(result['source'])
                        successes.append(result['success'])
                        self.results.append(BenchmarkResult(
                            test_name=f"web_{category}",
                            query=query,
                            response_time=result['response_time'],
                            response_length=result['response_length'],
                            source=result['source'],
                            success=result['success'],
                            optimization_applied="web_optimized",
                            platform="web",
                            timestamp=datetime.now()
                        ))
                
                web_results.append({
                    "category": category,
                    "query": query,
                    "avg_time": statistics.mean(times),
                    "min_time": min(times),
                    "max_time": max(times),
                    "success_rate": sum(successes) / len(successes),
                    "most_common_source": max(set(sources), key=sources.count)
                })
        
        return {
            "category_results": web_results,
            "summary": self._summarize_category_results(web_results)
        }
    
    async def _run_unified_benchmark(self, iterations: int, concurrent: int) -> Dict[str, Any]:
        """統合システムベンチマーク"""
        logger.info("📊 Running Unified API benchmark...")
        
        # 統合チャットエンドポイントをテスト
        unified_results = []
        
        for category, queries in self.test_cases.items():
            for query in queries[:3]:  # 各カテゴリ上位3件をテスト
                times = []
                sources = []
                
                for _ in range(iterations):
                    result = await self._test_unified_api(query)
                    times.append(result['response_time'])
                    sources.append(result['source'])
                    
                    self.results.append(BenchmarkResult(
                        test_name=f"unified_{category}",
                        query=query,
                        response_time=result['response_time'],
                        response_length=result['response_length'],
                        source=result['source'],
                        success=result['success'],
                        optimization_applied="unified_optimized",
                        platform="unified",
                        timestamp=datetime.now()
                    ))
                
                unified_results.append({
                    "category": category,
                    "query": query,
                    "avg_time": statistics.mean(times),
                    "sources": sources
                })
        
        return {
            "results": unified_results,
            "summary": self._summarize_category_results(unified_results)
        }
    
    async def _run_platform_benchmark(self, iterations: int) -> Dict[str, Any]:
        """プラットフォーム別ベンチマーク"""
        logger.info("📊 Running platform-specific benchmark...")
        
        platform_results = {}
        
        # Web プラットフォーム
        web_times = []
        for query in self.test_cases["high_frequency"][:5]:
            for _ in range(iterations):
                result = await self._test_web_api(query)
                web_times.append(result['response_time'])
        
        # LINE プラットフォーム（模擬）
        line_times = []
        for query in self.test_cases["line_specific"][:5]:
            for _ in range(iterations):
                result = await self._test_unified_api(query, platform="line")
                line_times.append(result['response_time'])
        
        platform_results = {
            "web": {
                "avg_time": statistics.mean(web_times),
                "median_time": statistics.median(web_times),
                "p95_time": self._percentile(web_times, 95),
                "tests_count": len(web_times)
            },
            "line": {
                "avg_time": statistics.mean(line_times),
                "median_time": statistics.median(line_times),
                "p95_time": self._percentile(line_times, 95),
                "tests_count": len(line_times)
            }
        }
        
        return platform_results
    
    async def _run_load_test(self) -> Dict[str, Any]:
        """負荷テスト"""
        logger.info("📊 Running load test...")
        
        # 同時リクエスト数を段階的に増加
        load_results = {}
        test_query = "坪単価について教えて"
        
        for concurrent_users in [1, 5, 10, 20]:
            logger.info(f"   Testing with {concurrent_users} concurrent users...")
            
            # 各ユーザーが5回リクエスト
            tasks = []
            for user in range(concurrent_users):
                for request in range(5):
                    tasks.append(self._test_web_api(f"{test_query} (user{user}_req{request})"))
            
            start_time = time.time()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            total_time = time.time() - start_time
            
            # 結果分析
            successful_results = [r for r in results if not isinstance(r, Exception)]
            failed_count = len(results) - len(successful_results)
            
            if successful_results:
                response_times = [r['response_time'] for r in successful_results]
                load_results[f"{concurrent_users}_users"] = {
                    "total_requests": len(tasks),
                    "successful_requests": len(successful_results),
                    "failed_requests": failed_count,
                    "success_rate": len(successful_results) / len(tasks),
                    "total_time": total_time,
                    "requests_per_second": len(successful_results) / total_time,
                    "avg_response_time": statistics.mean(response_times),
                    "p95_response_time": self._percentile(response_times, 95)
                }
            else:
                load_results[f"{concurrent_users}_users"] = {
                    "total_requests": len(tasks),
                    "successful_requests": 0,
                    "failed_requests": failed_count,
                    "success_rate": 0,
                    "error": "All requests failed"
                }
        
        return load_results
    
    async def _test_web_api(self, query: str) -> Dict[str, Any]:
        """Web API単体テスト"""
        try:
            start_time = time.time()
            
            response = requests.post(
                f"{self.base_url}/chat",
                json={"question": query, "username": "benchmark_user", "platform": "web"},
                timeout=30
            )
            
            end_time = time.time()
            response_time = end_time - start_time
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "response_time": response_time,
                    "response_length": len(data.get("answer", "")),
                    "source": data.get("performance", {}).get("source", "unknown"),
                    "success": True
                }
            else:
                return {
                    "response_time": response_time,
                    "response_length": 0,
                    "source": "error",
                    "success": False
                }
                
        except Exception as e:
            return {
                "response_time": 30.0,  # タイムアウト時間
                "response_length": 0,
                "source": f"error_{type(e).__name__}",
                "success": False
            }
    
    async def _test_unified_api(self, query: str, platform: str = "web") -> Dict[str, Any]:
        """統合API単体テスト"""
        try:
            start_time = time.time()
            
            response = requests.post(
                f"{self.base_url}/chat",
                json={"question": query, "username": "benchmark_user", "platform": platform},
                timeout=30
            )
            
            end_time = time.time()
            response_time = end_time - start_time
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "response_time": response_time,
                    "response_length": len(data.get("answer", "")),
                    "source": data.get("performance", {}).get("source", "unknown"),
                    "success": True
                }
            else:
                return {
                    "response_time": response_time,
                    "response_length": 0,
                    "source": "error",
                    "success": False
                }
                
        except Exception as e:
            return {
                "response_time": 30.0,
                "response_length": 0,
                "source": f"error_{type(e).__name__}",
                "success": False
            }
    
    def _analyze_results(self) -> Dict[str, Any]:
        """結果分析"""
        if not self.results:
            return {"error": "No results to analyze"}
        
        # 基本統計
        all_times = [r.response_time for r in self.results]
        success_rate = sum(1 for r in self.results if r.success) / len(self.results)
        
        # ソース別分析
        source_analysis = {}
        for result in self.results:
            source = result.source
            if source not in source_analysis:
                source_analysis[source] = []
            source_analysis[source].append(result.response_time)
        
        source_stats = {}
        for source, times in source_analysis.items():
            source_stats[source] = {
                "count": len(times),
                "avg_time": statistics.mean(times),
                "min_time": min(times),
                "max_time": max(times),
                "percentage": len(times) / len(self.results) * 100
            }
        
        # カテゴリ別分析
        category_analysis = {}
        for result in self.results:
            category = result.test_name
            if category not in category_analysis:
                category_analysis[category] = []
            category_analysis[category].append(result.response_time)
        
        category_stats = {}
        for category, times in category_analysis.items():
            category_stats[category] = {
                "count": len(times),
                "avg_time": statistics.mean(times),
                "p95_time": self._percentile(times, 95)
            }
        
        # パフォーマンス目標達成状況
        targets_achieved = self._check_performance_targets(source_stats)
        
        return {
            "overall_stats": {
                "total_tests": len(self.results),
                "avg_response_time": statistics.mean(all_times),
                "median_response_time": statistics.median(all_times),
                "p95_response_time": self._percentile(all_times, 95),
                "success_rate": success_rate,
                "min_response_time": min(all_times),
                "max_response_time": max(all_times)
            },
            "source_analysis": source_stats,
            "category_analysis": category_stats,
            "performance_targets": targets_achieved,
            "optimization_effectiveness": self._calculate_optimization_effectiveness(source_stats)
        }
    
    def _check_performance_targets(self, source_stats: Dict[str, Dict]) -> Dict[str, Any]:
        """パフォーマンス目標達成チェック"""
        targets = self.performance_targets
        achieved = {}
        
        # テンプレート応答時間
        if "template" in source_stats:
            template_avg = source_stats["template"]["avg_time"]
            achieved["template_response_time"] = {
                "target": targets["template_response_max"],
                "actual": template_avg,
                "achieved": template_avg <= targets["template_response_max"]
            }
        
        # RAG応答時間
        rag_sources = [s for s in source_stats.keys() if "rag" in s]
        if rag_sources:
            rag_times = []
            for source in rag_sources:
                rag_times.extend([source_stats[source]["avg_time"]])
            rag_avg = statistics.mean(rag_times)
            achieved["rag_response_time"] = {
                "target": targets["rag_response_max"],
                "actual": rag_avg,
                "achieved": rag_avg <= targets["rag_response_max"]
            }
        
        # キャッシュ応答時間
        if "cache" in source_stats:
            cache_avg = source_stats["cache"]["avg_time"]
            achieved["cache_response_time"] = {
                "target": targets["cache_response_max"],
                "actual": cache_avg,
                "achieved": cache_avg <= targets["cache_response_max"]
            }
        
        # テンプレートヒット率
        template_percentage = source_stats.get("template", {}).get("percentage", 0) / 100
        achieved["template_hit_rate"] = {
            "target": targets["template_hit_rate_min"],
            "actual": template_percentage,
            "achieved": template_percentage >= targets["template_hit_rate_min"]
        }
        
        # RAG使用率
        rag_percentage = sum(stats.get("percentage", 0) for source, stats in source_stats.items() if "rag" in source) / 100
        achieved["rag_usage_rate"] = {
            "target": targets["rag_usage_max"],
            "actual": rag_percentage,
            "achieved": rag_percentage <= targets["rag_usage_max"]
        }
        
        return achieved
    
    def _calculate_optimization_effectiveness(self, source_stats: Dict[str, Dict]) -> Dict[str, Any]:
        """最適化効果算出"""
        total_requests = sum(stats["count"] for stats in source_stats.values())
        
        # 高速応答率（1秒以下）
        fast_responses = sum(
            stats["count"] for stats in source_stats.values()
            if stats["avg_time"] <= 1.0
        )
        fast_response_rate = fast_responses / total_requests if total_requests > 0 else 0
        
        # 最適化適用率
        optimized_sources = ["template", "cache", "template_optimized", "instant_template"]
        optimized_responses = sum(
            stats["count"] for source, stats in source_stats.items()
            if any(opt in source for opt in optimized_sources)
        )
        optimization_rate = optimized_responses / total_requests if total_requests > 0 else 0
        
        return {
            "fast_response_rate": fast_response_rate,
            "optimization_applied_rate": optimization_rate,
            "avg_optimization_speed_gain": self._calculate_speed_gain(source_stats),
            "effectiveness_score": (fast_response_rate + optimization_rate) / 2
        }
    
    def _calculate_speed_gain(self, source_stats: Dict[str, Dict]) -> float:
        """速度向上率算出"""
        # テンプレート vs RAG の速度差を計算
        template_time = source_stats.get("template", {}).get("avg_time", 0)
        rag_time = max([
            stats.get("avg_time", 0) for source, stats in source_stats.items()
            if "rag" in source
        ], default=0)
        
        if template_time > 0 and rag_time > 0:
            speed_gain = ((rag_time - template_time) / rag_time) * 100
            return max(speed_gain, 0)
        
        return 0
    
    def _generate_recommendations(self, analysis: Dict[str, Any]) -> List[str]:
        """推奨事項生成"""
        recommendations = []
        
        if "overall_stats" not in analysis:
            return ["Cannot generate recommendations: insufficient data"]
        
        overall = analysis["overall_stats"]
        targets = analysis.get("performance_targets", {})
        
        # 全体的な応答時間
        if overall["avg_response_time"] > 2.0:
            recommendations.append("🚀 全体的な応答時間が目標を上回っています。RAG使用率をさらに削減してください")
        
        # テンプレート応答時間
        template_target = targets.get("template_response_time")
        if template_target and not template_target["achieved"]:
            recommendations.append("⚡ テンプレート応答が遅いです。キーワードマッチングアルゴリズムを最適化してください")
        
        # RAG使用率
        rag_target = targets.get("rag_usage_rate")
        if rag_target and not rag_target["achieved"]:
            recommendations.append("🚫 RAG使用率が高すぎます。テンプレートカバレッジを拡大してください")
        
        # 成功率
        if overall["success_rate"] < self.performance_targets["success_rate_min"]:
            recommendations.append("❌ 成功率が低いです。エラーハンドリングを強化してください")
        
        # P95応答時間
        if overall["p95_response_time"] > 5.0:
            recommendations.append("📊 P95応答時間が長いです。タイムアウト設定を見直してください")
        
        # 最適化効果
        effectiveness = analysis.get("optimization_effectiveness", {})
        if effectiveness.get("effectiveness_score", 0) < 0.8:
            recommendations.append("🔧 最適化効果が低いです。キャッシュ戦略とテンプレート戦略を見直してください")
        
        if not recommendations:
            recommendations.append("✅ システムは目標パフォーマンスを達成しています")
        
        return recommendations
    
    def _summarize_category_results(self, results: List[Dict]) -> Dict[str, Any]:
        """カテゴリ結果要約"""
        if not results:
            return {}
        
        times = [r["avg_time"] for r in results]
        success_rates = [r.get("success_rate", 1.0) for r in results]
        
        return {
            "total_categories": len(results),
            "avg_response_time": statistics.mean(times),
            "fastest_category": min(results, key=lambda x: x["avg_time"]),
            "slowest_category": max(results, key=lambda x: x["avg_time"]),
            "avg_success_rate": statistics.mean(success_rates)
        }
    
    def _percentile(self, values: List[float], percentile: int) -> float:
        """パーセンタイル計算"""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        index = int(len(sorted_values) * (percentile / 100))
        return sorted_values[min(index, len(sorted_values) - 1)]
    
    def export_results(self, filename: str = None) -> str:
        """結果エクスポート"""
        if filename is None:
            filename = f"benchmark_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        export_data = {
            "benchmark_info": {
                "timestamp": datetime.now().isoformat(),
                "total_tests": len(self.results),
                "test_duration": "completed"
            },
            "results": [r.to_dict() for r in self.results],
            "analysis": self._analyze_results()
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"📄 Results exported to {filename}")
        return filename
    
    def export_csv(self, filename: str = None) -> str:
        """CSV形式でエクスポート"""
        if filename is None:
            filename = f"benchmark_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'test_name', 'query', 'response_time', 'response_length', 
                'source', 'success', 'optimization_applied', 'platform', 'timestamp'
            ])
            
            for result in self.results:
                writer.writerow([
                    result.test_name, result.query, result.response_time,
                    result.response_length, result.source, result.success,
                    result.optimization_applied, result.platform, result.timestamp.isoformat()
                ])
        
        logger.info(f"📊 CSV exported to {filename}")
        return filename

# ==============================================================================
# 簡易ベンチマーク実行
# ==============================================================================

class QuickSpeedTest:
    """簡易速度テスト"""
    
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
    
    async def run_quick_test(self) -> Dict[str, Any]:
        """5分間クイックテスト"""
        logger.info("🏃‍♂️ Running 5-minute quick speed test...")
        
        # 高頻度質問のテスト
        quick_queries = [
            "坪単価",
            "標準仕様",
            "断熱性能",
            "AI相談",
            "資料請求"
        ]
        
        results = []
        
        for query in quick_queries:
            # 3回測定
            times = []
            for _ in range(3):
                try:
                    start_time = time.time()
                    response = requests.post(
                        f"{self.base_url}/chat",
                        json={"question": query, "platform": "web"},
                        timeout=10
                    )
                    end_time = time.time()
                    
                    if response.status_code == 200:
                        data = response.json()
                        times.append(end_time - start_time)
                        results.append({
                            "query": query,
                            "response_time": end_time - start_time,
                            "source": data.get("performance", {}).get("source", "unknown"),
                            "success": True
                        })
                    else:
                        results.append({
                            "query": query,
                            "response_time": end_time - start_time,
                            "source": "error",
                            "success": False
                        })
                        
                except Exception as e:
                    results.append({
                        "query": query,
                        "response_time": 10.0,
                        "source": f"error_{type(e).__name__}",
                        "success": False
                    })
            
            if times:
                avg_time = statistics.mean(times)
                logger.info(f"   {query}: {avg_time:.2f}s avg")
        
        # 簡易分析
        successful_results = [r for r in results if r["success"]]
        if successful_results:
            avg_response_time = statistics.mean([r["response_time"] for r in successful_results])
            success_rate = len(successful_results) / len(results)
            
            # ソース分析
            sources = [r["source"] for r in successful_results]
            source_counts = {source: sources.count(source) for source in set(sources)}
            
            return {
                "quick_test_results": {
                    "total_tests": len(results),
                    "successful_tests": len(successful_results),
                    "avg_response_time": avg_response_time,
                    "success_rate": success_rate,
                    "source_distribution": source_counts
                },
                "performance_grade": (
                    "A" if avg_response_time <= 1.0 and success_rate >= 0.95 else
                    "B" if avg_response_time <= 2.0 and success_rate >= 0.90 else
                    "C" if avg_response_time <= 3.0 and success_rate >= 0.80 else
                    "D"
                ),
                "optimization_status": (
                    "✅ Excellent" if avg_response_time <= 1.0 else
                    "⚡ Good" if avg_response_time <= 2.0 else
                    "⚠️ Needs Improvement" if avg_response_time <= 3.0 else
                    "❌ Poor"
                ),
                "recommendations": self._get_quick_recommendations(avg_response_time, success_rate, source_counts)
            }
        else:
            return {
                "error": "All tests failed",
                "results": results
            }
    
    def _get_quick_recommendations(self, avg_time: float, success_rate: float, sources: Dict[str, int]) -> List[str]:
        """クイック推奨事項"""
        recommendations = []
        
        if avg_time > 2.0:
            recommendations.append("Response time is too slow - consider increasing template coverage")
        
        if success_rate < 0.9:
            recommendations.append("Success rate is low - check error handling")
        
        template_usage = sources.get("template", 0) + sources.get("template_optimized", 0)
        rag_usage = sum(count for source, count in sources.items() if "rag" in source)
        
        if rag_usage > template_usage:
            recommendations.append("RAG usage is high - expand template patterns")
        
        if not recommendations:
            recommendations.append("System performing well")
        
        return recommendations

# ==============================================================================
# CLI実行
# ==============================================================================

async def main():
    """メインベンチマーク実行"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Speed Optimization Benchmark Suite")
    parser.add_argument("--url", default="http://localhost:8080", help="Base URL for API")
    parser.add_argument("--quick", action="store_true", help="Run quick 5-minute test")
    parser.add_argument("--iterations", type=int, default=3, help="Iterations per test")
    parser.add_argument("--concurrent", type=int, default=1, help="Concurrent requests")
    parser.add_argument("--export", default="json", choices=["json", "csv"], help="Export format")
    
    args = parser.parse_args()
    
    if args.quick:
        # クイックテスト
        quick_test = QuickSpeedTest(args.url)
        results = await quick_test.run_quick_test()
        
        print("\n🏃‍♂️ Quick Speed Test Results")
        print("=" * 50)
        
        if "error" not in results:
            quick_results = results["quick_test_results"]
            print(f"Total Tests: {quick_results['total_tests']}")
            print(f"Success Rate: {quick_results['success_rate']:.1%}")
            print(f"Average Response Time: {quick_results['avg_response_time']:.2f}s")
            print(f"Performance Grade: {results['performance_grade']}")
            print(f"Status: {results['optimization_status']}")
            
            print("\nRecommendations:")
            for rec in results['recommendations']:
                print(f"  • {rec}")
        else:
            print(f"❌ Test failed: {results['error']}")
    
    else:
        # 包括的ベンチマーク
        benchmark = SpeedOptimizationBenchmark(args.url)
        results = await benchmark.run_comprehensive_benchmark(args.iterations, args.concurrent)
        
        print("\n🚀 Comprehensive Benchmark Results")
        print("=" * 50)
        
        summary = results["benchmark_summary"]
        analysis = results["performance_analysis"]
        
        print(f"Total Time: {summary['total_time']:.1f}s")
        print(f"Total Tests: {summary['total_tests']}")
        
        if "overall_stats" in analysis:
            overall = analysis["overall_stats"]
            print(f"Average Response Time: {overall['avg_response_time']:.2f}s")
            print(f"Success Rate: {overall['success_rate']:.1%}")
            print(f"P95 Response Time: {overall['p95_response_time']:.2f}s")
        
        print("\nRecommendations:")
        for rec in results["recommendations"]:
            print(f"  • {rec}")
        
        # エクスポート
        if args.export == "json":
            filename = benchmark.export_results()
        else:
            filename = benchmark.export_csv()
        
        print(f"\n📄 Results exported to: {filename}")

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())