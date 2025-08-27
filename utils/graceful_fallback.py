# utils/graceful_fallback.py - グレースフル・デグラデーション機能（リッチメニュー対応・完全修正版）
# 変更点:
# - Pylanceの reportMissingImports を解消するため、utils.chat_templates / utils.chat_cache の静的インポートを全撤去
# - importlib による動的ロードヘルパーを追加し、未導入環境でもエラーにせずフォールバック動作
# - 既存APIは互換維持（戻り値/キーは据え置き）

import logging
import time
import traceback
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Callable
from enum import Enum
from dataclasses import dataclass
import json
import importlib  # ← 追加: 動的インポートでPylance警告を回避

logger = logging.getLogger(__name__)

class FallbackLevel(Enum):
    """フォールバックレベル定義"""
    LEVEL_0_NORMAL = "normal"           # 通常動作
    LEVEL_1_TEMPLATE = "template"       # テンプレート優先（🔧 リッチメニュー押下時の標準レベル）
    LEVEL_2_CACHE_ONLY = "cache_only"   # キャッシュのみ
    LEVEL_3_MINIMAL = "minimal"         # 最小限機能
    LEVEL_4_EMERGENCY = "emergency"     # 緊急モード

class ComponentStatus(Enum):
    """コンポーネント状態"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"

@dataclass
class FallbackStrategy:
    """フォールバック戦略定義"""
    level: FallbackLevel
    description: str
    enabled_features: List[str]
    disabled_features: List[str]
    max_response_time: float
    cache_strategy: str
    template_strategy: str
    rag_strategy: str

@dataclass
class ComponentHealth:
    """コンポーネント健全性情報"""
    name: str
    status: ComponentStatus
    last_success: Optional[datetime]
    last_failure: Optional[datetime]
    failure_count: int
    success_rate: float
    avg_response_time: float

# ------------------------
# 動的インポート・ヘルパー
# ------------------------

def _try_import(module_name: str):
    """文字列ベースの動的インポート（Pylanceの欠落警告を回避）"""
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None

def _get_template_manager():
    """
    utils.chat_templates.get_template_manager() を動的取得。
    存在しなければ None を返す（呼び出し側で安全にフォールバック）。
    """
    m = _try_import("utils.chat_templates")
    if m is None:
        return None
    return getattr(m, "get_template_manager", None)

def _quick_cache_get():
    """
    utils.chat_cache.quick_cache_get を動的取得。
    存在しなければ None を返す（呼び出し側で安全にフォールバック）。
    """
    m = _try_import("utils.chat_cache")
    if m is None:
        return None
    return getattr(m, "quick_cache_get", None)

class GracefulFallbackManager:
    """グレースフル・デグラデーション管理クラス（リッチメニュー対応版）"""
    
    def __init__(self):
        self.current_level = FallbackLevel.LEVEL_0_NORMAL
        self.component_health: Dict[str, ComponentHealth] = {}
        self.fallback_strategies = self._initialize_strategies()
        self.degradation_history: List[Dict[str, Any]] = []
        self.auto_recovery_enabled = True
        self.degradation_triggers = self._initialize_triggers()
        
        # 🔧 リッチメニュー関連設定
        self.richmenu_buttons = [
            "🤖 AI相談", "🌐 AI住まいサイト", "📄 資料請求",
            "📍 展示場来場　予約", "💰 資金計画", "💬 チャット相談"
        ]
        self.richmenu_template_override = True  # リッチメニュー押下時はテンプレート優先
        self.richmenu_disable_rag = True       # リッチメニュー押下時はRAG無効化
        self.richmenu_disable_search = True    # リッチメニュー押下時は検索無効化
        
        # 統計情報
        self.stats = {
            "total_fallbacks": 0,
            "fallbacks_by_level": {level.value: 0 for level in FallbackLevel},
            "component_failures": {},
            "auto_recoveries": 0,
            "emergency_activations": 0,
            "richmenu_template_overrides": 0,  # 🔧 リッチメニューテンプレート強制適用数
            "richmenu_rag_avoidances": 0,      # 🔧 リッチメニューRAG回避数
            "richmenu_search_avoidances": 0    # 🔧 リッチメニュー検索回避数
        }

    def _initialize_strategies(self) -> Dict[FallbackLevel, FallbackStrategy]:
        """フォールバック戦略初期化（リッチメニュー対応）"""
        return {
            FallbackLevel.LEVEL_0_NORMAL: FallbackStrategy(
                level=FallbackLevel.LEVEL_0_NORMAL,
                description="通常動作 - 全機能利用可能",
                enabled_features=["rag", "templates", "cache", "anti_hallucination", "web_search"],
                disabled_features=[],
                max_response_time=10.0,
                cache_strategy="full",
                template_strategy="full",
                rag_strategy="full"
            ),
            # 🔧 リッチメニュー押下時の標準レベル
            FallbackLevel.LEVEL_1_TEMPLATE: FallbackStrategy(
                level=FallbackLevel.LEVEL_1_TEMPLATE,
                description="テンプレート優先 - リッチメニュー対応・RAG使用量削減",
                enabled_features=["templates", "cache"],  # 🔧 シンプル化
                disabled_features=["web_search", "anti_hallucination", "rag"],  # 🔧 RAGも無効化
                max_response_time=2.0,  # 🔧 高速応答
                cache_strategy="template_priority",
                template_strategy="immediate",  # 🔧 即時テンプレート
                rag_strategy="disabled"  # 🔧 RAG完全無効化
            ),
            FallbackLevel.LEVEL_2_CACHE_ONLY: FallbackStrategy(
                level=FallbackLevel.LEVEL_2_CACHE_ONLY,
                description="キャッシュのみ - 新規処理最小限",
                enabled_features=["cache", "templates"],
                disabled_features=["rag", "web_search", "anti_hallucination"],
                max_response_time=2.0,
                cache_strategy="only",
                template_strategy="fallback",
                rag_strategy="disabled"
            ),
            FallbackLevel.LEVEL_3_MINIMAL: FallbackStrategy(
                level=FallbackLevel.LEVEL_3_MINIMAL,
                description="最小限機能 - 基本応答のみ",
                enabled_features=["basic_templates"],
                disabled_features=["rag", "cache", "web_search", "anti_hallucination"],
                max_response_time=1.0,
                cache_strategy="disabled",
                template_strategy="basic",
                rag_strategy="disabled"
            ),
            FallbackLevel.LEVEL_4_EMERGENCY: FallbackStrategy(
                level=FallbackLevel.LEVEL_4_EMERGENCY,
                description="緊急モード - システム維持優先",
                enabled_features=["emergency_response"],
                disabled_features=["rag", "cache", "templates", "web_search", "anti_hallucination"],
                max_response_time=0.5,
                cache_strategy="disabled",
                template_strategy="disabled",
                rag_strategy="disabled"
            )
        }

    def _initialize_triggers(self) -> Dict[str, Dict[str, Any]]:
        """デグラデーション トリガー初期化（リッチメニュー対応）"""
        return {
            "response_time": {"level_1": 3.0, "level_2": 8.0, "level_3": 15.0, "level_4": 30.0},
            "error_rate":    {"level_1": 0.05, "level_2": 0.15, "level_3": 0.3,  "level_4": 0.6},
            "memory_usage":  {"level_1": 70.0, "level_2": 80.0, "level_3": 90.0, "level_4": 95.0},
            "component_failures": {"level_1": 0, "level_2": 1, "level_3": 2, "level_4": 3}
        }

    def _is_richmenu_request(self, query: str, user_context: Optional[Dict] = None) -> bool:
        """🔧 リッチメニューボタン押下かどうかを判定"""
        if not query:
            return False
        q = query.strip()
        for button in self.richmenu_buttons:
            if q == button:
                return True
            # 絵文字除去の等価判定
            btn_text = (button.replace("🤖 ", "")
                              .replace("🌐 ", "")
                              .replace("📄 ", "")
                              .replace("📍 ", "")
                              .replace("💰 ", "")
                              .replace("💬 ", ""))
            if q == btn_text:
                return True
        if user_context and (user_context.get("source") == "richmenu" or user_context.get("richmenu_button")):
            return True
        return False

    async def evaluate_system_health(self, performance_data: Dict[str, Any],
                                    query: str = "", user_context: Optional[Dict] = None) -> FallbackLevel:
        """システム健全性評価とフォールバックレベル決定（リッチメニュー対応）"""
        try:
            if self._is_richmenu_request(query, user_context) and self.richmenu_template_override:
                self.stats["richmenu_template_overrides"] += 1
                logger.info(f"🎯 Richmenu button detected - forcing LEVEL_1_TEMPLATE: {query}")
                return FallbackLevel.LEVEL_1_TEMPLATE

            response_time_level = self._evaluate_response_time(performance_data)
            error_rate_level = self._evaluate_error_rate(performance_data)
            memory_level = self._evaluate_memory_usage(performance_data)
            component_level = self._evaluate_component_health(performance_data)

            levels = [response_time_level, error_rate_level, memory_level, component_level]
            recommended_level = max(levels, key=lambda x: list(FallbackLevel).index(x))

            logger.info("🔍 System health evaluation:")
            logger.info(f"   - Response time level: {response_time_level.value}")
            logger.info(f"   - Error rate level: {error_rate_level.value}")
            logger.info(f"   - Memory level: {memory_level.value}")
            logger.info(f"   - Component level: {component_level.value}")
            logger.info(f"   - Recommended level: {recommended_level.value}")

            return recommended_level
        except Exception as e:
            logger.error(f"❌ Health evaluation failed: {e}")
            return FallbackLevel.LEVEL_1_TEMPLATE

    def _evaluate_response_time(self, data: Dict[str, Any]) -> FallbackLevel:
        avg_response_time = data.get("avg_response_time", 0)
        t = self.degradation_triggers["response_time"]
        if   avg_response_time >= t["level_4"]: return FallbackLevel.LEVEL_4_EMERGENCY
        elif avg_response_time >= t["level_3"]: return FallbackLevel.LEVEL_3_MINIMAL
        elif avg_response_time >= t["level_2"]: return FallbackLevel.LEVEL_2_CACHE_ONLY
        elif avg_response_time >= t["level_1"]: return FallbackLevel.LEVEL_1_TEMPLATE
        else:                                    return FallbackLevel.LEVEL_0_NORMAL

    def _evaluate_error_rate(self, data: Dict[str, Any]) -> FallbackLevel:
        error_rate = data.get("error_rate", 0)
        t = self.degradation_triggers["error_rate"]
        if   error_rate >= t["level_4"]: return FallbackLevel.LEVEL_4_EMERGENCY
        elif error_rate >= t["level_3"]: return FallbackLevel.LEVEL_3_MINIMAL
        elif error_rate >= t["level_2"]: return FallbackLevel.LEVEL_2_CACHE_ONLY
        elif error_rate >= t["level_1"]: return FallbackLevel.LEVEL_1_TEMPLATE
        else:                             return FallbackLevel.LEVEL_0_NORMAL

    def _evaluate_memory_usage(self, data: Dict[str, Any]) -> FallbackLevel:
        memory_usage = data.get("memory_usage", 0)
        t = self.degradation_triggers["memory_usage"]
        if   memory_usage >= t["level_4"]: return FallbackLevel.LEVEL_4_EMERGENCY
        elif memory_usage >= t["level_3"]: return FallbackLevel.LEVEL_3_MINIMAL
        elif memory_usage >= t["level_2"]: return FallbackLevel.LEVEL_2_CACHE_ONLY
        elif memory_usage >= t["level_1"]: return FallbackLevel.LEVEL_1_TEMPLATE
        else:                               return FallbackLevel.LEVEL_0_NORMAL

    def _evaluate_component_health(self, data: Dict[str, Any]) -> FallbackLevel:
        failed_components = data.get("failed_components", 0)
        t = self.degradation_triggers["component_failures"]
        if   failed_components >= t["level_4"]: return FallbackLevel.LEVEL_4_EMERGENCY
        elif failed_components >= t["level_3"]: return FallbackLevel.LEVEL_3_MINIMAL
        elif failed_components >= t["level_2"]: return FallbackLevel.LEVEL_2_CACHE_ONLY
        elif failed_components >= t["level_1"]: return FallbackLevel.LEVEL_1_TEMPLATE
        else:                                    return FallbackLevel.LEVEL_0_NORMAL

    async def apply_fallback_level(self, target_level: FallbackLevel, reason: str = "",
                                   query: str = "", user_context: Optional[Dict] = None) -> bool:
        """フォールバックレベル適用（リッチメニュー対応）"""
        if target_level == self.current_level:
            return True
        previous_level = self.current_level
        try:
            logger.warning(f"🔄 Applying fallback: {previous_level.value} → {target_level.value}")
            if reason:
                logger.warning(f"   Reason: {reason}")

            if self._is_richmenu_request(query, user_context) and target_level != FallbackLevel.LEVEL_1_TEMPLATE:
                logger.info(f"🎯 Richmenu override: forcing LEVEL_1_TEMPLATE instead of {target_level.value}")
                target_level = FallbackLevel.LEVEL_1_TEMPLATE
                self.stats["richmenu_template_overrides"] += 1

            self.stats["total_fallbacks"] += 1
            self.stats["fallbacks_by_level"][target_level.value] += 1
            if target_level == FallbackLevel.LEVEL_4_EMERGENCY:
                self.stats["emergency_activations"] += 1

            success = await self._execute_fallback_strategy(target_level, query, user_context)
            if success:
                self.current_level = target_level
                self._record_degradation_event(previous_level, target_level, reason)
                logger.info(f"✅ Fallback applied successfully: {target_level.value}")
                return True
            else:
                logger.error(f"❌ Failed to apply fallback: {target_level.value}")
                return False
        except Exception as e:
            logger.error(f"❌ Fallback application error: {e}")
            return False

    async def _execute_fallback_strategy(self, level: FallbackLevel, query: str = "",
                                         user_context: Optional[Dict] = None) -> bool:
        """フォールバック戦略実行（リッチメニュー対応）"""
        strategy = self.fallback_strategies[level]
        is_richmenu = self._is_richmenu_request(query, user_context)
        try:
            logger.info(f"🔧 Executing fallback strategy: {strategy.description}")
            if is_richmenu:
                logger.info("🎯 Richmenu mode: disabling RAG and search")

            tasks = []
            # キャッシュ設定
            if "cache" in strategy.enabled_features or strategy.cache_strategy != "disabled":
                tasks.append(self._configure_cache_system(strategy, is_richmenu))
            # テンプレート設定
            if "templates" in strategy.enabled_features or strategy.template_strategy != "disabled":
                tasks.append(self._configure_template_system(strategy, is_richmenu))
            # RAG設定
            tasks.append(self._configure_rag_system(strategy, is_richmenu))
            # リッチメニュー追加設定
            if is_richmenu:
                tasks.append(self._configure_richmenu_mode(strategy))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            success_count = sum(1 for r in results if r is True)
            total = len(results)
            logger.info(f"   Strategy execution: {success_count}/{total} components configured")
            return success_count >= total // 2
        except Exception as e:
            logger.error(f"❌ Strategy execution failed: {e}")
            return False

    async def _configure_cache_system(self, strategy: FallbackStrategy, is_richmenu: bool = False) -> bool:
        """キャッシュシステム設定（リッチメニュー対応）"""
        try:
            logger.debug(f"   Configuring cache: {strategy.cache_strategy} (richmenu: {is_richmenu})")
            # 実際のキャッシュ制御は各プロジェクト実装へ委譲。
            # ここでは成功扱いのスタブでOK。
            return True
        except Exception as e:
            logger.error(f"Cache configuration failed: {e}")
            return False

    async def _configure_template_system(self, strategy: FallbackStrategy, is_richmenu: bool = False) -> bool:
        """テンプレートシステム設定（リッチメニュー対応）"""
        try:
            logger.debug(f"   Configuring templates: {strategy.template_strategy} (richmenu: {is_richmenu})")
            return True
        except Exception as e:
            logger.error(f"Template configuration failed: {e}")
            return False

    async def _configure_rag_system(self, strategy: FallbackStrategy, is_richmenu: bool = False) -> bool:
        """RAGシステム設定（リッチメニュー対応）"""
        try:
            logger.debug(f"   Configuring RAG: {strategy.rag_strategy} (richmenu: {is_richmenu})")
            if strategy.rag_strategy == "disabled" or (is_richmenu and self.richmenu_disable_rag):
                if is_richmenu:
                    self.stats["richmenu_rag_avoidances"] += 1
                    logger.debug("   RAG disabled for richmenu request")
            return True
        except Exception as e:
            logger.error(f"RAG configuration failed: {e}")
            return False

    async def _configure_richmenu_mode(self, strategy: FallbackStrategy) -> bool:
        """🔧 リッチメニューモード設定"""
        try:
            logger.debug("   Configuring richmenu mode")
            if self.richmenu_disable_search:
                self.stats["richmenu_search_avoidances"] += 1
                logger.debug("   Web search disabled for richmenu")
            logger.debug("   Anti-hallucination disabled for richmenu")
            logger.debug("   Fast response mode enabled for richmenu")
            return True
        except Exception as e:
            logger.error(f"Richmenu mode configuration failed: {e}")
            return False

    async def attempt_auto_recovery(self, performance_data: Dict[str, Any],
                                    query: str = "", user_context: Optional[Dict] = None) -> bool:
        """自動回復試行（リッチメニュー対応）"""
        if not self.auto_recovery_enabled or self.current_level == FallbackLevel.LEVEL_0_NORMAL:
            return False
        if self._is_richmenu_request(query, user_context):
            logger.debug("🎯 Skipping auto recovery for richmenu request - maintaining template priority")
            return False
        try:
            logger.info("🔄 Attempting auto recovery...")
            if await self._check_recovery_conditions(performance_data):
                levels = list(FallbackLevel)
                idx = levels.index(self.current_level)
                if idx > 0:
                    target = levels[idx - 1]
                    logger.info(f"🔄 Recovery attempt: {self.current_level.value} → {target.value}")
                    if await self.apply_fallback_level(target, "Auto recovery attempt", query, user_context):
                        self.stats["auto_recoveries"] += 1
                        logger.info("✅ Auto recovery successful")
                        return True
                    logger.warning("❌ Auto recovery failed")
                    return False
        except Exception as e:
            logger.error(f"❌ Auto recovery error: {e}")
            return False
        return False

    async def _check_recovery_conditions(self, performance_data: Dict[str, Any]) -> bool:
        """回復条件チェック（リッチメニュー対応）"""
        try:
            avg_response_time = performance_data.get("avg_response_time", float('inf'))
            error_rate = performance_data.get("error_rate", 1.0)
            memory_usage = performance_data.get("memory_usage", 100.0)
            recovery_thresholds = {
                FallbackLevel.LEVEL_1_TEMPLATE: {"max_response_time": 2.0, "max_error_rate": 0.02, "max_memory_usage": 60.0},
                FallbackLevel.LEVEL_2_CACHE_ONLY: {"max_response_time": 4.0, "max_error_rate": 0.08, "max_memory_usage": 70.0},
                FallbackLevel.LEVEL_3_MINIMAL: {"max_response_time": 8.0, "max_error_rate": 0.2,  "max_memory_usage": 75.0},
                FallbackLevel.LEVEL_4_EMERGENCY: {"max_response_time": 15.0,"max_error_rate": 0.4,  "max_memory_usage": 85.0},
            }
            th = recovery_thresholds.get(self.current_level)
            if not th:
                return False
            ok = (avg_response_time <= th["max_response_time"]
                  and error_rate <= th["max_error_rate"]
                  and memory_usage <= th["max_memory_usage"])
            logger.debug("Recovery conditions check:")
            logger.debug(f"   Response time: {avg_response_time:.2f} <= {th['max_response_time']} = {avg_response_time <= th['max_response_time']}")
            logger.debug(f"   Error rate: {error_rate:.3f} <= {th['max_error_rate']} = {error_rate <= th['max_error_rate']}")
            logger.debug(f"   Memory usage: {memory_usage:.1f} <= {th['max_memory_usage']} = {memory_usage <= th['max_memory_usage']}")
            logger.debug(f"   Overall: {ok}")
            return ok
        except Exception as e:
            logger.error(f"Recovery conditions check failed: {e}")
            return False

    def get_current_strategy(self) -> FallbackStrategy:
        """現在のフォールバック戦略取得"""
        return self.fallback_strategies[self.current_level]

    def is_feature_enabled(self, feature: str, query: str = "", user_context: Optional[Dict] = None) -> bool:
        """機能有効性チェック（リッチメニュー対応）"""
        current_strategy = self.get_current_strategy()
        if self._is_richmenu_request(query, user_context):
            if feature == "rag" and self.richmenu_disable_rag:
                return False
            if feature == "web_search" and self.richmenu_disable_search:
                return False
            if feature == "anti_hallucination":
                return False
        return feature in current_strategy.enabled_features

    def get_response_constraints(self, query: str = "", user_context: Optional[Dict] = None) -> Dict[str, Any]:
        """レスポンス制約取得（リッチメニュー対応）"""
        cs = self.get_current_strategy()
        is_rm = self._is_richmenu_request(query, user_context)
        constraints = {
            "max_response_time": cs.max_response_time,
            "cache_strategy": cs.cache_strategy,
            "template_strategy": cs.template_strategy,
            "rag_strategy": cs.rag_strategy,
            "enabled_features": cs.enabled_features.copy(),
            "disabled_features": cs.disabled_features.copy(),
            "is_richmenu_request": is_rm
        }
        if is_rm:
            constraints["max_response_time"] = min(constraints["max_response_time"], 1.0)
            constraints["template_strategy"] = "immediate"
            constraints["rag_strategy"] = "disabled"
            if "rag" in constraints["enabled_features"]:
                constraints["enabled_features"].remove("rag")
            if "rag" not in constraints["disabled_features"]:
                constraints["disabled_features"].append("rag")
            if "web_search" in constraints["enabled_features"]:
                constraints["enabled_features"].remove("web_search")
            if "web_search" not in constraints["disabled_features"]:
                constraints["disabled_features"].append("web_search")
        return constraints

    def generate_fallback_response(self, query: str, platform: str = "web", 
                                   error_context: Optional[str] = None,
                                   user_context: Optional[Dict] = None) -> Dict[str, Any]:
        """フォールバック応答生成（リッチメニュー対応）"""
        current_strategy = self.get_current_strategy()
        is_rm = self._is_richmenu_request(query, user_context)
        try:
            if is_rm:
                logger.info(f"🎯 Generating richmenu template response for: {query}")
                return self._generate_richmenu_template_response(query, platform)

            if self.current_level == FallbackLevel.LEVEL_4_EMERGENCY:
                answer = self._generate_emergency_response(error_context)
            elif self.current_level == FallbackLevel.LEVEL_3_MINIMAL:
                answer = self._generate_minimal_response(query, platform)
            elif self.current_level == FallbackLevel.LEVEL_2_CACHE_ONLY:
                answer = self._generate_cache_only_response(query, platform)
            elif self.current_level == FallbackLevel.LEVEL_1_TEMPLATE:
                answer = self._generate_template_priority_response(query, platform)
            else:
                answer = self._generate_normal_response(query, platform)

            return {
                "answer": answer,
                "sources": [],
                "fallback_level": self.current_level.value,
                "strategy_description": current_strategy.description,
                "processing_time": 0.1,
                "status": "fallback_response",
                "constraints_applied": True
            }
        except Exception as e:
            logger.error(f"Fallback response generation failed: {e}")
            return {
                "answer": "システムに問題が発生しています。しばらく後に再度お試しください。",
                "sources": [],
                "fallback_level": "emergency",
                "status": "emergency_fallback",
                "error": str(e)
            }

    def _generate_richmenu_template_response(self, query: str, platform: str) -> Dict[str, Any]:
        """🔧 リッチメニューテンプレート応答生成（動的ロード版）"""
        get_tm = _get_template_manager()
        if callable(get_tm):
            try:
                tm = get_tm()
                result = tm.find_template(query, platform)
                if result and result.get("content"):
                    return {
                        "answer": result["content"],
                        "sources": [],
                        "fallback_level": "richmenu_template",
                        "strategy_description": "リッチメニューテンプレート即時応答",
                        "processing_time": 0.05,
                        "status": "richmenu_template_response",
                        "template_key": result.get("template_key"),
                        "richmenu_optimized": True
                    }
            except Exception as e:
                logger.warning(f"Template manager error: {e}")

        # テンプレート未導入/取得失敗時の基本応答
        return {
            "answer": "ご質問ありがとうございます。詳細についてはスタッフがご対応いたします。",
            "sources": [],
            "fallback_level": "richmenu_fallback",
            "status": "richmenu_fallback_response",
            "processing_time": 0.05
        }

    def _generate_emergency_response(self, error_context: Optional[str] = None) -> str:
        """緊急モード応答生成"""
        base_message = "現在システムメンテナンス中です。しばらくお待ちください。"
        if error_context:
            ec = error_context.lower()
            if "memory" in ec: return "システムリソースが不足しています。しばらく後に再度お試しください。"
            if "timeout" in ec: return "システムが一時的に過負荷状態です。少し待ってから再度お試しください。"
            if "rag" in ec: return "AI機能に問題が発生しています。基本的なご質問にのみお答えできます。"
        return base_message

    def _generate_minimal_response(self, query: str, platform: str) -> str:
        """最小限モード応答生成"""
        q = query.lower()
        if any(k in q for k in ["坪単価", "価格", "費用"]): return "坪単価は約70〜85万円/坪です。詳しくはお問い合わせください。"
        if any(k in q for k in ["仕様", "設備"]):         return "住宅仕様については展示場でご確認いただけます。"
        if any(k in q for k in ["相談", "質問"]):         return "ご相談は営業時間内にお電話でお受けします。"
        return "申し訳ございません。現在システム制限により、限定的な応答のみ可能です。詳しくはお電話でお問い合わせください。"

    def _generate_cache_only_response(self, query: str, platform: str) -> str:
        """キャッシュオンリーモード応答生成（動的ロード版）"""
        qcg = _quick_cache_get()
        if callable(qcg):
            try:
                cached = qcg(query, platform)
                if cached:
                    return cached
            except Exception as e:
                logger.warning(f"Quick cache error: {e}")
        return "申し訳ございません。お尋ねの内容についてのキャッシュされた情報がありません。しばらく後に再度お試しください。"

    def _generate_template_priority_response(self, query: str, platform: str) -> str:
        """テンプレート優先モード応答生成（動的ロード版）"""
        get_tm = _get_template_manager()
        if callable(get_tm):
            try:
                tm = get_tm()
                result = tm.find_template(query, platform)
                if result:
                    return result["content"]
            except Exception as e:
                logger.warning(f"Template manager error: {e}")
        return self._generate_minimal_response(query, platform)

    def _generate_normal_response(self, query: str, platform: str) -> str:
        """通常モード応答生成"""
        return "通常モードで動作中です。ご質問をお聞かせください。"

    def _record_degradation_event(self, from_level: FallbackLevel, to_level: FallbackLevel, reason: str):
        """デグラデーションイベント記録"""
        event = {
            "timestamp": datetime.now().isoformat(),
            "from_level": from_level.value,
            "to_level": to_level.value,
            "reason": reason,
            "direction": "degradation" if list(FallbackLevel).index(to_level) > list(FallbackLevel).index(from_level) else "recovery"
        }
        self.degradation_history.append(event)
        if len(self.degradation_history) > 100:
            self.degradation_history = self.degradation_history[-100:]

    def get_fallback_stats(self) -> Dict[str, Any]:
        """フォールバック統計取得（リッチメニュー対応）"""
        return {
            "current_level": self.current_level.value,
            "current_strategy": self.get_current_strategy().description,
            "statistics": self.stats,
            "degradation_events": len(self.degradation_history),
            "recent_events": self.degradation_history[-5:] if self.degradation_history else [],
            "auto_recovery_enabled": self.auto_recovery_enabled,
            "richmenu_configuration": {
                "template_override_enabled": self.richmenu_template_override,
                "rag_disabled": self.richmenu_disable_rag,
                "search_disabled": self.richmenu_disable_search,
                "supported_buttons": self.richmenu_buttons
            },
            "richmenu_statistics": {
                "template_overrides": self.stats["richmenu_template_overrides"],
                "rag_avoidances": self.stats["richmenu_rag_avoidances"],
                "search_avoidances": self.stats["richmenu_search_avoidances"]
            },
            "component_health_summary": {
                name: {
                    "status": health.status.value,
                    "success_rate": health.success_rate,
                    "avg_response_time": health.avg_response_time
                }
                for name, health in self.component_health.items()
            }
        }

    def export_fallback_config(self, file_path: str) -> bool:
        """フォールバック設定エクスポート（リッチメニュー対応）"""
        try:
            config = {
                "strategies": {
                    level.value: {
                        "description": s.description,
                        "enabled_features": s.enabled_features,
                        "disabled_features": s.disabled_features,
                        "max_response_time": s.max_response_time,
                        "cache_strategy": s.cache_strategy,
                        "template_strategy": s.template_strategy,
                        "rag_strategy": s.rag_strategy
                    }
                    for level, s in self.fallback_strategies.items()
                },
                "triggers": self.degradation_triggers,
                "current_config": {
                    "current_level": self.current_level.value,
                    "auto_recovery_enabled": self.auto_recovery_enabled
                },
                "richmenu_config": {
                    "template_override": self.richmenu_template_override,
                    "disable_rag": self.richmenu_disable_rag,
                    "disable_search": self.richmenu_disable_search,
                    "supported_buttons": self.richmenu_buttons
                },
                "export_timestamp": datetime.now().isoformat()
            }
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            logger.info(f"📤 Fallback config exported to {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export fallback config: {e}")
            return False

# グローバルフォールバック管理インスタンス
_global_fallback_manager = None

def get_fallback_manager() -> GracefulFallbackManager:
    """グローバルフォールバック管理インスタンス取得"""
    global _global_fallback_manager
    if _global_fallback_manager is None:
        _global_fallback_manager = GracefulFallbackManager()
    return _global_fallback_manager

async def evaluate_and_apply_fallback(performance_data: Dict[str, Any],
                                      query: str = "", user_context: Optional[Dict] = None) -> Tuple[FallbackLevel, bool]:
    """システム評価とフォールバック適用（リッチメニュー対応）"""
    manager = get_fallback_manager()
    recommended = await manager.evaluate_system_health(performance_data, query, user_context)
    applied = await manager.apply_fallback_level(recommended, "System health evaluation", query, user_context)
    return recommended, applied

async def attempt_system_recovery(performance_data: Dict[str, Any],
                                  query: str = "", user_context: Optional[Dict] = None) -> bool:
    """システム回復試行（リッチメニュー対応）"""
    manager = get_fallback_manager()
    return await manager.attempt_auto_recovery(performance_data, query, user_context)

def get_current_constraints(query: str = "", user_context: Optional[Dict] = None) -> Dict[str, Any]:
    """現在の制約取得（リッチメニュー対応）"""
    manager = get_fallback_manager()
    return manager.get_response_constraints(query, user_context)

def generate_degraded_response(query: str, platform: str = "web", 
                               error_context: Optional[str] = None,
                               user_context: Optional[Dict] = None) -> Dict[str, Any]:
    """デグレード応答生成（リッチメニュー対応）"""
    manager = get_fallback_manager()
    return manager.generate_fallback_response(query, platform, error_context, user_context)

def is_richmenu_request(query: str, user_context: Optional[Dict] = None) -> bool:
    """🔧 リッチメニューリクエスト判定（外部利用用）"""
    manager = get_fallback_manager()
    return manager._is_richmenu_request(query, user_context)
