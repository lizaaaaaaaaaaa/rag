# integration/anti_hallucination_integration.py - 最適化版（リッチメニュー押下時は無効化）

import logging
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

# ハルチネーション対策システムをインポート（条件付き）
try:
    from utils.housing_subsidy_anti_hallucination import (
        process_housing_subsidy_query,
        AntiHallucinationResult
    )
    ANTI_HALLUCINATION_MODULE_AVAILABLE = True
except ImportError:
    ANTI_HALLUCINATION_MODULE_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.info("ℹ️ Anti-hallucination module not available, using basic filtering")

logger = logging.getLogger(__name__)

class OptimizedAntiHallucinationIntegration:
    """最適化ハルチネーション対策統合クラス（リッチメニュー押下時は無効化・AI相談時のみ有効）"""
    
    def __init__(self):
        # リッチメニューの固定応答キーワード（ハルチネーション対策を無効化）
        self.richmenu_keywords = [
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
        
        # 🚀 厳格化：補助金関連キーワードを限定（AI相談での実際の質問時のみ適用）
        self.strict_subsidy_keywords = [
            # 明確な補助金制度名のみ
            "zeh補助金", "zeh支援事業", "ネット・ゼロ・エネルギー・ハウス支援事業",
            "こどもエコすまい支援事業", "子どもエコすまい", "子育てエコホーム支援事業",
            "住宅ローン控除", "住宅ローン減税", "住宅借入金等特別控除",
            "長期優良住宅化リフォーム推進事業",
            "既存住宅における断熱リフォーム支援事業"
        ]
        
        # 🚀 年度限定キーワード（より厳格）
        self.temporal_keywords = [
            "2024年度", "2025年度", "令和6年度", "令和7年度",
            "2024年最新", "2025年最新", "現在実施中の",
            "今年度の補助金", "最新の補助金制度"
        ]
        
        # 🚀 地域キーワード（特定地域のみ）
        self.specific_location_keywords = [
            "兵庫県", "大阪府", "京都府", "奈良県", "和歌山県", "滋賀県",
            "加東市", "明石市", "三木市", "加古川市", "神戸市", "姫路市"
        ]
        
        # 🚀 処理統計（最適化監視用）
        self.processing_stats = {
            "should_use_calls": 0,
            "should_use_approved": 0,
            "richmenu_blocked": 0,
            "processing_attempts": 0,
            "processing_successes": 0,
            "processing_timeouts": 0,
            "processing_errors": 0,
            "sync_fallbacks": 0
        }
    
    def is_richmenu_action(self, query: str) -> bool:
        """リッチメニューの押下アクションかどうかを判定"""
        query_stripped = query.strip()
        
        # 完全一致チェック（絵文字付き・絵文字なし両方）
        for keyword in self.richmenu_keywords:
            if query_stripped == keyword:
                logger.info(f"🚫 リッチメニュー押下を検出、ハルチネーション対策を無効化: {query}")
                return True
        
        # 部分一致チェック（短いキーワードの場合）
        short_keywords = ["AI相談", "資料請求", "展示場来場", "資金計画", "チャット相談"]
        for keyword in short_keywords:
            if query_stripped == keyword or query_stripped.endswith(keyword):
                logger.info(f"🚫 リッチメニュー関連キーワードを検出、ハルチネーション対策を無効化: {query}")
                return True
        
        return False
    
    def should_use_anti_hallucination_strict(self, query: str) -> bool:
        """🚀 厳格なハルチネーション対策使用判定（リッチメニュー押下時は無効化）"""
        self.processing_stats["should_use_calls"] += 1
        
        # リッチメニュー押下の場合は絶対に無効化
        if self.is_richmenu_action(query):
            self.processing_stats["richmenu_blocked"] += 1
            logger.info(f"🚫 リッチメニュー押下のためハルチネーション対策をスキップ: {query}")
            return False
        
        if not ANTI_HALLUCINATION_MODULE_AVAILABLE:
            return False
        
        query_lower = query.lower().strip()
        
        # 🚀 厳格条件1: 明確な補助金制度名が含まれる
        has_specific_subsidy = any(
            keyword in query_lower for keyword in self.strict_subsidy_keywords
        )
        
        # 🚀 厳格条件2: 最新情報を明示的に求めている
        has_temporal_request = any(
            keyword in query_lower for keyword in self.temporal_keywords
        )
        
        # 🚀 厳格条件3: 特定地域の情報を求めている
        has_specific_location = any(
            keyword in query_lower for keyword in self.specific_location_keywords
        )
        
        # 🚀 すべての条件のうち、2つ以上満たす場合のみ適用
        conditions_met = sum([has_specific_subsidy, has_temporal_request, has_specific_location])
        
        # 🚀 更に厳格：質問の長さも考慮（短文は除外）
        is_substantial_query = len(query) > 30
        
        should_use = conditions_met >= 2 and is_substantial_query
        
        if should_use:
            self.processing_stats["should_use_approved"] += 1
            logger.info(f"🛡️ AI相談でのハルチネーション対策を承認: conditions={conditions_met}/3, length={len(query)}")
        else:
            logger.debug(f"🚫 ハルチネーション対策をスキップ: conditions={conditions_met}/3, length={len(query)}")
        
        return should_use
    
    def extract_user_location_fast(self, query: str, user_context: Dict = None) -> str:
        """🚀 高速地域抽出（最小限処理）"""
        # 明確な地域名のみ抽出
        for location in self.specific_location_keywords:
            if location in query:
                return location
        
        # ユーザーコンテキストから取得（簡素化）
        if user_context and "location" in user_context:
            return user_context["location"]
        
        return "兵庫県"  # デフォルト（最も可能性の高い地域）
    
    async def process_with_anti_hallucination_optimized(
        self,
        query: str,
        platform: str,
        user_context: Dict = None,
        original_rag_response: str = None,
        timeout: float = 8.0  # 🔧 短縮：デフォルト8秒
    ) -> Dict[str, Any]:
        """🚀 最適化ハルチネーション対策処理（リッチメニュー押下時は無効化）"""
        
        self.processing_stats["processing_attempts"] += 1
        
        # リッチメニュー押下の場合は処理を行わず、固定テンプレートに委譲
        if self.is_richmenu_action(query):
            logger.info(f"🚫 リッチメニュー押下のためハルチネーション対策をスキップし、固定テンプレートに委譲: {query}")
            return self._create_richmenu_response(query, platform)
        
        logger.info(f"🛡️ AI相談でのハルチネーション対策処理（最適化版）: {query[:40]}...")
        
        if not ANTI_HALLUCINATION_MODULE_AVAILABLE:
            return self._create_basic_filter_response(query, original_rag_response, platform)
        
        try:
            # 🚀 地域情報の高速抽出
            user_location = self.extract_user_location_fast(query, user_context)
            
            # 🚀 タイムアウト付きハルチネーション対策実行
            try:
                result = await asyncio.wait_for(
                    process_housing_subsidy_query(
                        query=query,
                        user_location=user_location,
                        platform=platform
                    ),
                    timeout=timeout
                )
                
                self.processing_stats["processing_successes"] += 1
                
                # 結果の統合処理
                integrated_response = self._integrate_responses_optimized(
                    result, original_rag_response, platform
                )
                
                return integrated_response
                
            except asyncio.TimeoutError:
                self.processing_stats["processing_timeouts"] += 1
                logger.warning(f"⏰ Anti-hallucination timeout ({timeout}s), using basic filter")
                return self._create_basic_filter_response(query, original_rag_response, platform)
                
        except Exception as e:
            self.processing_stats["processing_errors"] += 1
            logger.error(f"❌ Anti-hallucination error: {e}")
            return self._create_basic_filter_response(query, original_rag_response, platform)
    
    def _create_richmenu_response(self, query: str, platform: str) -> Dict[str, Any]:
        """🚀 リッチメニュー押下時の応答（ハルチネーション対策なし）"""
        logger.info(f"🚫 リッチメニュー押下のためハルチネーション対策を完全スキップ: {query}")
        
        return {
            "answer": "",  # 空文字列を返して固定テンプレートシステムに完全委譲
            "confidence_level": 1.0,  # 固定テンプレートは100%信頼性
            "verification_method": "richmenu_fixed_template",
            "verification_note": "🔘 リッチメニュー固定応答",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,  # 使用していない
            "processing_method": "richmenu_bypass"
        }
    
    def _create_basic_filter_response(self, query: str, original_response: str, platform: str) -> Dict[str, Any]:
        """🚀 基本フィルタ応答（軽量版ハルチネーション対策）"""
        self.processing_stats["sync_fallbacks"] += 1
        
        if not original_response:
            basic_answer = "お尋ねの補助金制度について、最新情報は制度運営機関の公式サイトでご確認いただくことをお勧めいたします。"
        else:
            # 🚀 基本的な注意書き追加（軽量処理）
            if any(keyword in query.lower() for keyword in ["補助金", "助成金", "支援金"]):
                notice = "\n\n※補助金制度は年度ごとに変更される可能性があります。最新情報については公式サイトでご確認ください。"
                basic_answer = original_response + notice
            else:
                basic_answer = original_response
        
        return {
            "answer": self._adjust_for_platform_fast(basic_answer, platform),
            "confidence_level": 0.6,
            "verification_method": "basic_filter",
            "verification_note": "⚠️ 基本フィルタリング適用",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "sources": [],
            "warnings": ["簡易処理のため最新情報は公式確認推奨"],
            "anti_hallucination_used": True,
            "processing_method": "lightweight"
        }
    
    def _integrate_responses_optimized(
        self,
        anti_hallucination_result: AntiHallucinationResult,
        original_rag_response: Optional[str],
        platform: str
    ) -> Dict[str, Any]:
        """🚀 最適化応答統合処理（速度重視）"""
        
        # 🚀 信頼性レベルに基づく高速統合戦略
        confidence = anti_hallucination_result.confidence_level
        
        if confidence >= 0.8:
            # 高信頼性：そのまま使用
            primary_answer = anti_hallucination_result.answer
            verification_note = "✅ 高信頼性で確認済み"
            
        elif confidence >= 0.5:
            # 中信頼性：簡易マージ
            if original_rag_response and len(original_rag_response) > 20:
                primary_answer = f"{anti_hallucination_result.answer}\n\n【参考】{original_rag_response[:150]}..."
            else:
                primary_answer = anti_hallucination_result.answer
            verification_note = "⚠️ 中程度の信頼性（要確認推奨）"
            
        else:
            # 低信頼性：元回答ベース
            if original_rag_response:
                primary_answer = original_rag_response + "\n\n※最新情報については公式サイトでご確認ください。"
            else:
                primary_answer = anti_hallucination_result.answer
            verification_note = "ℹ️ 低信頼性（公式確認必須）"
        
        # 🚀 最終調整（プラットフォーム別・高速）
        final_answer = self._adjust_for_platform_fast(primary_answer, platform)
        
        return {
            "answer": final_answer,
            "confidence_level": confidence,
            "verification_method": anti_hallucination_result.verification_method,
            "verification_note": verification_note,
            "last_updated": anti_hallucination_result.last_updated,
            "sources": [
                {
                    "title": source.title,
                    "url": source.url,
                    "reliability": source.reliability_score
                }
                for source in anti_hallucination_result.sources[:2]  # 🔧 削減：3→2
            ],
            "warnings": anti_hallucination_result.warnings[:3],  # 🔧 削減
            "anti_hallucination_used": True,
            "processing_method": "optimized"
        }
    
    def _adjust_for_platform_fast(self, answer: str, platform: str) -> str:
        """🚀 高速プラットフォーム別調整"""
        
        if platform == "line":
            # LINE用：400文字制限
            if len(answer) > 400:
                # 重要部分を保持しつつ短縮
                lines = answer.split('\n')
                condensed = []
                current_length = 0
                
                for line in lines:
                    if current_length + len(line) < 350:
                        condensed.append(line)
                        current_length += len(line)
                    else:
                        break
                
                answer = '\n'.join(condensed) + "\n\n詳細は公式サイトをご確認ください。"
            
            # 改行調整
            answer = answer.replace('\n\n\n', '\n\n')
            
        else:
            # Web用：800文字制限
            if len(answer) > 800:
                answer = answer[:750] + "...\n\n詳細については公式サイトをご確認ください。"
        
        return answer
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """🚀 処理統計取得（最適化監視用）"""
        total_calls = self.processing_stats["should_use_calls"]
        total_attempts = self.processing_stats["processing_attempts"]
        
        return {
            "anti_hallucination_optimization_stats": self.processing_stats,
            "richmenu_optimization": {
                "richmenu_blocked_count": self.processing_stats["richmenu_blocked"],
                "richmenu_block_rate": (self.processing_stats["richmenu_blocked"] / total_calls * 100) if total_calls > 0 else 0
            },
            "efficiency_metrics": {
                "approval_rate": (self.processing_stats["should_use_approved"] / total_calls * 100) if total_calls > 0 else 0,
                "success_rate": (self.processing_stats["processing_successes"] / total_attempts * 100) if total_attempts > 0 else 0,
                "timeout_rate": (self.processing_stats["processing_timeouts"] / total_attempts * 100) if total_attempts > 0 else 0,
                "sync_fallback_rate": (self.processing_stats["sync_fallbacks"] / total_attempts * 100) if total_attempts > 0 else 0
            },
            "optimization_features": [
                "🚫 Richmenu press blocking (fixed template priority)",
                "🚀 Strict keyword filtering (reduced triggers)",
                "⏰ 8s timeout (reduced from default)",
                "🔧 Basic filter fallback",
                "📏 Platform-specific length limits",
                "🎯 2/3 condition requirement"
            ],
            "performance_targets": {
                "richmenu_block_rate": "100% (all richmenu presses blocked)",
                "approval_rate": "< 20% (strict filtering for AI chat only)",
                "success_rate": "> 80%",
                "timeout_rate": "< 15%",
                "processing_time": "< 8s average"
            }
        }

# ==============================================================================
# 🚀 最適化統合関数（リッチメニュー対応版）
# ==============================================================================

# グローバルインスタンス
_optimized_integration = OptimizedAntiHallucinationIntegration()

async def enhance_web_chat_response_optimized(
    query: str,
    original_response: str,
    user_context: Dict = None,
    timeout: float = 8.0
) -> Dict[str, Any]:
    """🚀 Webチャット回答の最適化強化（リッチメニュー押下時は無効化）"""
    
    # リッチメニュー押下の場合は固定テンプレートに完全委譲
    if _optimized_integration.is_richmenu_action(query):
        logger.info("🚫 リッチメニュー押下のためWebチャットハルチネーション対策をスキップ")
        return {
            "answer": original_response,  # 元の応答をそのまま返す
            "confidence_level": 1.0,
            "verification_method": "richmenu_fixed_template",
            "verification_note": "🔘 リッチメニュー固定応答",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "richmenu_bypass"
        }
    
    # 🚀 AI相談での厳格な条件チェック
    if _optimized_integration.should_use_anti_hallucination_strict(query):
        logger.info("🛡️ AI相談でのハルチネーション対策を実行（Webチャット）")
        
        enhanced_response = await _optimized_integration.process_with_anti_hallucination_optimized(
            query=query,
            platform="web",
            user_context=user_context,
            original_rag_response=original_response,
            timeout=timeout
        )
        
        return enhanced_response
    else:
        # 🚀 通常のRAG応答をそのまま返す（高速パス）
        return {
            "answer": original_response,
            "confidence_level": 0.8,
            "verification_method": "standard_rag",
            "verification_note": "📚 社内データベース",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "fast_pass"
        }

async def enhance_line_chat_response_optimized(
    query: str,
    user_id: str,
    original_response: str = None,
    timeout: float = 6.0  # 🔧 LINE用はより短く
) -> Dict[str, Any]:
    """🚀 LINEチャット回答の最適化強化（リッチメニュー押下時は無効化）"""
    
    # リッチメニュー押下の場合は固定テンプレートに完全委譲
    if _optimized_integration.is_richmenu_action(query):
        logger.info("🚫 リッチメニュー押下のためLINEハルチネーション対策をスキップ")
        return {
            "answer": "",  # 空文字列を返して固定テンプレートシステムに委譲
            "confidence_level": 1.0,
            "verification_method": "richmenu_fixed_template",
            "verification_note": "🔘 リッチメニュー固定応答",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "richmenu_bypass"
        }
    
    # 🚀 AI相談での厳格な条件チェック
    if _optimized_integration.should_use_anti_hallucination_strict(query):
        logger.info("🛡️ AI相談でのハルチネーション対策を実行（LINE）")
        
        user_context = {"user_id": user_id, "platform": "line"}
        
        enhanced_response = await _optimized_integration.process_with_anti_hallucination_optimized(
            query=query,
            platform="line",
            user_context=user_context,
            original_rag_response=original_response,
            timeout=timeout
        )
        
        return enhanced_response
    else:
        # 🚀 通常応答（高速パス）
        return {
            "answer": original_response or "申し訳ございません。詳しくはお問い合わせください。",
            "confidence_level": 0.8,
            "verification_method": "standard_rag",
            "verification_note": "📚 社内データ",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "fast_pass"
        }

# ==============================================================================
# 🚀 同期版関数（イベントループエラー対策・リッチメニュー対応版）
# ==============================================================================

def enhance_line_chat_response_sync_optimized(
    query: str,
    user_id: str,
    original_response: str = None
) -> Dict[str, Any]:
    """🚀 LINEチャット回答の同期版強化（リッチメニュー押下時は無効化）"""
    
    # リッチメニュー押下の場合は固定テンプレートに完全委譲
    if _optimized_integration.is_richmenu_action(query):
        logger.info("🚫 リッチメニュー押下のため同期版LINEハルチネーション対策をスキップ")
        return {
            "answer": "",  # 空文字列を返して固定テンプレートシステムに委譲
            "confidence_level": 1.0,
            "verification_method": "richmenu_fixed_template", 
            "verification_note": "🔘 リッチメニュー固定応答",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "sync_richmenu_bypass"
        }
    
    # 🚀 AI相談での厳格条件チェック（同期版）
    if _optimized_integration.should_use_anti_hallucination_strict(query):
        logger.info("🛡️ AI相談での同期版ハルチネーション対策を実行")
        
        # 🚀 同期版基本フィルタリング（軽量処理）
        return _optimized_integration._create_basic_filter_response(query, original_response, "line")
    else:
        # 🚀 高速パス（処理なし）
        return {
            "answer": original_response or "申し訳ございません。詳しくはお問い合わせください。",
            "confidence_level": 0.8,
            "verification_method": "standard_rag",
            "verification_note": "📚 社内データ",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "sync_fast_pass"
        }

def enhance_web_chat_response_sync_optimized(
    query: str,
    original_response: str,
    user_context: Dict = None
) -> Dict[str, Any]:
    """🚀 Webチャット回答の同期版強化（リッチメニュー対応）"""
    
    # リッチメニュー押下の場合は元の応答をそのまま返す
    if _optimized_integration.is_richmenu_action(query):
        logger.info("🚫 リッチメニュー押下のため同期版Webハルチネーション対策をスキップ")
        return {
            "answer": original_response,
            "confidence_level": 1.0,
            "verification_method": "richmenu_fixed_template",
            "verification_note": "🔘 リッチメニュー固定応答", 
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "sync_richmenu_bypass"
        }
    
    # 🚀 AI相談での厳格条件チェック（同期版）
    if _optimized_integration.should_use_anti_hallucination_strict(query):
        logger.info("🛡️ AI相談での同期版ハルチネーション対策を実行")
        
        # 🚀 同期版基本フィルタリング
        return _optimized_integration._create_basic_filter_response(query, original_response, "web")
    else:
        # 🚀 高速パス
        return {
            "answer": original_response,
            "confidence_level": 0.8,
            "verification_method": "standard_rag",
            "verification_note": "📚 社内データベース",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "sync_fast_pass"
        }

# ==============================================================================
# 統計取得関数
# ==============================================================================

def get_anti_hallucination_optimization_stats() -> Dict[str, Any]:
    """🚀 最適化統計取得（リッチメニュー対応）"""
    return _optimized_integration.get_processing_stats()

# ==============================================================================
# 旧関数名の互換性維持（既存コードとの互換性のため）
# ==============================================================================

# 最適化版を優先使用するが、旧関数名でもアクセス可能
enhance_web_chat_response = enhance_web_chat_response_optimized
enhance_line_chat_response = enhance_line_chat_response_optimized
enhance_line_chat_response_sync = enhance_line_chat_response_sync_optimized
enhance_web_chat_response_sync = enhance_web_chat_response_sync_optimized

# ==============================================================================
# リッチメニュー判定用外部関数
# ==============================================================================

def is_richmenu_action(query: str) -> bool:
    """リッチメニュー押下判定（外部からの呼び出し用）"""
    return _optimized_integration.is_richmenu_action(query)

def should_skip_anti_hallucination(query: str) -> bool:
    """ハルチネーション対策をスキップすべきかの判定（外部からの呼び出し用）"""
    return _optimized_integration.is_richmenu_action(query)

# ==============================================================================
# テスト・デバッグ用
# ==============================================================================

class OptimizedAntiHallucinationTest:
    """最適化統合テスト用クラス（リッチメニュー対応）"""
    
    def __init__(self):
        self.integration = OptimizedAntiHallucinationIntegration()
    
    async def test_richmenu_blocking(self):
        """リッチメニュー押下ブロックテスト"""
        richmenu_cases = [
            "🤖 AI相談",
            "🌐 AI住まいサイト", 
            "📋 資料請求",
            "📍 展示場来場",
            "💰 資金計画",
            "💬 チャット相談",
            "AI相談",
            "資料請求"
        ]
        
        print("🧪 Richmenu Blocking Test Results:")
        print("=" * 50)
        
        for query in richmenu_cases:
            is_blocked = self.integration.is_richmenu_action(query)
            should_use = self.integration.should_use_anti_hallucination_strict(query)
            
            status = "✅ BLOCKED" if is_blocked and not should_use else "❌ NOT BLOCKED"
            print(f"{status} '{query}' -> blocked={is_blocked}, should_use={should_use}")
    
    async def test_strict_conditions(self):
        """厳格条件テスト（AI相談時のみ）"""
        test_cases = [
            # 承認されるべきケース（AI相談時）
            ("兵庫県の2024年度ZEH補助金について教えてください", True),
            ("加東市のこどもエコすまい支援事業2024年最新情報はどうなっていますか", True),
            ("現在実施中の住宅ローン控除制度について神戸市での適用例を知りたい", True),
            
            # 拒否されるべきケース
            ("住宅ローン控除について", False),
            ("補助金", False),
            ("ZEH補助金", False),
            ("坪単価について教えて", False),
            ("標準仕様はどんな感じ？", False),
            
            # リッチメニュー（拒否されるべき）
            ("🤖 AI相談", False),
            ("📋 資料請求", False)
        ]
        
        print("\n🧪 Strict Condition Test Results (AI Chat Only):")
        print("=" * 60)
        
        for query, expected in test_cases:
            is_richmenu = self.integration.is_richmenu_action(query)
            result = self.integration.should_use_anti_hallucination_strict(query)
            
            if is_richmenu:
                expected = False  # リッチメニューは必ず拒否
            
            status = "✅ PASS" if result == expected else "❌ FAIL"
            note = "(richmenu)" if is_richmenu else ""
            print(f"{status} '{query[:40]}...' -> {result} (expected: {expected}) {note}")
        
        stats = self.integration.get_processing_stats()
        print(f"\nApproval rate: {stats['efficiency_metrics']['approval_rate']:.1f}%")
        print(f"Richmenu block rate: {stats['richmenu_optimization']['richmenu_block_rate']:.1f}%")

if __name__ == "__main__":
    async def main():
        tester = OptimizedAntiHallucinationTest()
        await tester.test_richmenu_blocking()
        await tester.test_strict_conditions()
    
    asyncio.run(main())