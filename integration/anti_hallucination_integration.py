import logging
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
import os

# ハルシネーション対策システムをインポート（条件付き）
try:
    from utils.housing_subsidy_anti_hallucination import (
        process_housing_subsidy_query,
        AntiHallucinationResult
    )
    ANTI_HALLUCINATION_MODULE_AVAILABLE = True
except ImportError:
    ANTI_HALLUCINATION_MODULE_AVAILABLE = False

logger = logging.getLogger(__name__)

class OptimizedAntiHallucinationIntegration:
    """最適化ハルシネーション対策統合クラス（速度優先・リッチメニュー対応）"""
    
    def __init__(self):
        # 環境変数から設定を読み込み（デフォルトは無効）
        self.enabled = os.environ.get("ENABLE_ANTI_HALLUCINATION", "false").lower() == "true"
        
        # リッチメニューの固定応答キーワード（ハルシネーション対策を完全無効化）
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
            "チャット相談",
            "展示場来場　予約"
        ]
        
        # 厳格化：補助金関連キーワードを限定（AI相談での実際の質問時のみ適用）
        self.strict_subsidy_keywords = [
            # 明確な補助金制度名のみ
            "zeh補助金", "zeh支援事業", "ネット・ゼロ・エネルギー・ハウス支援事業",
            "こどもエコすまい支援事業", "子どもエコすまい", "子育てエコホーム支援事業",
            "住宅ローン控除", "住宅ローン減税", "住宅借入金等特別控除",
            "長期優良住宅化リフォーム推進事業",
            "既存住宅における断熱リフォーム支援事業"
        ]
        
        # 年度限定キーワード（より厳格）
        self.temporal_keywords = [
            "2024年度", "2025年度", "令和6年度", "令和7年度",
            "2024年最新", "2025年最新", "現在実施中の",
            "今年度の補助金", "最新の補助金制度"
        ]
        
        # 地域キーワード（特定地域のみ）
        self.specific_location_keywords = [
            "兵庫県", "大阪府", "京都府", "奈良県", "和歌山県", "滋賀県",
            "加東市", "明石市", "三木市", "加古川市", "神戸市", "姫路市"
        ]
        
        # 処理統計（最適化監視用）
        self.processing_stats = {
            "total_calls": 0,
            "enabled_checks": 0,
            "disabled_by_env": 0,
            "richmenu_blocked": 0,
            "conditions_approved": 0,
            "processing_successes": 0,
            "processing_timeouts": 0,
            "processing_errors": 0,
            "basic_filter_used": 0
        }
    
    def is_richmenu_action(self, query: str) -> bool:
        """リッチメニューの押下アクションかどうかを判定"""
        query_stripped = query.strip()
        
        # 完全一致チェック（絵文字付き・絵文字なし両方）
        for keyword in self.richmenu_keywords:
            if query_stripped == keyword:
                logger.info(f"リッチメニュー押下を検出（ハルシネーション対策スキップ）: {query}")
                return True
        
        # 部分一致チェック（短いキーワードの場合）
        short_keywords = ["AI相談", "資料請求", "展示場来場", "資金計画", "チャット相談", "展示場来場　予約"]
        for keyword in short_keywords:
            if query_stripped == keyword or query_stripped.endswith(keyword):
                logger.info(f"リッチメニュー関連キーワードを検出（ハルシネーション対策スキップ）: {query}")
                return True
        
        return False
    
    def should_use_anti_hallucination_strict(self, query: str) -> bool:
        """厳格なハルシネーション対策使用判定（環境変数とリッチメニューを考慮）"""
        self.processing_stats["total_calls"] += 1
        
        # 環境変数でOFFの場合（デフォルト）
        if not self.enabled:
            self.processing_stats["disabled_by_env"] += 1
            logger.debug(f"ハルシネーション対策が無効化されています: {query}")
            return False
        
        # リッチメニュー押下の場合は絶対に無効化
        if self.is_richmenu_action(query):
            self.processing_stats["richmenu_blocked"] += 1
            return False
        
        # モジュールが利用不可の場合
        if not ANTI_HALLUCINATION_MODULE_AVAILABLE:
            logger.warning("Anti-hallucination module not available")
            return False
        
        query_lower = query.lower().strip()
        
        # 厳格条件1: 明確な補助金制度名が含まれる
        has_specific_subsidy = any(
            keyword in query_lower for keyword in self.strict_subsidy_keywords
        )
        
        # 厳格条件2: 最新情報を明示的に求めている
        has_temporal_request = any(
            keyword in query_lower for keyword in self.temporal_keywords
        )
        
        # 厳格条件3: 特定地域の情報を求めている
        has_specific_location = any(
            keyword in query_lower for keyword in self.specific_location_keywords
        )
        
        # すべての条件のうち、2つ以上満たす場合のみ適用
        conditions_met = sum([has_specific_subsidy, has_temporal_request, has_specific_location])
        
        # 更に厳格：質問の長さも考慮（短文は除外）
        is_substantial_query = len(query) > 30
        
        should_use = conditions_met >= 2 and is_substantial_query
        
        if should_use:
            self.processing_stats["conditions_approved"] += 1
            logger.info(f"ハルシネーション対策を適用: {query}")
        else:
            logger.debug(f"ハルシネーション対策条件を満たさず: {query}")
        
        return should_use
    
    def extract_user_location_fast(self, query: str, user_context: Dict = None) -> str:
        """高速地域抽出（最小限処理）"""
        # 明確な地域名のみ抽出
        for location in self.specific_location_keywords:
            if location in query:
                return location
        
        # ユーザーコンテキストから取得（簡素化）
        if user_context and "location" in user_context:
            return user_context["location"]
        
        return "兵庫県"  # デフォルト
    
    async def process_with_anti_hallucination_optimized(
        self,
        query: str,
        platform: str,
        user_context: Dict = None,
        original_rag_response: str = None,
        timeout: float = 8.0
    ) -> Dict[str, Any]:
        """最適化ハルシネーション対策処理"""
        
        # 環境変数チェック
        if not self.enabled:
            return self._create_passthrough_response(original_rag_response, platform)
        
        # リッチメニュー押下の場合
        if self.is_richmenu_action(query):
            return self._create_richmenu_response(query, platform)
        
        # モジュール利用不可の場合
        if not ANTI_HALLUCINATION_MODULE_AVAILABLE:
            return self._create_basic_filter_response(query, original_rag_response, platform)
        
        try:
            # 地域情報の高速抽出
            user_location = self.extract_user_location_fast(query, user_context)
            
            # タイムアウト付きハルシネーション対策実行
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
                logger.warning(f"Anti-hallucination timeout ({timeout}s)")
                return self._create_basic_filter_response(query, original_rag_response, platform)
                
        except Exception as e:
            self.processing_stats["processing_errors"] += 1
            logger.error(f"Anti-hallucination error: {e}")
            return self._create_basic_filter_response(query, original_rag_response, platform)
    
    def _create_passthrough_response(self, original_response: str, platform: str) -> Dict[str, Any]:
        """環境変数でOFFの場合のパススルー応答"""
        return {
            "answer": original_response or "",
            "confidence_level": 1.0,
            "verification_method": "passthrough",
            "verification_note": "ハルシネーション対策無効",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "disabled_by_env"
        }
    
    def _create_richmenu_response(self, query: str, platform: str) -> Dict[str, Any]:
        """リッチメニュー押下時の応答（空文字列で固定テンプレートに完全委譲）"""
        return {
            "answer": "",  # 空文字列を返して固定テンプレートシステムに完全委譲
            "confidence_level": 1.0,
            "verification_method": "richmenu_fixed_template",
            "verification_note": "リッチメニュー固定応答",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "richmenu_bypass"
        }
    
    def _create_basic_filter_response(self, query: str, original_response: str, platform: str) -> Dict[str, Any]:
        """基本フィルタ応答（軽量版）"""
        self.processing_stats["basic_filter_used"] += 1
        
        if not original_response:
            basic_answer = "お尋ねの補助金制度について、最新情報は制度運営機関の公式サイトでご確認いただくことをお勧めいたします。"
        else:
            # 基本的な注意書き追加（軽量処理）
            if any(keyword in query.lower() for keyword in ["補助金", "助成金", "支援金"]):
                notice = "\n\n※補助金制度は年度ごとに変更される可能性があります。最新情報については公式サイトでご確認ください。"
                basic_answer = original_response + notice
            else:
                basic_answer = original_response
        
        return {
            "answer": self._adjust_for_platform_fast(basic_answer, platform),
            "confidence_level": 0.6,
            "verification_method": "basic_filter",
            "verification_note": "基本フィルタリング適用",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "sources": [],
            "warnings": ["簡易処理のため最新情報は公式確認推奨"],
            "anti_hallucination_used": True,
            "processing_method": "lightweight"
        }
    
    def _integrate_responses_optimized(
        self,
        anti_hallucination_result: 'AntiHallucinationResult',
        original_rag_response: Optional[str],
        platform: str
    ) -> Dict[str, Any]:
        """最適化応答統合処理"""
        
        # 信頼性レベルに基づく高速統合戦略
        confidence = anti_hallucination_result.confidence_level
        
        if confidence >= 0.8:
            # 高信頼性：そのまま使用
            primary_answer = anti_hallucination_result.answer
            verification_note = "高信頼性で確認済み"
            
        elif confidence >= 0.5:
            # 中信頼性：簡易マージ
            if original_rag_response and len(original_rag_response) > 20:
                primary_answer = f"{anti_hallucination_result.answer}\n\n【参考】{original_rag_response[:150]}..."
            else:
                primary_answer = anti_hallucination_result.answer
            verification_note = "中程度の信頼性（要確認推奨）"
            
        else:
            # 低信頼性：元回答ベース
            if original_rag_response:
                primary_answer = original_rag_response + "\n\n※最新情報については公式サイトでご確認ください。"
            else:
                primary_answer = anti_hallucination_result.answer
            verification_note = "低信頼性（公式確認必須）"
        
        # 最終調整（プラットフォーム別）
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
                for source in anti_hallucination_result.sources[:2]  # 上位2件のみ
            ],
            "warnings": anti_hallucination_result.warnings[:3],  # 上位3件のみ
            "anti_hallucination_used": True,
            "processing_method": "optimized"
        }
    
    def _adjust_for_platform_fast(self, answer: str, platform: str) -> str:
        """高速プラットフォーム別調整"""
        
        if platform == "line":
            # LINE用：400文字制限
            if len(answer) > 400:
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
        """処理統計取得"""
        total = self.processing_stats["total_calls"]
        
        return {
            "statistics": self.processing_stats,
            "rates": {
                "disabled_rate": (self.processing_stats["disabled_by_env"] / total * 100) if total > 0 else 0,
                "richmenu_block_rate": (self.processing_stats["richmenu_blocked"] / total * 100) if total > 0 else 0,
                "approval_rate": (self.processing_stats["conditions_approved"] / total * 100) if total > 0 else 0,
                "success_rate": (self.processing_stats["processing_successes"] / self.processing_stats["conditions_approved"] * 100) 
                    if self.processing_stats["conditions_approved"] > 0 else 0
            },
            "configuration": {
                "enabled": self.enabled,
                "module_available": ANTI_HALLUCINATION_MODULE_AVAILABLE
            }
        }

