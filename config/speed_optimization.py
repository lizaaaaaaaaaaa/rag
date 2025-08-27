# config/speed_optimization.py - 速度最適化統合設定

import os
import time
import logging
from typing import Dict, Any, List
from collections import deque
from datetime import datetime, timedelta

class SpeedOptimizationConfig:
    """速度最適化設定管理クラス"""
    
    # ==============================================================================
    # 🚀 LLM最適化設定
    # ==============================================================================
    LLM_OPTIMIZATION = {
        "max_tokens": int(os.getenv("OPTIMIZED_MAX_TOKENS", "250")),  # 大幅削減
        "request_timeout": int(os.getenv("OPTIMIZED_REQUEST_TIMEOUT", "12")),  # 短縮
        "streaming": os.getenv("ENABLE_STREAMING", "true").lower() == "true",
        "temperature": float(os.getenv("OPTIMIZED_TEMPERATURE", "0.1")),
        "max_retries": int(os.getenv("OPTIMIZED_MAX_RETRIES", "2"))
    }
    
    # ==============================================================================
    # 🚀 RAG最適化設定（質問到着後のみ使用）
    # ==============================================================================
    RAG_OPTIMIZATION = {
        "search_k": int(os.getenv("OPTIMIZED_SEARCH_K", "1")),  # 削減：2→1
        "rag_timeout": int(os.getenv("OPTIMIZED_RAG_TIMEOUT", "6")),  # 削減：8→6秒
        "cache_expire_time": int(os.getenv("RAG_CACHE_EXPIRE", "1800")),  # 30分
        "enable_rag_avoidance": os.getenv("ENABLE_RAG_AVOIDANCE", "true").lower() == "true",
        "rag_usage_target": float(os.getenv("RAG_USAGE_TARGET", "0.05")),  # 5%以下
        "embedding_batch_size": int(os.getenv("EMBEDDING_BATCH_SIZE", "32")),
        "disable_for_richmenu": True,  # リッチメニュー押下時はRAG無効化
        "require_user_question": True   # ユーザー質問がある場合のみRAG使用
    }
    
    # ==============================================================================
    # 🚀 キャッシュ最適化設定
    # ==============================================================================
    CACHE_OPTIMIZATION = {
        "max_cache_size": int(os.getenv("OPTIMIZED_CACHE_SIZE", "2000")),  # 拡大
        "cache_expire_hours": int(os.getenv("CACHE_EXPIRE_HOURS", "1")),
        "enable_faq_preload": os.getenv("ENABLE_FAQ_PRELOAD", "true").lower() == "true",
        "cache_cleanup_interval": int(os.getenv("CACHE_CLEANUP_INTERVAL", "180"))  # 3分
    }
    
    # ==============================================================================
    # 🚀 テンプレート最適化設定（リッチメニュー優先）
    # ==============================================================================
    TEMPLATE_OPTIMIZATION = {
        "enable_instant_templates": os.getenv("ENABLE_INSTANT_TEMPLATES", "true").lower() == "true",
        "template_priority_over_rag": True,  # 常にテンプレート優先
        "max_template_length": int(os.getenv("MAX_TEMPLATE_LENGTH", "800")),
        "line_template_length": int(os.getenv("LINE_TEMPLATE_LENGTH", "400")),
        "force_template_for_richmenu": True,  # リッチメニューは強制的にテンプレート使用
        "richmenu_bypass_all": True  # リッチメニューは全処理をバイパス
    }
    
    # ==============================================================================
    # 🚀 LINEボット最適化設定（テンプレート即時応答）
    # ==============================================================================
    LINE_OPTIMIZATION = {
        "duplicate_window": int(os.getenv("LINE_DUPLICATE_WINDOW", "45")),  # 短縮
        "event_window": int(os.getenv("LINE_EVENT_WINDOW", "8")),
        "log_throttle_window": int(os.getenv("LINE_LOG_THROTTLE", "120")),  # ログ削減
        "rag_timeout": int(os.getenv("LINE_RAG_TIMEOUT", "3")),  # 超短縮
        "enable_ultra_strict_rag": os.getenv("LINE_ULTRA_STRICT_RAG", "true").lower() == "true",
        "richmenu_instant_response": True,  # リッチメニューは即時応答
        "richmenu_skip_rag": True,  # リッチメニューはRAGスキップ
        "richmenu_skip_search": True,  # リッチメニューは検索スキップ
        "richmenu_skip_llm": True  # リッチメニューはLLM処理スキップ
    }
    
    # ==============================================================================
    # 🚀 アンチハルチネーション最適化設定（質問到着後のみ）
    # ==============================================================================
    ANTI_HALLUCINATION_OPTIMIZATION = {
        "enable_strict_filtering": os.getenv("STRICT_ANTI_HALLUCINATION", "true").lower() == "true",
        "timeout_seconds": int(os.getenv("ANTI_HALLUCINATION_TIMEOUT", "8")),
        "conditions_required": int(os.getenv("ANTI_HALLUCINATION_CONDITIONS", "2")),  # 2/3条件
        "min_query_length": int(os.getenv("ANTI_HALLUCINATION_MIN_LENGTH", "30")),
        "enable_basic_filter_fallback": os.getenv("ENABLE_BASIC_FILTER", "true").lower() == "true",
        "disable_for_richmenu": True,  # リッチメニュー押下時は無効
        "require_user_question": True   # ユーザー質問がある場合のみ使用
    }
    
    # ==============================================================================
    # 🚀 Web検索最適化設定（質問到着後のみ）
    # ==============================================================================
    WEB_SEARCH_OPTIMIZATION = {
        "enable_web_search": os.getenv("ENABLE_WEB_SEARCH", "false").lower() == "true",
        "search_timeout": int(os.getenv("WEB_SEARCH_TIMEOUT", "5")),
        "max_results": int(os.getenv("WEB_SEARCH_MAX_RESULTS", "3")),
        "disable_for_richmenu": True,  # リッチメニュー押下時は無効
        "require_explicit_request": True,  # 明示的な要求時のみ検索
        "require_user_question": True  # ユーザー質問がある場合のみ使用
    }
    
    # ==============================================================================
    # 🚀 パフォーマンス目標設定
    # ==============================================================================
    PERFORMANCE_TARGETS = {
        "template_response_time": 0.3,      # 300ms以下（リッチメニュー用）
        "rag_response_time": 6.0,           # 6秒以下（質問応答用）
        "cache_hit_response_time": 0.1,     # 100ms以下
        "line_response_time": 0.5,          # 500ms以下（リッチメニュー）
        "template_hit_rate": 0.95,          # 95%以上（リッチメニュー）
        "rag_usage_rate": 0.05,             # 5%以下
        "cache_hit_rate": 0.70,             # 70%以上
        "anti_hallucination_usage": 0.02,   # 2%以下
        "richmenu_response_time": 0.2       # 200ms以下（超高速）
    }
    
    # ==============================================================================
    # 🚀 機能有効化制御
    # ==============================================================================
    FEATURE_FLAGS = {
        # 最適化機能
        "enable_speed_optimization": os.getenv("ENABLE_SPEED_OPTIMIZATION", "true").lower() == "true",
        "enable_rag_avoidance": os.getenv("ENABLE_RAG_AVOIDANCE", "true").lower() == "true",
        "enable_instant_templates": os.getenv("ENABLE_INSTANT_TEMPLATES", "true").lower() == "true",
        "enable_ultra_fast_cache": os.getenv("ENABLE_ULTRA_FAST_CACHE", "true").lower() == "true",
        
        # リッチメニュー専用フラグ
        "richmenu_force_template": True,  # リッチメニューは強制テンプレート
        "richmenu_skip_all_processing": True,  # リッチメニューは全処理スキップ
        "richmenu_instant_only": True,  # リッチメニューは即時応答のみ
        
        # デバッグ・監視
        "enable_performance_monitoring": os.getenv("ENABLE_PERF_MONITORING", "true").lower() == "true",
        "enable_detailed_logging": os.getenv("ENABLE_DETAILED_LOGGING", "false").lower() == "true",
        "log_slow_responses": os.getenv("LOG_SLOW_RESPONSES", "true").lower() == "true",
        "slow_response_threshold": float(os.getenv("SLOW_RESPONSE_THRESHOLD", "3.0")),
        
        # 互換性
        "enable_legacy_fallback": os.getenv("ENABLE_LEGACY_FALLBACK", "false").lower() == "true",
        "maintain_backward_compatibility": os.getenv("BACKWARD_COMPATIBILITY", "true").lower() == "true"
    }
    
    # ==============================================================================
    # 🚀 リッチメニュー専用設定
    # ==============================================================================
    RICHMENU_OPTIMIZATION = {
        "bypass_all": True,  # 全処理バイパス
        "template_only": True,  # テンプレートのみ使用
        "no_rag": True,  # RAG使用しない
        "no_search": True,  # 検索使用しない
        "no_llm": True,  # LLM使用しない
        "no_anti_hallucination": True,  # アンチハルシネーション使用しない
        "instant_response": True,  # 即時応答
        "max_response_time": 0.2  # 最大200ms
    }
    
    @classmethod
    def should_use_template_only(cls, message_text: str) -> bool:
        """テンプレートのみ使用すべきか判定"""
        # リッチメニューのキーワード
        richmenu_keywords = [
            "🤖 AI相談",
            "🌐 AI住まいサイト", 
            "📋 資料請求",
            "📍 展示場来場　予約",
            "💰 資金計画",
            "💬 チャット相談"
        ]
        
        # リッチメニューボタンの場合は常にテンプレート
        for keyword in richmenu_keywords:
            if keyword in message_text:
                return True
        
        return False
    
    @classmethod
    def should_skip_rag(cls, message_text: str) -> bool:
        """RAGをスキップすべきか判定"""
        # リッチメニューボタンの場合は常にスキップ
        if cls.should_use_template_only(message_text):
            return True
        
        # その他の条件でもRAGスキップ判定
        if cls.RAG_OPTIMIZATION.get("disable_for_richmenu"):
            return cls.should_use_template_only(message_text)
        
        return False
    
    @classmethod
    def should_skip_web_search(cls, message_text: str) -> bool:
        """Web検索をスキップすべきか判定"""
        # リッチメニューボタンの場合は常にスキップ
        if cls.should_use_template_only(message_text):
            return True
        
        # Web検索は明示的な要求がない限りスキップ
        if cls.WEB_SEARCH_OPTIMIZATION.get("require_explicit_request"):
            search_keywords = ["最新", "ニュース", "現在", "今"]
            return not any(keyword in message_text for keyword in search_keywords)
        
        return False
    
    @classmethod
    def should_skip_anti_hallucination(cls, message_text: str) -> bool:
        """アンチハルシネーションをスキップすべきか判定"""
        # リッチメニューボタンの場合は常にスキップ
        if cls.should_use_template_only(message_text):
            return True
        
        # 短い質問の場合もスキップ
        if len(message_text) < cls.ANTI_HALLUCINATION_OPTIMIZATION.get("min_query_length", 30):
            return True
        
        return False
    
    @classmethod
    def get_processing_flags(cls, message_text: str) -> Dict[str, bool]:
        """メッセージに対する処理フラグを取得"""
        is_richmenu = cls.should_use_template_only(message_text)
        
        return {
            "use_template_only": is_richmenu,
            "skip_rag": is_richmenu or cls.should_skip_rag(message_text),
            "skip_web_search": is_richmenu or cls.should_skip_web_search(message_text),
            "skip_anti_hallucination": is_richmenu or cls.should_skip_anti_hallucination(message_text),
            "skip_llm": is_richmenu,
            "instant_response": is_richmenu,
            "is_richmenu": is_richmenu
        }
    
    @classmethod
    def get_all_settings(cls) -> Dict[str, Any]:
        """全設定取得"""
        return {
            "llm_optimization": cls.LLM_OPTIMIZATION,
            "rag_optimization": cls.RAG_OPTIMIZATION,
            "cache_optimization": cls.CACHE_OPTIMIZATION,
            "template_optimization": cls.TEMPLATE_OPTIMIZATION,
            "line_optimization": cls.LINE_OPTIMIZATION,
            "anti_hallucination_optimization": cls.ANTI_HALLUCINATION_OPTIMIZATION,
            "web_search_optimization": cls.WEB_SEARCH_OPTIMIZATION,
            "richmenu_optimization": cls.RICHMENU_OPTIMIZATION,
            "performance_targets": cls.PERFORMANCE_TARGETS,
            "feature_flags": cls.FEATURE_FLAGS
        }
    
    @classmethod
    def validate_settings(cls) -> Dict[str, Any]:
        """設定値検証"""
        warnings = []
        errors = []
        
        # LLM設定検証
        if cls.LLM_OPTIMIZATION["max_tokens"] > 500:
            warnings.append("max_tokens > 500 may cause slow responses")
        if cls.LLM_OPTIMIZATION["request_timeout"] > 15:
            warnings.append("request_timeout > 15s may cause user experience issues")
        
        # RAG設定検証（質問応答時のみ使用）
        if not cls.RAG_OPTIMIZATION["disable_for_richmenu"]:
            warnings.append("RAG should be disabled for richmenu responses")
        
        # リッチメニュー設定検証
        if not cls.RICHMENU_OPTIMIZATION["template_only"]:
            errors.append("Richmenu must use template only")
        
        return {
            "status": "error" if errors else "warning" if warnings else "valid",
            "errors": errors,
            "warnings": warnings
        }
    
    @classmethod
    def get_environment_template(cls) -> str:
        """環境変数テンプレート生成"""
        return """# Speed Optimization Configuration Template
# Copy to .env file and adjust values as needed

# LLM Optimization
OPTIMIZED_MAX_TOKENS=250
OPTIMIZED_REQUEST_TIMEOUT=12
ENABLE_STREAMING=true
OPTIMIZED_TEMPERATURE=0.1
OPTIMIZED_MAX_RETRIES=2

# RAG Optimization (User questions only)
OPTIMIZED_SEARCH_K=1
OPTIMIZED_RAG_TIMEOUT=6
RAG_CACHE_EXPIRE=1800
ENABLE_RAG_AVOIDANCE=true
RAG_USAGE_TARGET=0.05
EMBEDDING_BATCH_SIZE=32

# Cache Optimization
OPTIMIZED_CACHE_SIZE=2000
CACHE_EXPIRE_HOURS=1
ENABLE_FAQ_PRELOAD=true
CACHE_CLEANUP_INTERVAL=180

# Template Optimization (Richmenu priority)
ENABLE_INSTANT_TEMPLATES=true
TEMPLATE_PRIORITY=true
MAX_TEMPLATE_LENGTH=800
LINE_TEMPLATE_LENGTH=400

# LINE Bot Optimization
LINE_DUPLICATE_WINDOW=45
LINE_EVENT_WINDOW=8
LINE_LOG_THROTTLE=120
LINE_RAG_TIMEOUT=3
LINE_ULTRA_STRICT_RAG=true

# Anti-Hallucination Optimization (User questions only)
STRICT_ANTI_HALLUCINATION=true
ANTI_HALLUCINATION_TIMEOUT=8
ANTI_HALLUCINATION_CONDITIONS=2
ANTI_HALLUCINATION_MIN_LENGTH=30
ENABLE_BASIC_FILTER=true

# Web Search (User questions only)
ENABLE_WEB_SEARCH=false
WEB_SEARCH_TIMEOUT=5
WEB_SEARCH_MAX_RESULTS=3

# Performance Monitoring
ENABLE_PERF_MONITORING=true
ENABLE_DETAILED_LOGGING=false
LOG_SLOW_RESPONSES=true
SLOW_RESPONSE_THRESHOLD=3.0

# Feature Flags
ENABLE_SPEED_OPTIMIZATION=true
ENABLE_RAG_AVOIDANCE=true
ENABLE_ULTRA_FAST_CACHE=true
BACKWARD_COMPATIBILITY=true
"""

