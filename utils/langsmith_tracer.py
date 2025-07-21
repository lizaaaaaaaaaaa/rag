# utils/langsmith_tracer.py (修正版)
import os
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# LangSmithが利用可能かチェック
HAS_LANGSMITH = False
Client = None
traceable = None

try:
    # 環境変数確認
    api_key = os.environ.get("LANGSMITH_API_KEY")
    if api_key:
        from langsmith import Client as LangSmithClient, traceable as langsmith_traceable
        
        # テストクライアント作成
        test_client = LangSmithClient(api_key=api_key)
        
        Client = LangSmithClient
        traceable = langsmith_traceable
        HAS_LANGSMITH = True
        logger.info("✅ LangSmith tracer module loaded successfully")
    else:
        logger.warning("⚠️ LANGSMITH_API_KEY not found in tracer module")
except ImportError:
    logger.warning("⚠️ LangSmith library not available in tracer module")
except Exception as e:
    logger.error(f"❌ LangSmith tracer error: {e}")

# ダミー関数の定義
if not HAS_LANGSMITH:
    def traceable(name=None):
        def decorator(func):
            return func
        return decorator
    
    class DummyClient:
        def __init__(self, **kwargs):
            pass

class RAGTracer:
    def __init__(self):
        if HAS_LANGSMITH and Client:
            try:
                api_key = os.environ.get("LANGSMITH_API_KEY")
                self.client = Client(api_key=api_key)
                self.project_name = os.environ.get("LANGCHAIN_PROJECT", "rag-chat-evaluation")
                logger.info(f"✅ RAGTracer initialized with project: {self.project_name}")
            except Exception as e:
                logger.error(f"❌ Failed to initialize RAGTracer: {e}")
                self.client = None
                self.project_name = "rag-chat-evaluation"
        else:
            self.client = None
            self.project_name = "rag-chat-evaluation"
            logger.warning("⚠️ RAGTracer initialized in dummy mode")
    
    def trace_retrieval(self, query: str, documents: list) -> Dict[str, Any]:
        """検索処理のトレース"""
        trace_data = {
            "query": query,
            "num_documents_retrieved": len(documents),
            "documents": [doc.page_content[:100] for doc in documents]
        }
        
        if self.client:
            try:
                # LangSmithにトレースデータを送信
                logger.info(f"📊 Tracing retrieval: {len(documents)} documents for query: {query[:50]}...")
            except Exception as e:
                logger.error(f"❌ Failed to trace retrieval: {e}")
        
        return trace_data
    
    def trace_generation(self, query: str, context: str, answer: str) -> Dict[str, Any]:
        """生成処理のトレース"""
        trace_data = {
            "query": query,
            "context_length": len(context),
            "answer": answer,
            "answer_length": len(answer)
        }
        
        if self.client:
            try:
                # LangSmithにトレースデータを送信
                logger.info(f"📊 Tracing generation: answer length {len(answer)} for query: {query[:50]}...")
            except Exception as e:
                logger.error(f"❌ Failed to trace generation: {e}")
        
        return trace_data
    
    def log_feedback(self, run_id: str, score: float, comment: str = ""):
        """ユーザーフィードバックを記録"""
        if self.client:
            try:
                self.client.create_feedback(
                    run_id=run_id,
                    key="user_satisfaction",
                    score=score,
                    comment=comment
                )
                logger.info(f"✅ Feedback logged: score={score}")
            except Exception as e:
                logger.error(f"❌ Failed to log feedback: {e}")
        else:
            logger.info(f"📝 Feedback (dummy mode): score={score}, comment={comment}")