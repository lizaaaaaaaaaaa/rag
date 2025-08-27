# utils/graceful_fallback.py - グレースフル・デグラデーション機能（リッチメニュー対応修正版）

import logging
import time
import traceback
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Callable
from enum import Enum
from dataclasses import dataclass
import json

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
            "response_time": {
                "level_1": 3.0,    # 🔧 3秒以上でテンプレート優先（短縮）
                "level_2": 8.0,    # 8秒以上でレベル2
                "level_3": 15.0,   # 15秒以上でレベル3
                "level_4": 30.0    # 30秒以上で緊急
            },
            "error_rate": {
                "level_1": 0.05,   # 🔧 5%以上でテンプレート優先（厳格化）
                "level_2": 0.15,   # 15%以上でレベル2
                "level_3": 0.3,    # 30%以上でレベル3
                "level_4": 0.6     # 60%以上で緊急
            },
            "memory_usage": {
                "level_1": 70.0,   # 🔧 70%以上でテンプレート優先（厳格化）
                "level_2": 80.0,   # 80%以上でレベル2
                "level_3": 90.0,   # 90%以上でレベル3
                "level_4": 95.0    # 95%以上で緊急
            },
            "component_failures": {
                "level_1": 0,      # 🔧 軽微な問題でもテンプレート優先
                "level_2": 1,      # 1つ失敗でレベル2
                "level_3": 2,      # 2つ失敗でレベル3
                "level_4": 3       # 3つ以上で緊急
            }
        }

    def _is_richmenu_request(self, query: str, user_context: Optional[Dict] = None) -> bool:
        """🔧 リッチメニューボタン押下かどうかを判定"""
        if not query:
            return False
        
        query_stripped = query.strip()
        
        # リッチメニューボタンとの完全一致チェック
        for button in self.richmenu_buttons:
            if query_stripped == button:
                return True
        
        # 部分一致チェック（絵文字なしでも判定）
        for button in self.richmenu_buttons:
            button_text = button.replace("🤖 ", "").replace("🌐 ", "").replace("📄 ", "").replace("📍 ", "").replace("💰 ", "").replace("💬 ", "")
            if query_stripped == button_text:
                return True
        
        # ユーザーコンテキストからの判定
        if user_context:
            if user_context.get("source") == "richmenu" or user_context.get("richmenu_button"):
                return True
        
        return False

    async def evaluate_system_health(self, performance_data: Dict[str, Any],
                                   query: str = "", user_context: Optional[Dict] = None) -> FallbackLevel:
        """システム健全性評価とフォールバックレベル決定（リッチメニュー対応）"""
        try:
            # 🔧 リッチメニューボタン押下の場合は強制的にテンプレート優先
            if self._is_richmenu_request(query, user_context):
                if self.richmenu_template_override:
                    self.stats["richmenu_template_overrides"] += 1
                    logger.info(f"🎯 Richmenu button detected - forcing LEVEL_1_TEMPLATE: {query}")
                    return FallbackLevel.LEVEL_1_TEMPLATE
            
            # 通常のシステム健全性評価
            # 各指標の評価
            response_time_level = self._evaluate_response_time(performance_data)
            error_rate_level = self._evaluate_error_rate(performance_data)
            memory_level = self._evaluate_memory_usage(performance_data)
            component_level = self._evaluate_component_health(performance_data)
            
            # 最も高いレベルを採用
            levels = [response_time_level, error_rate_level, memory_level, component_level]
            recommended_level = max(levels, key=lambda x: list(FallbackLevel).index(x))
            
            logger.info(f"🔍 System health evaluation:")
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
        """レスポンスタイム評価（リッチメニュー対応）"""
        avg_response_time = data.get("avg_response_time", 0)
        
        triggers = self.degradation_triggers["response_time"]
        
        if avg_response_time >= triggers["level_4"]:
            return FallbackLevel.LEVEL_4_EMERGENCY
        elif avg_response_time >= triggers["level_3"]:
            return FallbackLevel.LEVEL_3_MINIMAL
        elif avg_response_time >= triggers["level_2"]:
            return FallbackLevel.LEVEL_2_CACHE_ONLY
        elif avg_response_time >= triggers["level_1"]:
            return FallbackLevel.LEVEL_1_TEMPLATE  # 🔧 早めにテンプレート優先
        else:
            return FallbackLevel.LEVEL_0_NORMAL

    def _evaluate_error_rate(self, data: Dict[str, Any]) -> FallbackLevel:
        """エラー率評価（リッチメニュー対応）"""
        error_rate = data.get("error_rate", 0)
        
        triggers = self.degradation_triggers["error_rate"]
        
        if error_rate >= triggers["level_4"]:
            return FallbackLevel.LEVEL_4_EMERGENCY
        elif error_rate >= triggers["level_3"]:
            return FallbackLevel.LEVEL_3_MINIMAL
        elif error_rate >= triggers["level_2"]:
            return FallbackLevel.LEVEL_2_CACHE_ONLY
        elif error_rate >= triggers["level_1"]:
            return FallbackLevel.LEVEL_1_TEMPLATE  # 🔧 エラー発生時は即座にテンプレート優先
        else:
            return FallbackLevel.LEVEL_0_NORMAL

    def _evaluate_memory_usage(self, data: Dict[str, Any]) -> FallbackLevel:
        """メモリ使用量評価（リッチメニュー対応）"""
        memory_usage = data.get("memory_usage", 0)
        
        triggers = self.degradation_triggers["memory_usage"]
        
        if memory_usage >= triggers["level_4"]:
            return FallbackLevel.LEVEL_4_EMERGENCY
        elif memory_usage >= triggers["level_3"]:
            return FallbackLevel.LEVEL_3_MINIMAL
        elif memory_usage >= triggers["level_2"]:
            return FallbackLevel.LEVEL_2_CACHE_ONLY
        elif memory_usage >= triggers["level_1"]:
            return FallbackLevel.LEVEL_1_TEMPLATE  # 🔧 メモリ不足時はテンプレート優先
        else:
            return FallbackLevel.LEVEL_0_NORMAL

    def _evaluate_component_health(self, data: Dict[str, Any]) -> FallbackLevel:
        """コンポーネント健全性評価（リッチメニュー対応）"""
        failed_components = data.get("failed_components", 0)
        
        triggers = self.degradation_triggers["component_failures"]
        
        if failed_components >= triggers["level_4"]:
            return FallbackLevel.LEVEL_4_EMERGENCY
        elif failed_components >= triggers["level_3"]:
            return FallbackLevel.LEVEL_3_MINIMAL
        elif failed_components >= triggers["level_2"]:
            return FallbackLevel.LEVEL_2_CACHE_ONLY
        elif failed_components >= triggers["level_1"]:
            return FallbackLevel.LEVEL_1_TEMPLATE  # 🔧 軽微な問題でもテンプレート優先
        else:
            return FallbackLevel.LEVEL_0_NORMAL

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
            
            # 🔧 リッチメニューボタン押下の場合の特別処理
            if self._is_richmenu_request(query, user_context):
                if target_level != FallbackLevel.LEVEL_1_TEMPLATE:
                    logger.info(f"🎯 Richmenu override: forcing LEVEL_1_TEMPLATE instead of {target_level.value}")
                    target_level = FallbackLevel.LEVEL_1_TEMPLATE
                    self.stats["richmenu_template_overrides"] += 1
            
            # 統計更新
            self.stats["total_fallbacks"] += 1
            self.stats["fallbacks_by_level"][target_level.value] += 1
            
            if target_level == FallbackLevel.LEVEL_4_EMERGENCY:
                self.stats["emergency_activations"] += 1
            
            # フォールバック実行
            success = await self._execute_fallback_strategy(target_level, query, user_context)
            
            if success:
                self.current_level = target_level
                
                # 履歴記録
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
                logger.info(f"🎯 Richmenu mode: disabling RAG and search")
            
            # 各システムにフォールバック設定を適用
            tasks = []
            
            # キャッシュシステム設定
            if "cache" in strategy.enabled_features or strategy.cache_strategy != "disabled":
                tasks.append(self._configure_cache_system(strategy, is_richmenu))
            
            # テンプレートシステム設定
            if "templates" in strategy.enabled_features or strategy.template_strategy != "disabled":
                tasks.append(self._configure_template_system(strategy, is_richmenu))
            
            # RAGシステム設定
            tasks.append(self._configure_rag_system(strategy, is_richmenu))
            
            # 🔧 リッチメニュー用の追加設定
            if is_richmenu:
                tasks.append(self._configure_richmenu_mode(strategy))
            
            # 並行実行
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 結果確認
            success_count = sum(1 for result in results if result is True)
            total_count = len(results)
            
            logger.info(f"   Strategy execution: {success_count}/{total_count} components configured")
            
            return success_count >= total_count // 2  # 半数以上成功で OK
            
        except Exception as e:
            logger.error(f"❌ Strategy execution failed: {e}")
            return False

    async def _configure_cache_system(self, strategy: FallbackStrategy, is_richmenu: bool = False) -> bool:
        """キャッシュシステム設定（リッチメニュー対応）"""
        try:
            logger.debug(f"   Configuring cache: {strategy.cache_strategy} (richmenu: {is_richmenu})")
            
            if strategy.cache_strategy == "disabled":
                return True
            elif strategy.cache_strategy == "template_priority" and is_richmenu:
                # 🔧 リッチメニューテンプレート優先キャッシュ
                logger.debug("   Richmenu template priority cache enabled")
                return True
            elif strategy.cache_strategy == "only":
                return True
            elif strategy.cache_strategy == "aggressive":
                return True
            elif strategy.cache_strategy == "full":
                return True
            
            return True
            
        except Exception as e:
            logger.error(f"Cache configuration failed: {e}")
            return False

    async def _configure_template_system(self, strategy: FallbackStrategy, is_richmenu: bool = False) -> bool:
        """テンプレートシステム設定（リッチメニュー対応）"""
        try:
            logger.debug(f"   Configuring templates: {strategy.template_strategy} (richmenu: {is_richmenu})")
            
            if strategy.template_strategy == "disabled":
                return True
            elif strategy.template_strategy == "immediate" and is_richmenu:
                # 🔧 リッチメニュー即時テンプレート
                logger.debug("   Richmenu immediate template mode enabled")
                return True
            elif strategy.template_strategy == "basic":
                return True
            elif strategy.template_strategy == "priority":
                return True
            elif strategy.template_strategy == "fallback":
                return True
            elif strategy.template_strategy == "full":
                return True
            
            return True
            
        except Exception as e:
            logger.error(f"Template configuration failed: {e}")
            return False

    async def _configure_rag_system(self, strategy: FallbackStrategy, is_richmenu: bool = False) -> bool:
        """RAGシステム設定（リッチメニュー対応）"""
        try:
            logger.debug(f"   Configuring RAG: {strategy.rag_strategy} (richmenu: {is_richmenu})")
            
            if strategy.rag_strategy == "disabled" or (is_richmenu and self.richmenu_disable_rag):
                # 🔧 リッチメニュー時は強制的にRAG無効化
                if is_richmenu:
                    self.stats["richmenu_rag_avoidances"] += 1
                    logger.debug("   RAG disabled for richmenu request")
                return True
            elif strategy.rag_strategy == "limited":
                return True
            elif strategy.rag_strategy == "full":
                return True
            
            return True
            
        except Exception as e:
            logger.error(f"RAG configuration failed: {e}")
            return False

    async def _configure_richmenu_mode(self, strategy: FallbackStrategy) -> bool:
        """🔧 リッチメニューモード設定"""
        try:
            logger.debug("   Configuring richmenu mode")
            
            # Web検索無効化
            if self.richmenu_disable_search:
                self.stats["richmenu_search_avoidances"] += 1
                logger.debug("   Web search disabled for richmenu")
            
            # アンチハルチネーション無効化
            logger.debug("   Anti-hallucination disabled for richmenu")
            
            # 高速応答モード
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
        
        # 🔧 リッチメニューボタン押下時は回復を試行しない（テンプレート優先維持）
        if self._is_richmenu_request(query, user_context):
            logger.debug("🎯 Skipping auto recovery for richmenu request - maintaining template priority")
            return False
        
        try:
            logger.info("🔄 Attempting auto recovery...")
            
            # 回復条件チェック
            recovery_possible = await self._check_recovery_conditions(performance_data)
            
            if recovery_possible:
                # 1段階上位レベルに回復試行
                target_levels = list(FallbackLevel)
                current_index = target_levels.index(self.current_level)
                
                if current_index > 0:
                    target_level = target_levels[current_index - 1]
                    
                    logger.info(f"🔄 Recovery attempt: {self.current_level.value} → {target_level.value}")
                    
                    success = await self.apply_fallback_level(target_level, "Auto recovery attempt", query, user_context)
                    
                    if success:
                        self.stats["auto_recoveries"] += 1
                        logger.info("✅ Auto recovery successful")
                        return True
                    else:
                        logger.warning("❌ Auto recovery failed")
                        return False
                        
        except Exception as e:
            logger.error(f"❌ Auto recovery error: {e}")
            return False
        
        return False

    async def _check_recovery_conditions(self, performance_data: Dict[str, Any]) -> bool:
        """回復条件チェック（リッチメニュー対応）"""
        try:
            # 基本指標の改善確認
            avg_response_time = performance_data.get("avg_response_time", float('inf'))
            error_rate = performance_data.get("error_rate", 1.0)
            memory_usage = performance_data.get("memory_usage", 100.0)
            
            # 🔧 回復閾値（リッチメニュー対応でより厳しい条件）
            recovery_thresholds = {
                FallbackLevel.LEVEL_1_TEMPLATE: {
                    "max_response_time": 2.0,  # 🔧 短縮（テンプレート優先からの回復は厳しく）
                    "max_error_rate": 0.02,    # 🔧 厳格化
                    "max_memory_usage": 60.0   # 🔧 厳格化
                },
                FallbackLevel.LEVEL_2_CACHE_ONLY: {
                    "max_response_time": 4.0,
                    "max_error_rate": 0.08,
                    "max_memory_usage": 70.0
                },
                FallbackLevel.LEVEL_3_MINIMAL: {
                    "max_response_time": 8.0,
                    "max_error_rate": 0.2,
                    "max_memory_usage": 75.0
                },
                FallbackLevel.LEVEL_4_EMERGENCY: {
                    "max_response_time": 15.0,
                    "max_error_rate": 0.4,
                    "max_memory_usage": 85.0
                }
            }
            
            threshold = recovery_thresholds.get(self.current_level)
            if not threshold:
                return False
            
            # 全条件をクリア
            conditions_met = (
                avg_response_time <= threshold["max_response_time"] and
                error_rate <= threshold["max_error_rate"] and
                memory_usage <= threshold["max_memory_usage"]
            )
            
            logger.debug(f"Recovery conditions check:")
            logger.debug(f"   Response time: {avg_response_time:.2f} <= {threshold['max_response_time']} = {avg_response_time <= threshold['max_response_time']}")
            logger.debug(f"   Error rate: {error_rate:.3f} <= {threshold['max_error_rate']} = {error_rate <= threshold['max_error_rate']}")
            logger.debug(f"   Memory usage: {memory_usage:.1f} <= {threshold['max_memory_usage']} = {memory_usage <= threshold['max_memory_usage']}")
            logger.debug(f"   Overall: {conditions_met}")
            
            return conditions_met
            
        except Exception as e:
            logger.error(f"Recovery conditions check failed: {e}")
            return False

    def get_current_strategy(self) -> FallbackStrategy:
        """現在のフォールバック戦略取得"""
        return self.fallback_strategies[self.current_level]

    def is_feature_enabled(self, feature: str, query: str = "", user_context: Optional[Dict] = None) -> bool:
        """機能有効性チェック（リッチメニュー対応）"""
        current_strategy = self.get_current_strategy()
        
        # 🔧 リッチメニューボタン押下時の特別制御
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
        current_strategy = self.get_current_strategy()
        is_richmenu = self._is_richmenu_request(query, user_context)
        
        constraints = {
            "max_response_time": current_strategy.max_response_time,
            "cache_strategy": current_strategy.cache_strategy,
            "template_strategy": current_strategy.template_strategy,
            "rag_strategy": current_strategy.rag_strategy,
            "enabled_features": current_strategy.enabled_features.copy(),
            "disabled_features": current_strategy.disabled_features.copy(),
            "is_richmenu_request": is_richmenu
        }
        
        # 🔧 リッチメニュー時の追加制約
        if is_richmenu:
            constraints["max_response_time"] = min(constraints["max_response_time"], 1.0)  # 高速応答
            constraints["template_strategy"] = "immediate"  # 即時テンプレート
            constraints["rag_strategy"] = "disabled"  # RAG無効化
            
            # 機能制御の上書き
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
        is_richmenu = self._is_richmenu_request(query, user_context)
        
        try:
            # 🔧 リッチメニューボタン押下時は即座にテンプレート応答
            if is_richmenu:
                logger.info(f"🎯 Generating richmenu template response for: {query}")
                return self._generate_richmenu_template_response(query, platform)
            
            # 通常のフォールバック応答処理
            if self.current_level == FallbackLevel.LEVEL_4_EMERGENCY:
                # 緊急モード
                answer = self._generate_emergency_response(error_context)
                
            elif self.current_level == FallbackLevel.LEVEL_3_MINIMAL:
                # 最小限モード
                answer = self._generate_minimal_response(query, platform)
                
            elif self.current_level == FallbackLevel.LEVEL_2_CACHE_ONLY:
                # キャッシュオンリーモード
                answer = self._generate_cache_only_response(query, platform)
                
            elif self.current_level == FallbackLevel.LEVEL_1_TEMPLATE:
                # テンプレート優先モード
                answer = self._generate_template_priority_response(query, platform)
                
            else:
                # 通常モード（このケースは稀）
                answer = self._generate_normal_response(query, platform)
            
            return {
                "answer": answer,
                "sources": [],
                "fallback_level": self.current_level.value,
                "strategy_description": current_strategy.description,
                "processing_time": 0.1,  # 固定値
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
        """🔧 リッチメニューテンプレート応答生成"""
        try:
            from utils.chat_templates import get_template_manager
            template_manager = get_template_manager()
            
            template_result = template_manager.find_template(query, platform)
            
            if template_result and template_result.get("content"):
                return {
                    "answer": template_result["content"],
                    "sources": [],
                    "fallback_level": "richmenu_template",
                    "strategy_description": "リッチメニューテンプレート即時応答",
                    "processing_time": 0.05,  # 高速
                    "status": "richmenu_template_response",
                    "template_key": template_result.get("template_key"),
                    "richmenu_optimized": True
                }
            else:
                # テンプレートが見つからない場合の基本応答
                return {
                    "answer": "ご質問ありがとうございます。詳細についてはスタッフがご対応いたします。",
                    "sources": [],
                    "fallback_level": "richmenu_fallback",
                    "status": "richmenu_fallback_response",
                    "processing_time": 0.05
                }
                
        except ImportError:
            return {
                "answer": "テンプレートシステムが利用できません。スタッフがご対応いたします。",
                "sources": [],
                "fallback_level": "richmenu_error",
                "status": "richmenu_error_response",
                "processing_time": 0.05
            }

    def _generate_emergency_response(self, error_context: Optional[str] = None) -> str:
        """緊急モード応答生成"""
        base_message = "現在システムメンテナンス中です。しばらくお待ちください。"
        
        if error_context:
            if "memory" in error_context.lower():
                return "システムリソースが不足しています。しばらく後に再度お試しください。"
            elif "timeout" in error_context.lower():
                return "システムが一時的に過負荷状態です。少し待ってから再度お試しください。"
            elif "rag" in error_context.lower():
                return "AI機能に問題が発生しています。基本的なご質問にのみお答えできます。"
        
        return base_message

    def _generate_minimal_response(self, query: str, platform: str) -> str:
        """最小限モード応答生成"""
        query_lower = query.lower()
        
        # 基本的なキーワードマッチングのみ
        if any(kw in query_lower for kw in ["坪単価", "価格", "費用"]):
            return "坪単価は約70〜85万円/坪です。詳しくはお問い合わせください。"
        elif any(kw in query_lower for kw in ["仕様", "設備"]):
            return "住宅仕様については展示場でご確認いただけます。"
        elif any(kw in query_lower for kw in ["相談", "質問"]):
            return "ご相談は営業時間内にお電話でお受けします。"
        else:
            return "申し訳ございません。現在システム制限により、限定的な応答のみ可能です。詳しくはお電話でお問い合わせください。"

    def _generate_cache_only_response(self, query: str, platform: str) -> str:
        """キャッシュオンリーモード応答生成"""
        # 実際の実装では、キャッシュから応答を取得
        try:
            from utils.chat_cache import quick_cache_get
            cached_response = quick_cache_get(query, platform)
            
            if cached_response:
                return cached_response
            else:
                return "申し訳ございません。お尋ねの内容についてのキャッシュされた情報がありません。しばらく後に再度お試しください。"
                
        except ImportError:
            return "キャッシュシステムをご利用いただけません。お電話でお問い合わせください。"

    def _generate_template_priority_response(self, query: str, platform: str) -> str:
        """テンプレート優先モード応答生成"""
        try:
            from utils.chat_templates import get_template_manager
            template_manager = get_template_manager()
            
            template_result = template_manager.find_template(query, platform)
            
            if template_result:
                return template_result["content"]
            else:
                return self._generate_minimal_response(query, platform)
                
        except ImportError:
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
        
        # 履歴サイズ制限
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
            "richmenu_configuration": {  # 🔧 リッチメニュー設定情報
                "template_override_enabled": self.richmenu_template_override,
                "rag_disabled": self.richmenu_disable_rag,
                "search_disabled": self.richmenu_disable_search,
                "supported_buttons": self.richmenu_buttons
            },
            "richmenu_statistics": {  # 🔧 リッチメニュー統計
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
                        "description": strategy.description,
                        "enabled_features": strategy.enabled_features,
                        "disabled_features": strategy.disabled_features,
                        "max_response_time": strategy.max_response_time,
                        "cache_strategy": strategy.cache_strategy,
                        "template_strategy": strategy.template_strategy,
                        "rag_strategy": strategy.rag_strategy
                    }
                    for level, strategy in self.fallback_strategies.items()
                },
                "triggers": self.degradation_triggers,
                "current_config": {
                    "current_level": self.current_level.value,
                    "auto_recovery_enabled": self.auto_recovery_enabled
                },
                "richmenu_config": {  # 🔧 リッチメニュー設定追加
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
    
    # システム健全性評価（リッチメニュー考慮）
    recommended_level = await manager.evaluate_system_health(performance_data, query, user_context)
    
    # フォールバック適用
    applied = await manager.apply_fallback_level(recommended_level, "System health evaluation", query, user_context)
    
    return recommended_level, applied

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