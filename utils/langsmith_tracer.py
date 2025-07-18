# utils/langsmith_tracer.py (新規作成)
import os
from langsmith import Client, traceable
from langchain.callbacks import LangChainTracer
from typing import Any, Dict

class RAGTracer:
    def __init__(self):
        self.client = Client()
        self.project_name = os.environ.get("LANGCHAIN_PROJECT", "rag-chat-evaluation")
    
    @traceable(name="rag_retrieval")
    def trace_retrieval(self, query: str, documents: list) -> Dict[str, Any]:
        """検索処理のトレース"""
        return {
            "query": query,
            "num_documents_retrieved": len(documents),
            "documents": [doc.page_content[:100] for doc in documents]
        }
    
    @traceable(name="rag_generation")
    def trace_generation(self, query: str, context: str, answer: str) -> Dict[str, Any]:
        """生成処理のトレース"""
        return {
            "query": query,
            "context_length": len(context),
            "answer": answer,
            "answer_length": len(answer)
        }
    
    def log_feedback(self, run_id: str, score: float, comment: str = ""):
        """ユーザーフィードバックを記録"""
        self.client.create_feedback(
            run_id=run_id,
            key="user_satisfaction",
            score=score,
            comment=comment
        )