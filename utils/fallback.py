# utils/fallback.py (新規作成)
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class RAGFallbackHandler:
    def __init__(self):
        self.fallback_strategies = [
            self._try_web_search,
            self._try_general_llm,
            self._return_default_response
        ]
    
    async def handle_failure(self, query: str, error: Exception) -> Dict[str, Any]:
        """エラー時のフォールバック処理"""
        logger.error(f"RAG処理エラー: {error}")
        
        for strategy in self.fallback_strategies:
            try:
                result = await strategy(query)
                if result:
                    logger.info(f"フォールバック成功: {strategy.__name__}")
                    return result
            except Exception as e:
                logger.error(f"フォールバック失敗 {strategy.__name__}: {e}")
                continue
        
        return self._return_error_response()
    
    async def _try_web_search(self, query: str) -> Optional[Dict]:
        """Web検索による回答生成"""
        from utils.web_search import GoogleSearcher
        searcher = GoogleSearcher()
        
        if searcher.should_search_web(query):
            answer = searcher.get_enhanced_answer(query, use_web_search=True)
            return {"answer": answer, "fallback": "web_search"}
        return None
    
    async def _try_general_llm(self, query: str) -> Optional[Dict]:
        """一般的なLLM回答"""
        try:
            from llm.llm_runner import load_llm
            llm, _, _ = load_llm()
            
            prompt = f"""質問に対して、一般的な知識に基づいて丁寧に回答してください。
不明な点がある場合は、推測ではなく「詳細は確認が必要です」と答えてください。

質問: {query}

回答:"""
            
            response = llm.invoke(prompt)
            answer = response.content if hasattr(response, 'content') else str(response)
            
            return {"answer": answer, "fallback": "general_llm"}
        except Exception:
            return None
    
    def _return_default_response(self, query: str = "") -> Dict:
        """デフォルト応答"""
        return {
            "answer": "申し訳ございません。一時的にシステムに問題が発生しています。しばらくしてから再度お試しください。",
            "fallback": "default"
        }
    
    def _return_error_response(self) -> Dict:
        """エラー応答"""
        return {
            "answer": "システムエラーが発生しました。管理者にお問い合わせください。",
            "error": True
        }