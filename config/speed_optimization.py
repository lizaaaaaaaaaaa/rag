import os
import time
import logging
from typing import Dict, Any, List, Optional
from collections import deque
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class SpeedOptimizationConfig:
    """速度最適化設定管理クラス（完全修正版）"""
    
    # ==============================================================================
    # 🚀 環境変数から設定読み込み（.env.recommended準拠）
    # ==============================================================================
    
    # テンプレート優先設定（リッチメニュー対応）
    TEMPLATE_PRIORITY = os.environ.get("TEMPLATE_PRIORITY", "false").lower() == "true"
    ENABLE_RAG_AVOIDANCE = os.environ.get("ENABLE_RAG_AVOIDANCE", "false").lower() == "true"
    
    # RAG最適化
    OPTIMIZED_SEARCH_K = int(os.environ.get("OPTIMIZED_SEARCH_K", "4"))
    OPTIMIZED_RAG_TIMEOUT = float(os.environ.get("OPTIMIZED_RAG_TIMEOUT", "8"))
    
    # 外部サービス（デフォルトOFF）
    ENABLE_WEB_SEARCH = os.environ.get("ENABLE_WEB_SEARCH", "false").lower() == "true"
    ENABLE_ANTI_HALLUCINATION = os.environ.get("ENABLE_ANTI_HALLUCINATION", "false").lower() == "true"
    
    # リランキング
    RERANK_TOPN = int(os.environ.get("RERANK_TOPN", "3"))
    
    # ローカルLLM（デフォルトOFF）
    USE_LOCAL_LLM = os.environ.get("USE_LOCAL_LLM", "false").lower() == "true"
    
    # LINE専用設定
    LINE_RAG_STRICT = os.environ.get("LINE_RAG_STRICT", "true").lower() == "true"
    LINE_USE_TEMPLATES_ONLY = os.environ.get("LINE_USE_TEMPLATES_ONLY", "true").lower() == "true"
    LINE_TEMPLATE_CACHE_TTL = int(os.environ.get("LINE_TEMPLATE_CACHE_TTL", "3600"))
    LINE_ALLOW_WEB_SEARCH = os.environ.get("LINE_ALLOW_WEB_SEARCH", "false").lower() == "true"
    
    # 検証設定
    ENABLE_VERIFICATION = os.environ.get("ENABLE_VERIFICATION", "false").lower() == "true"
    
    # フォールバック設定
    GRACEFUL_FALLBACK_LEVELS = os.environ.get("GRACEFUL_FALLBACK_LEVELS", "template,cache,rag").split(",")
    
    # ==============================================================================
    # 🚀 LLM最適化設定
    # ==============================================================================
    LLM_OPTIMIZATION = {
        "use_local_llm": USE_LOCAL_LLM,
        "max_tokens": 500 if not USE_LOCAL_LLM else 300,
        "request_timeout": 10,
        "temperature": 0.0,
        "streaming": False,  # ストリーミング無効（現状未実装）
        "model": "gpt-3.5-turbo-0125" if not USE_LOCAL_LLM else None
    }
    
    # ==============================================================================
    # 🚀 RAG最適化設定
    # ==============================================================================
    RAG_OPTIMIZATION = {
        "search_k": OPTIMIZED_SEARCH_K,
        "rag_timeout": OPTIMIZED_RAG_TIMEOUT,
        "enable_rag_avoidance": ENABLE_RAG_AVOIDANCE,
        "max_documents": 3,
        "similarity_threshold": 0.7,
        "enable_query_expansion": False,  # クエリ拡張OFF
        "enable_reranking": True,
        "rerank_topn": RERANK_TOPN
    }
    
    # ==============================================================================
    # 🚀 キャッシュ最適化設定
    # ==============================================================================
    CACHE_OPTIMIZATION = {
        "max_cache_size": 1000,
        "cache_expire_hours": 24,
        "enable_ultra_fast_cache": True,
        "cache_cleanup_interval": 300  # 5分
    }
    
    # ==============================================================================
    # 🚀 テンプレート最適化設定
    # ==============================================================================
    TEMPLATE_OPTIMIZATION = {
        "template_priority": TEMPLATE_PRIORITY,
        "enable_instant_templates": True,
        "max_template_length": 800,
        "line_template_length": 400,
        "force_template_for_richmenu": True
    }
    
    # ==============================================================================
    # 🚀 LINEボット最適化設定
    # ==============================================================================
    LINE_OPTIMIZATION = {
        "rag_strict": LINE_RAG_STRICT,
        "use_templates_only": LINE_USE_TEMPLATES_ONLY,
        "template_cache_ttl": LINE_TEMPLATE_CACHE_TTL,
        "allow_web_search": LINE_ALLOW_WEB_SEARCH,
        "duplicate_window": 60,
        "event_window": 10,
        "log_throttle_window": 300,
        "richmenu_instant_response": True
    }
    
    # ==============================================================================
    # 🚀 外部サービス設定
    # ==============================================================================
    EXTERNAL_SERVICES = {
        "web_search": {
            "enabled": ENABLE_WEB_SEARCH,
            "timeout": 5,
            "max_results": 3
        },
        "anti_hallucination": {
            "enabled": ENABLE_ANTI_HALLUCINATION,
            "timeout": 8,
            "strict_mode": True,
            "conditions_required": 2,
            "min_query_length": 30
        },
        "verification": {
            "enabled": ENABLE_VERIFICATION,
            "timeout": 5
        }
    }
    
    # ==============================================================================
    # 🚀 リッチメニュー専用設定
    # ==============================================================================
    RICHMENU_KEYWORDS = [
        "🤖 AI相談",
        "🌐 AI住まいサイト", 
        "📋 資料請求",
        "📍 展示場来場",
        "💰 資金計画",
        "💬 チャット相談",
        "AI相談",
        "AI住まいサイト",
        "資料請求",
        "展示場来場",
        "資金計画",
        "チャット相談"
    ]
    
    # ==============================================================================
    # 🚀 パフォーマンス目標
    # ==============================================================================
    PERFORMANCE_TARGETS = {
        "web_p95": 1.5,  # Web p95 ≤ 1.5秒
        "line_richmenu": 0.2,  # LINE押下 ≤ 0.2秒
        "rag_usage_increase": 0.2,  # RAG使用率20%以上増加
        "cache_hit_rate": 0.7,  # キャッシュヒット率70%
        "error_rate": 0.01  # エラー率1%以下
    }
    
    @classmethod
    def is_richmenu_action(cls, message_text: str) -> bool:
        """リッチメニューアクションかどうか判定"""
        if not message_text:
            return False
        
        message_stripped = message_text.strip()
        
        # 完全一致チェック
        for keyword in cls.RICHMENU_KEYWORDS:
            if message_stripped == keyword:
                return True
        
        # 部分一致チェック（短いキーワード）
        short_keywords = ["AI相談", "資料請求", "展示場来場", "資金計画", "チャット相談"]
        for keyword in short_keywords:
            if message_stripped == keyword or message_stripped.endswith(keyword):
                return True
        
        return False
    
    @classmethod
    def get_processing_strategy(cls, message_text: str, platform: str = "web") -> Dict[str, Any]:
        """メッセージに対する処理戦略を決定"""
        
        is_richmenu = cls.is_richmenu_action(message_text)
        
        if platform == "line":
            if is_richmenu:
                # LINEリッチメニュー：固定テンプレートのみ
                return {
                    "strategy": "richmenu_instant",
                    "use_template": True,
                    "use_rag": False,
                    "use_web_search": False,
                    "use_anti_hallucination": False,
                    "use_llm": False,
                    "max_response_time": 0.2,
                    "priority": "instant"
                }
            elif cls.LINE_USE_TEMPLATES_ONLY:
                # LINE通常：テンプレート優先
                return {
                    "strategy": "line_template_first",
                    "use_template": True,
                    "use_rag": cls.LINE_RAG_STRICT,
                    "use_web_search": cls.LINE_ALLOW_WEB_SEARCH,
                    "use_anti_hallucination": False,
                    "use_llm": True,
                    "max_response_time": 3.0,
                    "priority": "speed"
                }
            else:
                # LINE通常：RAG使用
                return {
                    "strategy": "line_rag",
                    "use_template": False,
                    "use_rag": True,
                    "use_web_search": cls.LINE_ALLOW_WEB_SEARCH,
                    "use_anti_hallucination": cls.ENABLE_ANTI_HALLUCINATION,
                    "use_llm": True,
                    "max_response_time": 5.0,
                    "priority": "accuracy"
                }
        else:
            # Web
            if cls.TEMPLATE_PRIORITY and not cls.ENABLE_RAG_AVOIDANCE:
                # テンプレート優先OFF、RAG回避OFF → RAG優先
                return {
                    "strategy": "web_rag_first",
                    "use_template": False,
                    "use_rag": True,
                    "use_web_search": cls.ENABLE_WEB_SEARCH,
                    "use_anti_hallucination": cls.ENABLE_ANTI_HALLUCINATION,
                    "use_llm": True,
                    "max_response_time": 8.0,
                    "priority": "accuracy"
                }
            else:
                # デフォルト
                return {
                    "strategy": "web_balanced",
                    "use_template": True,
                    "use_rag": True,
                    "use_web_search": cls.ENABLE_WEB_SEARCH,
                    "use_anti_hallucination": cls.ENABLE_ANTI_HALLUCINATION,
                    "use_llm": True,
                    "max_response_time": 5.0,
                    "priority": "balanced"
                }
    
    @classmethod
    def should_skip_rag(cls, message_text: str, platform: str = "web") -> bool:
        """RAGをスキップすべきか判定"""
        # リッチメニューは常にスキップ
        if cls.is_richmenu_action(message_text):
            return True
        
        # RAG回避が有効な場合
        if cls.ENABLE_RAG_AVOIDANCE:
            # 短い質問はスキップ
            if len(message_text) < 10:
                return True
            
            # テンプレートマッチする場合はスキップ
            template_keywords = ["こんにちは", "ありがとう", "はい", "いいえ"]
            if any(keyword in message_text for keyword in template_keywords):
                return True
        
        return False
    
    @classmethod
    def should_use_web_search(cls, message_text: str) -> bool:
        """Web検索を使用すべきか判定"""
        # 無効な場合
        if not cls.ENABLE_WEB_SEARCH:
            return False
        
        # リッチメニューは使用しない
        if cls.is_richmenu_action(message_text):
            return False
        
        # 最新情報を求める場合のみ
        search_triggers = ["最新", "今日", "現在", "ニュース", "2024", "2025"]
        return any(trigger in message_text for trigger in search_triggers)
    
    @classmethod
    def should_use_anti_hallucination(cls, message_text: str) -> bool:
        """アンチハルシネーション対策を使用すべきか判定"""
        # 無効な場合
        if not cls.ENABLE_ANTI_HALLUCINATION:
            return False
        
        # リッチメニューは使用しない
        if cls.is_richmenu_action(message_text):
            return False
        
        # 補助金関連の質問のみ
        subsidy_keywords = ["補助金", "助成金", "支援金", "ZEH", "エコ"]
        has_subsidy = any(keyword in message_text for keyword in subsidy_keywords)
        
        # 長さ条件
        is_long_enough = len(message_text) > 30
        
        return has_subsidy and is_long_enough
    
    @classmethod
    def get_fallback_chain(cls) -> List[str]:
        """フォールバックチェーン取得"""
        return cls.GRACEFUL_FALLBACK_LEVELS
    
    @classmethod
    def get_config_summary(cls) -> Dict[str, Any]:
        """設定サマリー取得"""
        return {
            "mode": "speed_optimized",
            "template_priority": cls.TEMPLATE_PRIORITY,
            "rag_avoidance": cls.ENABLE_RAG_AVOIDANCE,
            "rag_config": {
                "search_k": cls.OPTIMIZED_SEARCH_K,
                "timeout": cls.OPTIMIZED_RAG_TIMEOUT,
                "rerank_topn": cls.RERANK_TOPN
            },
            "external_services": {
                "web_search": cls.ENABLE_WEB_SEARCH,
                "anti_hallucination": cls.ENABLE_ANTI_HALLUCINATION,
                "verification": cls.ENABLE_VERIFICATION
            },
            "line_config": {
                "rag_strict": cls.LINE_RAG_STRICT,
                "templates_only": cls.LINE_USE_TEMPLATES_ONLY,
                "cache_ttl": cls.LINE_TEMPLATE_CACHE_TTL
            },
            "use_local_llm": cls.USE_LOCAL_LLM,
            "fallback_levels": cls.GRACEFUL_FALLBACK_LEVELS
        }
    
    @classmethod
    def validate_configuration(cls) -> Dict[str, Any]:
        """設定検証"""
        issues = []
        warnings = []
        
        # 速度最適化チェック
        if cls.TEMPLATE_PRIORITY and not cls.ENABLE_RAG_AVOIDANCE:
            warnings.append("TEMPLATE_PRIORITY=false but ENABLE_RAG_AVOIDANCE=false may slow Web responses")
        
        if cls.ENABLE_WEB_SEARCH:
            warnings.append("ENABLE_WEB_SEARCH=true may slow down responses")
        
        if cls.ENABLE_ANTI_HALLUCINATION:
            warnings.append("ENABLE_ANTI_HALLUCINATION=true may slow down responses")
        
        if cls.USE_LOCAL_LLM:
            warnings.append("USE_LOCAL_LLM=true significantly slows responses")
        
        if cls.OPTIMIZED_SEARCH_K > 5:
            warnings.append(f"OPTIMIZED_SEARCH_K={cls.OPTIMIZED_SEARCH_K} may be too high")
        
        if cls.OPTIMIZED_RAG_TIMEOUT > 10:
            warnings.append(f"OPTIMIZED_RAG_TIMEOUT={cls.OPTIMIZED_RAG_TIMEOUT} may cause timeouts")
        
        # LINE設定チェック
        if not cls.LINE_USE_TEMPLATES_ONLY and not cls.LINE_RAG_STRICT:
            issues.append("LINE configuration conflict: templates_only=false but rag_strict=false")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "optimization_level": cls._get_optimization_level()
        }
    
    @classmethod
    def _get_optimization_level(cls) -> str:
        """最適化レベル判定"""
        score = 0
        max_score = 7
        
        # スコア計算
        if not cls.TEMPLATE_PRIORITY and not cls.ENABLE_RAG_AVOIDANCE:
            score += 1  # RAG優先
        if not cls.ENABLE_WEB_SEARCH:
            score += 1
        if not cls.ENABLE_ANTI_HALLUCINATION:
            score += 1
        if not cls.USE_LOCAL_LLM:
            score += 1
        if cls.OPTIMIZED_SEARCH_K <= 4:
            score += 1
        if cls.OPTIMIZED_RAG_TIMEOUT <= 8:
            score += 1
        if cls.RERANK_TOPN <= 3:
            score += 1
        
        percentage = (score / max_score) * 100
        
        if percentage >= 85:
            return "maximum"
        elif percentage >= 70:
            return "high"
        elif percentage >= 50:
            return "medium"
        else:
            return "low"