# ==============================================================================
# パフォーマンス監視クラス
# ==============================================================================

class SpeedOptimizationMonitor:
    """速度最適化監視クラス"""
    
    def __init__(self):
        self.config = SpeedOptimizationConfig()
        self.logger = logging.getLogger(__name__)
        
        # メトリクス収集
        self.response_times = deque(maxlen=1000)
        self.slow_responses = deque(maxlen=100)
        self.optimization_stats = {
            "total_requests": 0,
            "template_hits": 0,
            "rag_hits": 0,
            "cache_hits": 0,
            "rag_avoided": 0,
            "anti_hallucination_used": 0,
            "slow_responses": 0,
            "richmenu_responses": 0,
            "user_question_responses": 0
        }
        
    def record_response(self, response_time: float, source: str, optimizations: Dict[str, Any] = None):
        """応答記録"""
        self.response_times.append({
            "time": response_time,
            "source": source,
            "timestamp": datetime.now(),
            "optimizations": optimizations or {}
        })
        
        self.optimization_stats["total_requests"] += 1
        
        # ソース別統計
        if source.startswith("template"):
            self.optimization_stats["template_hits"] += 1
        elif source.startswith("rag"):
            self.optimization_stats["rag_hits"] += 1
        elif source == "cache":
            self.optimization_stats["cache_hits"] += 1
        
        if optimizations:
            if optimizations.get("rag_avoided"):
                self.optimization_stats["rag_avoided"] += 1
            if optimizations.get("anti_hallucination_used"):
                self.optimization_stats["anti_hallucination_used"] += 1
            if optimizations.get("is_richmenu"):
                self.optimization_stats["richmenu_responses"] += 1
            else:
                self.optimization_stats["user_question_responses"] += 1
        
        # 遅延応答記録（リッチメニューは別基準）
        threshold = 0.5 if optimizations and optimizations.get("is_richmenu") else self.config.FEATURE_FLAGS["slow_response_threshold"]
        if response_time > threshold:
            self.optimization_stats["slow_responses"] += 1
            self.slow_responses.append({
                "time": response_time,
                "source": source,
                "timestamp": datetime.now(),
                "optimizations": optimizations
            })
            
            if self.config.FEATURE_FLAGS["log_slow_responses"]:
                self.logger.warning(f"🐌 Slow response: {response_time:.2f}s, source: {source}")
    
    def get_performance_report(self) -> Dict[str, Any]:
        """パフォーマンスレポート取得"""
        if not self.response_times:
            return {"status": "no_data"}
        
        # 基本統計計算
        response_times_only = [r["time"] for r in self.response_times]
        avg_response_time = sum(response_times_only) / len(response_times_only)
        median_response_time = sorted(response_times_only)[len(response_times_only) // 2]
        p95_response_time = sorted(response_times_only)[int(len(response_times_only) * 0.95)]
        
        total = self.optimization_stats["total_requests"]
        
        # 最適化効果計算
        template_rate = (self.optimization_stats["template_hits"] / total * 100) if total > 0 else 0
        rag_rate = (self.optimization_stats["rag_hits"] / total * 100) if total > 0 else 0
        cache_rate = (self.optimization_stats["cache_hits"] / total * 100) if total > 0 else 0
        rag_avoidance_rate = (self.optimization_stats["rag_avoided"] / total * 100) if total > 0 else 0
        richmenu_rate = (self.optimization_stats["richmenu_responses"] / total * 100) if total > 0 else 0
        
        # 目標達成状況
        targets = self.config.PERFORMANCE_TARGETS
        target_achievements = {
            "avg_response_time": "✅ ACHIEVED" if avg_response_time <= 2.0 else "❌ MISSED",
            "template_hit_rate": "✅ ACHIEVED" if template_rate >= targets["template_hit_rate"] * 100 else "❌ MISSED",
            "rag_usage": "✅ ACHIEVED" if rag_rate <= targets["rag_usage_rate"] * 100 else "❌ MISSED",
            "cache_hit_rate": "✅ ACHIEVED" if cache_rate >= targets["cache_hit_rate"] * 100 else "❌ MISSED"
        }
        
        return {
            "performance_metrics": {
                "avg_response_time": avg_response_time,
                "median_response_time": median_response_time,
                "p95_response_time": p95_response_time,
                "total_requests": total,
                "slow_responses": self.optimization_stats["slow_responses"],
                "richmenu_responses": self.optimization_stats["richmenu_responses"],
                "user_question_responses": self.optimization_stats["user_question_responses"]
            },
            "optimization_effectiveness": {
                "template_hit_rate": template_rate,
                "rag_usage_rate": rag_rate,
                "cache_hit_rate": cache_rate,
                "rag_avoidance_rate": rag_avoidance_rate,
                "richmenu_rate": richmenu_rate,
                "anti_hallucination_usage": (self.optimization_stats["anti_hallucination_used"] / total * 100) if total > 0 else 0
            },
            "target_achievements": target_achievements,
            "optimization_status": {
                "overall": "✅ OPTIMIZED" if all("✅" in v for v in target_achievements.values()) else "⚠️ NEEDS_IMPROVEMENT",
                "speed_grade": "A" if avg_response_time <= 1.0 else "B" if avg_response_time <= 2.0 else "C" if avg_response_time <= 3.0 else "D"
            },
            "recent_slow_responses": list(self.slow_responses)[-10:],  # 最新10件
            "timestamp": datetime.now().isoformat()
        }

# ==============================================================================
# グローバル監視インスタンス
# ==============================================================================
global_speed_monitor = SpeedOptimizationMonitor()

# ==============================================================================
# 最適化ヘルパー関数
# ==============================================================================

def apply_speed_optimizations():
    """速度最適化設定適用"""
    config = SpeedOptimizationConfig()
    
    if config.FEATURE_FLAGS["enable_speed_optimization"]:
        # 環境変数に最適化設定を反映
        optimizations = config.get_all_settings()
        
        logging.getLogger(__name__).info("🚀 Speed optimizations applied:")
        logging.getLogger(__name__).info(f"   - Max tokens: {optimizations['llm_optimization']['max_tokens']}")
        logging.getLogger(__name__).info(f"   - RAG timeout: {optimizations['rag_optimization']['rag_timeout']}s")
        logging.getLogger(__name__).info(f"   - Cache size: {optimizations['cache_optimization']['max_cache_size']}")
        logging.getLogger(__name__).info(f"   - RAG avoidance: {optimizations['rag_optimization']['enable_rag_avoidance']}")
        logging.getLogger(__name__).info(f"   - Richmenu instant: {optimizations['richmenu_optimization']['instant_response']}")
        
        return True
    else:
        logging.getLogger(__name__).info("ℹ️ Speed optimization disabled by feature flag")
        return False

def check_optimization_health() -> Dict[str, Any]:
    """最適化健全性チェック"""
    config = SpeedOptimizationConfig()
    validation = config.validate_settings()
    monitor_report = global_speed_monitor.get_performance_report()
    
    return {
        "config_validation": validation,
        "performance_report": monitor_report,
        "recommendations": _generate_optimization_recommendations(monitor_report),
        "health_score": _calculate_optimization_health_score(monitor_report),
        "timestamp": datetime.now().isoformat()
    }

def _generate_optimization_recommendations(performance_report: Dict[str, Any]) -> List[str]:
    """最適化推奨事項生成"""
    recommendations = []
    
    if performance_report.get("status") == "no_data":
        return ["System needs more usage data for recommendations"]
    
    metrics = performance_report["performance_metrics"]
    effectiveness = performance_report["optimization_effectiveness"]
    
    # リッチメニュー応答に基づく推奨
    if effectiveness.get("richmenu_rate", 0) > 0:
        richmenu_responses = metrics.get("richmenu_responses", 0)
        if richmenu_responses > 0:
            recommendations.append("✅ Richmenu responses using instant templates")
    
    # 応答時間に基づく推奨
    if metrics["avg_response_time"] > 3.0:
        recommendations.append("🚀 Consider reducing RAG timeout further for user questions")
        recommendations.append("📈 Increase template coverage")
    
    # キャッシュ効率に基づく推奨
    if effectiveness["cache_hit_rate"] < 60:
        recommendations.append("💾 Increase cache size or improve cache key normalization")
    
    # RAG使用率に基づく推奨（ユーザー質問のみ）
    if effectiveness["rag_usage_rate"] > 10:
        recommendations.append("🚫 RAG usage high for user questions - review query patterns")
    
    # 遅延応答に基づく推奨
    if metrics["slow_responses"] > metrics["total_requests"] * 0.1:
        recommendations.append("⏰ Review timeout settings")
        recommendations.append("🔧 Check system resource allocation")
    
    if not recommendations:
        recommendations.append("✅ System performing optimally")
    
    return recommendations

def _calculate_optimization_health_score(performance_report: Dict[str, Any]) -> Dict[str, Any]:
    """最適化健全性スコア算出"""
    if performance_report.get("status") == "no_data":
        return {"score": 0, "grade": "N/A", "status": "insufficient_data"}
    
    achievements = performance_report["target_achievements"]
    achieved_count = sum(1 for v in achievements.values() if "✅" in v)
    total_targets = len(achievements)
    
    score = (achieved_count / total_targets) * 100
    
    if score >= 90:
        grade = "A+"
        status = "excellent"
    elif score >= 80:
        grade = "A"
        status = "very_good"
    elif score >= 70:
        grade = "B"
        status = "good"
    elif score >= 60:
        grade = "C"
        status = "needs_improvement"
    else:
        grade = "D"
        status = "requires_attention"
    
    return {
        "score": score,
        "grade": grade,
        "status": status,
        "achieved_targets": achieved_count,
        "total_targets": total_targets
    }

if __name__ == "__main__":
    # 設定テスト
    config = SpeedOptimizationConfig()
    
    print("🚀 Speed Optimization Configuration Test")
    print("=" * 50)
    
    # リッチメニューメッセージテスト
    test_messages = [
        "🤖 AI相談",
        "🌐 AI住まいサイト",
        "普通の質問です",
        "最新のニュースを教えて"
    ]
    
    print("\nMessage Processing Flags Test:")
    for msg in test_messages:
        flags = config.get_processing_flags(msg)
        print(f"\nMessage: {msg}")
        print(f"  Flags: {flags}")
    
    # 設定値表示
    settings = config.get_all_settings()
    for category, values in settings.items():
        print(f"\n{category.upper()}:")
        for key, value in values.items():
            print(f"  {key}: {value}")
    
    # 設定検証
    validation = config.validate_settings()
    print(f"\nValidation Status: {validation['status']}")
    if validation['warnings']:
        print("Warnings:")
        for warning in validation['warnings']:
            print(f"  ⚠️ {warning}")
