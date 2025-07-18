# rag/reranker.py (新規作成)
from sentence_transformers import CrossEncoder
import numpy as np

class CrossEncoderReranker:
    def __init__(self, model_name="cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.cross_encoder = CrossEncoder(model_name)
    
    def rerank(self, query: str, documents: list, top_k: int = 3):
        if not documents:
            return documents
        
        # クエリと各ドキュメントのペアを作成
        pairs = [(query, doc.page_content) for doc in documents]
        
        # 関連度スコアを計算
        scores = self.cross_encoder.predict(pairs)
        
        # スコア順にソート
        scored_docs = list(zip(documents, scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        
        return [doc for doc, score in scored_docs[:top_k]]