# グローバルインスタンス
_optimized_integration = OptimizedAntiHallucinationIntegration()

async def enhance_web_chat_response_optimized(
    query: str,
    original_response: str,
    user_context: Dict = None,
    timeout: float = 8.0
) -> Dict[str, Any]:
    """Webチャット回答の最適化強化"""
    
    # 環境変数でOFFの場合（デフォルト）
    if not _optimized_integration.enabled:
        return _optimized_integration._create_passthrough_response(original_response, "web")
    
    # リッチメニュー押下の場合（Webでは通常発生しないが念のため）
    if _optimized_integration.is_richmenu_action(query):
        return {
            "answer": original_response,
            "confidence_level": 1.0,
            "verification_method": "richmenu_fixed_template",
            "verification_note": "リッチメニュー固定応答",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "richmenu_bypass"
        }
    
    # 厳格な条件チェック
    if _optimized_integration.should_use_anti_hallucination_strict(query):
        enhanced_response = await _optimized_integration.process_with_anti_hallucination_optimized(
            query=query,
            platform="web",
            user_context=user_context,
            original_rag_response=original_response,
            timeout=timeout
        )
        return enhanced_response
    else:
        # 通常のRAG応答をそのまま返す
        return {
            "answer": original_response,
            "confidence_level": 0.8,
            "verification_method": "standard_rag",
            "verification_note": "社内データベース",
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
    timeout: float = 6.0
) -> Dict[str, Any]:
    """LINEチャット回答の最適化強化"""
    
    # 環境変数でOFFの場合（デフォルト）
    if not _optimized_integration.enabled:
        return _optimized_integration._create_passthrough_response(original_response or "", "line")
    
    # リッチメニュー押下の場合
    if _optimized_integration.is_richmenu_action(query):
        return {
            "answer": "",  # 空文字列で固定テンプレートに委譲
            "confidence_level": 1.0,
            "verification_method": "richmenu_fixed_template",
            "verification_note": "リッチメニュー固定応答",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "richmenu_bypass"
        }
    
    # 厳格な条件チェック
    if _optimized_integration.should_use_anti_hallucination_strict(query):
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
        # 通常応答
        return {
            "answer": original_response or "申し訳ございません。詳しくはお問い合わせください。",
            "confidence_level": 0.8,
            "verification_method": "standard_rag",
            "verification_note": "社内データ",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "fast_pass"
        }

