import logging
import time
import re
import asyncio
import os
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from uuid import uuid4
import traceback

# RAG関連のインポート
try:
    from langchain.schema import Document
    from langchain.vectorstores import VectorStore
    from langchain.chains import RetrievalQA
except ImportError:
    Document = None
    VectorStore = None
    RetrievalQA = None

# リランカーのインポート
try:
    from rag.reranker import get_reranker
    RERANKER_AVAILABLE = True
except ImportError:
    RERANKER_AVAILABLE = False

# LangSmithトレース
try:
    from utils.langsmith_tracer import RAGTracer
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    class RAGTracer:
        def trace_retrieval(self, *args, **kwargs): pass
        def trace_generation(self, *args, **kwargs): pass

logger = logging.getLogger(__name__)

class OptimizedRAGProcessingService:
    """最適化版RAG処理統合サービス（速度優先）"""
    
    def __init__(self):
        self.vectorstore = None
        self.rag_chain = None
        self.llm_instance = None
        self.tracer = RAGTracer() if LANGSMITH_AVAILABLE else None
        self.reranker = get_reranker() if RERANKER_AVAILABLE else None
        
        # 環境変数から設定を読み込み
        self.max_documents = int(os.environ.get("MAX_DOCUMENTS", "3"))  # 削減: 5→3
        self.similarity_threshold = float(os.environ.get("SIMILARITY_THRESHOLD", "0.7"))
        self.enable_query_expansion = os.environ.get("ENABLE_QUERY_EXPANSION", "false").lower() == "true"  # デフォルトOFF
        self.enable_reranking = os.environ.get("ENABLE_RERANKING", "true").lower() == "true"
        self.enable_source_display = os.environ.get("ENABLE_SOURCE_DISPLAY", "true").lower() == "true"  # 出典表示
        self.rag_timeout = float(os.environ.get("OPTIMIZED_RAG_TIMEOUT", "8"))  # タイムアウト8秒
        
        # パフォーマンス統計
        self.stats = {
            "total_queries": 0,
            "successful_retrievals": 0,
            "successful_generations": 0,
            "failed_queries": 0,
            "timeout_queries": 0,
            "average_retrieval_time": 0.0,
            "average_generation_time": 0.0,
            "total_retrieval_time": 0.0,
            "total_generation_time": 0.0,
            "reranking_count": 0,
            "query_expansion_count": 0
        }
        
        # クエリ処理履歴（デバッグ用・軽量化）
        self.query_history = []
        self.max_history_size = 20  # 削減: 100→20

    def initialize(self, vectorstore=None, rag_chain=None, llm_instance=None) -> bool:
        """RAGコンポーネントの初期化"""
        try:
            self.vectorstore = vectorstore
            self.rag_chain = rag_chain  
            self.llm_instance = llm_instance
            
            # 初期化確認
            components_ready = {
                "vectorstore": self.vectorstore is not None,
                "rag_chain": self.rag_chain is not None,
                "llm_instance": self.llm_instance is not None,
                "reranker": self.reranker is not None
            }
            
            ready_count = sum(components_ready.values())
            logger.info(f"🚀 Optimized RAG Service initialized: {ready_count}/4 components")
            logger.info(f"  Config: max_docs={self.max_documents}, timeout={self.rag_timeout}s, "
                       f"expansion={self.enable_query_expansion}, rerank={self.enable_reranking}")
            
            return ready_count >= 2  # 最低限必要なコンポーネント
            
        except Exception as e:
            logger.error(f"RAG service initialization error: {e}")
            return False

    async def process_query(self, query: str, platform: str = "web", 
                          user_context: Optional[Dict] = None) -> Dict[str, Any]:
        """最適化版RAGクエリ処理"""
        start_time = time.time()
        self.stats["total_queries"] += 1
        
        query_id = str(uuid4())[:8]
        
        try:
            # タイムアウト付き処理
            result = await asyncio.wait_for(
                self._process_query_internal(query, platform, user_context, query_id),
                timeout=self.rag_timeout
            )
            
            total_time = time.time() - start_time
            logger.info(f"✅ RAG completed in {total_time:.2f}s")
            
            return result
            
        except asyncio.TimeoutError:
            self.stats["timeout_queries"] += 1
            total_time = time.time() - start_time
            logger.warning(f"⏰ RAG timeout after {total_time:.2f}s")
            
            return {
                "answer": self._get_timeout_response(platform),
                "sources": [],
                "success": False,
                "error": "timeout",
                "processing_time": total_time,
                "method": "rag_timeout",
                "query_id": query_id
            }
            
        except Exception as e:
            self.stats["failed_queries"] += 1
            total_time = time.time() - start_time
            logger.error(f"❌ RAG failed: {e}")
            
            return {
                "answer": self._generate_error_response(query, platform),
                "sources": [],
                "success": False,
                "error": str(e),
                "processing_time": total_time,
                "method": "rag_error",
                "query_id": query_id
            }

    async def _process_query_internal(self, query: str, platform: str, 
                                     user_context: Optional[Dict], query_id: str) -> Dict[str, Any]:
        """内部処理（タイムアウト管理用）"""
        
        # 1. クエリの前処理（軽量化）
        processed_query = self._preprocess_query_fast(query)
        
        # 2. クエリ拡張（OFFの場合スキップ）
        if self.enable_query_expansion:
            expanded_queries = self._expand_query_fast(processed_query)
            self.stats["query_expansion_count"] += 1
        else:
            expanded_queries = [processed_query]
        
        # 3. ドキュメント検索（高速化）
        retrieval_result = await self._retrieve_documents_fast(expanded_queries)
        
        # 4. リランキング（有効な場合）
        if self.enable_reranking and self.reranker and retrieval_result["documents"]:
            retrieval_result = self._apply_reranking(processed_query, retrieval_result)
        
        # 5. 応答生成（高速化）
        generation_result = await self._generate_response_fast(
            query, retrieval_result, platform, user_context
        )
        
        # 6. 結果の後処理（出典付き）
        final_result = self._postprocess_result_fast(generation_result, retrieval_result)
        
        # 統計更新
        self._update_stats_fast(retrieval_result, generation_result)
        
        return final_result

    def _preprocess_query_fast(self, query: str) -> str:
        """高速クエリ前処理"""
        # 基本的なクリーニングのみ
        processed = query.strip()
        
        # 複数空白の正規化
        processed = re.sub(r'\s+', ' ', processed)
        
        # 長すぎるクエリの切り詰め
        if len(processed) > 200:
            processed = processed[:200]
        
        return processed

    def _expand_query_fast(self, query: str) -> List[str]:
        """高速クエリ拡張（最小限）"""
        expanded = [query]
        
        # 重要なキーワードのみ拡張
        key_expansions = {
            "坪単価": ["価格"],
            "補助金": ["助成金"],
            "耐震": ["地震"]
        }
        
        for key, synonyms in key_expansions.items():
            if key in query:
                # 最初の同義語のみ追加（高速化）
                expanded.append(query.replace(key, synonyms[0]))
                break  # 1つだけ拡張
        
        return expanded[:2]  # 最大2クエリ

    async def _retrieve_documents_fast(self, queries: List[str]) -> Dict[str, Any]:
        """高速ドキュメント検索"""
        retrieval_start = time.time()
        
        if not self.vectorstore:
            return {"documents": [], "retrieval_time": 0}
        
        all_documents = []
        
        for query in queries[:2]:  # 最大2クエリまで
            try:
                # スコア付き検索（可能な場合）
                if hasattr(self.vectorstore, 'similarity_search_with_score'):
                    docs_with_scores = self.vectorstore.similarity_search_with_score(
                        query, 
                        k=self.max_documents
                    )
                    # 閾値フィルタリング
                    filtered = [(doc, score) for doc, score in docs_with_scores 
                              if score >= self.similarity_threshold]
                    all_documents.extend(filtered)
                else:
                    # 通常検索
                    docs = self.vectorstore.similarity_search(
                        query, 
                        k=self.max_documents
                    )
                    all_documents.extend([(doc, 1.0) for doc in docs])
                
            except Exception as e:
                logger.error(f"Retrieval error: {e}")
                continue
        
        # 重複除去（高速版）
        unique_docs = self._deduplicate_fast(all_documents)
        
        retrieval_time = time.time() - retrieval_start
        self.stats["total_retrieval_time"] += retrieval_time
        
        if unique_docs:
            self.stats["successful_retrievals"] += 1
        
        return {
            "documents": unique_docs,
            "retrieval_time": retrieval_time,
            "count": len(unique_docs)
        }

    def _deduplicate_fast(self, documents: List[Tuple[Any, float]]) -> List[Tuple[Any, float]]:
        """高速重複除去"""
        if not documents:
            return []
        
        # スコア順にソート
        sorted_docs = sorted(documents, key=lambda x: x[1], reverse=True)
        
        # 簡易的な重複チェック（最初の50文字のハッシュ）
        seen = set()
        unique = []
        
        for doc, score in sorted_docs:
            content = getattr(doc, 'page_content', str(doc))[:50]
            content_hash = hash(content)
            
            if content_hash not in seen:
                seen.add(content_hash)
                unique.append((doc, score))
                
                if len(unique) >= self.max_documents:
                    break
        
        return unique

    def _apply_reranking(self, query: str, retrieval_result: Dict) -> Dict:
        """リランキング適用"""
        try:
            documents = retrieval_result["documents"]
            if not documents or not self.reranker:
                return retrieval_result
            
            # ドキュメントのみ抽出
            docs_only = [doc for doc, _ in documents]
            
            # リランキング実行
            reranked = self.reranker.rerank(
                query=query,
                documents=docs_only,
                top_k=min(self.max_documents, len(docs_only))
            )
            
            # スコアを再付与
            reranked_with_scores = [(doc, 1.0 - i * 0.1) for i, doc in enumerate(reranked)]
            
            retrieval_result["documents"] = reranked_with_scores
            self.stats["reranking_count"] += 1
            
            return retrieval_result
            
        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            return retrieval_result

    async def _generate_response_fast(self, original_query: str, retrieval_result: Dict,
                                     platform: str, user_context: Optional[Dict]) -> Dict[str, Any]:
        """高速応答生成"""
        generation_start = time.time()
        
        documents = retrieval_result.get("documents", [])
        if not documents:
            return {
                "answer": "申し訳ございません。お尋ねの内容に関する情報が見つかりませんでした。",
                "method": "no_documents",
                "generation_time": time.time() - generation_start
            }
        
        try:
            # コンテキスト構築（軽量化）
            context = self._build_context_fast(documents)
            
            # LLM呼び出し
            if self.llm_instance:
                answer = await self._call_llm_fast(original_query, context, platform)
            elif self.rag_chain:
                answer = await self._call_rag_chain_fast(original_query)
            else:
                raise Exception("No generation method available")
            
            # 出典情報の追加（有効な場合）
            if self.enable_source_display and documents:
                answer = self._add_sources_to_answer(answer, documents)
            
            generation_time = time.time() - generation_start
            self.stats["total_generation_time"] += generation_time
            self.stats["successful_generations"] += 1
            
            return {
                "answer": answer,
                "method": "llm_fast" if self.llm_instance else "rag_chain",
                "generation_time": generation_time
            }
            
        except Exception as e:
            logger.error(f"Generation error: {e}")
            return {
                "answer": "申し訳ございません。応答の生成中にエラーが発生しました。",
                "method": "generation_error",
                "error": str(e),
                "generation_time": time.time() - generation_start
            }

    def _build_context_fast(self, documents: List[Tuple[Any, float]]) -> str:
        """高速コンテキスト構築"""
        context_parts = []
        total_length = 0
        max_length = 1500  # コンテキストの最大長
        
        for doc, score in documents[:self.max_documents]:
            content = getattr(doc, 'page_content', str(doc))
            
            # 長さ制限
            if total_length + len(content) > max_length:
                remaining = max_length - total_length
                if remaining > 100:
                    content = content[:remaining] + "..."
                else:
                    break
            
            context_parts.append(content)
            total_length += len(content)
        
        return "\n\n".join(context_parts)

    async def _call_llm_fast(self, query: str, context: str, platform: str) -> str:
        """高速LLM呼び出し"""
        # シンプルなプロンプト
        if platform == "line":
            prompt = f"""以下の情報を基に質問に簡潔に答えてください。

情報: {context}

質問: {query}

回答:"""
        else:
            prompt = f"""以下の情報を基に質問に答えてください。

情報: {context}

質問: {query}

回答:"""
        
        # LLM呼び出し
        if hasattr(self.llm_instance, 'ainvoke'):
            response = await self.llm_instance.ainvoke(prompt)
        elif hasattr(self.llm_instance, 'invoke'):
            response = self.llm_instance.invoke(prompt)
        else:
            response = self.llm_instance(prompt)
        
        # 応答抽出
        if hasattr(response, 'content'):
            answer = response.content
        else:
            answer = str(response)
        
        return self._clean_response_fast(answer)

    async def _call_rag_chain_fast(self, query: str) -> str:
        """高速RAGチェーン呼び出し"""
        if hasattr(self.rag_chain, 'ainvoke'):
            result = await self.rag_chain.ainvoke({"query": query})
        elif hasattr(self.rag_chain, 'invoke'):
            result = self.rag_chain.invoke({"query": query})
        else:
            result = self.rag_chain({"query": query})
        
        answer = result.get("result", "") or result.get("answer", "")
        return self._clean_response_fast(answer)

    def _clean_response_fast(self, raw_response: str) -> str:
        """高速応答クリーニング（最小限）"""
        if not raw_response or len(raw_response.strip()) < 3:
            return "申し訳ございません。詳細な情報をお答えできませんでした。"
        
        cleaned = raw_response.strip()
        
        # 不要なマーカーの除去（最小限）
        cleanup_patterns = [
            r"^質問[:：]\s*",
            r"^回答[:：]\s*",
            r"^情報[:：]\s*",
        ]
        
        for pattern in cleanup_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE)
        
        # 改行の正規化
        cleaned = re.sub(r'\n\s*\n', '\n', cleaned)
        
        return cleaned

    def _add_sources_to_answer(self, answer: str, documents: List[Tuple[Any, float]]) -> str:
        """出典情報を回答に追加"""
        if not documents or not self.enable_source_display:
            return answer
        
        # 出典情報の構築
        sources = []
        for i, (doc, score) in enumerate(documents[:2]):  # 上位2件のみ
            metadata = getattr(doc, 'metadata', {})
            source = metadata.get('source', '').replace('/tmp/', '').replace('.pdf', '')
            if source:
                sources.append(f"参考{i+1}: {source}")
        
        if sources:
            source_text = "\n\n【出典】\n" + "\n".join(sources)
            return answer + source_text
        
        return answer

    def _postprocess_result_fast(self, generation_result: Dict, retrieval_result: Dict) -> Dict[str, Any]:
        """高速結果後処理"""
        documents = retrieval_result.get("documents", [])
        
        # ソース情報（軽量版）
        sources = []
        if self.enable_source_display:
            for i, (doc, score) in enumerate(documents[:2]):
                metadata = getattr(doc, 'metadata', {})
                sources.append({
                    "index": i,
                    "source": metadata.get('source', 'unknown'),
                    "score": round(score, 2)
                })
        
        return {
            "answer": generation_result.get("answer", ""),
            "sources": sources,
            "success": True,
            "processing_details": {
                "retrieval_time": retrieval_result.get("retrieval_time", 0),
                "generation_time": generation_result.get("generation_time", 0),
                "document_count": len(documents),
                "method": generation_result.get("method", "unknown")
            }
        }

    def _get_timeout_response(self, platform: str) -> str:
        """タイムアウト時の応答"""
        if platform == "line":
            return "申し訳ございません。処理に時間がかかっています。もう一度お試しください。"
        else:
            return "申し訳ございません。処理がタイムアウトしました。もう一度お試しいただくか、より簡潔な質問でお試しください。"

    def _generate_error_response(self, query: str, platform: str) -> str:
        """エラー応答の生成"""
        if platform == "line":
            return "申し訳ございません。システムエラーが発生しました。しばらくしてからお試しください。"
        else:
            return "申し訳ございません。システムに問題が発生しました。しばらく時間をおいてから再度お試しください。"

    def _update_stats_fast(self, retrieval_result: Dict, generation_result: Dict) -> None:
        """高速統計更新"""
        query_count = self.stats["total_queries"]
        
        if query_count > 1:
            # 移動平均（簡易計算）
            alpha = 0.1  # 平滑化係数
            self.stats["average_retrieval_time"] = (
                (1 - alpha) * self.stats["average_retrieval_time"] + 
                alpha * retrieval_result.get("retrieval_time", 0)
            )
            self.stats["average_generation_time"] = (
                (1 - alpha) * self.stats["average_generation_time"] + 
                alpha * generation_result.get("generation_time", 0)
            )

    def get_service_stats(self) -> Dict[str, Any]:
        """サービス統計の取得"""
        total = self.stats["total_queries"]
        
        return {
            "performance": {
                "total_queries": total,
                "success_rate": (self.stats["successful_retrievals"] / total * 100) if total > 0 else 0,
                "timeout_rate": (self.stats["timeout_queries"] / total * 100) if total > 0 else 0,
                "average_retrieval_time": round(self.stats["average_retrieval_time"], 2),
                "average_generation_time": round(self.stats["average_generation_time"], 2)
            },
            "optimization": {
                "max_documents": self.max_documents,
                "timeout": self.rag_timeout,
                "query_expansion": self.enable_query_expansion,
                "reranking": self.enable_reranking,
                "reranking_count": self.stats["reranking_count"],
                "expansion_count": self.stats["query_expansion_count"]
            }
        }

    def health_check(self) -> Dict[str, Any]:
        """ヘルスチェック"""
        return {
            "status": "healthy" if self.vectorstore else "degraded",
            "components": {
                "vectorstore": self.vectorstore is not None,
                "rag_chain": self.rag_chain is not None,
                "llm": self.llm_instance is not None,
                "reranker": self.reranker is not None
            },
            "timestamp": datetime.now().isoformat()
        }

# グローバルサービスインスタンス
_global_rag_service = None

def get_rag_service() -> OptimizedRAGProcessingService:
    """グローバルRAGサービス取得"""
    global _global_rag_service
    
    if _global_rag_service is None:
        _global_rag_service = OptimizedRAGProcessingService()
    
    return _global_rag_service

def initialize_rag_service(vectorstore=None, rag_chain=None, llm_instance=None) -> bool:
    """RAGサービスの初期化"""
    service = get_rag_service()
    return service.initialize(vectorstore, rag_chain, llm_instance)

def reset_rag_service() -> OptimizedRAGProcessingService:
    """RAGサービスのリセット"""
    global _global_rag_service
    _global_rag_service = None
    return get_rag_service()

# 後方互換性のためのエイリアス
RAGProcessingService = OptimizedRAGProcessingService
