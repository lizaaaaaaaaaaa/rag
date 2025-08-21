# integration/anti_hallucination_integration.py - 統合システム

import logging
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

# ハルチネーション対策システムをインポート
from utils.housing_subsidy_anti_hallucination import (
    process_housing_subsidy_query,
    AntiHallucinationResult
)

logger = logging.getLogger(__name__)

class AntiHallucinationIntegration:
    """ハルチネーション対策統合クラス"""
    
    def __init__(self):
        # 補助金関連キーワードの判定用
        self.subsidy_keywords = [
            "補助金", "助成金", "支援金", "給付金", "控除", "減税",
            "ZEH", "省エネ", "断熱", "耐震", "リフォーム", "改修",
            "住宅ローン", "フラット35", "こどもエコ", "子育て世帯",
            "若年夫婦", "新婚", "長期優良", "認定住宅",
            "2024", "2025", "令和6", "令和7", "最新", "現在"
        ]
        
        # 地域キーワードの判定用
        self.location_keywords = [
            "兵庫", "大阪", "京都", "奈良", "和歌山", "滋賀",
            "加東", "明石", "三木", "加古川", "寝屋川", "関西"
        ]
    
    def should_use_anti_hallucination(self, query: str) -> bool:
        """ハルチネーション対策を使用すべきかの判定"""
        
        query_lower = query.lower()
        
        # 補助金関連キーワードの存在確認
        has_subsidy_keyword = any(
            keyword in query_lower for keyword in self.subsidy_keywords
        )
        
        # 最新情報を求めるキーワード
        needs_current_info = any(
            keyword in query_lower 
            for keyword in ["最新", "現在", "今", "2024", "2025"]
        )
        
        return has_subsidy_keyword or needs_current_info
    
    def extract_user_location(self, query: str, user_context: Dict = None) -> str:
        """ユーザーの地域情報を抽出"""
        
        # クエリから地域を抽出
        for location in self.location_keywords:
            if location in query:
                return location
        
        # ユーザーコンテキストから地域を取得
        if user_context:
            return user_context.get("location", "関西")
        
        return "関西"  # デフォルト
    
    async def process_with_anti_hallucination(
        self,
        query: str,
        platform: str,
        user_context: Dict = None,
        original_rag_response: str = None
    ) -> Dict[str, Any]:
        """ハルチネーション対策付きの統合処理"""
        
        logger.info(f"🛡️ Anti-hallucination processing: platform={platform}, query={query[:50]}...")
        
        try:
            # 地域情報の抽出
            user_location = self.extract_user_location(query, user_context)
            
            # ハルチネーション対策システムで処理
            result = await process_housing_subsidy_query(
                query=query,
                user_location=user_location,
                platform=platform
            )
            
            # 結果の統合処理
            integrated_response = self._integrate_responses(
                result, original_rag_response, platform
            )
            
            return integrated_response
            
        except Exception as e:
            logger.error(f"❌ Anti-hallucination integration error: {e}")
            return self._create_fallback_response(query, platform, str(e))
    
    def _integrate_responses(
        self,
        anti_hallucination_result: AntiHallucinationResult,
        original_rag_response: Optional[str],
        platform: str
    ) -> Dict[str, Any]:
        """回答の統合処理"""
        
        # 信頼性レベルに基づく統合戦略
        if anti_hallucination_result.confidence_level >= 0.7:
            # 高信頼性：ハルチネーション対策結果を主回答として使用
            primary_answer = anti_hallucination_result.answer
            verification_note = "✅ 最新情報で確認済み"
            
        elif anti_hallucination_result.confidence_level >= 0.4:
            # 中信頼性：両方の情報を併用
            primary_answer = self._merge_answers(
                anti_hallucination_result.answer,
                original_rag_response,
                platform
            )
            verification_note = "⚠️ 最新情報で補完済み（要確認）"
            
        else:
            # 低信頼性：元のRAG回答をベースに注意書きを追加
            if original_rag_response:
                primary_answer = original_rag_response + "\n\n※最新情報については公式サイトでご確認ください。"
            else:
                primary_answer = anti_hallucination_result.answer
            verification_note = "ℹ️ 一般的な情報です（最新確認推奨）"
        
        # 最終更新日の付加
        if anti_hallucination_result.last_updated:
            update_note = f"\n\n📅 最終更新: {anti_hallucination_result.last_updated}"
            primary_answer += update_note
        
        # プラットフォーム別の最終調整
        final_answer = self._adjust_for_platform(primary_answer, platform)
        
        return {
            "answer": final_answer,
            "confidence_level": anti_hallucination_result.confidence_level,
            "verification_method": anti_hallucination_result.verification_method,
            "verification_note": verification_note,
            "last_updated": anti_hallucination_result.last_updated,
            "sources": [
                {
                    "title": source.title,
                    "url": source.url,
                    "domain": source.source_domain,
                    "reliability": source.reliability_score,
                    "current": source.is_current
                }
                for source in anti_hallucination_result.sources[:3]
            ],
            "warnings": anti_hallucination_result.warnings,
            "anti_hallucination_used": True
        }
    
    def _merge_answers(
        self,
        anti_hallucination_answer: str,
        original_rag_answer: Optional[str],
        platform: str
    ) -> str:
        """回答のマージ"""
        
        if not original_rag_answer:
            return anti_hallucination_answer
        
        # プラットフォーム別の文字数制限
        max_length = 400 if platform == "line" else 800
        
        # マージ戦略：ハルチネーション対策回答をメインとし、RAG回答で補完
        merged = f"{anti_hallucination_answer}\n\n【参考情報】\n{original_rag_answer[:200]}..."
        
        if len(merged) > max_length:
            merged = anti_hallucination_answer
        
        return merged
    
    def _adjust_for_platform(self, answer: str, platform: str) -> str:
        """プラットフォーム別調整"""
        
        if platform == "line":
            # LINE用：簡潔で読みやすく
            max_length = 500
            if len(answer) > max_length:
                # 重要な情報を保持しながら短縮
                lines = answer.split('\n')
                condensed_lines = []
                current_length = 0
                
                for line in lines:
                    if current_length + len(line) < max_length - 50:
                        condensed_lines.append(line)
                        current_length += len(line)
                    else:
                        break
                
                answer = '\n'.join(condensed_lines) + "\n\n詳細は公式サイトをご確認ください。"
            
            # 改行の調整
            answer = answer.replace('\n\n', '\n')
            
        else:
            # Web用：詳細で包括的
            max_length = 1000
            if len(answer) > max_length:
                answer = answer[:max_length-50] + "...\n\n詳細については公式サイトをご確認ください。"
        
        return answer
    
    def _create_fallback_response(
        self, 
        query: str, 
        platform: str, 
        error_msg: str
    ) -> Dict[str, Any]:
        """フォールバック回答の作成"""
        
        fallback_answer = f"申し訳ございません。『{query}』についての最新情報の確認中にエラーが発生しました。住宅補助金の制度は年度ごとに変更される可能性がありますので、最新情報については直接管轄の行政機関にお問い合わせいただくことをお勧めいたします。"
        
        return {
            "answer": fallback_answer,
            "confidence_level": 0.0,
            "verification_method": "error_fallback",
            "verification_note": "❌ 検索エラー",
            "last_updated": None,
            "sources": [],
            "warnings": [f"検索エラー: {error_msg}"],
            "anti_hallucination_used": True
        }