# 同期版関数
def enhance_line_chat_response_sync_optimized(
    query: str,
    user_id: str,
    original_response: str = None
) -> Dict[str, Any]:
    """LINEチャット回答の同期版強化"""
    
    # 環境変数でOFFの場合（デフォルト）
    if not _optimized_integration.enabled:
        return _optimized_integration._create_passthrough_response(original_response or "", "line")
    
    # リッチメニュー押下の場合
    if _optimized_integration.is_richmenu_action(query):
        return {
            "answer": "",  # 空文字列で固定テンプレートに委譲
            "confidence_level": 1.0,
            "verification_method": "richmenu_fixed_template",
            "verification_note": "リッチメニュー固定応答",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "sync_richmenu_bypass"
        }
    
    # 厳格条件チェック（同期版）
    if _optimized_integration.should_use_anti_hallucination_strict(query):
        # 同期版基本フィルタリング
        return _optimized_integration._create_basic_filter_response(query, original_response, "line")
    else:
        return {
            "answer": original_response or "申し訳ございません。詳しくはお問い合わせください。",
            "confidence_level": 0.8,
            "verification_method": "standard_rag",
            "verification_note": "社内データ",
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
    """Webチャット回答の同期版強化"""
    
    # 環境変数でOFFの場合（デフォルト）
    if not _optimized_integration.enabled:
        return _optimized_integration._create_passthrough_response(original_response, "web")
    
    # リッチメニュー押下の場合（Webでは通常発生しないが念のため）
    if _optimized_integration.is_richmenu_action(query):
        return {
            "answer": original_response,
            "confidence_level": 1.0,
            "verification_method": "richmenu_fixed_template",
            "verification_note": "リッチメニュー固定応答",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "sync_richmenu_bypass"
        }
    
    # 厳格条件チェック（同期版）
    if _optimized_integration.should_use_anti_hallucination_strict(query):
        return _optimized_integration._create_basic_filter_response(query, original_response, "web")
    else:
        return {
            "answer": original_response,
            "confidence_level": 0.8,
            "verification_method": "standard_rag",
            "verification_note": "社内データベース",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False,
            "processing_method": "sync_fast_pass"
        }

# 統計取得関数
def get_anti_hallucination_optimization_stats() -> Dict[str, Any]:
    """最適化統計取得"""
    return _optimized_integration.get_processing_stats()

# 旧関数名の互換性維持
enhance_web_chat_response = enhance_web_chat_response_optimized
enhance_line_chat_response = enhance_line_chat_response_optimized
enhance_line_chat_response_sync = enhance_line_chat_response_sync_optimized
enhance_web_chat_response_sync = enhance_web_chat_response_sync_optimized

# 外部呼び出し用関数
def is_richmenu_action(query: str) -> bool:
    """リッチメニュー押下判定"""
    return _optimized_integration.is_richmenu_action(query)

def should_skip_anti_hallucination(query: str) -> bool:
    """ハルシネーション対策をスキップすべきかの判定"""
    return not _optimized_integration.enabled or _optimized_integration.is_richmenu_action(query)
