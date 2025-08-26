# services/rag_processing_service.py - RAG処理統合サービス

import logging
import time
import re
import asyncio
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

class RAGProcessingService:
    """RAG処理統合サービス"""
    
    def __init__(self):
        self.vectorstore = None
        self.rag_chain = None
        self.llm_instance = None
        self.tracer = RAGTracer() if LANGSMITH_AVAILABLE else None
        
        # パフォーマンス統計
        self.stats = {
            "total_queries": 0,
            "successful_retrievals": 0,
            "successful_generations": 0,
            "failed_queries": 0,
            "average_retrieval_time": 0.0,
            "average_generation_time": 0.0,
            "total_retrieval_time": 0.0,
            "total_generation_time": 0.0,
            "document_hit_count": {},  # ドキュメント別ヒット統計
            "query_categories": {}     # クエリカテゴリ別統計
        }
        
        # 設定
        self.max_documents = 5
        self.similarity_threshold = 0.7
        self.enable_query_expansion = True
        self.enable_result_ranking = True
        self.enable_context_filtering = True
        
        # クエリ処理履歴（デバッグ用）
        self.query_history = []
        self.max_history_size = 100

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
                "llm_instance": self.llm_instance is not None
            }
            
            ready_count = sum(components_ready.values())
            logger.info(f"🔧 RAG Service initialized: {ready_count}/3 components ready")
            
            for component, status in components_ready.items():
                if status:
                    logger.info(f"  ✅ {component}: Ready")
                else:
                    logger.warning(f"  ❌ {component}: Not available")
            
            return ready_count >= 2  # vectorstore + (rag_chain or llm_instance)
            
        except Exception as e:
            logger.error(f"RAG service initialization error: {e}")
            return False

    async def process_query(self, query: str, platform: str = "web", 
                          user_context: Optional[Dict] = None) -> Dict[str, Any]:
        """RAGクエリ処理のメイン関数"""
        start_time = time.time()
        self.stats["total_queries"] += 1
        
        # クエリ履歴に追加
        query_record = {
            "query": query,
            "timestamp": datetime.now().isoformat(),
            "platform": platform,
            "query_id": str(uuid4())[:8]
        }
        
        if len(self.query_history) >= self.max_history_size:
            self.query_history.pop(0)
        self.query_history.append(query_record)
        
        try:
            # 1. クエリの前処理・拡張
            processed_query = self._preprocess_query(query)
            if self.enable_query_expansion:
                expanded_queries = self._expand_query(processed_query)
            else:
                expanded_queries = [processed_query]
            
            # 2. ドキュメント検索
            retrieval_result = await self._retrieve_documents(expanded_queries)
            
            # 3. 応答生成
            generation_result = await self._generate_response(
                query, retrieval_result, platform, user_context
            )
            
            # 4. 結果の後処理
            final_result = self._postprocess_result(generation_result, retrieval_result)
            
            # 統計更新
            total_time = time.time() - start_time
            self._update_stats(True, total_time, retrieval_result, generation_result)
            
            logger.info(f"✅ RAG processing completed: {total_time:.3f}s, "
                       f"docs={len(retrieval_result.get('documents', []))}")
            
            return final_result
            
        except Exception as e:
            self.stats["failed_queries"] += 1
            total_time = time.time() - start_time
            
            logger.error(f"❌ RAG processing failed: {e}")
            logger.error(traceback.format_exc())
            
            return {
                "answer": self._generate_error_response(query, platform),
                "sources": [],
                "success": False,
                "error": str(e),
                "processing_time": total_time,
                "method": "rag_error",
                "query_id": query_record["query_id"]
            }

    def _preprocess_query(self, query: str) -> str:
        """クエリの前処理"""
        # 基本的なクリーニング
        processed = query.strip()
        
        # 不要な文字の除去
        processed = re.sub(r'[^\w\s\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]', '', processed)
        
        # 複数空白の正規化
        processed = re.sub(r'\s+', ' ', processed)
        
        # 質問形式の正規化
        question_patterns = [
            (r'(.+)について教えて.*', r'\1'),
            (r'(.+)はどう.*', r'\1'),
            (r'(.+)を知りたい.*', r'\1'),
            (r'(.+)の説明.*', r'\1')
        ]
        
        for pattern, replacement in question_patterns:
            if re.match(pattern, processed):
                processed = re.sub(pattern, replacement, processed)
                break
        
        return processed

    def _expand_query(self, query: str) -> List[str]:
        """クエリ拡張"""
        expanded = [query]
        
        # 同義語・関連語の追加
        expansion_map = {
            "坪単価": ["価格", "費用", "コスト"],
            "仕様": ["設備", "スペック", "標準"],
            "耐震": ["地震", "安全性", "構造"],
            "断熱": ["省エネ", "気密", "温度"],
            "補助金": ["助成金", "支援金", "減税"]
        }
        
        for key, synonyms in expansion_map.items():
            if key in query:
                for synonym in synonyms:
                    if synonym not in query:
                        expanded.append(query.replace(key, synonym))
        
        return expanded

    async def _retrieve_documents(self, queries: List[str]) -> Dict[str, Any]:
        """ドキュメント検索"""
        retrieval_start = time.time()
        
        if not self.vectorstore:
            raise Exception("Vectorstore not available")
        
        all_documents = []
        search_metadata = []
        
        for query in queries:
            try:
                # 類似度検索
                docs = self.vectorstore.similarity_search(
                    query, 
                    k=self.max_documents
                )
                
                # スコア付き検索（可能な場合）
                if hasattr(self.vectorstore, 'similarity_search_with_score'):
                    docs_with_scores = self.vectorstore.similarity_search_with_score(
                        query, 
                        k=self.max_documents
                    )
                    scored_docs = [(doc, score) for doc, score in docs_with_scores 
                                  if score >= self.similarity_threshold]
                else:
                    scored_docs = [(doc, 1.0) for doc in docs]
                
                all_documents.extend(scored_docs)
                search_metadata.append({
                    "query": query,
                    "results_count": len(scored_docs),
                    "search_time": time.time() - retrieval_start
                })
                
            except Exception as e:
                logger.error(f"Document retrieval error for query '{query}': {e}")
                continue
        
        # 重複除去・ランキング
        unique_docs = self._deduplicate_and_rank_documents(all_documents)
        
        retrieval_time = time.time() - retrieval_start
        self.stats["total_retrieval_time"] += retrieval_time
        
        # トレース
        if self.tracer:
            docs_only = [doc for doc, score in unique_docs]
            self.tracer.trace_retrieval(" | ".join(queries), docs_only)
        
        result = {
            "documents": unique_docs,
            "retrieval_time": retrieval_time,
            "search_metadata": search_metadata,
            "total_candidates": len(all_documents),
            "final_count": len(unique_docs)
        }
        
        if unique_docs:
            self.stats["successful_retrievals"] += 1
        
        return result

    def _deduplicate_and_rank_documents(self, documents: List[Tuple[Any, float]]) -> List[Tuple[Any, float]]:
        """ドキュメントの重複除去とランキング"""
        if not documents:
            return []
        
        # コンテンツベースの重複除去
        seen_content = set()
        unique_docs = []
        
        # スコア順にソート
        sorted_docs = sorted(documents, key=lambda x: x[1], reverse=True)
        
        for doc, score in sorted_docs:
            content = getattr(doc, 'page_content', str(doc))
            content_hash = hash(content[:200])  # 最初の200文字でハッシュ化
            
            if content_hash not in seen_content:
                seen_content.add(content_hash)
                unique_docs.append((doc, score))
                
                # 統計更新
                doc_source = getattr(doc, 'metadata', {}).get('source', 'unknown')
                if doc_source not in self.stats["document_hit_count"]:
                    self.stats["document_hit_count"][doc_source] = 0
                self.stats["document_hit_count"][doc_source] += 1
            
            if len(unique_docs) >= self.max_documents:
                break
        
        return unique_docs

    async def _generate_response(self, original_query: str, retrieval_result: Dict,
                               platform: str, user_context: Optional[Dict]) -> Dict[str, Any]:
        """応答生成"""
        generation_start = time.time()
        
        documents = retrieval_result.get("documents", [])
        if not documents:
            return {
                "answer": "申し訳ございません。お尋ねの内容に関する詳細な情報が見つかりませんでした。",
                "method": "no_documents",
                "generation_time": time.time() - generation_start
            }
        
        try:
            # RAGチェーンを使用した生成
            if self.rag_chain:
                result = await self._generate_with_rag_chain(original_query, documents)
            elif self.llm_instance:
                result = await self._generate_with_llm_direct(original_query, documents, platform)
            else:
                raise Exception("No generation method available")
            
            generation_time = time.time() - generation_start
            self.stats["total_generation_time"] += generation_time
            self.stats["successful_generations"] += 1
            
            # トレース
            if self.tracer:
                context = "\n".join([getattr(doc, "page_content", "") for doc, _ in documents])
                self.tracer.trace_generation(original_query, context, result.get("answer", ""))
            
            result["generation_time"] = generation_time
            return result
            
        except Exception as e:
            logger.error(f"Response generation error: {e}")
            return {
                "answer": "申し訳ございません。応答の生成中にエラーが発生しました。",
                "method": "generation_error",
                "error": str(e),
                "generation_time": time.time() - generation_start
            }

    async def _generate_with_rag_chain(self, query: str, documents: List[Tuple[Any, float]]) -> Dict[str, Any]:
        """RAGチェーンを使用した生成"""
        try:
            if hasattr(self.rag_chain, 'ainvoke'):
                result = await self.rag_chain.ainvoke({"query": query})
            elif hasattr(self.rag_chain, 'invoke'):
                result = self.rag_chain.invoke({"query": query})
            else:
                result = self.rag_chain({"query": query})
            
            raw_answer = result.get("result", "") or result.get("answer", "")
            cleaned_answer = self._clean_rag_response(raw_answer)
            
            return {
                "answer": cleaned_answer,
                "method": "rag_chain",
                "raw_result": result
            }
            
        except Exception as e:
            raise Exception(f"RAG chain generation failed: {e}")

    async def _generate_with_llm_direct(self, query: str, documents: List[Tuple[Any, float]], 
                                      platform: str) -> Dict[str, Any]:
        """LLM直接呼び出しによる生成"""
        try:
            # コンテキスト構築
            context_parts = []
            for doc, score in documents[:3]:  # 上位3つのドキュメントを使用
                content = getattr(doc, 'page_content', str(doc))
                if content:
                    context_parts.append(f"参考情報: {content[:500]}")
            
            context = "\n\n".join(context_parts)
            
            # プラットフォーム別プロンプト
            if platform == "line":
                prompt_template = """以下の参考情報を基に、ユーザーの質問に親しみやすく簡潔に答えてください。絵文字を適度に使用し、LINEメッセージとして自然な形式で回答してください。

参考情報:
{context}

質問: {query}

回答:"""
            else:
                prompt_template = """以下の参考情報を基に、ユーザーの質問に詳しく丁寧に答えてください。専門的な内容も分かりやすく説明してください。

参考情報:
{context}

質問: {query}

回答:"""
            
            prompt = prompt_template.format(context=context, query=query)
            
            # LLM呼び出し
            if hasattr(self.llm_instance, 'ainvoke'):
                response = await self.llm_instance.ainvoke(prompt)
            elif hasattr(self.llm_instance, 'invoke'):
                response = self.llm_instance.invoke(prompt)
            else:
                response = self.llm_instance(prompt)
            
            # 応答の抽出
            if hasattr(response, 'content'):
                answer = response.content
            else:
                answer = str(response)
            
            cleaned_answer = self._clean_rag_response(answer)
            
            return {
                "answer": cleaned_answer,
                "method": "llm_direct",
                "prompt_length": len(prompt)
            }
            
        except Exception as e:
            raise Exception(f"LLM direct generation failed: {e}")

    def _clean_rag_response(self, raw_response: str) -> str:
        """RAG応答のクリーンアップ"""
        if not raw_response or len(raw_response.strip()) < 3:
            return "申し訳ございません。お尋ねの内容について詳細な情報をお答えできませんでした。"

        cleaned = raw_response.strip()

        # 構造化マーカーの除去
        cleanup_patterns = [
            r"関連文書が見つかりました[:：]?\s*",
            r"関連情報が見つかりました[:：]?\s*",
            r"\d+\.\s*【質問】[^】]*】\s*",
            r"【回答】\s*",
            r"【質問】\s*",
            r"出典[:：]\s*[^\n]*",
            r"/tmp/tmp[a-zA-Z0-9_]*\.pdf",
            r"\([pP]\d+\)",
            r"^\d+\.\s*",
            r"【[^】]*】",
            r"^質問[:：]\s*",
            r"^回答[:：]\s*",
            r"参考情報[:：].*?\n",
        ]

        for pattern in cleanup_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.IGNORECASE)

        # 改行・空白の正規化
        lines = [line.strip() for line in cleaned.split('\n') if line.strip()]
        
        # 重複行の除去
        unique_lines = []
        seen_content = set()
        
        for line in lines:
            if len(line) < 5:  # 短すぎる行はスキップ
                continue
            
            line_normalized = re.sub(r'[。、\s]', '', line.lower())
            if any(line_normalized in s or s in line_normalized for s in seen_content):
                continue
            
            seen_content.add(line_normalized)
            unique_lines.append(line)

        # 最適な応答を選択
        if unique_lines:
            # 最も長い行を選択（通常最も情報量が多い）
            best_line = max(unique_lines, key=len)
            
            # 文の完全性をチェック
            if len(best_line) > 20 and (best_line.endswith('。') or best_line.endswith('です') or best_line.endswith('ます')):
                return best_line
            
            # 複数行を結合
            result = '。'.join(unique_lines[:2])  # 最大2行まで結合
            if not result.endswith('。'):
                result += '。'
            return result
        
        # フォールバック
        return "申し訳ございません。お尋ねの内容について、より詳しい情報をご提供するため、直接お問い合わせいただければと思います。"

    def _postprocess_result(self, generation_result: Dict, retrieval_result: Dict) -> Dict[str, Any]:
        """結果の後処理"""
        # ソース情報の構築
        sources = []
        documents = retrieval_result.get("documents", [])
        
        for i, (doc, score) in enumerate(documents[:3]):  # 上位3つのソース
            metadata = getattr(doc, 'metadata', {})
            content = getattr(doc, 'page_content', '')
            
            source_info = {
                "index": i,
                "content_preview": content[:200] + "..." if len(content) > 200 else content,
                "metadata": {
                    "source": metadata.get('source', 'unknown'),
                    "page": metadata.get('page', 0),
                    "relevance_score": round(score, 3)
                },
                "document_length": len(content)
            }
            sources.append(source_info)

        return {
            "answer": generation_result.get("answer", ""),
            "sources": sources,
            "success": True,
            "processing_details": {
                "retrieval_time": retrieval_result.get("retrieval_time", 0),
                "generation_time": generation_result.get("generation_time", 0),
                "total_candidates": retrieval_result.get("total_candidates", 0),
                "final_document_count": len(documents),
                "generation_method": generation_result.get("method", "unknown")
            },
            "metadata": {
                "search_queries": len(retrieval_result.get("search_metadata", [])),
                "highest_relevance_score": max([score for _, score in documents]) if documents else 0,
                "processing_timestamp": datetime.now().isoformat()
            }
        }

    def _generate_error_response(self, query: str, platform: str) -> str:
        """エラー応答の生成"""
        if platform == "line":
            return """申し訳ございません😅

システムの調子が良くないようです。
しばらく時間をおいてから、もう一度お試しください。

お急ぎの場合は、スタッフまで直接お問い合わせください📞"""
        else:
            return """申し訳ございません。システムに問題が発生しているため、お尋ねの内容について適切な回答をご提供することができません。

しばらく時間をおいてから再度お試しいただくか、お急ぎの場合は直接スタッフまでお問い合わせください。"""

    def _update_stats(self, success: bool, total_time: float, 
                     retrieval_result: Dict, generation_result: Dict) -> None:
        """統計情報の更新"""
        if success:
            # 平均時間の更新
            query_count = self.stats["total_queries"]
            
            retrieval_time = retrieval_result.get("retrieval_time", 0)
            generation_time = generation_result.get("generation_time", 0)
            
            # 移動平均の計算
            if query_count > 1:
                self.stats["average_retrieval_time"] = (
                    (self.stats["average_retrieval_time"] * (query_count - 1) + retrieval_time) / query_count
                )
                self.stats["average_generation_time"] = (
                    (self.stats["average_generation_time"] * (query_count - 1) + generation_time) / query_count
                )
            else:
                self.stats["average_retrieval_time"] = retrieval_time
                self.stats["average_generation_time"] = generation_time

    def get_service_stats(self) -> Dict[str, Any]:
        """サービス統計の取得"""
        total_queries = self.stats["total_queries"]
        
        return {
            "performance": {
                "total_queries": total_queries,
                "success_rate": (self.stats["successful_retrievals"] / total_queries * 100) if total_queries > 0 else 0,
                "generation_success_rate": (self.stats["successful_generations"] / total_queries * 100) if total_queries > 0 else 0,
                "average_retrieval_time": self.stats["average_retrieval_time"],
                "average_generation_time": self.stats["average_generation_time"],
                "total_processing_time": self.stats["total_retrieval_time"] + self.stats["total_generation_time"]
            },
            "document_usage": {
                "most_referenced_sources": dict(sorted(
                    self.stats["document_hit_count"].items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:10]),
                "total_document_hits": sum(self.stats["document_hit_count"].values()),
                "unique_sources": len(self.stats["document_hit_count"])
            },
            "configuration": {
                "max_documents": self.max_documents,
                "similarity_threshold": self.similarity_threshold,
                "query_expansion_enabled": self.enable_query_expansion,
                "result_ranking_enabled": self.enable_result_ranking,
                "context_filtering_enabled": self.enable_context_filtering
            },
            "system_status": {
                "vectorstore_available": self.vectorstore is not None,
                "rag_chain_available": self.rag_chain is not None,
                "llm_available": self.llm_instance is not None,
                "langsmith_tracing": LANGSMITH_AVAILABLE and self.tracer is not None
            }
        }

    def get_recent_queries(self, limit: int = 10) -> List[Dict[str, Any]]:
        """最近のクエリ履歴取得"""
        return self.query_history[-limit:] if self.query_history else []

    def clear_stats(self) -> Dict[str, Any]:
        """統計のクリア"""
        old_stats = self.stats.copy()
        
        self.stats = {
            "total_queries": 0,
            "successful_retrievals": 0,
            "successful_generations": 0,
            "failed_queries": 0,
            "average_retrieval_time": 0.0,
            "average_generation_time": 0.0,
            "total_retrieval_time": 0.0,
            "total_generation_time": 0.0,
            "document_hit_count": {},
            "query_categories": {}
        }
        
        self.query_history.clear()
        
        return {
            "status": "stats_cleared",
            "previous_stats": old_stats,
            "timestamp": datetime.now().isoformat()
        }

    def health_check(self) -> Dict[str, Any]:
        """ヘルスチェック"""
        issues = []
        status = "healthy"
        
        # コンポーネント可用性チェック
        if not self.vectorstore:
            issues.append("Vectorstore not available")
            status = "degraded"
        
        if not self.rag_chain and not self.llm_instance:
            issues.append("No generation method available")
            status = "unhealthy"
        
        # パフォーマンスチェック
        if self.stats["total_queries"] > 10:
            success_rate = self.stats["successful_retrievals"] / self.stats["total_queries"]
            if success_rate < 0.8:
                issues.append("Low success rate")
                status = "degraded"
            
            avg_time = self.stats["average_retrieval_time"] + self.stats["average_generation_time"]
            if avg_time > 10.0:
                issues.append("High response time")
                status = "degraded"
        
        return {
            "status": status,
            "issues": issues,
            "component_status": {
                "vectorstore": self.vectorstore is not None,
                "rag_chain": self.rag_chain is not None,
                "llm_instance": self.llm_instance is not None,
                "tracer": self.tracer is not None
            },
            "performance_summary": {
                "total_queries": self.stats["total_queries"],
                "success_rate": (self.stats["successful_retrievals"] / self.stats["total_queries"] * 100) if self.stats["total_queries"] > 0 else 100,
                "average_total_time": self.stats["average_retrieval_time"] + self.stats["average_generation_time"]
            },
            "timestamp": datetime.now().isoformat()
        }

# グローバルサービスインスタンス
_global_rag_service = None

def get_rag_service() -> RAGProcessingService:
    """グローバルRAGサービス取得"""
    global _global_rag_service
    
    if _global_rag_service is None:
        _global_rag_service = RAGProcessingService()
    
    return _global_rag_service

def initialize_rag_service(vectorstore=None, rag_chain=None, llm_instance=None) -> bool:
    """RAGサービスの初期化"""
    service = get_rag_service()
    return service.initialize(vectorstore, rag_chain, llm_instance)

def reset_rag_service() -> RAGProcessingService:
    """RAGサービスのリセット"""
    global _global_rag_service
    _global_rag_service = None
    return get_rag_service()