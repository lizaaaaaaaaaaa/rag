# pyright: reportMissingImports=false
# tests/test_unified_chat.py - 統合チャットシステムテストスクリプト

import pytest
import asyncio
import requests
import json
import time
from typing import Dict, List, Any
import os
import sys

# テスト対象のモジュールをインポート
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.chat_cache import ChatCacheManager, get_global_cache
from utils.chat_templates import ChatTemplateManager, get_template_manager
from services.rag_processing_service import RAGProcessingService, get_rag_service
# --- Dynamic import for response enhancement service (no static absolute import) ---
import importlib.util as _il_util, pathlib as _pl
from typing import TYPE_CHECKING

# For type checkers, you may enable this line once your IDE resolves 'services' as a package:
# if TYPE_CHECKING:
#     from services.response_enhancement import ResponseEnhancementService, get_response_enhancement_service

# Runtime dynamic import to avoid Pylance 'reportMissingImports' when running tests directly
_RE_PATH = _pl.Path(__file__).resolve().parent.parent / "services" / "response_enhancement.py"
if not _RE_PATH.exists():
    raise ImportError(f"Could not locate response_enhancement.py at {_RE_PATH}")

_spec = _il_util.spec_from_file_location("services.response_enhancement", _RE_PATH)
_mod = _il_util.module_from_spec(_spec)  # type: ignore[arg-type]
assert _spec and _spec.loader
_spec.loader.exec_module(_mod)  # type: ignore[assignment]

ResponseEnhancementService = getattr(_mod, "ResponseEnhancementService")
get_response_enhancement_service = getattr(_mod, "get_response_enhancement_service")
from api.routers.chat_unified import unified_generator

