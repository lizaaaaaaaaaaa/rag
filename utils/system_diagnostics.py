# utils/system_diagnostics.py - 包括的システム診断ユーティリティ（完全修正版）
# 改訂点:
# - Pylance reportMissingImports 対応: utils.chat_cache / utils.chat_templates の静的インポートを全撤去
# - importlib による動的ロード + フォールバックで安全に継続
# - 既存の公開API/戻り値は互換維持

import os
import sys
import time
import logging
import traceback
import asyncio
import psutil
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import json
import hashlib
from dataclasses import dataclass, asdict
import importlib  # ← 追加: 動的インポートでPylance警告を回避

logger = logging.getLogger(__name__)

# ------------------------
# 動的インポート・ヘルパー
# ------------------------
def _try_import(module_name: str):
    """存在すればモジュールを返し、無ければ None。"""
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None

def _get_template_manager():
    """
    utils.chat_templates.get_template_manager を動的取得。
    戻り値: callable | None
    """
    m = _try_import("utils.chat_templates")
    if m is None:
        return None
    return getattr(m, "get_template_manager", None)

def _get_chat_cache_funcs():
    """
    utils.chat_cache の代表関数をまとめて動的取得。
    戻り値: dict(str -> callable|None)
    """
    m = _try_import("utils.chat_cache")
    if m is None:
        return {
            "get_global_cache": None,
            "quick_cache_get": None,
            "quick_cache_set": None,
        }
    return {
        "get_global_cache": getattr(m, "get_global_cache", None),
        "quick_cache_get": getattr(m, "quick_cache_get", None),
        "quick_cache_set": getattr(m, "quick_cache_set", None),
    }

@dataclass
class ComponentStatus:
    """コンポーネント状態クラス"""
    name: str
    status: str  # "healthy", "degraded", "failed", "unknown"
    last_check: datetime
    response_time: float
    error_count: int
    details: Dict[str, Any]
    recommendations: List[str]

@dataclass
class SystemHealth:
    """システム健全性クラス"""
    overall_status: str
    uptime: float
    components: Dict[str, ComponentStatus]
    performance_metrics: Dict[str, float]
    resource_usage: Dict[str, float]
    alerts: List[str]
    timestamp: datetime

