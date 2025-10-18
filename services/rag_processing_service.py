# services/rag_processing_service.py  — 完全修正版
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
    Document = Any
    VectorStore = Any
    RetrievalQA = Any

# LangSmithトレース（任意）
try:
    from utils.langsmith_tracer import RAGTracer
    LANGSMITH_AVAILABLE = True
except Exception:
    LANGSMITH_AVAILABLE = False
    class RAGTracer:
        def __init__(self): ...
        def start_span(self, *args, **kw): ...
        def end_span(self, *args, **kw): ...
        def trace_retrieval(self, *args, **kwargs): pass
        def trace_generation(self, *args, **kwargs): pass

logger = logging.getLogger(__name__)

# 追加：プレースホルダー検知の共通パターン（禁止語）
_PLACEHOLDER_BLOCK_RE = re.compile(
    r"(○○|〇〇|◯◯|××|XX|[Xx]{2,}|TBD|未定|要確認|？？？|\?{2,}|＜.*?＞|ここに.*?を書く)"
)

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
        # 修正：厳格制御フラグの真偽値パース
        self.strict_rag_only = os.environ.get("STRICT_RAG_ONLY", "false").lower() in ("1","true","yes","on")
        self.strict_grounded = os.environ.get("STRICT_GROUNDED_ANSWERING", "true").lower() in ("1","true","yes")
        self.location_intent_strict = os.environ.get("LOCATION_INTENT_STRICT", "true").lower() in ("1","true","yes")
        self.rag_timeout = float(os.environ.get("OPTIMIZED_RAG_TIMEOUT", "8"))  # タイムアウト8秒
        
        # パフォーマンス統計
        self.stats = {
            "total_queries": 0,
            "successful_retrievals": 0,
            "successful_generations": 0,
            "total_retrieval_time": 0.0,
            "total_generation_time": 0.0,
            "query_expansion_count": 0,
            "reranking_count": 0
        }

    def initialize(self, vectorstore=None, rag_chain=None, llm_instance=None) -> bool:
        """RAGの初期化"""
        try:
            if vectorstore is not None:
                self.vectorstore = vectorstore
            if rag_chain is not None:
                self.rag_chain = rag_chain
            if llm_instance is not None:
                self.llm_instance = llm_instance
            logger.info("RAG service initialized.")
            return True
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
            result["latency_ms"] = int((time.time() - start_time) * 1000)
            result["query_id"] = query_id
            return result
        
        except asyncio.TimeoutError:
            logger.warning(f"[{query_id}] RAG timeout")
            return {
                "answer": self._get_timeout_response(platform),
                "sources": [],
                "success": False,
                "processing_details": {"method": "timeout"},
                "latency_ms": int((time.time() - start_time) * 1000),
                "query_id": query_id
            }
        except Exception as e:
            logger.error(f"[{query_id}] RAG error: {e}\n{traceback.format_exc()}")
            return {
                "answer": self._generate_error_response(query, platform),
                "sources": [],
                "success": False,
                "processing_details": {"method": "error", "error": str(e)},
                "latency_ms": int((time.time() - start_time) * 1000),
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
        
        # 6. 厳格ガード適用（本文には出典を付けない）
        final_result = self._apply_strict_guards(query, generation_result, retrieval_result, platform)
        
        # 統計更新
        self._update_stats_fast(retrieval_result, generation_result)
        
        return final_result

    def _preprocess_query_fast(self, query: str) -> str:
        """高速プリプロセス"""
        q = (query or "").strip()
        # 余計な空白・制御文字を除去
        q = re.sub(r"\s+", " ", q)
        return q

    def _expand_query_fast(self, query: str) -> List[str]:
        """簡易クエリ拡張（同義語＋かな表記など）"""
        variants = {query}
        # 必要があれば簡易的に追加
        if "エリア" in query:
            variants.add(query.replace("エリア", "地域"))
        if "地域" in query:
            variants.add(query.replace("地域", "エリア"))
        return list(variants)

    async def _retrieve_documents_fast(self, queries: List[str]) -> Dict[str, Any]:
        """高速ドキュメント検索"""
        start = time.time()
        docs: List[Tuple[Any, float]] = []
        
        if not self.vectorstore:
            logger.warning("Vectorstore is not initialized.")
            return {"documents": [], "retrieval_time": 0.0, "count": 0}
        
        try:
            # ベクトル検索（Top-K）
            for q in queries:
                results = self.vectorstore.similarity_search_with_score(q, k=self.max_documents)
                for d, score in results:
                    # 修正：しきい値フィルタを撤廃（実装間のスコア定義差を吸収）
                    docs.append((d, score))
            
            retrieval_time = time.time() - start
            
            # 重複排除（同一ページ等）
            seen = set()
            unique_docs: List[Tuple[Any, float]] = []
            for doc, score in docs:
                key = (getattr(doc, "metadata", {}).get("source", ""), getattr(doc, "metadata", {}).get("page", -1))
                if key not in seen:
                    seen.add(key)
                    unique_docs.append((doc, score))
            
            # スコアでソート（昇順/降順は実装依存。必要なら逆に）
            unique_docs = sorted(unique_docs, key=lambda x: (x[1] if x[1] is not None else 0.0))
            
            return {
                "documents": unique_docs[:self.max_documents],
                "retrieval_time": retrieval_time,
                "count": len(unique_docs)
            }
        except Exception as e:
            logger.error(f"Retrieval failed: {e}")
            return {"documents": [], "retrieval_time": 0.0, "count": 0}

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
            
            # スコアを再付与（簡易）
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
            # RAGヒットなし時は固定文（LLMで補わない）
            return {
                "answer": "資料内に該当情報が見つかりませんでした。",
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
            
            # 出典情報の追加は本文に付与しない（sourcesはメタで返す）
            
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
        """LLMを直接呼び出す（LangChain LLMインスタンスを保持している場合）"""
        # 簡易プロンプト（ここに“推測禁止・出典不要”はプロンプト側で設定済み想定）
        prompt = f"""以下のコンテキストの範囲内で日本語で簡潔に回答してください。
コンテキスト:
{context}

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
        """高速応答クリーニング（最小限 + プレースホルダー除去）"""
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

        # 追加：プレースホルダーは表示前に安全な表現に置換
        cleaned = _PLACEHOLDER_BLOCK_RE.sub("（資料に記載なし）", cleaned)
        
        return cleaned

    def _add_sources_to_answer(self, answer: str, documents: List[Tuple[Any, float]]) -> str:
        """出典は本文に付与しない（sourcesはメタで返す）"""
        return answer

    def _postprocess_result_fast(self, generation_result: Dict, retrieval_result: Dict) -> Dict[str, Any]:
        """高速結果後処理"""
        documents = retrieval_result.get("documents", [])
        
        # ソース情報（本文には付与しないがメタで返す）
        sources = []
        if self.enable_source_display:
            for i, (doc, score) in enumerate(documents[:2]):
                metadata = getattr(doc, 'metadata', {})
                safe_score = round(score, 2) if isinstance(score, (int, float)) else None
                sources.append({
                    "index": i,
                    "source": metadata.get('source', 'unknown'),
                    "score": safe_score
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

    # ========= 厳格ガード一式 =========
    def _apply_strict_guards(self, query: str, generation_result: Dict, retrieval_result: Dict, platform: str) -> Dict[str, Any]:
        """当て字・根拠外地名・RAG未ヒットをブロックし、固定文へ差し替える"""
        documents = retrieval_result.get("documents", [])
        answer = (generation_result or {}).get("answer", "") or ""

        # 1) RAG未ヒット or 厳格RAGオンでヒット0 → 固定文
        if self.strict_rag_only and not documents:
            return self._fixed_noinfo_result(retrieval_result, generation_result)

        if self.strict_grounded:
            # 2) プレースホルダ検知（拡張）
            if _PLACEHOLDER_BLOCK_RE.search(answer):
                return self._fixed_noinfo_result(retrieval_result, generation_result)
            # 3) 地名系は本文一致を要求
            if self.location_intent_strict and self._is_location_intent(query):
                if self._contains_location_like(answer):
                    ctx = self._concat_docs_text(documents)
                    for loc in self._extract_locations(answer):
                        if loc not in ctx:
                            return self._fixed_noinfo_result(retrieval_result, generation_result)

        # ここまで通過したらそのまま返す（本文に出典は付けない）
        return self._postprocess_result_fast(generation_result, retrieval_result)

    def _fixed_noinfo_result(self, retrieval_result: Dict, generation_result: Dict) -> Dict[str, Any]:
        """固定文（資料内に見つからない）で返却。sourcesは空で返す"""
        return {
            "answer": "資料内に該当情報が見つかりませんでした。",
            "sources": [],
            "success": True,
            "processing_details": {
                "retrieval_time": retrieval_result.get("retrieval_time", 0),
                "generation_time": generation_result.get("generation_time", 0),
                "document_count": 0,
                "method": "guard_blocked"
            }
        }

    def _is_location_intent(self, text: str) -> bool:
        return bool(re.search(r"(どこ|エリア|地域|周辺|対応地域|施工可能|対応エリア)", text))

    def _contains_location_like(self, text: str) -> bool:
        return bool(re.search(r"(市|区|町|村|郡|都|道|府|県)", text))

    def _extract_locations(self, text: str) -> List[str]:
        return re.findall(r"([一-龠々ヶーA-Za-z0-9]+(?:市|区|町|村|郡|都|道|府|県))", text)

    def _concat_docs_text(self, documents: List[Tuple[Any, float]]) -> str:
        parts = []
        for doc_tuple in documents:
            try:
                doc, score = doc_tuple
            except Exception:
                doc = doc_tuple[0] if isinstance(doc_tuple, (list, tuple)) else doc_tuple
            content = getattr(doc, 'page_content', '') if doc else ''
            if content:
                parts.append(content)
        return "\n".join(parts)
    # ========= 追加ここまで =========

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
        try:
            self.stats["successful_retrievals"] += 1 if retrieval_result.get("documents") else 0
        except Exception:
            pass
        try:
            self.stats["successful_generations"] += 1 if generation_result.get("answer") else 0
        except Exception:
            pass


# リランカー（任意）
try:
    from rag.reranker import get_reranker
    RERANKER_AVAILABLE = True
except Exception:
    RERANKER_AVAILABLE = False
    def get_reranker(): return None


def initialize_rag_service(vectorstore=None, rag_chain=None, llm_instance=None) -> bool:
    """RAGサービスの初期化"""
    service = get_rag_service()
    return service.initialize(vectorstore, rag_chain, llm_instance)

def reset_rag_service() -> OptimizedRAGProcessingService:
    """RAGサービスのリセット"""
    global _global_rag_service
    _global_rag_service = None
    return get_rag_service()

# グローバル・シングルトン
_global_rag_service = None

def get_rag_service():
    global _global_rag_service
    if _global_rag_service is None:
        _global_rag_service = OptimizedRAGProcessingService()
    return _global_rag_service

# 後方互換性のためのエイリアス
RAGProcessingService = OptimizedRAGProcessingService