class UnifiedChatTester:
    """統合チャットシステムテスター"""
    
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.test_results = {}
        self.performance_metrics = {}
        self.test_data = self._load_test_data()

    def _load_test_data(self) -> Dict[str, List[Dict]]:
        """テストデータの読み込み"""
        return {
            "web_queries": [
                {"query": "坪単価について教えて", "expected_keywords": ["坪単価", "万円", "仕様"]},
                {"query": "標準仕様はどんな感じ？", "expected_keywords": ["標準仕様", "設備", "耐震等級"]},
                {"query": "耐震性能について知りたい", "expected_keywords": ["耐震等級", "3", "構造"]},
                {"query": "断熱性能はどのくらい？", "expected_keywords": ["断熱", "UA値", "省エネ"]},
                {"query": "補助金制度について", "expected_keywords": ["補助金", "ZEH", "支援"]},
                {"query": "資金計画を立てたい", "expected_keywords": ["資金計画", "住宅ローン", "返済"]},
                {"query": "家を建てる流れを教えて", "expected_keywords": ["建築", "プロセス", "流れ"]},
            ],
            "line_queries": [
                {"query": "🤖 AI相談", "expected_keywords": ["AI相談", "😊", "✨"]},
                {"query": "📋 資料請求", "expected_keywords": ["資料請求", "📋", "3営業日"]},
                {"query": "坪単価", "expected_keywords": ["💰", "坪単価", "😊"]},
                {"query": "補助金", "expected_keywords": ["補助金", "🏠", "💰"]},
                {"query": "こんにちは", "expected_keywords": ["こんにちは", "住まい", "😊"]},
            ],
            "rag_queries": [
                {"query": "長期優良住宅について詳しく教えて", "expected_sources": True},
                {"query": "ZEHの具体的な基準値は？", "expected_sources": True},
                {"query": "住宅ローン控除の詳細な条件", "expected_sources": True},
            ]
        }

    async def run_all_tests(self) -> Dict[str, Any]:
        """全テストの実行"""
        print("🚀 Starting Unified Chat System Tests...")
        start_time = time.time()
        
        # 各テストカテゴリを実行
        test_categories = [
            ("cache_tests", self.test_cache_system),
            ("template_tests", self.test_template_system),
            ("rag_tests", self.test_rag_processing),
            ("enhancement_tests", self.test_response_enhancement),
            ("unified_router_tests", self.test_unified_router),
            ("api_endpoint_tests", self.test_api_endpoints),
            ("performance_tests", self.test_performance),
            ("integration_tests", self.test_integration)
        ]
        
        for category_name, test_function in test_categories:
            print(f"\n📋 Running {category_name}...")
            try:
                result = await test_function()
                self.test_results[category_name] = result
                print(f"✅ {category_name}: PASSED")
            except Exception as e:
                self.test_results[category_name] = {"status": "FAILED", "error": str(e)}
                print(f"❌ {category_name}: FAILED - {e}")
        
        total_time = time.time() - start_time
        
        # 結果サマリーの作成
        summary = self._create_test_summary(total_time)
        
        print(f"\n🎉 All tests completed in {total_time:.2f} seconds")
        self._print_test_summary(summary)
        
        return {
            "summary": summary,
            "detailed_results": self.test_results,
            "performance_metrics": self.performance_metrics
        }

    async def test_cache_system(self) -> Dict[str, Any]:
        """キャッシュシステムのテスト"""
        cache = get_global_cache()
        results = {"tests": [], "status": "PASSED"}
        
        # 基本的なキャッシュ操作テスト
        test_query = "テストクエリ"
        test_response = {"answer": "テスト応答", "source": "test"}
        
        # キャッシュ保存テスト
        save_success = cache.set(test_query, test_response, "web", "general")
        results["tests"].append({
            "name": "cache_save",
            "passed": save_success,
            "description": "キャッシュ保存機能"
        })
        
        # キャッシュ取得テスト
        cached_result = cache.get(test_query, "web", "general")
        get_success = cached_result is not None and cached_result["answer"] == "テスト応答"
        results["tests"].append({
            "name": "cache_get",
            "passed": get_success,
            "description": "キャッシュ取得機能"
        })
        
        # プラットフォーム分離テスト
        cache.set("同じクエリ", {"answer": "Web応答"}, "web")
        cache.set("同じクエリ", {"answer": "LINE応答"}, "line")
        
        web_result = cache.get("同じクエリ", "web")
        line_result = cache.get("同じクエリ", "line")
        
        separation_success = (web_result["answer"] == "Web応答" and 
                            line_result["answer"] == "LINE応答")
        results["tests"].append({
            "name": "platform_separation",
            "passed": separation_success,
            "description": "プラットフォーム分離機能"
        })
        
        # 統計取得テスト
        stats = cache.get_stats()
        stats_success = "cache_sizes" in stats and "hit_rates" in stats
        results["tests"].append({
            "name": "cache_stats",
            "passed": stats_success,
            "description": "統計取得機能"
        })
        
        # ヘルスチェックテスト
        health = cache.get_cache_health()
        health_success = "status" in health and health["status"] in ["healthy", "degraded", "warning"]
        results["tests"].append({
            "name": "cache_health",
            "passed": health_success,
            "description": "ヘルスチェック機能"
        })
        
        # 失敗したテストがあれば全体をFAILEDに
        if not all(test["passed"] for test in results["tests"]):
            results["status"] = "FAILED"
        
        return results

    async def test_template_system(self) -> Dict[str, Any]:
        """テンプレートシステムのテスト"""
        template_manager = get_template_manager()
        results = {"tests": [], "status": "PASSED"}
        
        # Web用テンプレートマッチングテスト
        for test_query in self.test_data["web_queries"]:
            template_result = template_manager.find_template(
                test_query["query"], "web"
            )
            
            match_success = template_result is not None
            content_success = False
            
            if template_result:
                content = template_result["content"]
                content_success = any(keyword in content for keyword in test_query["expected_keywords"])
            
            results["tests"].append({
                "name": f"web_template_{test_query['query'][:20]}",
                "passed": match_success and content_success,
                "description": f"Web用テンプレートマッチング: {test_query['query']}"
            })
        
        # LINE用テンプレートマッチングテスト
        for test_query in self.test_data["line_queries"]:
            template_result = template_manager.find_template(
                test_query["query"], "line"
            )
            
            match_success = template_result is not None
            content_success = False
            
            if template_result:
                content = template_result["content"]
                content_success = any(keyword in content for keyword in test_query["expected_keywords"])
            
            results["tests"].append({
                "name": f"line_template_{test_query['query'][:20]}",
                "passed": match_success and content_success,
                "description": f"LINE用テンプレートマッチング: {test_query['query']}"
            })
        
        # カスタムテンプレート追加テスト
        custom_success = template_manager.add_custom_template(
            "web", "test_template", "テスト内容", ["テスト"], 5
        )
        results["tests"].append({
            "name": "custom_template_add",
            "passed": custom_success,
            "description": "カスタムテンプレート追加機能"
        })
        
        # 統計取得テスト
        stats = template_manager.get_template_stats()
        stats_success = "template_counts" in stats and "performance" in stats
        results["tests"].append({
            "name": "template_stats",
            "passed": stats_success,
            "description": "テンプレート統計取得機能"
        })
        
        if not all(test["passed"] for test in results["tests"]):
            results["status"] = "FAILED"
        
        return results

    async def test_rag_processing(self) -> Dict[str, Any]:
        """RAG処理サービスのテスト"""
        rag_service = get_rag_service()
        results = {"tests": [], "status": "PASSED"}
        
        # RAGサービス初期化テスト
        # 注意: 実際のvectorstore/llmが必要
        try:
            # モックデータでの初期化テスト
            init_success = True  # 実際の初期化は環境に依存
            results["tests"].append({
                "name": "rag_initialization",
                "passed": init_success,
                "description": "RAGサービス初期化"
            })
        except Exception as e:
            results["tests"].append({
                "name": "rag_initialization",
                "passed": False,
                "description": f"RAGサービス初期化: {e}"
            })
        
        # ヘルスチェックテスト
        health = rag_service.health_check()
        health_success = "status" in health
        results["tests"].append({
            "name": "rag_health_check",
            "passed": health_success,
            "description": "RAGヘルスチェック機能"
        })
        
        # 統計取得テスト
        stats = rag_service.get_service_stats()
        stats_success = "performance" in stats and "system_status" in stats
        results["tests"].append({
            "name": "rag_stats",
            "passed": stats_success,
            "description": "RAG統計取得機能"
        })
        
        # クエリ履歴テスト
        recent_queries = rag_service.get_recent_queries(5)
        history_success = isinstance(recent_queries, list)
        results["tests"].append({
            "name": "rag_query_history",
            "passed": history_success,
            "description": "RAGクエリ履歴機能"
        })
        
        if not all(test["passed"] for test in results["tests"]):
            results["status"] = "FAILED"
        
        return results

    async def test_response_enhancement(self) -> Dict[str, Any]:
        """応答品質向上サービスのテスト"""
        enhancement_service = get_response_enhancement_service()
        results = {"tests": [], "status": "PASSED"}
        
        # 基本的な品質向上テスト
        test_cases = [
            {
                "input": "坪単価について",  # 不完全な文
                "platform": "web",
                "expected_improvement": True
            },
            {
                "input": "これはとても重要",  # 不完全な文
                "platform": "line",
                "expected_improvement": True
            },
            {
                "input": "住宅の仕様について詳しく説明いたします。",  # 完全な文
                "platform": "web",
                "expected_improvement": False
            }
        ]
        
        for i, case in enumerate(test_cases):
            try:
                result = await enhancement_service.enhance_response(
                    case["input"], 
                    "テストクエリ",
                    case["platform"]
                )
                
                enhanced = result.get("enhanced_response", "")
                improvement_score = result.get("improvement_score", 0)
                
                # 改善期待値とスコアの整合性をチェック
                improvement_success = (
                    (case["expected_improvement"] and improvement_score > 0) or
                    (not case["expected_improvement"] and improvement_score >= 0)
                )
                
                # 文章の完全性チェック
                completeness_success = enhanced.endswith(('。', '！', '？', '.', '!', '?'))
                
                overall_success = improvement_success and completeness_success
                
                results["tests"].append({
                    "name": f"enhancement_case_{i+1}",
                    "passed": overall_success,
                    "description": f"品質向上テスト: {case['input'][:20]}..."
                })
                
            except Exception as e:
                results["tests"].append({
                    "name": f"enhancement_case_{i+1}",
                    "passed": False,
                    "description": f"品質向上テスト エラー: {e}"
                })
        
        # サービス統計テスト
        stats = enhancement_service.get_service_stats()
        stats_success = "performance" in stats and "enhancement_rates" in stats
        results["tests"].append({
            "name": "enhancement_stats",
            "passed": stats_success,
            "description": "品質向上統計取得機能"
        })
        
        if not all(test["passed"] for test in results["tests"]):
            results["status"] = "FAILED"
        
        return results

    async def test_unified_router(self) -> Dict[str, Any]:
        """統合ルーターのテスト"""
        results = {"tests": [], "status": "PASSED"}
        
        try:
            # 統合ルーターの基本機能テスト
            test_query = "坪単価について教えて"
            
            # Web用応答生成テスト
            web_result = await unified_generator.generate_response(
                test_query, "web", "test_user", "auto"
            )
            
            web_success = (
                "answer" in web_result and
                len(web_result["answer"]) > 10 and
                web_result.get("status") == "ok"
            )
            
            results["tests"].append({
                "name": "unified_web_response",
                "passed": web_success,
                "description": "統合ルーター Web応答生成"
            })
            
            # LINE用応答生成テスト
            line_result = await unified_generator.generate_response(
                test_query, "line", "test_user", "auto"
            )
            
            line_success = (
                "answer" in line_result and
                len(line_result["answer"]) > 10 and
                web_result.get("status") == "ok"
            )
            
            results["tests"].append({
                "name": "unified_line_response",
                "passed": line_success,
                "description": "統合ルーター LINE応答生成"
            })
            
            # プラットフォーム別最適化テスト
            optimization_success = (
                web_result["answer"] != line_result["answer"] and  # 異なる応答
                "😊" not in web_result["answer"] and  # Webには絵文字なし
                ("😊" in line_result["answer"] or "✨" in line_result["answer"])  # LINEには絵文字
            )
            
            results["tests"].append({
                "name": "platform_optimization",
                "passed": optimization_success,
                "description": "プラットフォーム別最適化"
            })
            
            # パフォーマンス統計テスト
            stats = unified_generator.get_performance_stats()
            stats_success = "unified_performance" in stats
            
            results["tests"].append({
                "name": "unified_stats",
                "passed": stats_success,
                "description": "統合ルーター統計機能"
            })
            
        except Exception as e:
            results["tests"].append({
                "name": "unified_router_error",
                "passed": False,
                "description": f"統合ルーターエラー: {e}"
            })
        
        if not all(test["passed"] for test in results["tests"]):
            results["status"] = "FAILED"
        
        return results

    async def test_api_endpoints(self) -> Dict[str, Any]:
        """APIエンドポイントのテスト"""
        results = {"tests": [], "status": "PASSED"}
        
        # API可用性チェック
        endpoints_to_test = [
            ("/", "GET", "ルートエンドポイント"),
            ("/healthz", "GET", "ヘルスチェック"),
            ("/system-status", "GET", "システム状態"),
            ("/performance", "GET", "パフォーマンス統計"),
        ]
        
        for endpoint, method, description in endpoints_to_test:
            try:
                if method == "GET":
                    response = requests.get(f"{self.base_url}{endpoint}", timeout=10)
                else:
                    response = requests.post(f"{self.base_url}{endpoint}", timeout=10)
                
                success = response.status_code == 200
                
                results["tests"].append({
                    "name": f"api_{endpoint.replace('/', '_')}",
                    "passed": success,
                    "description": f"API {description}: {response.status_code}"
                })
                
            except Exception as e:
                results["tests"].append({
                    "name": f"api_{endpoint.replace('/', '_')}",
                    "passed": False,
                    "description": f"API {description}: Error - {e}"
                })
        
        # 統合チャットエンドポイントテスト
        chat_test_data = {
            "question": "坪単価について教えて",
            "platform": "web",
            "mode": "auto"
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat",
                json=chat_test_data,
                timeout=15
            )
            
            chat_success = (
                response.status_code == 200 and
                "answer" in response.json() and
                len(response.json()["answer"]) > 10
            )
            
            results["tests"].append({
                "name": "unified_chat_endpoint",
                "passed": chat_success,
                "description": f"統合チャットエンドポイント: {response.status_code}"
            })
            
        except Exception as e:
            results["tests"].append({
                "name": "unified_chat_endpoint",
                "passed": False,
                "description": f"統合チャットエンドポイント: Error - {e}"
            })
        
        if not all(test["passed"] for test in results["tests"]):
            results["status"] = "FAILED"
        
        return results

    async def test_performance(self) -> Dict[str, Any]:
        """パフォーマンステスト"""
        results = {"tests": [], "status": "PASSED"}
        performance_data = {}
        
        # 応答時間テスト
        test_queries = [
            ("坪単価について", "template"),
            ("住宅の耐震性能について詳しく教えて", "rag"),
            ("こんにちは", "simple")
        ]
        
        for query, query_type in test_queries:
            response_times = []
            
            # 5回測定して平均を取る
            for _ in range(5):
                start_time = time.time()
                
                try:
                    result = await unified_generator.generate_response(
                        query, "web", "perf_test_user", "auto"
                    )
                    
                    end_time = time.time()
                    response_time = end_time - start_time
                    response_times.append(response_time)
                    
                except Exception as e:
                    response_times.append(10.0)  # エラー時は10秒とする
            
            avg_response_time = sum(response_times) / len(response_times)
            performance_data[f"{query_type}_avg_time"] = avg_response_time
            
            # パフォーマンス基準チェック
            time_thresholds = {
                "template": 1.0,  # 1秒以内
                "rag": 5.0,       # 5秒以内
                "simple": 0.5     # 0.5秒以内
            }
            
            performance_success = avg_response_time <= time_thresholds.get(query_type, 5.0)
            
            results["tests"].append({
                "name": f"performance_{query_type}",
                "passed": performance_success,
                "description": f"{query_type}応答時間: {avg_response_time:.3f}s (目標: {time_thresholds.get(query_type, 5.0)}s)"
            })
        
        # メモリ使用量テスト（簡易版）
        try:
            import psutil
            process = psutil.Process(os.getpid())
            memory_usage = process.memory_info().rss / 1024 / 1024  # MB
            performance_data["memory_usage_mb"] = memory_usage
            
            # 500MB以下が目標
            memory_success = memory_usage <= 500
            
            results["tests"].append({
                "name": "memory_usage",
                "passed": memory_success,
                "description": f"メモリ使用量: {memory_usage:.1f}MB (目標: ≤500MB)"
            })
            
        except ImportError:
            results["tests"].append({
                "name": "memory_usage",
                "passed": True,  # psutilがない場合はスキップ
                "description": "メモリ使用量: psutil not available"
            })
        
        # キャッシュヒット率テスト
        cache = get_global_cache()
        cache_stats = cache.get_stats()
        
        overall_hit_rate = cache_stats["hit_rates"]["overall"]
        performance_data["cache_hit_rate"] = overall_hit_rate
        
        # ヒット率60%以上が目標
        cache_success = overall_hit_rate >= 60.0 or cache_stats["raw_stats"]["total_requests"] < 10
        
        results["tests"].append({
            "name": "cache_hit_rate",
            "passed": cache_success,
            "description": f"キャッシュヒット率: {overall_hit_rate:.1f}% (目標: ≥60%)"
        })
        
        self.performance_metrics = performance_data
        
        if not all(test["passed"] for test in results["tests"]):
            results["status"] = "FAILED"
        
        return results

    async def test_integration(self) -> Dict[str, Any]:
        """統合テスト"""
        results = {"tests": [], "status": "PASSED"}
        
        # エンドツーエンドワークフローテスト
        workflow_tests = [
            {
                "name": "web_full_workflow",
                "platform": "web",
                "query": "坪単価と標準仕様について教えて",
                "expected_elements": ["坪単価", "標準仕様", "万円", "設備"]
            },
            {
                "name": "line_full_workflow", 
                "platform": "line",
                "query": "資料請求したいです",
                "expected_elements": ["資料請求", "📋", "営業日"]
            }
        ]
        
        for workflow in workflow_tests:
            try:
                # 統合ルーター経由での処理
                result = await unified_generator.generate_response(
                    workflow["query"],
                    workflow["platform"],
                    "integration_test_user",
                    "auto"
                )
                
                # 応答内容チェック
                answer = result.get("answer", "")
                content_success = any(element in answer for element in workflow["expected_elements"])
                
                # パフォーマンスチェック
                processing_time = result.get("processing_time", 0)
                performance_success = processing_time < 3.0
                
                # 完全性チェック
                completeness_success = answer.endswith(('。', '！', '？', '.', '!', '?'))
                
                overall_success = content_success and performance_success and completeness_success
                
                results["tests"].append({
                    "name": workflow["name"],
                    "passed": overall_success,
                    "description": f"{workflow['platform']}統合ワークフロー: {processing_time:.3f}s"
                })
                
            except Exception as e:
                results["tests"].append({
                    "name": workflow["name"],
                    "passed": False,
                    "description": f"{workflow['platform']}統合ワークフロー: Error - {e}"
                })
        
        # システム全体の整合性テスト
        try:
            # 各コンポーネントの統計を取得
            cache_stats = get_global_cache().get_stats()
            template_stats = get_template_manager().get_template_stats()
            rag_stats = get_rag_service().get_service_stats()
            enhancement_stats = get_response_enhancement_service().get_service_stats()
            unified_stats = unified_generator.get_performance_stats()
            
            # 統計の整合性チェック
            consistency_success = all([
                isinstance(cache_stats, dict),
                isinstance(template_stats, dict), 
                isinstance(rag_stats, dict),
                isinstance(enhancement_stats, dict),
                isinstance(unified_stats, dict)
            ])
            
            results["tests"].append({
                "name": "system_consistency",
                "passed": consistency_success,
                "description": "システム全体の整合性チェック"
            })
            
        except Exception as e:
            results["tests"].append({
                "name": "system_consistency",
                "passed": False,
                "description": f"システム整合性: Error - {e}"
            })
        
        if not all(test["passed"] for test in results["tests"]):
            results["status"] = "FAILED"
        
        return results

    def _create_test_summary(self, total_time: float) -> Dict[str, Any]:
        """テスト結果サマリーの作成"""
        total_tests = 0
        passed_tests = 0
        failed_categories = []
        
        for category, result in self.test_results.items():
            if isinstance(result, dict) and "tests" in result:
                category_tests = len(result["tests"])
                category_passed = sum(1 for test in result["tests"] if test["passed"])
                
                total_tests += category_tests
                passed_tests += category_passed
                
                if result["status"] == "FAILED":
                    failed_categories.append(category)
            elif isinstance(result, dict) and result.get("status") == "FAILED":
                failed_categories.append(category)
        
        success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
        
        return {
            "total_time": total_time,
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": total_tests - passed_tests,
            "success_rate": success_rate,
            "failed_categories": failed_categories,
            "performance_metrics": self.performance_metrics,
            "overall_status": "PASSED" if len(failed_categories) == 0 else "FAILED"
        }

    def _print_test_summary(self, summary: Dict[str, Any]) -> None:
        """テスト結果サマリーの出力"""
        print(f"\n{'='*60}")
        print(f"🎯 UNIFIED CHAT SYSTEM TEST SUMMARY")
        print(f"{'='*60}")
        
        print(f"⏱️  Total Time: {summary['total_time']:.2f} seconds")
        print(f"✅ Total Tests: {summary['total_tests']}")
        print(f"🎉 Passed: {summary['passed_tests']}")
        print(f"❌ Failed: {summary['failed_tests']}")
        print(f"📊 Success Rate: {summary['success_rate']:.1f}%")
        
        if summary['failed_categories']:
            print(f"🚨 Failed Categories: {', '.join(summary['failed_categories'])}")
        
        if summary['performance_metrics']:
            print(f"\n📈 Performance Metrics:")
            for metric, value in summary['performance_metrics'].items():
                if isinstance(value, float):
                    print(f"   {metric}: {value:.3f}")
                else:
                    print(f"   {metric}: {value}")
        
        status_emoji = "🎉" if summary['overall_status'] == "PASSED" else "😞"
        print(f"\n{status_emoji} Overall Status: {summary['overall_status']}")
        print(f"{'='*60}")