class SystemDiagnostics:
    """包括的システム診断クラス"""
    
    def __init__(self):
        self.check_history: List[SystemHealth] = []
        self.max_history = 100
        self.startup_time = time.time()
        self.last_full_check = None
        self.component_checkers = self._initialize_component_checkers()
        
        # アラート閾値
        self.thresholds = {
            "cpu_usage": 80.0,
            "memory_usage": 85.0,
            "response_time": 5.0,
            "error_rate": 0.05,
            "disk_usage": 90.0
        }

    def _initialize_component_checkers(self) -> Dict[str, callable]:
        """コンポーネントチェッカー初期化"""
        return {
            "rag_system": self._check_rag_system,
            "vectorstore": self._check_vectorstore,
            "llm_instance": self._check_llm_instance,
            "cache_system": self._check_cache_system,
            "line_bot": self._check_line_bot,
            "web_chat": self._check_web_chat,
            "file_system": self._check_file_system,
            "dependencies": self._check_dependencies,
            "performance": self._check_performance,
            "security": self._check_security
        }

    async def run_comprehensive_check(self) -> SystemHealth:
        """包括的システムチェック実行"""
        start_time = time.time()
        logger.info("🔍 Starting comprehensive system diagnostics...")
        
        components = {}
        alerts = []
        overall_issues = 0
        
        # 各コンポーネントのチェック
        for component_name, checker_func in self.component_checkers.items():
            try:
                logger.info(f"   Checking {component_name}...")
                component_status = await self._run_component_check(component_name, checker_func)
                components[component_name] = component_status
                
                if component_status.status in ["degraded", "failed"]:
                    overall_issues += 1
                    alerts.extend([f"{component_name}: {rec}" for rec in component_status.recommendations])
                    
            except Exception as e:
                logger.error(f"❌ Component check failed for {component_name}: {e}")
                components[component_name] = ComponentStatus(
                    name=component_name,
                    status="failed",
                    last_check=datetime.now(),
                    response_time=0.0,
                    error_count=1,
                    details={"error": str(e)},
                    recommendations=[f"Check {component_name} configuration and dependencies"]
                )
                overall_issues += 1

        # システム全体の状態判定
        if overall_issues == 0:
            overall_status = "healthy"
        elif overall_issues <= 2:
            overall_status = "degraded"
        else:
            overall_status = "critical"

        # パフォーマンスメトリクス取得
        performance_metrics = await self._collect_performance_metrics()
        resource_usage = self._get_resource_usage()

        # システムヘルス作成
        system_health = SystemHealth(
            overall_status=overall_status,
            uptime=time.time() - self.startup_time,
            components=components,
            performance_metrics=performance_metrics,
            resource_usage=resource_usage,
            alerts=alerts,
            timestamp=datetime.now()
        )

        # 履歴に追加
        self._add_to_history(system_health)
        self.last_full_check = datetime.now()
        
        check_duration = time.time() - start_time
        logger.info(f"✅ System diagnostics completed in {check_duration:.2f}s")
        logger.info(f"   Overall Status: {overall_status.upper()}")
        logger.info(f"   Issues Found: {overall_issues}")
        logger.info(f"   Alerts Generated: {len(alerts)}")

        return system_health

    async def _run_component_check(self, name: str, checker_func: callable) -> ComponentStatus:
        """個別コンポーネントチェック実行"""
        start_time = time.time()
        
        try:
            if asyncio.iscoroutinefunction(checker_func):
                result = await checker_func()
            else:
                result = checker_func()
                
            response_time = time.time() - start_time
            
            # 結果の正規化
            if isinstance(result, dict):
                status = result.get("status", "unknown")
                details = result.get("details", {})
                recommendations = result.get("recommendations", [])
                error_count = result.get("error_count", 0)
            else:
                status = "healthy" if result else "failed"
                details = {}
                recommendations = []
                error_count = 0 if result else 1

            return ComponentStatus(
                name=name,
                status=status,
                last_check=datetime.now(),
                response_time=response_time,
                error_count=error_count,
                details=details,
                recommendations=recommendations
            )
            
        except Exception as e:
            return ComponentStatus(
                name=name,
                status="failed",
                last_check=datetime.now(),
                response_time=time.time() - start_time,
                error_count=1,
                details={"error": str(e), "traceback": traceback.format_exc() },
                recommendations=[f"Fix {name} component error: {str(e)[:100]}"]
            )

    # ==========================================================================
    # 個別コンポーネントチェッカー
    # ==========================================================================
    
    async def _check_rag_system(self) -> Dict[str, Any]:
        """RAGシステムチェック"""
        details = {}
        recommendations = []
        error_count = 0
        
        try:
            # main.pyからRAG状態取得
            from main import get_shared_rag_components
            rag_components = get_shared_rag_components()
            
            vectorstore = rag_components.get("vectorstore")
            rag_chain = rag_components.get("rag_chain_template")
            llm_instance = rag_components.get("llm_instance")
            is_initialized = rag_components.get("is_initialized", False)
            
            details.update({
                "initialized": is_initialized,
                "vectorstore_available": vectorstore is not None,
                "rag_chain_available": rag_chain is not None,
                "llm_available": llm_instance is not None,
                "shared_globally": rag_components.get("shared_globally", False)
            })
            
            # RAGクイックテスト
            if rag_chain:
                try:
                    test_result = rag_chain.invoke({"query": "システム診断テスト"})
                    if test_result and test_result.get("result"):
                        details["quick_test"] = "passed"
                    else:
                        details["quick_test"] = "empty_result"
                        error_count += 1
                        recommendations.append("RAG chain returns empty results")
                except Exception as test_error:
                    details["quick_test"] = f"failed: {str(test_error)}"
                    error_count += 1
                    recommendations.append("RAG quick test failed")
            
            # 診断情報の取得
            if hasattr(rag_components, 'diagnostics'):
                details["diagnostics"] = rag_components['diagnostics']
            
            # 状態判定
            if is_initialized and vectorstore and rag_chain and llm_instance:
                status = "healthy" if error_count == 0 else "degraded"
            else:
                status = "failed"
                recommendations.append("RAG system not fully initialized")
                error_count += 1
                
        except ImportError:
            status = "failed"
            details["error"] = "Cannot import RAG components"
            recommendations.append("Check main.py and RAG module imports")
            error_count += 1
        except Exception as e:
            status = "failed"
            details["error"] = str(e)
            recommendations.append("RAG system check failed - see details")
            error_count += 1
        
        return {
            "status": status,
            "details": details,
            "recommendations": recommendations,
            "error_count": error_count
        }

    def _check_vectorstore(self) -> Dict[str, Any]:
        """ベクトルストアチェック"""
        details = {}
        recommendations = []
        error_count = 0
        
        try:
            # ベクトルストアファイル確認
            vector_paths = [
                "rag/vectorstore/index.faiss",
                "rag/vectorstore/index.pkl"
            ]
            
            for path in vector_paths:
                if os.path.exists(path):
                    file_size = os.path.getsize(path)
                    details[f"{os.path.basename(path)}_exists"] = True
                    details[f"{os.path.basename(path)}_size"] = file_size
                    if file_size < 1000:  # 1KB未満は異常
                        recommendations.append(f"{path} file is too small ({file_size} bytes)")
                        error_count += 1
                else:
                    details[f"{os.path.basename(path)}_exists"] = False
                    recommendations.append(f"Missing vectorstore file: {path}")
                    error_count += 1

            # ディレクトリ権限確認
            vector_dir = "rag/vectorstore"
            if os.path.exists(vector_dir):
                details["directory_readable"] = os.access(vector_dir, os.R_OK)
                details["directory_writable"] = os.access(vector_dir, os.W_OK)
                if not details["directory_readable"]:
                    recommendations.append("Vectorstore directory not readable")
                    error_count += 1
            else:
                details["directory_exists"] = False
                recommendations.append("Vectorstore directory does not exist")
                error_count += 1

            # 高速RAGキャッシュ確認
            try:
                from rag.fast_rag_chain import get_super_fast_cache_stats
                cache_stats = get_super_fast_cache_stats()
                details["cache_stats"] = cache_stats
                if cache_stats["cache_performance"]["hit_rate"] < 50:
                    recommendations.append("Low cache hit rate - consider cache optimization")
            except ImportError:
                details["fast_rag_available"] = False
                recommendations.append("Fast RAG chain module not available")

            # 状態判定
            if error_count == 0:
                status = "healthy"
            elif error_count <= 1:
                status = "degraded"
            else:
                status = "failed"
                
        except Exception as e:
            status = "failed"
            details["error"] = str(e)
            recommendations.append("Vectorstore check failed")
            error_count += 1
        
        return {
            "status": status,
            "details": details,
            "recommendations": recommendations,
            "error_count": error_count
        }

    def _check_llm_instance(self) -> Dict[str, Any]:
        """LLMインスタンスチェック"""
        details = {}
        recommendations = []
        error_count = 0
        
        try:
            # LLM設定ファイル確認
            llm_configs = [
                "llm/llm_runner.py",
                "config/llm_config.py"  # 想定
            ]
            for config_path in llm_configs:
                details[f"{os.path.basename(config_path)}_exists"] = os.path.exists(config_path)

            # 環境変数チェック
            llm_env_vars = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"]
            available_keys = []
            for env_var in llm_env_vars:
                if os.getenv(env_var):
                    available_keys.append(env_var)
                    details[f"{env_var.lower()}_available"] = True
                else:
                    details[f"{env_var.lower()}_available"] = False
            if not available_keys:
                recommendations.append("No LLM API keys found in environment variables")
                error_count += 1
            else:
                details["available_api_keys"] = len(available_keys)

            # LLMインスタンステスト
            try:
                from llm.llm_runner import load_llm
                llm_result = load_llm()
                if isinstance(llm_result, tuple) and len(llm_result) >= 1:
                    llm_instance = llm_result[0]
                    details["llm_loaded"] = True
                    details["llm_type"] = type(llm_instance).__name__
                    try:
                        test_response = llm_instance.invoke("Hello")
                        details["llm_test"] = "passed" if test_response else "empty_response"
                        if not test_response:
                            error_count += 1
                            recommendations.append("LLM returns empty responses")
                    except Exception as test_error:
                        details["llm_test"] = f"failed: {str(test_error)}"
                        error_count += 1
                        recommendations.append("LLM test invocation failed")
                else:
                    details["llm_loaded"] = False
                    error_count += 1
                    recommendations.append("LLM loading returned unexpected format")
            except Exception as load_error:
                details["llm_load_error"] = str(load_error)
                error_count += 1
                recommendations.append("Failed to load LLM instance")

            # 状態判定
            if error_count == 0:
                status = "healthy"
            elif error_count <= 1:
                status = "degraded"
            else:
                status = "failed"
                
        except Exception as e:
            status = "failed"
            details["error"] = str(e)
            recommendations.append("LLM instance check failed")
            error_count += 1
        
        return {
            "status": status,
            "details": details,
            "recommendations": recommendations,
            "error_count": error_count
        }

    def _check_cache_system(self) -> Dict[str, Any]:
        """キャッシュシステムチェック（動的ロード版）"""
        details = {}
        recommendations = []
        error_count = 0
        
        try:
            # 統合キャッシュチェック
            try:
                from api.routers.chat_unified import optimized_generator
                unified_stats = optimized_generator.get_performance_stats()
                details["unified_cache"] = {
                    "available": True,
                    "hit_rate": unified_stats["optimization_performance"]["cache_hit_rate"],
                    "total_requests": unified_stats["optimization_performance"]["total_requests"]
                }
                if unified_stats["optimization_performance"]["cache_hit_rate"] < 30:
                    recommendations.append("Low unified cache hit rate")
                    error_count += 1
            except ImportError:
                details["unified_cache"] = {"available": False}
                recommendations.append("Unified cache system not available")

            # LINE キャッシュチェック
            try:
                from api.routers.line_bot_ultra_fast import smart_router
                line_stats = smart_router.get_stats()
                details["line_cache"] = {
                    "available": True,
                    "rich_menu_hit_rate": line_stats["optimization_metrics"]["rich_menu_hit_rate"],
                    "instant_responses": line_stats["response_distribution"]["instant_responses"]
                }
                if line_stats["optimization_metrics"]["rich_menu_hit_rate"] < 80:
                    recommendations.append("Low LINE rich menu cache hit rate")
            except ImportError:
                details["line_cache"] = {"available": False}

            # グローバルキャッシュ（動的ロード）
            cache_funcs = _get_chat_cache_funcs()
            get_global_cache = cache_funcs["get_global_cache"]
            if callable(get_global_cache):
                try:
                    global_cache = get_global_cache()
                    cache_health = global_cache.get_cache_health()
                    details["global_cache"] = {
                        "status": cache_health.get("status", "unknown"),
                        "issues": cache_health.get("issues", [])
                    }
                    if cache_health.get("status") != "healthy":
                        recs = cache_health.get("recommendations", [])
                        if recs:
                            recommendations.extend(recs)
                        error_count += 1
                except Exception as e:
                    details["global_cache"] = {"available": False, "error": str(e)}
                    error_count += 1
            else:
                details["global_cache"] = {"available": False}

            # 状態判定
            if error_count == 0:
                status = "healthy"
            elif error_count <= 1:
                status = "degraded"
            else:
                status = "failed"
                
        except Exception as e:
            status = "failed"
            details["error"] = str(e)
            recommendations.append("Cache system check failed")
            error_count += 1
        
        return {
            "status": status,
            "details": details,
            "recommendations": recommendations,
            "error_count": error_count
        }

    def _check_line_bot(self) -> Dict[str, Any]:
        """LINE Botチェック"""
        details = {}
        recommendations = []
        error_count = 0
        
        try:
            # 環境変数チェック
            line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
            line_secret = os.getenv("LINE_CHANNEL_SECRET")
            details["access_token_available"] = bool(line_token)
            details["channel_secret_available"] = bool(line_secret)
            if not line_token:
                recommendations.append("LINE_CHANNEL_ACCESS_TOKEN not set")
                error_count += 1
            if not line_secret:
                recommendations.append("LINE_CHANNEL_SECRET not set")
                error_count += 1

            # LINE SDK確認
            try:
                from linebot.v3 import WebhookHandler, MessagingApi
                details["line_sdk_available"] = True
            except ImportError:
                details["line_sdk_available"] = False
                recommendations.append("LINE SDK not available")
                error_count += 1

            # LINE Bot統計
            try:
                from api.routers.line_bot_ultra_fast import smart_router, duplicate_prevention
                router_stats = smart_router.get_stats()
                dup_stats = duplicate_prevention.get_stats()
                details["line_stats"] = {
                    "total_requests": router_stats["total_requests"],
                    "instant_response_rate": router_stats["optimization_metrics"]["instant_response_rate"],
                    "rag_avoidance_rate": router_stats["optimization_metrics"]["rag_avoidance_rate"],
                    "duplicate_prevention": dup_stats["prevention_stats"]
                }
                if router_stats["optimization_metrics"]["instant_response_rate"] < 80:
                    recommendations.append("Low LINE instant response rate")
            except ImportError:
                details["line_stats"] = {"available": False}

            # 状態判定
            if error_count == 0:
                status = "healthy"
            elif error_count <= 1:
                status = "degraded"
            else:
                status = "failed"
                
        except Exception as e:
            status = "failed"
            details["error"] = str(e)
            recommendations.append("LINE Bot check failed")
            error_count += 1
        
        return {
            "status": status,
            "details": details,
            "recommendations": recommendations,
            "error_count": error_count
        }

    def _check_web_chat(self) -> Dict[str, Any]:
        """Webチャットチェック（テンプレートは動的ロード）"""
        details = {}
        recommendations = []
        error_count = 0
        
        try:
            # Webチャット統計取得
            try:
                from api.routers.chat_unified import optimized_generator
                stats = optimized_generator.get_performance_stats()
                details["web_chat_stats"] = {
                    "total_requests": stats["optimization_performance"]["total_requests"],
                    "template_hit_rate": stats["optimization_performance"]["template_hit_rate"],
                    "rag_avoidance_rate": stats["optimization_performance"]["rag_avoidance_rate"],
                    "cache_hit_rate": stats["optimization_performance"]["cache_hit_rate"]
                }
                if "web_optimization_performance" in stats:
                    web_stats = stats["web_optimization_performance"]
                    details["web_quality"] = {
                        "web_template_hit_rate": web_stats["web_template_hit_rate"],
                        "generic_responses_avoided": web_stats["generic_responses_avoided"]
                    }
                    if web_stats["web_template_hit_rate"] < 60:
                        recommendations.append("Low web template hit rate")
                        error_count += 1
            except ImportError:
                details["web_chat_available"] = False
                recommendations.append("Web chat module not available")
                error_count += 1

            # テンプレートシステム（動的ロード）
            get_tm = _get_template_manager()
            if callable(get_tm):
                try:
                    template_manager = get_tm()
                    template_stats = template_manager.get_stats()
                    details["template_system"] = {
                        "total_templates": template_stats["template_counts"]["total_templates"],
                        "match_rate": template_stats["performance"]["match_rate"],
                        "fallback_rate": template_stats["performance"]["fallback_rate"]
                    }
                    if template_stats["performance"]["match_rate"] < 70:
                        recommendations.append("Low template match rate")
                except Exception as e:
                    details["template_system"] = {"available": False, "error": str(e)}
            else:
                details["template_system"] = {"available": False}

            # 状態判定
            if error_count == 0:
                status = "healthy"
            elif error_count <= 1:
                status = "degraded"
            else:
                status = "failed"
                
        except Exception as e:
            status = "failed"
            details["error"] = str(e)
            recommendations.append("Web chat check failed")
            error_count += 1
        
        return {
            "status": status,
            "details": details,
            "recommendations": recommendations,
            "error_count": error_count
        }

    def _check_file_system(self) -> Dict[str, Any]:
        """ファイルシステムチェック"""
        details = {}
        recommendations = []
        error_count = 0
        
        try:
            # 重要ディレクトリの確認
            important_dirs = [
                "rag", "rag/vectorstore", "api", "api/routers", "utils", "llm", "templates", "data"
            ]
            for dir_path in important_dirs:
                if os.path.exists(dir_path):
                    details[f"{dir_path.replace('/', '_')}_exists"] = True
                    details[f"{dir_path.replace('/', '_')}_readable"] = os.access(dir_path, os.R_OK)
                    details[f"{dir_path.replace('/', '_')}_writable"] = os.access(dir_path, os.W_OK)
                else:
                    details[f"{dir_path.replace('/', '_')}_exists"] = False
                    if dir_path in ["rag/vectorstore", "data"]:
                        recommendations.append(f"Create missing directory: {dir_path}")

            # ディスク使用量チェック
            try:
                disk_usage = psutil.disk_usage('.')
                disk_percent = (disk_usage.used / disk_usage.total) * 100
                details["disk_usage"] = {
                    "total_gb": disk_usage.total / (1024**3),
                    "used_gb": disk_usage.used / (1024**3),
                    "free_gb": disk_usage.free / (1024**3),
                    "usage_percent": disk_percent
                }
                if disk_percent > self.thresholds["disk_usage"]:
                    recommendations.append(f"High disk usage: {disk_percent:.1f}%")
                    error_count += 1
            except Exception:
                details["disk_usage"] = {"available": False}

            # 重要ファイルの確認
            important_files = [
                "main.py",
                "requirements.txt",
                "rag/fast_rag_chain.py",
                "api/routers/chat_unified.py",
                "api/routers/line_bot_ultra_fast.py"
            ]
            missing_files = []
            for file_path in important_files:
                if os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)
                    details[f"{file_path.replace('/', '_')}_size"] = file_size
                else:
                    missing_files.append(file_path)
            if missing_files:
                details["missing_files"] = missing_files
                recommendations.extend([f"Missing file: {f}" for f in missing_files])
                error_count += len(missing_files)

            # 状態判定
            if error_count == 0:
                status = "healthy"
            elif error_count <= 2:
                status = "degraded"
            else:
                status = "failed"
                
        except Exception as e:
            status = "failed"
            details["error"] = str(e)
            recommendations.append("File system check failed")
            error_count += 1
        
        return {
            "status": status,
            "details": details,
            "recommendations": recommendations,
            "error_count": error_count
        }

    def _check_dependencies(self) -> Dict[str, Any]:
        """依存関係チェック"""
        details = {}
        recommendations = []
        error_count = 0
        
        try:
            # 重要なPythonパッケージの確認
            critical_packages = [
                "fastapi", "langchain", "sentence_transformers", "faiss-cpu", "psutil", "pydantic"
            ]
            optional_packages = ["linebot", "google-cloud-secretmanager", "openai", "anthropic"]
            
            for package in critical_packages:
                try:
                    __import__(package.replace("-", "_"))
                    details[f"{package}_available"] = True
                except ImportError:
                    details[f"{package}_available"] = False
                    recommendations.append(f"Install critical package: {package}")
                    error_count += 1

            optional_available = 0
            for package in optional_packages:
                try:
                    __import__(package.replace("-", "_"))
                    details[f"{package}_available"] = True
                    optional_available += 1
                except ImportError:
                    details[f"{package}_available"] = False
            details["optional_packages_available"] = optional_available

            # Pythonバージョンチェック
            python_version = sys.version_info
            details["python_version"] = f"{python_version.major}.{python_version.minor}.{python_version.micro}"
            if python_version.major < 3 or (python_version.major == 3 and python_version.minor < 8):
                recommendations.append("Python version should be 3.8 or higher")
                error_count += 1

            # 状態判定
            if error_count == 0:
                status = "healthy"
            elif error_count <= 1:
                status = "degraded"
            else:
                status = "failed"
                
        except Exception as e:
            status = "failed"
            details["error"] = str(e)
            recommendations.append("Dependencies check failed")
            error_count += 1
        
        return {
            "status": status,
            "details": details,
            "recommendations": recommendations,
            "error_count": error_count
        }

    async def _check_performance(self) -> Dict[str, Any]:
        """パフォーマンスチェック"""
        details = {}
        recommendations = []
        error_count = 0
        
        try:
            # レスポンスタイム測定
            response_times = []
            test_operations = [
                ("cache_access", self._test_cache_access),
                ("template_matching", self._test_template_matching),
                ("file_access", self._test_file_access)
            ]
            for test_name, test_func in test_operations:
                try:
                    start_time = time.time()
                    await test_func() if asyncio.iscoroutinefunction(test_func) else test_func()
                    test_time = time.time() - start_time
                    response_times.append(test_time)
                    details[f"{test_name}_time"] = test_time
                    if test_time > self.thresholds["response_time"]:
                        recommendations.append(f"Slow {test_name}: {test_time:.3f}s")
                        error_count += 1
                except Exception as test_error:
                    details[f"{test_name}_error"] = str(test_error)
                    error_count += 1

            # 平均レスポンスタイム
            if response_times:
                avg_response_time = sum(response_times) / len(response_times)
                details["average_response_time"] = avg_response_time
                if avg_response_time > self.thresholds["response_time"]:
                    recommendations.append(f"High average response time: {avg_response_time:.3f}s")

            # メモリ使用量詳細
            try:
                process = psutil.Process()
                memory_info = process.memory_info()
                memory_percent = process.memory_percent()
                details["memory_usage"] = {
                    "rss_mb": memory_info.rss / (1024**2),
                    "vms_mb": memory_info.vms / (1024**2),
                    "percent": memory_percent
                }
                if memory_percent > self.thresholds["memory_usage"]:
                    recommendations.append(f"High memory usage: {memory_percent:.1f}%")
                    error_count += 1
            except Exception:
                details["memory_usage"] = {"available": False}

            # 状態判定
            if error_count == 0:
                status = "healthy"
            elif error_count <= 2:
                status = "degraded"
            else:
                status = "failed"
                
        except Exception as e:
            status = "failed"
            details["error"] = str(e)
            recommendations.append("Performance check failed")
            error_count += 1
        
        return {
            "status": status,
            "details": details,
            "recommendations": recommendations,
            "error_count": error_count
        }

    def _check_security(self) -> Dict[str, Any]:
        """セキュリティチェック"""
        details = {}
        recommendations = []
        error_count = 0
        
        try:
            # 環境変数のセキュリティチェック
            sensitive_vars = [
                "LINE_CHANNEL_ACCESS_TOKEN", "LINE_CHANNEL_SECRET", 
                "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"
            ]
            for var in sensitive_vars:
                value = os.getenv(var, "")
                details[f"{var.lower()}_set"] = bool(value)
                if value and len(value) < 20:
                    recommendations.append(f"{var} seems too short")
                    error_count += 1

            # ファイル権限チェック
            sensitive_files = [".env", "config.py", "secrets.json"]
            for file_path in sensitive_files:
                if os.path.exists(file_path):
                    file_stat = os.stat(file_path)
                    file_mode = oct(file_stat.st_mode)[-3:]
                    details[f"{file_path.replace('.', '_')}_permissions"] = file_mode
                    if file_mode in ["777", "666", "644"]:
                        recommendations.append(f"Overly permissive file permissions: {file_path}")

            # デバッグモードチェック
            debug_indicators = [("DEBUG", os.getenv("DEBUG")),
                                ("ENVIRONMENT", os.getenv("ENVIRONMENT")),
                                ("LOG_LEVEL", os.getenv("LOG_LEVEL"))]
            for var_name, var_value in debug_indicators:
                if var_value:
                    details[f"{var_name.lower()}_value"] = var_value
                    if var_value.lower() in ["true", "1", "debug", "development"]:
                        recommendations.append(f"Debug mode enabled: {var_name}={var_value}")

            # 状態判定
            if error_count == 0:
                status = "healthy"
            elif error_count <= 1:
                status = "degraded" 
            else:
                status = "failed"
                
        except Exception as e:
            status = "failed"
            details["error"] = str(e)
            recommendations.append("Security check failed")
            error_count += 1
        
        return {
            "status": status,
            "details": details,
            "recommendations": recommendations,
            "error_count": error_count
        }

    # ==========================================================================
    # テストヘルパー関数（動的ロード版）
    # ==========================================================================
    
    def _test_cache_access(self):
        """キャッシュアクセステスト（utils.chat_cache を動的ロード）"""
        funcs = _get_chat_cache_funcs()
        qget = funcs["quick_cache_get"]
        qset = funcs["quick_cache_set"]
        if not (callable(qget) and callable(qset)):
            return False
        try:
            test_key = "diagnostic_test"
            test_value = "test_response"
            qset(test_key, test_value)
            retrieved = qget(test_key)
            return retrieved == test_value
        except Exception:
            return False

    def _test_template_matching(self):
        """テンプレートマッチングテスト（utils.chat_templates を動的ロード）"""
        get_tm = _get_template_manager()
        if not callable(get_tm):
            return False
        try:
            template_manager = get_tm()
            result = template_manager.find_template("坪単価", "web")
            return result is not None
        except Exception:
            return False

    def _test_file_access(self):
        """ファイルアクセステスト"""
        try:
            test_file = "diagnostic_test.tmp"
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("test")
            with open(test_file, 'r', encoding='utf-8') as f:
                content = f.read()
            os.remove(test_file)
            return content == "test"
        except Exception:
            return False

    # ==========================================================================
    # パフォーマンス・リソース監視
    # ==========================================================================
    async def _collect_performance_metrics(self) -> Dict[str, float]:
        """パフォーマンスメトリクス収集"""
        metrics = {}
        try:
            # 統合チャット統計
            from api.routers.chat_unified import optimized_generator
            unified_stats = optimized_generator.get_performance_stats()
            metrics["total_requests"] = unified_stats["optimization_performance"]["total_requests"]
            metrics["cache_hit_rate"] = unified_stats["optimization_performance"]["cache_hit_rate"]
            metrics["template_hit_rate"] = unified_stats["optimization_performance"]["template_hit_rate"]
        except ImportError:
            pass

        try:
            # LINE Bot統計
            from api.routers.line_bot_ultra_fast import smart_router
            line_stats = smart_router.get_stats()
            metrics["line_total_requests"] = line_stats["total_requests"]
            metrics["line_instant_response_rate"] = line_stats["optimization_metrics"]["instant_response_rate"]
        except ImportError:
            pass

        return metrics

    def _get_resource_usage(self) -> Dict[str, float]:
        """リソース使用量取得"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            process = psutil.Process()
            process_memory = process.memory_percent()
            return {
                "cpu_usage": cpu_percent,
                "memory_usage": memory_percent,
                "process_memory_usage": process_memory,
                "memory_available_gb": memory.available / (1024**3)
            }
        except Exception as e:
            logger.error(f"Resource usage check failed: {e}")
            return {"error": str(e)}

    # ==========================================================================
    # ユーティリティ関数
    # ==========================================================================
    def _add_to_history(self, system_health: SystemHealth):
        """履歴にシステムヘルスを追加"""
        self.check_history.append(system_health)
        if len(self.check_history) > self.max_history:
            self.check_history = self.check_history[-self.max_history:]

    def get_health_summary(self) -> Dict[str, Any]:
        """健全性サマリー取得"""
        if not self.check_history:
            return {"status": "no_data", "message": "No diagnostic history available"}
        latest = self.check_history[-1]
        component_summary = {
            name: {"status": st.status, "response_time": st.response_time, "error_count": st.error_count}
            for name, st in latest.components.items()
        }
        return {
            "overall_status": latest.overall_status,
            "timestamp": latest.timestamp.isoformat(),
            "uptime_hours": latest.uptime / 3600,
            "component_summary": component_summary,
            "total_alerts": len(latest.alerts),
            "resource_usage": latest.resource_usage,
            "last_check": self.last_full_check.isoformat() if self.last_full_check else None
        }

    def get_trends(self, hours: int = 24) -> Dict[str, Any]:
        """トレンド分析"""
        if len(self.check_history) < 2:
            return {"status": "insufficient_data"}
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_checks = [c for c in self.check_history if c.timestamp >= cutoff_time]
        if not recent_checks:
            return {"status": "no_recent_data"}

        status_changes = []
        for i in range(1, len(recent_checks)):
            prev_status = recent_checks[i-1].overall_status
            curr_status = recent_checks[i].overall_status
            if prev_status != curr_status:
                status_changes.append({
                    "timestamp": recent_checks[i].timestamp.isoformat(),
                    "from": prev_status, "to": curr_status
                })

        performance_trend = {}
        first_check = recent_checks[0]
        last_check = recent_checks[-1]
        for metric_name in first_check.performance_metrics:
            if metric_name in last_check.performance_metrics:
                first_value = first_check.performance_metrics[metric_name]
                last_value = last_check.performance_metrics[metric_name]
                if first_value > 0:
                    change_percent = ((last_value - first_value) / first_value) * 100
                    performance_trend[metric_name] = {
                        "change_percent": change_percent,
                        "direction": "improving" if change_percent > 0 else "degrading" if change_percent < -5 else "stable"
                    }

        avg_resp = sum(
            c.performance_metrics.get("average_response_time", 0) for c in recent_checks
        ) / len(recent_checks) if recent_checks else 0

        return {
            "period_hours": hours,
            "checks_analyzed": len(recent_checks),
            "status_changes": status_changes,
            "performance_trends": performance_trend,
            "average_response_time": avg_resp
        }

    def export_diagnostics(self, file_path: str) -> bool:
        """診断結果のエクスポート"""
        try:
            export_data = {
                "export_timestamp": datetime.now().isoformat(),
                "system_info": {
                    "uptime": time.time() - self.startup_time,
                    "python_version": sys.version,
                    "working_directory": os.getcwd()
                },
                "latest_check": asdict(self.check_history[-1]) if self.check_history else None,
                "health_summary": self.get_health_summary(),
                "trends_24h": self.get_trends(24),
                "check_history_count": len(self.check_history),
                "thresholds": self.thresholds
            }
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, default=str)
            logger.info(f"📤 Diagnostics exported to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export diagnostics: {e}")
            return False

# グローバル診断インスタンス
_global_diagnostics = None

def get_system_diagnostics() -> SystemDiagnostics:
    """グローバル診断インスタンス取得"""
    global _global_diagnostics
    if _global_diagnostics is None:
        _global_diagnostics = SystemDiagnostics()
    return _global_diagnostics

async def run_quick_health_check() -> Dict[str, Any]:
    """クイックヘルスチェック実行"""
    diagnostics = get_system_diagnostics()
    quick_checks = ["rag_system", "cache_system", "performance"]
    results = {}
    overall_issues = 0
    for check_name in quick_checks:
        if check_name in diagnostics.component_checkers:
            try:
                checker = diagnostics.component_checkers[check_name]
                result = await diagnostics._run_component_check(check_name, checker)
                results[check_name] = {
                    "status": result.status,
                    "response_time": result.response_time,
                    "error_count": result.error_count
                }
                if result.status in ["degraded", "failed"]:
                    overall_issues += 1
            except Exception as e:
                results[check_name] = {"status": "failed", "error": str(e)}
                overall_issues += 1
    overall_status = "healthy" if overall_issues == 0 else "degraded" if overall_issues <= 1 else "critical"
    return {
        "overall_status": overall_status,
        "timestamp": datetime.now().isoformat(),
        "quick_check_results": results,
        "issues_found": overall_issues,
        "uptime": time.time() - diagnostics.startup_time
    }
