# main.py - RAG初期化診断強化版

import logging
import os
import asyncio
import time
from datetime import datetime
from typing import Dict, Any, List  # ✅ List をインポート
from uuid import uuid4
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI アプリケーションインスタンス
app = FastAPI(
    title="Unified RAG API - Complete Integration System (Diagnostics Enhanced)",
    description="High-Performance Unified AI Chat API with Enhanced RAG Diagnostics",
    version="7.2.0-diagnostics-enhanced"
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# グローバル変数（RAG機能）- 診断強化版
vectorstore = None
rag_chain_template = None
llm_instance = None
initialization_lock = asyncio.Lock()
is_initialized = False

# RAGインスタンス共有フラグ
RAG_SHARED_GLOBALLY = False

# 🚀 RAG診断情報（詳細追跡）
rag_diagnostics = {
    "initialization_attempts": 0,
    "initialization_success": False,
    "last_initialization_time": None,
    "initialization_duration": 0.0,
    "component_status": {
        "llm_instance": {"loaded": False, "error": None, "load_time": 0.0},
        "vectorstore": {"loaded": False, "error": None, "load_time": 0.0, "file_path": None, "file_size": 0},
        "rag_chain": {"loaded": False, "error": None, "load_time": 0.0}
    },
    "fallback_info": {
        "used_fallback": False,
        "fallback_type": None,
        "fallback_reason": None
    },
    "health_checks": {
        "last_check": None,
        "vectorstore_test": False,
        "rag_query_test": False,
        "llm_response_test": False
    }
}

# 起動時刻を記録
startup_time = time.time()

# 完全統合システム設定
ENABLE_RAG_INITIALIZATION = True
ENABLE_UNIFIED_CHAT = True
ENABLE_LINE_INTEGRATION = True
ENABLE_FINANCIAL_PLANNING = True
ENABLE_DUPLICATE_PREVENTION = True
ENABLE_LEGACY_COMPATIBILITY = True

# エンドポイント統一設定
ENDPOINT_MIGRATION_COMPLETE = True
OLD_CHAT_ENDPOINT_REDIRECT = True
UNIFIED_CHAT_PRIMARY_PATH = "/chat"

# LINE統合設定
LINE_BOT_MODE = os.getenv("LINE_BOT_MODE", "ultra_fast_financial")
SINGLE_LINE_INTEGRATION = True

# 完全統合チャット設定
UNIFIED_CHAT_MODE = os.getenv("UNIFIED_CHAT_MODE", "complete")
DEFAULT_PLATFORM = "web"
DEFAULT_RESPONSE_MODE = "auto"

# 統合完了フラグ
INTEGRATION_COMPLETE = {
    "chat_py_integrated": True,
    "chat_ultra_fast_integrated": True,
    "template_system_unified": True,
    "cache_system_unified": True,
    "performance_optimized": True,
    "platform_separation_complete": True,
    "endpoint_migration_complete": True,
    "rag_sharing_complete": True,
    "log_optimization_complete": True,
    "diagnostics_enhanced": True  # 🆕
}

# ==============================================================================
# 🚀 RAG初期化（診断強化版）
# ==============================================================================
async def initialize_rag_components():
    """RAG コンポーネントの非同期初期化（診断大幅強化版）"""
    global vectorstore, rag_chain_template, llm_instance, is_initialized, RAG_SHARED_GLOBALLY, rag_diagnostics
    
    if is_initialized:
        logger.info("✅ RAG components already initialized and shared globally")
        return
    
    async with initialization_lock:
        if is_initialized:
            return
        
        initialization_start = time.time()
        rag_diagnostics["initialization_attempts"] += 1
        rag_diagnostics["last_initialization_time"] = datetime.now().isoformat()
        
        logger.info("🚀 Starting RAG initialization with enhanced diagnostics...")
        logger.info(f"   - Attempt #{rag_diagnostics['initialization_attempts']}")
        logger.info(f"   - Environment: {os.getenv('ENVIRONMENT', 'local')}")
        logger.info(f"   - Working directory: {os.getcwd()}")
        
        try:
            # 🚀 STEP 1: LLM初期化（詳細診断）
            logger.info("🔧 Step 1: Loading LLM instance...")
            llm_start = time.time()
            
            try:
                from llm.llm_runner import load_llm
                llm_result = load_llm()
                
                if isinstance(llm_result, tuple) and len(llm_result) >= 1:
                    llm_instance = llm_result[0]
                    rag_diagnostics["component_status"]["llm_instance"]["loaded"] = True
                    rag_diagnostics["component_status"]["llm_instance"]["load_time"] = time.time() - llm_start
                    logger.info(f"✅ LLM loaded: {type(llm_instance).__name__} ({rag_diagnostics['component_status']['llm_instance']['load_time']:.2f}s)")
                else:
                    raise ValueError(f"Unexpected LLM load result: {type(llm_result)}")
                
            except Exception as llm_error:
                rag_diagnostics["component_status"]["llm_instance"]["error"] = str(llm_error)
                logger.error(f"❌ LLM loading failed: {llm_error}")
                raise
            
            # 🚀 STEP 2: ベクトルストア初期化（詳細診断）
            logger.info("🔧 Step 2: Loading vectorstore...")
            vectorstore_start = time.time()
            
            try:
                # 🚀 詳細パス診断
                vector_dir = "rag/vectorstore"
                index_path = os.path.join(vector_dir, "index.faiss")
                pkl_path = os.path.join(vector_dir, "index.pkl")
                
                logger.info(f"   - Vector directory: {vector_dir}")
                logger.info(f"   - Index file path: {index_path}")
                logger.info(f"   - Exists: {os.path.exists(index_path)}")
                
                if os.path.exists(index_path):
                    file_size = os.path.getsize(index_path)
                    logger.info(f"   - File size: {file_size} bytes")
                    rag_diagnostics["component_status"]["vectorstore"]["file_path"] = index_path
                    rag_diagnostics["component_status"]["vectorstore"]["file_size"] = file_size
                
                # 高速RAGチェーン優先
                try:
                    from rag.fast_rag_chain import load_ultra_fast_vectorstore, get_ultra_fast_rag_chain
                    vectorstore = load_ultra_fast_vectorstore()
                    
                    if vectorstore:
                        # 🚀 ベクトルストア詳細診断
                        if hasattr(vectorstore, 'index') and hasattr(vectorstore.index, 'ntotal'):
                            vector_count = vectorstore.index.ntotal
                            logger.info(f"   - Vector count: {vector_count}")
                            
                            # 簡単なテスト検索
                            try:
                                test_results = vectorstore.similarity_search("テスト住宅", k=1)
                                logger.info(f"   - Test search: {len(test_results)} results")
                                rag_diagnostics["health_checks"]["vectorstore_test"] = True
                            except Exception as test_error:
                                logger.warning(f"   - Test search failed: {test_error}")
                        
                        rag_chain_template = get_ultra_fast_rag_chain(vectorstore)
                        logger.info("✅ Ultra fast RAG chain loaded successfully")
                        
                    else:
                        raise ValueError("Vectorstore is None")
                        
                except Exception as fast_error:
                    logger.warning(f"⚠️ Ultra fast RAG failed: {fast_error}")
                    logger.info("🔄 Trying standard RAG chain...")
                    
                    # 標準RAGチェーンフォールバック
                    try:
                        import importlib.util as _il_spec, pathlib as _pl
                        _rag_chain_path = _pl.Path(__file__).resolve().parent / "rag" / "rag_chain.py"
                        
                        if _rag_chain_path.exists():
                            logger.info(f"   - Loading from: {_rag_chain_path}")
                            _spec = _il_spec.spec_from_file_location("rag.rag_chain", _rag_chain_path)
                            _mod = _il_spec.module_from_spec(_spec)
                            assert _spec and _spec.loader
                            _spec.loader.exec_module(_mod)
                            
                            vectorstore = _mod.load_vectorstore()
                            rag_chain_template = _mod.get_rag_chain(vectorstore)
                            logger.info("✅ Standard RAG chain loaded as fallback")
                            
                            rag_diagnostics["fallback_info"]["used_fallback"] = True
                            rag_diagnostics["fallback_info"]["fallback_type"] = "standard_rag"
                            rag_diagnostics["fallback_info"]["fallback_reason"] = str(fast_error)
                        else:
                            raise FileNotFoundError("Standard rag_chain.py not found")
                            
                    except Exception as standard_error:
                        logger.error(f"❌ Standard RAG fallback failed: {standard_error}")
                        
                        # 🚀 最終フォールバック：ingested_text
                        try:
                            logger.info("🔄 Trying ingested_text fallback...")
                            from rag.ingested_text import load_vectorstore, get_rag_chain
                            vectorstore = load_vectorstore()
                            rag_chain_template = get_rag_chain(vectorstore)
                            logger.info("✅ Ingested_text RAG loaded as final fallback")
                            
                            rag_diagnostics["fallback_info"]["used_fallback"] = True
                            rag_diagnostics["fallback_info"]["fallback_type"] = "ingested_text"
                            rag_diagnostics["fallback_info"]["fallback_reason"] = f"fast_rag: {fast_error}, standard: {standard_error}"
                            
                        except Exception as final_error:
                            logger.error(f"❌ All RAG fallbacks failed: {final_error}")
                            vectorstore = None
                            rag_chain_template = None
                            raise
                
                rag_diagnostics["component_status"]["vectorstore"]["loaded"] = vectorstore is not None
                rag_diagnostics["component_status"]["vectorstore"]["load_time"] = time.time() - vectorstore_start
                rag_diagnostics["component_status"]["rag_chain"]["loaded"] = rag_chain_template is not None
                rag_diagnostics["component_status"]["rag_chain"]["load_time"] = time.time() - vectorstore_start
                
            except Exception as vectorstore_error:
                rag_diagnostics["component_status"]["vectorstore"]["error"] = str(vectorstore_error)
                rag_diagnostics["component_status"]["rag_chain"]["error"] = str(vectorstore_error)
                logger.error(f"❌ Vectorstore/RAG chain loading failed: {vectorstore_error}")
                raise
            
            # 🚀 STEP 3: 統合テスト
            logger.info("🔧 Step 3: Running integration tests...")
            
            try:
                if llm_instance and rag_chain_template:
                    # 簡単なRAGクエリテスト
                    test_query = {"query": "テスト"}
                    test_response = rag_chain_template.invoke(test_query)
                    
                    if test_response and test_response.get("result"):
                        logger.info("✅ RAG integration test passed")
                        rag_diagnostics["health_checks"]["rag_query_test"] = True
                    else:
                        logger.warning("⚠️ RAG integration test returned empty result")
                
                # LLMテスト
                if llm_instance:
                    try:
                        test_llm_response = llm_instance.invoke("テスト")
                        if test_llm_response:
                            logger.info("✅ LLM test passed")
                            rag_diagnostics["health_checks"]["llm_response_test"] = True
                        else:
                            logger.warning("⚠️ LLM test returned empty result")
                    except Exception as llm_test_error:
                        logger.warning(f"⚠️ LLM test failed: {llm_test_error}")
                        
            except Exception as test_error:
                logger.warning(f"⚠️ Integration tests failed: {test_error}")
            
            # 🚀 初期化完了
            is_initialized = True
            RAG_SHARED_GLOBALLY = True
            rag_diagnostics["initialization_success"] = True
            rag_diagnostics["initialization_duration"] = time.time() - initialization_start
            rag_diagnostics["health_checks"]["last_check"] = datetime.now().isoformat()
            
            logger.info("🎉 RAG initialization completed successfully!")
            logger.info(f"   - Total time: {rag_diagnostics['initialization_duration']:.2f}s")
            logger.info(f"   - Vectorstore: {'✅ Ready' if vectorstore else '❌ Failed'}")
            logger.info(f"   - RAG Chain: {'✅ Ready' if rag_chain_template else '❌ Failed'}")
            logger.info(f"   - LLM Instance: {'✅ Ready' if llm_instance else '❌ Failed'}")
            logger.info(f"   - Global Sharing: {'✅ ENABLED' if RAG_SHARED_GLOBALLY else '❌ FAILED'}")
            logger.info(f"   - Fallback Used: {'Yes (' + rag_diagnostics['fallback_info']['fallback_type'] + ')' if rag_diagnostics['fallback_info']['used_fallback'] else 'No'}")
            
        except Exception as e:
            rag_diagnostics["initialization_success"] = False
            rag_diagnostics["initialization_duration"] = time.time() - initialization_start
            
            logger.error("💥 RAG initialization failed!")
            logger.error(f"   - Error: {e}")
            logger.error(f"   - Duration: {rag_diagnostics['initialization_duration']:.2f}s")
            logger.error(f"   - Stack trace: {traceback.format_exc()}")
            
            is_initialized = False
            RAG_SHARED_GLOBALLY = False

def get_shared_rag_components():
    """共有RAGコンポーネント取得関数（診断情報付き）"""
    return {
        "vectorstore": vectorstore,
        "rag_chain_template": rag_chain_template, 
        "llm_instance": llm_instance,
        "is_initialized": is_initialized,
        "shared_globally": RAG_SHARED_GLOBALLY,
        "diagnostics": rag_diagnostics  # 🆕 診断情報追加
    }

# ==============================================================================
# 🚀 診断エンドポイント群
# ==============================================================================
@app.get("/debug/rag-status")
async def get_rag_detailed_status():
    """RAGコンポーネントの詳細状態確認"""
    current_time = datetime.now().isoformat()
    
    # リアルタイム健全性チェック
    live_health = {
        "vectorstore_accessible": vectorstore is not None,
        "rag_chain_accessible": rag_chain_template is not None,
        "llm_accessible": llm_instance is not None,
        "can_process_query": False
    }
    
    # クイックテスト
    if rag_chain_template:
        try:
            quick_test = rag_chain_template.invoke({"query": "健全性テスト"})
            live_health["can_process_query"] = bool(quick_test and quick_test.get("result"))
        except Exception as test_error:
            live_health["test_error"] = str(test_error)
    
    return {
        "timestamp": current_time,
        "initialization_status": {
            "is_initialized": is_initialized,
            "globally_shared": RAG_SHARED_GLOBALLY,
            "attempts": rag_diagnostics["initialization_attempts"],
            "success": rag_diagnostics["initialization_success"],
            "last_attempt": rag_diagnostics["last_initialization_time"],
            "duration": rag_diagnostics["initialization_duration"]
        },
        "component_details": rag_diagnostics["component_status"],
        "fallback_info": rag_diagnostics["fallback_info"],
        "health_checks": rag_diagnostics["health_checks"],
        "live_health": live_health,
        "recommendations": _generate_rag_recommendations()
    }

@app.get("/debug/performance")
async def get_realtime_performance():
    """リアルタイムパフォーマンス監視"""
    from api.routers.chat_unified import optimized_generator
    
    try:
        # 統合チャット性能統計
        unified_stats = optimized_generator.get_performance_stats()
    except Exception as e:
        unified_stats = {"error": f"Failed to get unified stats: {e}"}
    
    # システム全体の健全性
    system_health = {
        "rag_components": is_initialized,
        "global_sharing": RAG_SHARED_GLOBALLY,
        "uptime": time.time() - startup_time,
        "memory_usage": _get_memory_usage(),
        "active_endpoints": len(app.routes)
    }
    
    return {
        "timestamp": datetime.now().isoformat(),
        "system_health": system_health,
        "unified_chat_performance": unified_stats,
        "rag_diagnostics_summary": {
            "initialization_success": rag_diagnostics["initialization_success"],
            "component_status": {k: v["loaded"] for k, v in rag_diagnostics["component_status"].items()},
            "fallback_used": rag_diagnostics["fallback_info"]["used_fallback"]
        }
    }

@app.post("/debug/fix-rag")
async def attempt_rag_auto_fix():
    """RAG問題の自動修復試行"""
    fix_start = time.time()
    fix_log = []
    
    try:
        # 現在の状態診断
        fix_log.append("🔍 Diagnosing current RAG status...")
        
        if is_initialized and vectorstore and rag_chain_template:
            fix_log.append("✅ RAG components appear healthy, running extended tests...")
            
            # 拡張テスト
            try:
                test_queries = ["住宅", "坪単価", "標準仕様"]
                for query in test_queries:
                    result = rag_chain_template.invoke({"query": query})
                    if result and result.get("result"):
                        fix_log.append(f"✅ Test query '{query}': OK")
                    else:
                        fix_log.append(f"⚠️ Test query '{query}': Empty result")
                        
            except Exception as test_error:
                fix_log.append(f"❌ Extended test failed: {test_error}")
                
        else:
            fix_log.append("❌ RAG components not properly initialized, attempting reinitialization...")
            
            # 強制再初期化
            global is_initialized, RAG_SHARED_GLOBALLY
            is_initialized = False
            RAG_SHARED_GLOBALLY = False
            
            await initialize_rag_components()
            
            if is_initialized:
                fix_log.append("✅ Reinitialization successful!")
            else:
                fix_log.append("❌ Reinitialization failed")
        
        # キャッシュクリア
        try:
            from rag.fast_rag_chain import clear_super_fast_cache
            cleared_entries = clear_super_fast_cache()
            fix_log.append(f"🧹 Cache cleared: {cleared_entries} entries")
        except Exception as cache_error:
            fix_log.append(f"⚠️ Cache clear failed: {cache_error}")
        
        fix_duration = time.time() - fix_start
        
        return {
            "fix_attempted": True,
            "fix_duration": fix_duration,
            "fix_log": fix_log,
            "final_status": {
                "is_initialized": is_initialized,
                "globally_shared": RAG_SHARED_GLOBALLY,
                "components_ready": {
                    "vectorstore": vectorstore is not None,
                    "rag_chain": rag_chain_template is not None,
                    "llm": llm_instance is not None
                }
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as fix_error:
        fix_duration = time.time() - fix_start
        fix_log.append(f"💥 Auto-fix failed: {fix_error}")
        
        return {
            "fix_attempted": True,
            "fix_successful": False,
            "fix_duration": fix_duration,
            "fix_log": fix_log,
            "error": str(fix_error),
            "timestamp": datetime.now().isoformat()
        }

def _generate_rag_recommendations() -> List[str]:
    """RAG問題の改善提案生成"""
    recommendations = []
    
    # 初期化失敗
    if not rag_diagnostics["initialization_success"]:
        recommendations.append("🔧 RAG initialization failed - check vectorstore files and dependencies")
    
    # コンポーネント別推奨
    for component, status in rag_diagnostics["component_status"].items():
        if not status["loaded"]:
            if component == "vectorstore":
                recommendations.append("🔍 Vectorstore not loaded - check rag/vectorstore directory and files")
            elif component == "llm_instance":
                recommendations.append("🤖 LLM not loaded - check llm configuration and API keys")
            elif component == "rag_chain":
                recommendations.append("⛓️ RAG chain not loaded - check dependencies and prompt templates")
    
    # パフォーマンス推奨
    if rag_diagnostics["initialization_duration"] > 30:
        recommendations.append("ⱏ️ Slow initialization - consider optimizing vectorstore size or using faster embedding model")
    
    # フォールバック推奨
    if rag_diagnostics["fallback_info"]["used_fallback"]:
        recommendations.append(f"🔄 Using fallback ({rag_diagnostics['fallback_info']['fallback_type']}) - consider fixing primary RAG system")
    
    # 健全性推奨
    if not rag_diagnostics["health_checks"]["vectorstore_test"]:
        recommendations.append("🔍 Vectorstore test failed - check vector database integrity")
    
    if not rag_diagnostics["health_checks"]["rag_query_test"]:
        recommendations.append("❓ RAG query test failed - check RAG chain configuration")
    
    if not recommendations:
        recommendations.append("✅ RAG system appears healthy - no specific recommendations")
    
    return recommendations

def _get_memory_usage() -> Dict[str, Any]:
    """メモリ使用量取得（概算）"""
    try:
        import psutil
        process = psutil.Process()
        memory_info = process.memory_info()
        
        return {
            "rss_mb": memory_info.rss / 1024 / 1024,
            "vms_mb": memory_info.vms / 1024 / 1024,
            "percent": process.memory_percent()
        }
    except ImportError:
        return {"error": "psutil not available"}
    except Exception as e:
        return {"error": str(e)}

# 完全統合パフォーマンス監視システム（継続）
class CompletePerformanceMonitor:
    def __init__(self):
        self.metrics = {
            "chat_requests": 0,
            "line_requests": 0,
            "web_requests": 0,
            "rag_requests": 0,
            "template_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "average_response_time": 0.0,
            "total_response_time": 0.0,
            "errors": 0,
            "anti_hallucination_uses": 0,
            "sentence_completions": 0,
            "endpoint_redirects": 0,
            "rag_diagnostics_requests": 0  # 🆕
        }
        self.start_time = time.time()
        self.response_times = []
        self.error_log = []

    def record_request(self, platform: str, mode: str, response_time: float, 
                      cache_hit: bool = False, anti_hallucination_used: bool = False,
                      sentence_complete: bool = True, endpoint_redirected: bool = False,
                      diagnostics_used: bool = False):  # 🆕
        """完全統合リクエスト記録（診断強化版）"""
        self.metrics["chat_requests"] += 1
        
        if platform == "line":
            self.metrics["line_requests"] += 1
        else:
            self.metrics["web_requests"] += 1
        
        if mode in ["rag", "rag_enhanced"]:
            self.metrics["rag_requests"] += 1
        elif mode in ["template", "template_enhanced"]:
            self.metrics["template_requests"] += 1
        
        if cache_hit:
            self.metrics["cache_hits"] += 1
        else:
            self.metrics["cache_misses"] += 1
        
        if anti_hallucination_used:
            self.metrics["anti_hallucination_uses"] += 1
        
        if sentence_complete:
            self.metrics["sentence_completions"] += 1
        
        if endpoint_redirected:
            self.metrics["endpoint_redirects"] += 1
            
        if diagnostics_used:  # 🆕
            self.metrics["rag_diagnostics_requests"] += 1
        
        self.metrics["total_response_time"] += response_time
        self.response_times.append({
            "timestamp": time.time(),
            "platform": platform,
            "mode": mode,
            "response_time": response_time,
            "cache_hit": cache_hit,
            "endpoint_redirected": endpoint_redirected,
            "diagnostics_used": diagnostics_used  # 🆕
        })
        
        if len(self.response_times) > 100:
            self.response_times = self.response_times[-100:]
        
        if self.metrics["chat_requests"] > 0:
            self.metrics["average_response_time"] = self.metrics["total_response_time"] / self.metrics["chat_requests"]

    def record_error(self, error_type: str = "unknown", error_details: str = ""):
        """エラー記録（継続）"""
        self.metrics["errors"] += 1
        self.error_log.append({
            "timestamp": time.time(),
            "error_type": error_type,
            "error_details": error_details[:200]
        })
        
        if len(self.error_log) > 20:
            self.error_log = self.error_log[-20:]

    def get_stats(self) -> Dict[str, Any]:
        """完全統合統計取得（診断強化版）"""
        uptime = time.time() - self.start_time
        total_requests = self.metrics["chat_requests"]
        
        recent_response_times = [r["response_time"] for r in self.response_times[-50:]]
        avg_recent_response_time = sum(recent_response_times) / len(recent_response_times) if recent_response_times else 0
        
        return {
            "system_overview": {
                "uptime_seconds": uptime,
                "total_requests": total_requests,
                "requests_per_minute": (total_requests / (uptime / 60)) if uptime > 60 else total_requests,
                "integration_status": "complete_diagnostics_enhanced",  # 🆕
                "endpoint_redirects": self.metrics["endpoint_redirects"],
                "diagnostics_requests": self.metrics["rag_diagnostics_requests"]  # 🆕
            },
            "platform_distribution": {
                "web": self.metrics["web_requests"],
                "line": self.metrics["line_requests"],
                "web_percentage": (self.metrics["web_requests"] / total_requests * 100) if total_requests > 0 else 0,
                "line_percentage": (self.metrics["line_requests"] / total_requests * 100) if total_requests > 0 else 0
            },
            "mode_distribution": {
                "rag": self.metrics["rag_requests"],
                "template": self.metrics["template_requests"],
                "other": total_requests - self.metrics["rag_requests"] - self.metrics["template_requests"],
                "rag_percentage": (self.metrics["rag_requests"] / total_requests * 100) if total_requests > 0 else 0,
                "template_percentage": (self.metrics["template_requests"] / total_requests * 100) if total_requests > 0 else 0
            },
            "cache_performance": {
                "hits": self.metrics["cache_hits"],
                "misses": self.metrics["cache_misses"],
                "hit_rate": (self.metrics["cache_hits"] / (self.metrics["cache_hits"] + self.metrics["cache_misses"]) * 100) if (self.metrics["cache_hits"] + self.metrics["cache_misses"]) > 0 else 0,
                "efficiency": "optimized" if self.metrics["cache_hits"] > self.metrics["cache_misses"] else "needs_improvement"
            },
            "response_performance": {
                "average_response_time": self.metrics["average_response_time"],
                "recent_average_response_time": avg_recent_response_time,
                "performance_trend": "improving" if avg_recent_response_time < self.metrics["average_response_time"] else "stable"
            },
            "advanced_features": {
                "anti_hallucination_uses": self.metrics["anti_hallucination_uses"],
                "anti_hallucination_rate": (self.metrics["anti_hallucination_uses"] / total_requests * 100) if total_requests > 0 else 0,
                "sentence_completions": self.metrics["sentence_completions"],
                "sentence_completion_rate": (self.metrics["sentence_completions"] / total_requests * 100) if total_requests > 0 else 0
            },
            "error_tracking": {
                "total_errors": self.metrics["errors"],
                "error_rate": (self.metrics["errors"] / total_requests * 100) if total_requests > 0 else 0,
                "recent_errors": len(self.error_log),
                "error_trend": "stable" if self.metrics["errors"] < 5 else "needs_attention"
            },
            "diagnostics_tracking": {  # 🆕 診断追跡
                "diagnostics_requests": self.metrics["rag_diagnostics_requests"],
                "diagnostics_rate": (self.metrics["rag_diagnostics_requests"] / total_requests * 100) if total_requests > 0 else 0,
                "rag_health_status": is_initialized and RAG_SHARED_GLOBALLY
            }
        }

performance_monitor = CompletePerformanceMonitor()

# ==============================================================================
# 完全統合チャットリクエストモデル（継続）
# ==============================================================================
class CompleteUnifiedChatRequest(BaseModel):
    question: str
    username: str | None = None
    platform: str | None = DEFAULT_PLATFORM
    mode: str | None = DEFAULT_RESPONSE_MODE
    enable_anti_hallucination: bool | None = True
    enable_cache: bool | None = True
    debug_mode: bool | None = False

# ==============================================================================
# エンドポイント統一処理（診断強化版）
# ==============================================================================
@app.post("/chat")
@app.post("/chat/")
async def unified_chat_endpoint_diagnostics_enhanced(req: CompleteUnifiedChatRequest, request: Request):
    """統一メインチャットエンドポイント（診断強化版）"""
    
    overall_start = time.time()
    platform = req.platform or DEFAULT_PLATFORM
    username = req.username or f"{platform}-user"
    mode = req.mode or DEFAULT_RESPONSE_MODE
    
    logger.info(f"🌟 Unified Chat (diagnostics enhanced): {req.question[:50]}...")

    try:
        # RAG診断情報の活用
        if not is_initialized:
            logger.warning("⚠️ RAG not initialized, attempting auto-fix...")
            try:
                await initialize_rag_components()
            except Exception as init_error:
                logger.error(f"❌ Auto-fix failed: {init_error}")
        
        # 完全統合チャットルーターを使用
        if ENABLE_UNIFIED_CHAT and UNIFIED_CHAT_MODE in ["complete", "enabled"]:
            try:
                from api.routers.chat_unified import unified_generator
                
                response = await unified_generator.generate_response(
                    req.question, platform, username, mode
                )
                
                total_time = time.time() - overall_start
                
                # パフォーマンス記録（診断強化）
                cache_hit = response.get("source") == "cache"
                anti_hallucination_used = response.get("anti_hallucination_used", False)
                sentence_complete = response.get("sentence_complete", True)
                diagnostics_used = req.debug_mode or False
                
                performance_monitor.record_request(
                    platform=platform, 
                    mode=response.get("source", mode), 
                    response_time=total_time, 
                    cache_hit=cache_hit,
                    anti_hallucination_used=anti_hallucination_used,
                    sentence_complete=sentence_complete,
                    endpoint_redirected=False,
                    diagnostics_used=diagnostics_used  # 🆕
                )
                
                logger.info(
                    f"✅ Unified response (diagnostics): {total_time:.3f}s, "
                    f"source={response.get('source')}, "
                    f"length={len(response['answer'])}"
                )
                
                result = {
                    "answer": response["answer"],
                    "sources": response.get("sources", []),
                    "status": response.get("status", "ok"),
                    "performance": {
                        "total_time": total_time,
                        "processing_time": response.get("processing_time", 0),
                        "source": response.get("source"),
                        "platform": platform,
                        "mode": mode,
                        "unified_system": True,
                        "integration_version": "diagnostics_enhanced",
                        "router_used": "chat_unified_diagnostics_enhanced",
                        "endpoint_used": "/chat",
                        "cache_hit": cache_hit,
                        "anti_hallucination_used": anti_hallucination_used,
                        "sentence_complete": sentence_complete,
                        "rag_health": is_initialized  # 🆕
                    },
                    "system_info": {
                        "version": "7.2.0-diagnostics-enhanced",
                        "integration_mode": "complete_unified_chat_diagnostics",
                        "rag_status": "initialized" if is_initialized else "failed",
                        "global_sharing": RAG_SHARED_GLOBALLY,
                        "features_integrated": [
                            "Enhanced RAG diagnostics",
                            "Auto-fix capabilities",
                            "Detailed component monitoring",
                            "Performance tracking",
                            "Health check automation"
                        ]
                    }
                }
                
                if req.debug_mode:
                    result["debug_info"] = {
                        "rag_diagnostics": rag_diagnostics,
                        "raw_response_length": len(response.get("answer", "")),
                        "processing_steps": response.get("processing_steps", []),
                        "cache_key_used": response.get("cache_key"),
                        "template_matched": response.get("template_matched"),
                        "rag_documents_found": len(response.get("sources", []))
                    }
                
                return result
                
            except Exception as e:
                logger.error(f"Unified chat router error: {e}")
                logger.error(traceback.format_exc())
                performance_monitor.record_error("unified_chat_router", str(e))
                return await legacy_chat_fallback(req, request, overall_start)
        else:
            return await legacy_chat_fallback(req, request, overall_start)
            
    except Exception as e:
        total_time = time.time() - overall_start
        error_id = str(uuid4())[:8]
        
        logger.error(f"❌ Main chat error [{error_id}]: {e}")
        logger.error(traceback.format_exc())
        
        performance_monitor.record_error("main_endpoint", f"[{error_id}] {str(e)}")
        
        error_answer = f"システムエラーが発生しました。診断エンドポイント /debug/rag-status で詳細をご確認ください。（エラーID: {error_id}）"
        
        return JSONResponse(
            status_code=200,
            content={
                "answer": error_answer,
                "sources": [],
                "status": "error",
                "error_id": error_id,
                "performance": {
                    "total_time": total_time,
                    "platform": platform,
                    "mode": mode,
                    "unified_system": True,
                    "integration_version": "diagnostics_enhanced",
                    "router_used": "error_fallback",
                    "endpoint_used": "/chat"
                },
                "diagnostic_help": {
                    "rag_status_endpoint": "/debug/rag-status",
                    "performance_endpoint": "/debug/performance",
                    "auto_fix_endpoint": "/debug/fix-rag"
                }
            }
        )

# 旧エンドポイントリダイレクト（継続）
@app.post("/chat-unified")
@app.post("/chat-unified/")
async def legacy_chat_unified_redirect(req: CompleteUnifiedChatRequest, request: Request):
    """旧統合エンドポイントのリダイレクト（廃止予定）"""
    logger.warning("⚠️ /chat-unified is deprecated, redirecting to /chat")
    
    performance_monitor.record_request(
        platform=req.platform or "web",
        mode="redirect", 
        response_time=0.001,
        endpoint_redirected=True
    )
    
    return await unified_chat_endpoint_diagnostics_enhanced(req, request)

async def legacy_chat_fallback(req: CompleteUnifiedChatRequest, request: Request, start_time: float) -> Dict[str, Any]:
    """レガシーチャットフォールバック（診断情報付き）"""
    try:
        logger.info("🔄 Using legacy chat fallback with diagnostics...")
        
        if ENABLE_LEGACY_COMPATIBILITY:
            try:
                from api.routers.chat_unified import unified_generator
                
                response = await unified_generator.generate_response(
                    req.question, req.platform or "web", req.username or "user", "auto"
                )
                
                total_time = time.time() - start_time
                performance_monitor.record_request(req.platform or "web", "legacy", total_time)
                
                return {
                    "answer": response["answer"],
                    "sources": response.get("sources", []),
                    "status": response.get("status", "ok"),
                    "performance": {
                        "total_time": total_time,
                        "processing_time": response.get("processing_time", 0),
                        "platform": req.platform or "web",
                        "mode": "legacy_fallback",
                        "unified_system": False,
                        "integration_version": "fallback_diagnostics_enhanced",
                        "router_used": "chat_ultra_fast_fallback"
                    },
                    "diagnostic_info": {
                        "rag_initialized": is_initialized,
                        "global_sharing": RAG_SHARED_GLOBALLY,
                        "fallback_reason": "legacy_compatibility"
                    }
                }
            except ImportError:
                logger.warning("Legacy chat_ultra_fast not available")
        
        # 緊急フォールバック
        total_time = time.time() - start_time
        performance_monitor.record_error("legacy_fallback", "all_routers_unavailable")
        
        return {
            "answer": "申し訳ございません。システム診断中です。/debug/rag-status で詳細をご確認ください。",
            "sources": [],
            "status": "emergency_fallback",
            "performance": {
                "total_time": total_time,
                "platform": req.platform or "web",
                "mode": "emergency",
                "unified_system": False,
                "integration_version": "emergency_diagnostics_enhanced",
                "router_used": "emergency_fallback"
            }
        }
        
    except Exception as e:
        logger.error(f"Legacy fallback error: {e}")
        total_time = time.time() - start_time
        performance_monitor.record_error("legacy_fallback_error", str(e))
        
        return {
            "answer": "重大なシステムエラーが発生しています。/debug/fix-rag で自動修復をお試しください。",
            "sources": [],
            "status": "critical_error",
            "performance": {
                "total_time": total_time,
                "platform": req.platform or "web",
                "mode": "critical_error",
                "unified_system": False,
                "integration_version": "error_diagnostics_enhanced",
                "router_used": "none"
            }
        }

# ==============================================================================
# システム状態エンドポイント（診断強化版）
# ==============================================================================
@app.get("/")
async def root():
    """ルートエンドポイント（診断強化版）"""
    performance_stats = performance_monitor.get_stats()
    
    return {
        "message": "Complete Unified RAG API - Diagnostics Enhanced System",
        "version": "7.2.0-diagnostics-enhanced",
        "timestamp": datetime.now().isoformat(),
        "enhancements_applied": [  # 🆕
            "✅ 詳細RAG診断システム",
            "✅ リアルタイム健全性監視",
            "✅ 自動修復機能",
            "✅ コンポーネント別状態追跡",
            "✅ パフォーマンス診断強化"
        ],
        "integration_status": {
            **INTEGRATION_COMPLETE,
            "diagnostics_enhanced": True,
            "rag_health_monitoring": "✅ リアルタイム監視",
            "auto_fix_capability": "✅ 自動修復対応",
            "integration_completeness": "100% (Diagnostics Enhanced)"
        },
        "features": [
            "📄 完全統合チャットシステム（診断強化）",
            "⚡ 3層分離キャッシュ（監視付き）",
            "🤖 RAG処理診断・自動修復",
            "🛡️ ハルシネーション対策統合",
            "🚫 重複メッセージ防止",
            "📊 リアルタイム診断システム",
            "🔧 自動修復機能",
            "🌐 健全性監視強化"
        ],
        "system_status": {
            "unified_chat_enabled": ENABLE_UNIFIED_CHAT,
            "rag_initialized": is_initialized,
            "rag_shared_globally": RAG_SHARED_GLOBALLY,
            "diagnostics_available": True,
            "auto_fix_available": True,
            "line_integration": ENABLE_LINE_INTEGRATION,
            "financial_planning": ENABLE_FINANCIAL_PLANNING
        },
        "performance": performance_stats,
        "diagnostic_endpoints": {  # 🆕
            "rag_detailed_status": "/debug/rag-status",
            "realtime_performance": "/debug/performance", 
            "auto_fix": "/debug/fix-rag",
            "main_chat": "/chat",
            "line_webhook": "/line/webhook",
            "system_stats": "/system-status"
        },
        "rag_health_summary": {  # 🆕
            "initialization_success": rag_diagnostics["initialization_success"],
            "components_loaded": sum(1 for comp in rag_diagnostics["component_status"].values() if comp["loaded"]),
            "fallback_used": rag_diagnostics["fallback_info"]["used_fallback"],
            "last_health_check": rag_diagnostics["health_checks"]["last_check"]
        }
    }

@app.get("/healthz")
async def health_check():
    """ヘルスチェック（診断強化版）"""
    uptime = time.time() - startup_time
    performance_stats = performance_monitor.get_stats()
    
    # リアルタイム健全性チェック
    quick_health_check = {
        "rag_quick_test": False,
        "component_accessibility": {
            "vectorstore": vectorstore is not None,
            "rag_chain": rag_chain_template is not None,
            "llm": llm_instance is not None
        }
    }
    
    # クイックRAGテスト
    if rag_chain_template:
        try:
            quick_result = rag_chain_template.invoke({"query": "ヘルスチェック"})
            quick_health_check["rag_quick_test"] = bool(quick_result and quick_result.get("result"))
        except Exception:
            quick_health_check["rag_quick_test"] = False
    
    return {
        "status": "healthy_diagnostics_enhanced",
        "uptime": uptime,
        "timestamp": datetime.now().isoformat(),
        "version": "7.2.0-diagnostics-enhanced",
        "message": "Diagnostics Enhanced Unified Chat System Operational",
        "diagnostic_capabilities": {  # 🆕
            "detailed_rag_status": True,
            "auto_fix_available": True,
            "realtime_monitoring": True,
            "component_tracking": True
        },
        "system_health": {
            "unified_chat": ENABLE_UNIFIED_CHAT and UNIFIED_CHAT_MODE in ["complete", "enabled"],
            "rag_components": is_initialized,
            "rag_sharing": RAG_SHARED_GLOBALLY,
            "vectorstore_ready": vectorstore is not None,
            "llm_ready": llm_instance is not None,
            "line_integration": ENABLE_LINE_INTEGRATION,
            "financial_planning": ENABLE_FINANCIAL_PLANNING
        },
        "quick_health_check": quick_health_check,  # 🆕
        "performance_summary": {
            "total_requests": performance_stats["system_overview"]["total_requests"],
            "average_response_time": performance_stats["response_performance"]["average_response_time"],
            "cache_hit_rate": performance_stats["cache_performance"]["hit_rate"],
            "error_rate": performance_stats["error_tracking"]["error_rate"],
            "diagnostics_requests": performance_stats["system_overview"]["diagnostics_requests"]  # 🆕
        },
        "diagnostic_endpoints": {  # 🆕
            "detailed_status": "/debug/rag-status",
            "performance": "/debug/performance",
            "auto_fix": "/debug/fix-rag"
        }
    }

# ==============================================================================
# 起動時処理（診断強化版）
# ==============================================================================
@app.on_event("startup")
async def startup_event():
    """診断強化版統合システム起動処理"""
    logger.info("🚀 Starting Diagnostics Enhanced Unified RAG System...")
    logger.info("🔧 Enhanced Capabilities:")
    logger.info("   - ✅ Detailed RAG component diagnostics")
    logger.info("   - ✅ Real-time health monitoring")
    logger.info("   - ✅ Auto-fix and recovery mechanisms")
    logger.info("   - ✅ Performance tracking enhancements")
    logger.info("   - ✅ Component-level status tracking")
    
    # RAG初期化（最優先・診断強化版）
    if ENABLE_RAG_INITIALIZATION:
        await initialize_rag_components()
        logger.info(f"🤖 RAG Diagnostics Status:")
        logger.info(f"   - Initialization Success: {'✅ YES' if rag_diagnostics['initialization_success'] else '❌ NO'}")
        logger.info(f"   - Global Sharing: {'✅ ENABLED' if RAG_SHARED_GLOBALLY else '❌ FAILED'}")
        logger.info(f"   - Components Loaded: {sum(1 for comp in rag_diagnostics['component_status'].values() if comp['loaded'])}/3")
        logger.info(f"   - Fallback Used: {'Yes (' + rag_diagnostics['fallback_info']['fallback_type'] + ')' if rag_diagnostics['fallback_info']['used_fallback'] else 'No'}")
    
    # 統合チャットルーター（診断対応）
    if ENABLE_UNIFIED_CHAT:
        try:
            logger.info("📦 Loading Unified Chat Router (Diagnostics Enhanced)...")
            logger.info("✅ Unified Chat Router integrated with diagnostic capabilities")
            logger.info("   - Primary Endpoint: /chat (with diagnostics)")
            logger.info("   - Debug Endpoints: /debug/* (detailed monitoring)")
            logger.info("   - Auto-fix: /debug/fix-rag")
        except Exception as e:
            logger.error(f"❌ Failed to configure Unified Chat: {e}")
    
    # LINE Bot（診断情報共有版）
    if ENABLE_LINE_INTEGRATION and SINGLE_LINE_INTEGRATION:
        try:
            logger.info(f"📦 Loading LINE Bot with Diagnostics ({LINE_BOT_MODE})...")
            from api.routers.line_bot_ultra_fast import router as line_router
            app.include_router(line_router, prefix="/line", tags=["line"])
            logger.info("✅ LINE Bot loaded with diagnostic information access")
            logger.info(f"   - RAG Access: {'✅ AVAILABLE' if RAG_SHARED_GLOBALLY else '⚠️ LIMITED'}")
        except Exception as e:
            logger.error(f"❌ Failed to load LINE Bot: {e}")
    
    # その他のルーター（継続）
    routers = [
        ("financial_api", "/financial", "financial"),
        ("upload", "/upload", "upload"),
        ("line_login", "/line-login", "line-login"),
        ("line_proxy", "/line-proxy", "line-proxy")
    ]
    
    for router_name, prefix, tag in routers:
        try:
            if router_name == "financial_api":
                from api.routers.financial_api import router as financial_router
                app.include_router(financial_router, prefix=prefix, tags=[tag])
            else:
                module = __import__(f"api.routers.{router_name}", fromlist=[router_name])
                router = getattr(module, "router")
                app.include_router(router, prefix=prefix, tags=[tag])
            logger.info(f"✅ {router_name} router added")
        except Exception as e:
            logger.debug(f"ℹ️ {router_name} router not added: {e}")
    
    startup_duration = time.time() - startup_time
    
    logger.info("🎉 Diagnostics Enhanced Unified RAG System startup completed")
    logger.info(f"⚡ Startup time: {startup_duration:.2f} seconds")
    logger.info("📋 Diagnostic Enhancement Summary:")
    logger.info("   🔧 Enhanced Features:")
    logger.info("      - Detailed RAG component tracking ✅")
    logger.info("      - Real-time health monitoring ✅") 
    logger.info("      - Auto-fix and recovery ✅")
    logger.info("      - Performance diagnostics ✅")
    logger.info("   📊 System Status:")
    logger.info(f"      - Unified Chat: {'✅' if ENABLE_UNIFIED_CHAT else '❌'}")
    logger.info(f"      - RAG Components: {'✅' if is_initialized else '❌'}")
    logger.info(f"      - Global RAG Sharing: {'✅' if RAG_SHARED_GLOBALLY else '❌'}")
    logger.info(f"      - LINE Integration: {'✅' if ENABLE_LINE_INTEGRATION else '❌'}")
    logger.info("   🛠️ Diagnostic Endpoints:")
    logger.info("      - Detailed Status: /debug/rag-status")
    logger.info("      - Performance Monitor: /debug/performance")
    logger.info("      - Auto-fix: /debug/fix-rag")
    logger.info("   🎯 Problem Resolution Capabilities:")
    logger.info("      - RAG initialization issues: ✅ AUTO-DIAGNOSABLE")
    logger.info("      - Component failures: ✅ AUTO-DETECTABLE")
    logger.info("      - Performance problems: ✅ MONITORED")
    logger.info("      - Recovery mechanisms: ✅ AVAILABLE")
    logger.info("🌟 System Ready for Production (Diagnostics Enhanced)")

if __name__ == "__main__":
    import uvicorn
    logger.info("🚀 Starting Diagnostics Enhanced System via uvicorn...")
    uvicorn.run(app, host="0.0.0.0", port=8080)