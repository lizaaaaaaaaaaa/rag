import logging
import os
from typing import List, Tuple, Optional, Dict, Any
import numpy as np
from datetime import datetime
import time

# 遅延インポートと条件付きロード
try:
    from sentence_transformers import CrossEncoder
    CROSS_ENCODER_AVAILABLE = True
except ImportError:
    CROSS_ENCODER_AVAILABLE = False
    logging.warning("CrossEncoder not available. Reranking will be disabled.")

logger = logging.getLogger(__name__)

class OptimizedCrossEncoderReranker:
    """最適化版リランカー（速度優先・メモリ効率重視）"""
    
    def __init__(self, model_name: str = None, lazy_load: bool = True):
        """
        Args:
            model_name: 使用するモデル名（None の場合は環境変数から取得）
            lazy_load: True の場合、実際に使用されるまでモデルをロードしない
        """
        # 環境変数から設定を読み込み
        self.enabled = os.environ.get("ENABLE_RERANKING", "true").lower() == "true"
        self.top_n = int(os.environ.get("RERANK_TOPN", "3"))  # デフォルト3件
        self.max_input_length = int(os.environ.get("RERANK_MAX_LENGTH", "512"))  # 最大入力長
        self.batch_size = int(os.environ.get("RERANK_BATCH_SIZE", "8"))  # バッチサイズ
        
        # モデル名の決定
        if model_name is None:
            # 軽量モデルを優先
            model_name = os.environ.get(
                "RERANK_MODEL", 
                "cross-encoder/ms-marco-MiniLM-L-6-v2"  # 軽量で高速
            )
        self.model_name = model_name
        
        # 遅延ロード設定
        self.lazy_load = lazy_load
        self.cross_encoder = None
        self._model_loaded = False
        
        # 統計情報
        self.stats = {
            "total_rerank_calls": 0,
            "total_documents_processed": 0,
            "total_documents_returned": 0,
            "skipped_disabled": 0,
            "skipped_no_docs": 0,
            "skipped_single_doc": 0,
            "model_load_time": 0,
            "total_rerank_time": 0,
            "average_rerank_time": 0
        }
        
        # モデルロード（遅延ロードでない場合）
        if not lazy_load and self.enabled and CROSS_ENCODER_AVAILABLE:
            self._load_model()
    
    def _load_model(self):
        """モデルの遅延ロード"""
        if self._model_loaded or not CROSS_ENCODER_AVAILABLE:
            return
        
        start_time = time.time()
        try:
            logger.info(f"Loading reranker model: {self.model_name}")
            self.cross_encoder = CrossEncoder(
                self.model_name,
                max_length=self.max_input_length,
                device="cpu"  # GPUを使わない（速度優先）
            )
            self._model_loaded = True
            load_time = time.time() - start_time
            self.stats["model_load_time"] = load_time
            logger.info(f"Reranker model loaded in {load_time:.2f} seconds")
        except Exception as e:
            logger.error(f"Failed to load reranker model: {e}")
            self.enabled = False
            self._model_loaded = False
    
    def _truncate_text(self, text: str, max_length: int = None) -> str:
        """テキストを最大長に切り詰め（高速化のため）"""
        if max_length is None:
            max_length = self.max_input_length
        
        if len(text) <= max_length:
            return text
        
        # 単語境界で切り詰め
        truncated = text[:max_length]
        last_space = truncated.rfind(' ')
        if last_space > max_length * 0.8:  # 80%以上の位置にスペースがある場合
            truncated = truncated[:last_space]
        
        return truncated + "..."
    
    def rerank(
        self, 
        query: str, 
        documents: List[Any], 
        top_k: int = None,
        return_scores: bool = False
    ) -> List[Any]:
        """
        ドキュメントをリランキング（最適化版）
        
        Args:
            query: 検索クエリ
            documents: リランキング対象のドキュメントリスト
            top_k: 返すドキュメント数（None の場合は環境変数の値を使用）
            return_scores: スコアも返すかどうか
            
        Returns:
            リランキングされたドキュメントリスト（またはタプルのリスト）
        """
        self.stats["total_rerank_calls"] += 1
        
        # 無効化チェック
        if not self.enabled or not CROSS_ENCODER_AVAILABLE:
            self.stats["skipped_disabled"] += 1
            logger.debug("Reranking is disabled")
            return documents[:top_k or self.top_n] if not return_scores else [(doc, 1.0) for doc in documents[:top_k or self.top_n]]
        
        # ドキュメントが空の場合
        if not documents:
            self.stats["skipped_no_docs"] += 1
            return [] if not return_scores else []
        
        # ドキュメントが1件の場合はリランキング不要
        if len(documents) == 1:
            self.stats["skipped_single_doc"] += 1
            return documents if not return_scores else [(documents[0], 1.0)]
        
        # top_k の決定
        if top_k is None:
            top_k = self.top_n
        top_k = min(top_k, len(documents))
        
        # ドキュメント数が top_k 以下の場合、軽量処理
        if len(documents) <= top_k:
            # 少数の場合はリランキングをスキップ（高速化）
            if len(documents) <= 3:
                self.stats["skipped_single_doc"] += 1
                return documents if not return_scores else [(doc, 1.0 - i * 0.1) for i, doc in enumerate(documents)]
        
        # モデルの遅延ロード
        if not self._model_loaded:
            self._load_model()
            if not self._model_loaded:
                # モデルロード失敗
                return documents[:top_k] if not return_scores else [(doc, 1.0) for doc in documents[:top_k]]
        
        start_time = time.time()
        
        try:
            # クエリの切り詰め
            truncated_query = self._truncate_text(query)
            
            # ドキュメントテキストの抽出と切り詰め
            doc_texts = []
            for doc in documents:
                # ドキュメントからテキストを抽出
                if hasattr(doc, 'page_content'):
                    text = doc.page_content
                elif hasattr(doc, 'content'):
                    text = doc.content
                elif isinstance(doc, str):
                    text = doc
                elif isinstance(doc, dict):
                    text = doc.get('content', doc.get('text', str(doc)))
                else:
                    text = str(doc)
                
                # テキストの切り詰め
                doc_texts.append(self._truncate_text(text))
            
            # ペアの作成
            pairs = [(truncated_query, text) for text in doc_texts]
            
            # バッチ処理でスコア計算
            if len(pairs) > self.batch_size:
                # 大量のドキュメントの場合はバッチ処理
                scores = []
                for i in range(0, len(pairs), self.batch_size):
                    batch = pairs[i:i + self.batch_size]
                    batch_scores = self.cross_encoder.predict(batch)
                    scores.extend(batch_scores)
                scores = np.array(scores)
            else:
                # 少量の場合は一括処理
                scores = self.cross_encoder.predict(pairs)
            
            # スコアでソート
            scored_indices = np.argsort(scores)[::-1][:top_k]
            
            # 統計更新
            self.stats["total_documents_processed"] += len(documents)
            self.stats["total_documents_returned"] += len(scored_indices)
            
            rerank_time = time.time() - start_time
            self.stats["total_rerank_time"] += rerank_time
            self.stats["average_rerank_time"] = self.stats["total_rerank_time"] / self.stats["total_rerank_calls"]
            
            logger.debug(f"Reranked {len(documents)} documents to top {len(scored_indices)} in {rerank_time:.3f}s")
            
            # 結果の返却
            if return_scores:
                return [(documents[idx], float(scores[idx])) for idx in scored_indices]
            else:
                return [documents[idx] for idx in scored_indices]
            
        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            # エラー時は元の順序で返す
            return documents[:top_k] if not return_scores else [(doc, 1.0) for doc in documents[:top_k]]
    
    def rerank_with_metadata(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = None,
        content_key: str = "content",
        metadata_boost: Dict[str, float] = None
    ) -> List[Dict[str, Any]]:
        """
        メタデータを考慮したリランキング
        
        Args:
            query: 検索クエリ
            documents: ドキュメント辞書のリスト
            top_k: 返すドキュメント数
            content_key: コンテンツのキー名
            metadata_boost: メタデータによるスコアブースト設定
            
        Returns:
            リランキングされたドキュメントリスト
        """
        if not documents:
            return []
        
        # 基本的なリランキング（スコア付き）
        reranked_with_scores = self.rerank(
            query=query,
            documents=[doc.get(content_key, str(doc)) for doc in documents],
            top_k=top_k or self.top_n,
            return_scores=True
        )
        
        # メタデータブーストの適用
        if metadata_boost:
            boosted_docs = []
            for i, (content, base_score) in enumerate(reranked_with_scores):
                doc = documents[i]
                final_score = base_score
                
                # メタデータに基づくブースト
                for key, boost_value in metadata_boost.items():
                    if key in doc:
                        if isinstance(doc[key], bool) and doc[key]:
                            final_score *= (1 + boost_value)
                        elif isinstance(doc[key], (int, float)):
                            final_score *= (1 + boost_value * doc[key])
                
                boosted_docs.append((doc, final_score))
            
            # 再ソート
            boosted_docs.sort(key=lambda x: x[1], reverse=True)
            return [doc for doc, _ in boosted_docs[:top_k or self.top_n]]
        
        # メタデータブーストなしの場合
        return documents[:len(reranked_with_scores)]
    
    def get_stats(self) -> Dict[str, Any]:
        """統計情報の取得"""
        return {
            "configuration": {
                "enabled": self.enabled,
                "model_name": self.model_name,
                "top_n": self.top_n,
                "max_input_length": self.max_input_length,
                "batch_size": self.batch_size,
                "model_loaded": self._model_loaded
            },
            "statistics": self.stats,
            "performance": {
                "average_rerank_time_ms": self.stats["average_rerank_time"] * 1000,
                "documents_per_second": (
                    self.stats["total_documents_processed"] / self.stats["total_rerank_time"]
                    if self.stats["total_rerank_time"] > 0 else 0
                ),
                "skip_rate": (
                    (self.stats["skipped_disabled"] + self.stats["skipped_no_docs"] + self.stats["skipped_single_doc"]) 
                    / self.stats["total_rerank_calls"] * 100
                    if self.stats["total_rerank_calls"] > 0 else 0
                )
            }
        }
    
    def reset_stats(self):
        """統計情報のリセット"""
        self.stats = {
            "total_rerank_calls": 0,
            "total_documents_processed": 0,
            "total_documents_returned": 0,
            "skipped_disabled": 0,
            "skipped_no_docs": 0,
            "skipped_single_doc": 0,
            "model_load_time": self.stats.get("model_load_time", 0),  # モデルロード時間は保持
            "total_rerank_time": 0,
            "average_rerank_time": 0
        }

# グローバルインスタンス（遅延ロード）
_global_reranker = None

def get_reranker() -> OptimizedCrossEncoderReranker:
    """グローバルリランカーインスタンスの取得"""
    global _global_reranker
    if _global_reranker is None:
        _global_reranker = OptimizedCrossEncoderReranker(lazy_load=True)
    return _global_reranker

def rerank_documents(
    query: str,
    documents: List[Any],
    top_k: int = None
) -> List[Any]:
    """
    簡易リランキング関数（外部からの呼び出し用）
    
    Args:
        query: 検索クエリ
        documents: リランキング対象のドキュメント
        top_k: 返すドキュメント数
        
    Returns:
        リランキングされたドキュメントリスト
    """
    reranker = get_reranker()
    return reranker.rerank(query, documents, top_k)

def get_reranker_stats() -> Dict[str, Any]:
    """リランカーの統計情報取得"""
    reranker = get_reranker()
    return reranker.get_stats()

# 後方互換性のためのエイリアス
class CrossEncoderReranker(OptimizedCrossEncoderReranker):
    """後方互換性のためのエイリアスクラス"""
    def __init__(self, model_name="cross-encoder/ms-marco-MiniLM-L-6-v2"):
        super().__init__(model_name=model_name, lazy_load=False)
