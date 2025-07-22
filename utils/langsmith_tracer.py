# utils/langsmith_tracer.py (修正版)
import os
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# LangSmithが利用可能かチェック
HAS_LANGSMITH = False
Client = None
traceable = None

# トレースを一時的に無効化（エラー回避のため）
os.environ["LANGCHAIN_TRACING_V2"] = "false"

try:
    # 環境変数確認
    api_key = os.environ.get("LANGSMITH_API_KEY")
    if api_key and os.environ.get("DISABLE_LANGSMITH", "false").lower() != "true":
        from langsmith import Client as LangSmithClient, traceable as langsmith_traceable
        
        # テストクライアント作成（エラーハンドリング付き）
        try:
            test_client = LangSmithClient(api_key=api_key)
            # プロジェクトの存在確認をスキップ
            
            Client = LangSmithClient
            traceable = langsmith_traceable
            HAS_LANGSMITH = True
            
            # 成功したらトレースを有効化
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            logger.info("✅ LangSmith tracer module loaded successfully")
        except Exception as e:
            logger.warning(f"⚠️ LangSmith client initialization failed: {e}")
            HAS_LANGSMITH = False
    else:
        logger.warning("⚠️ LANGSMITH_API_KEY not found or disabled in tracer module")
except ImportError:
    logger.warning("⚠️ LangSmith library not available in tracer module")
except Exception as e:
    logger.error(f"❌ LangSmith tracer error: {e}")

# ダミー関数の定義
if not HAS_LANGSMITH:
    def traceable(name=None, **kwargs):
        def decorator(func):
            return func
        return decorator
    
    class DummyClient:
        def __init__(self, **kwargs):
            pass

class RAGTracer:
    def __init__(self):
        self.client = None
        self.project_name = "rag-chat-evaluation"
        
        if HAS_LANGSMITH and Client:
            try:
                api_key = os.environ.get("LANGSMITH_API_KEY")
                # プロジェクト名をシンプルに
                self.project_name = "default"
                os.environ["LANGCHAIN_PROJECT"] = self.project_name
                
                self.client = Client(api_key=api_key)
                logger.info(f"✅ RAGTracer initialized with project: {self.project_name}")
            except Exception as e:
                logger.error(f"❌ Failed to initialize RAGTracer: {e}")
                self.client = None
        else:
            logger.warning("⚠️ RAGTracer initialized in dummy mode")
    
    def trace_retrieval(self, query: str, documents: list) -> Dict[str, Any]:
        """検索処理のトレース"""
        trace_data = {
            "query": query,
            "num_documents_retrieved": len(documents),
            "documents": [doc.page_content[:100] for doc in documents]
        }
        
        # LangSmithトレースを一時的に無効化
        if self.client and False:  # 一時的に無効化
            try:
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
        
        # LangSmithトレースを一時的に無効化
        if self.client and False:  # 一時的に無効化
            try:
                logger.info(f"📊 Tracing generation: answer length {len(answer)} for query: {query[:50]}...")
            except Exception as e:
                logger.error(f"❌ Failed to trace generation: {e}")
        
        return trace_data
    
    def log_feedback(self, run_id: str, score: float, comment: str = ""):
        """ユーザーフィードバックを記録"""
        logger.info(f"📝 Feedback (local only): score={score}, comment={comment}")