# Webチャット用の統合関数
async def enhance_web_chat_response(
    query: str,
    original_response: str,
    user_context: Dict = None
) -> Dict[str, Any]:
    """Webチャット回答の強化"""
    
    integration = AntiHallucinationIntegration()
    
    # ハルチネーション対策が必要かチェック
    if integration.should_use_anti_hallucination(query):
        logger.info("🛡️ Using anti-hallucination for web chat")
        
        enhanced_response = await integration.process_with_anti_hallucination(
            query=query,
            platform="web",
            user_context=user_context,
            original_rag_response=original_response
        )
        
        return enhanced_response
    else:
        # 通常のRAG応答をそのまま返す
        return {
            "answer": original_response,
            "confidence_level": 0.8,
            "verification_method": "standard_rag",
            "verification_note": "📚 社内データベース",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False
        }

# LINEチャット用の統合関数
async def enhance_line_chat_response(
    query: str,
    user_id: str,
    original_response: str = None
) -> Dict[str, Any]:
    """LINEチャット回答の強化"""
    
    integration = AntiHallucinationIntegration()
    
    # ハルチネーション対策が必要かチェック
    if integration.should_use_anti_hallucination(query):
        logger.info("🛡️ Using anti-hallucination for LINE chat")
        
        # ユーザーコンテキストは簡易版
        user_context = {"user_id": user_id, "platform": "line"}
        
        enhanced_response = await integration.process_with_anti_hallucination(
            query=query,
            platform="line",
            user_context=user_context,
            original_rag_response=original_response
        )
        
        return enhanced_response
    else:
        # 通常のRAG応答をそのまま返す
        return {
            "answer": original_response or "申し訳ございません。お答えできませんでした。",
            "confidence_level": 0.8,
            "verification_method": "standard_rag",
            "verification_note": "📚 社内データ",
            "last_updated": None,
            "sources": [],
            "warnings": [],
            "anti_hallucination_used": False
        }

# ==============================================================================
# 既存システムへの統合パッチ
# ==============================================================================

# 1. chat.py用の統合パッチ
"""
api/routers/chat.py に以下のコードを追加：

# ファイル先頭にインポート追加
from integration.anti_hallucination_integration import enhance_web_chat_response

# chat_endpoint 関数内でRAG処理後に以下を追加：
if rag_chain_template:
    result = rag_chain_template.invoke({"query": query})
    raw_answer = result.get("result", "")
    
    # ハルチネーション対策の適用
    enhanced_result = await enhance_web_chat_response(
        query=query,
        original_response=raw_answer,
        user_context={"username": user}
    )
    
    answer = enhanced_result["answer"]
    
    # 追加情報をレスポンスに含める
    response = {
        "answer": answer,
        "sources": enhanced_result.get("sources", []),
        "verification": {
            "method": enhanced_result.get("verification_method"),
            "note": enhanced_result.get("verification_note"),
            "confidence": enhanced_result.get("confidence_level"),
            "last_updated": enhanced_result.get("last_updated"),
            "warnings": enhanced_result.get("warnings", [])
        },
        "status": "ok"
    }
"""