# ==============================================================================
# パフォーマンス監視クラス
# ==============================================================================

class SpeedOptimizationMonitor:
    """速度最適化監視クラス"""
    
    def __init__(self):
        self.config = SpeedOptimizationConfig()
        self.response_times = deque(maxlen=1000)
        self.richmenu_times = deque(maxlen=100)
        self.web_times = deque(maxlen=500)
        self.line_times = deque(maxlen=500)
        
        self.stats = {
            "total_requests": 0,
            "richmenu_requests": 0,
            "template_hits": 0,
            "rag_hits": 0,
            "cache_hits": 0,
            "web_search_uses": 0,
            "anti_hallucination_uses": 0,
            "errors": 0,
            "timeouts": 0
        }
    
    def record_response(
        self,
        response_time: float,
        platform: str,
        source: str,
        is_richmenu: bool = False,
        cache_hit: bool = False,
        error: bool = False
    ):
        """応答記録"""
        self.stats["total_requests"] += 1
        
        # プラットフォーム別記録
        if platform == "line":
            self.line_times.append(response_time)
            if is_richmenu:
                self.richmenu_times.append(response_time)
                self.stats["richmenu_requests"] += 1
        else:
            self.web_times.append(response_time)
        
        # ソース別統計
        if source == "template":
            self.stats["template_hits"] += 1
        elif source == "rag":
            self.stats["rag_hits"] += 1
        
        if cache_hit:
            self.stats["cache_hits"] += 1
        
        if error:
            self.stats["errors"] += 1
        
        # 全体記録
        self.response_times.append({
            "time": response_time,
            "platform": platform,
            "source": source,
            "is_richmenu": is_richmenu,
            "timestamp": datetime.now()
        })
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """パフォーマンスメトリクス取得"""
        total = self.stats["total_requests"]
        if total == 0:
            return {"status": "no_data"}
        
        # 応答時間計算
        def calculate_percentile(times: List[float], percentile: float) -> float:
            if not times:
                return 0
            sorted_times = sorted(times)
            index = int(len(sorted_times) * percentile)
            return sorted_times[min(index, len(sorted_times)-1)]
        
        web_p95 = calculate_percentile(list(self.web_times), 0.95) if self.web_times else 0
        line_avg = sum(self.line_times) / len(self.line_times) if self.line_times else 0
        richmenu_avg = sum(self.richmenu_times) / len(self.richmenu_times) if self.richmenu_times else 0
        
        # RAG使用率
        rag_usage_rate = (self.stats["rag_hits"] / total) * 100
        
        # キャッシュヒット率
        cache_hit_rate = (self.stats["cache_hits"] / total) * 100
        
        # 目標達成状況
        targets_met = {
            "web_p95": web_p95 <= self.config.PERFORMANCE_TARGETS["web_p95"],
            "line_richmenu": richmenu_avg <= self.config.PERFORMANCE_TARGETS["line_richmenu"],
            "rag_usage": rag_usage_rate >= self.config.PERFORMANCE_TARGETS["rag_usage_increase"] * 100,
            "cache_hit": cache_hit_rate >= self.config.PERFORMANCE_TARGETS["cache_hit_rate"] * 100
        }
        
        return {
            "summary": {
                "total_requests": total,
                "error_rate": (self.stats["errors"] / total) * 100,
                "richmenu_percentage": (self.stats["richmenu_requests"] / total) * 100
            },
            "response_times": {
                "web_p95": round(web_p95, 3),
                "line_average": round(line_avg, 3),
                "richmenu_average": round(richmenu_avg, 3)
            },
            "usage_rates": {
                "rag_usage": round(rag_usage_rate, 1),
                "template_usage": round((self.stats["template_hits"] / total) * 100, 1),
                "cache_hit": round(cache_hit_rate, 1)
            },
            "targets_met": targets_met,
            "optimization_score": sum(targets_met.values()) / len(targets_met) * 100
        }

# グローバルモニターインスタンス
global_monitor = SpeedOptimizationMonitor()

# ヘルパー関数
def get_optimization_config() -> SpeedOptimizationConfig:
    """最適化設定取得"""
    return SpeedOptimizationConfig()

def record_performance(
    response_time: float,
    platform: str = "web",
    source: str = "unknown",
    is_richmenu: bool = False,
    cache_hit: bool = False,
    error: bool = False
):
    """パフォーマンス記録"""
    global_monitor.record_response(
        response_time=response_time,
        platform=platform,
        source=source,
        is_richmenu=is_richmenu,
        cache_hit=cache_hit,
        error=error
    )

def get_performance_report() -> Dict[str, Any]:
    """パフォーマンスレポート取得"""
    return {
        "configuration": SpeedOptimizationConfig.get_config_summary(),
        "metrics": global_monitor.get_performance_metrics(),
        "validation": SpeedOptimizationConfig.validate_configuration(),
        "timestamp": datetime.now().isoformat()
    }