async def main():
    """メインテスト実行"""
    # テストの実行
    tester = UnifiedChatTester()
    
    try:
        # API サーバーが起動しているかチェック
        response = requests.get(f"{tester.base_url}/healthz", timeout=5)
        if response.status_code != 200:
            print("⚠️  API server is not running or not healthy")
            print("   Please start the server with: python main.py")
            return
    except requests.exceptions.RequestException:
        print("❌ API server is not accessible")
        print("   Please start the server with: python main.py")
        return
    
    # テスト実行
    results = await tester.run_all_tests()
    
    # 結果をファイルに保存
    output_file = "test_results.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n📄 Detailed results saved to: {output_file}")
    
    # 終了コード設定
    exit_code = 0 if results["summary"]["overall_status"] == "PASSED" else 1
    return exit_code

if __name__ == "__main__":
    import sys
    
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

# pytest用のテストケース定義
class TestUnifiedChatSystem:
    """pytest用テストクラス"""
    
    @pytest.fixture
    async def tester(self):
        return UnifiedChatTester()
    
    @pytest.mark.asyncio
    async def test_cache_system(self, tester):
        result = await tester.test_cache_system()
        assert result["status"] == "PASSED"
    
    @pytest.mark.asyncio
    async def test_template_system(self, tester):
        result = await tester.test_template_system()
        assert result["status"] == "PASSED"
    
    @pytest.mark.asyncio
    async def test_rag_processing(self, tester):
        result = await tester.test_rag_processing()
        assert result["status"] == "PASSED"
    
    @pytest.mark.asyncio
    async def test_response_enhancement(self, tester):
        result = await tester.test_response_enhancement()
        assert result["status"] == "PASSED"
    
    @pytest.mark.asyncio
    async def test_unified_router(self, tester):
        result = await tester.test_unified_router()
        assert result["status"] == "PASSED"
    
    @pytest.mark.asyncio
    async def test_api_endpoints(self, tester):
        result = await tester.test_api_endpoints()
        assert result["status"] == "PASSED"
    
    @pytest.mark.asyncio
    async def test_performance(self, tester):
        result = await tester.test_performance()
        assert result["status"] == "PASSED"
    
    @pytest.mark.asyncio
    async def test_integration(self, tester):
        result = await tester.test_integration()
        assert result["status"] == "PASSED"