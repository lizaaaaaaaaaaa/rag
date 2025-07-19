# rag/hybrid_search.py (新規作成)
from langchain.retrievers import BM25Retriever, EnsembleRetriever
from langchain_community.vectorstores import FAISS
import logging

logger = logging.getLogger(__name__)

# MeCabは日本語環境でのみ必要なので、オプショナルにする
try:
    import MeCab
    HAS_MECAB = True
except ImportError:
    logger.warning("MeCabが利用できません。基本的なトークナイザーを使用します。")
    HAS_MECAB = False

class HybridRetriever:
    def __init__(self, vectorstore, documents):
        self.vectorstore = vectorstore
        
        # BM25リトリーバー（キーワード検索）
        self.bm25_retriever = BM25Retriever.from_documents(documents)
        self.bm25_retriever.k = 5
        
        # ベクトルリトリーバー
        self.vector_retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
        
        # アンサンブルリトリーバー（重み付け組み合わせ）
        self.ensemble_retriever = EnsembleRetriever(
            retrievers=[self.bm25_retriever, self.vector_retriever],
            weights=[0.3, 0.7]  # ベクトル検索重視
        )
    
    def get_relevant_documents(self, query):
        return self.ensemble_retriever.get_relevant_documents(query)