# 2. line_bot_fixed.py用の統合パッチ
"""
api/routers/line_bot_fixed.py に以下のコードを追加：

# ファイル先頭にインポート追加
from integration.anti_hallucination_integration import enhance_line_chat_response

# process_general_question 関数を以下のように修正：
async def process_general_question(message_text: str, user_id: str) -> str:
    try:
        globals_dict = get_app_globals()
        original_response = None
        
        if globals_dict.get('rag_chain_template'):
            result = globals_dict['rag_chain_template'].invoke({"query": message_text})
            original_response = result.get("result", "")
        
        # ハルチネーション対策の適用
        enhanced_result = await enhance_line_chat_response(
            query=message_text,
            user_id=user_id,
            original_response=original_response
        )
        
        return enhanced_result["answer"]
        
    except Exception as e:
        logger.error(f"Error processing question: {e}")
        return "申し訳ございません。エラーが発生しました。"

# handle_text_message_ultimate 関数内で user_id を process_general_question に渡すように修正
"""

# 3. chat_ultra_fast.py用の統合パッチ
"""
api/routers/chat_ultra_fast.py に以下のコードを追加：

# ファイル先頭にインポート追加
from integration.anti_hallucination_integration import enhance_web_chat_response

# UnifiedResponseGenerator クラスの generate_unified_response メソッド内に追加：
async def generate_unified_response(self, query: str, user: str) -> Dict[str, Any]:
    start_time = time.time()
    
    try:
        # 既存のキャッシュチェック
        cached_response = self.cache.get(query)
        if cached_response:
            return cached_response
        
        # テンプレートマッチング
        template_response = self._match_unified_template(query)
        if template_response:
            result = {
                "answer": template_response,
                "processing_time": time.time() - start_time,
                "source": "template",
                "status": "ok"
            }
            self.cache.set(query, result)
            return result
        
        # RAG処理
        rag_response = await self._unified_rag_processing(query)
        if rag_response:
            # ハルチネーション対策の適用
            enhanced_result = await enhance_web_chat_response(
                query=query,
                original_response=rag_response,
                user_context={"username": user}
            )
            
            result = {
                "answer": enhanced_result["answer"],
                "processing_time": time.time() - start_time,
                "source": "rag_enhanced",
                "verification": enhanced_result.get("verification_note"),
                "last_updated": enhanced_result.get("last_updated"),
                "status": "ok"
            }
            self.cache.set(query, result)
            return result
        
        # フォールバック処理...
"""

# テスト用の統合テストクラス
class AntiHallucinationIntegrationTest:
    """統合テスト用クラス"""
    
    def __init__(self):
        self.integration = AntiHallucinationIntegration()
    
    async def test_web_integration(self):
        """Web統合テスト"""
        test_cases = [
            ("住宅ローン控除 2025年度について教えて", "住宅ローン控除の基本情報..."),
            ("ZEH補助金 兵庫県", "ZEH補助金の概要..."),
            ("最新の省エネ住宅支援制度", "省エネ住宅の支援制度...")
        ]
        
        for query, original_response in test_cases:
            print(f"\n=== Web統合テスト: {query} ===")
            
            result = await enhance_web_chat_response(
                query=query,
                original_response=original_response,
                user_context={"username": "test_user"}
            )
            
            print(f"回答: {result['answer'][:100]}...")
            print(f"信頼性: {result['confidence_level']:.2f}")
            print(f"検証方法: {result['verification_method']}")
            print(f"ハルチネーション対策: {result['anti_hallucination_used']}")
    
    async def test_line_integration(self):
        """LINE統合テスト"""
        test_cases = [
            ("こどもエコすまい支援事業", "test_user_1"),
            ("加東市の住宅補助金", "test_user_2"),
            ("最新の断熱リフォーム補助金", "test_user_3")
        ]
        
        for query, user_id in test_cases:
            print(f"\n=== LINE統合テスト: {query} ===")
            
            result = await enhance_line_chat_response(
                query=query,
                user_id=user_id,
                original_response="一般的な住宅情報です。"
            )
            
            print(f"回答: {result['answer'][:100]}...")
            print(f"信頼性: {result['confidence_level']:.2f}")
            print(f"最終更新日: {result['last_updated']}")
            print(f"警告: {result['warnings']}")

# メイン実行（テスト用）
if __name__ == "__main__":
    async def main():
        tester = AntiHallucinationIntegrationTest()
        await tester.test_web_integration()
        await tester.test_line_integration()
    
    asyncio.run(main())