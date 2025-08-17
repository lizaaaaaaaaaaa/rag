# rag/fast_rag_chain.py - Cloud Run対応版（signal削除、asyncio使用）

from __future__ import annotations
import os
import logging
import traceback
import asyncio
from pathlib import Path
from langchain_community.vectorstores import FAISS
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from sentence_transformers import SentenceTransformer
from langchain.schema import Document
from langchain_core.embeddings import Embeddings
import time
import concurrent.futures

logger = logging.getLogger(__name__)

LOCAL_VECTOR_DIR = "rag/vectorstore"
INDEX_NAME = "index"

# 超高速メモリキャッシュ
_ultra_fast_cache = {}
_cache_hits = 0
_cache_misses = 0
MAX_ULTRA_CACHE_SIZE = 200

class UltraFastEmbedding(Embeddings):
    """超高速埋め込みクラス（最適化版）"""
    def __init__(self, model_name: str = "intfloat/multilingual-e5-small"):
        logger.info(f"🚀 Loading ultra fast embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.model.eval()
        import torch
        if torch.get_num_threads() > 4:
            torch.set_num_threads(4)
        logger.info("✅ Ultra fast embedding model loaded")
    
    def embed_documents(self, texts):
        return self.model.encode(texts, show_progress_bar=False, convert_to_tensor=False, batch_size=16).tolist()
    
    def embed_query(self, text):
        return self.model.encode(text, convert_to_tensor=False).tolist()

def ultra_fast_cache_key(query: str) -> str:
    """超高速キャッシュキー生成"""
    return query.lower().strip()[:100]

def get_ultra_fast_cached_response(query: str) -> str | None:
    """超高速キャッシュから回答取得"""
    global _cache_hits, _cache_misses
    key = ultra_fast_cache_key(query)
    if key in _ultra_fast_cache:
        _cache_hits += 1
        logger.info(f"⚡ Ultra fast cache HIT for: {query[:30]}...")
        return _ultra_fast_cache[key]
    _cache_misses += 1
    return None

def set_ultra_fast_cached_response(query: str, response: str):
    """超高速キャッシュに応答保存"""
    global _ultra_fast_cache
    if len(_ultra_fast_cache) >= MAX_ULTRA_CACHE_SIZE:
        oldest_key = next(iter(_ultra_fast_cache))
        del _ultra_fast_cache[oldest_key]
    
    key = ultra_fast_cache_key(query)
    _ultra_fast_cache[key] = response
    logger.info(f"💾 Ultra fast cache SET for: {query[:30]}...")

def create_ultra_fast_response(raw_response: str, query: str) -> str:
    """超高速で自然な回答生成（改良版）"""
    if not raw_response or len(raw_response.strip()) < 3:
        return generate_ultra_quick_fallback(query)
    
    # 自然な回答生成を統合
    from rag.ingested_text import create_natural_response
    
    try:
        # ingested_textの自然回答生成機能を活用
        natural_response = create_natural_response(raw_response, query)
        
        if natural_response and len(natural_response.strip()) > 10:
            return natural_response
        else:
            return generate_ultra_quick_fallback(query)
            
    except Exception as e:
        logger.error(f"Natural response generation error: {e}")
        return generate_ultra_quick_fallback(query)

def generate_ultra_quick_fallback(query: str) -> str:
    """統一されたフォールバック回答（LINEボットと同じ品質）"""
    if "坪単価" in query or "価格" in query:
        return "坪単価についてご案内いたします。標準仕様では約70〜85万円/坪が目安となりますが、お客様のご希望される仕様によって変動いたします。詳細なお見積りをご提供いたしますので、お気軽にお問い合わせください。"
    elif "仕様" in query or "標準" in query:
        return "標準仕様についてご説明いたします。耐震等級3の長期優良住宅を基準とし、高品質な住まいをご提供するため、様々な設備や性能を標準装備としております。詳細は展示場でご確認いただけます。"
    elif "断熱" in query or "性能" in query:
        return "断熱性能については、高品質な断熱材を使用し、快適な住環境を実現しています。ZEH基準に対応した省エネ性能で、一年中快適にお過ごしいただけます。"
    elif "資料" in query:
        return "資料請求を承ります。お名前、ご住所、お電話番号をお教えいただければ、詳しい資料をお送りいたします。"
    elif "見学" in query or "展示" in query:
        return "展示場見学を承ります。ご希望の日時をお聞かせください。スタッフが丁寧にご案内いたします。"
    else:
        return "お尋ねの内容について詳しくご案内いたします。住宅に関することでしたら何でもお気軽にお問い合わせください。"

def load_ultra_fast_vectorstore():
    """超高速ベクトルストア読み込み"""
    try:
        index_path = os.path.join(LOCAL_VECTOR_DIR, f"{INDEX_NAME}.faiss")
        
        if not os.path.exists(index_path):
            logger.warning("Vectorstore not found, creating minimal one...")
            return create_minimal_vectorstore_ultra_fast()
        
        embeddings = UltraFastEmbedding()
        vectorstore = FAISS.load_local(
            LOCAL_VECTOR_DIR,
            embeddings,
            index_name=INDEX_NAME,
            allow_dangerous_deserialization=True
        )
        
        logger.info("✅ Ultra fast vectorstore loaded")
        return vectorstore
        
    except Exception as e:
        logger.error(f"Ultra fast vectorstore load error: {e}")
        return create_minimal_vectorstore_ultra_fast()

def create_minimal_vectorstore_ultra_fast():
    """最小限のベクトルストア作成"""
    embeddings = UltraFastEmbedding()
    
    minimal_docs = [
        Document(
            page_content="キノエデザインの坪単価は約70〜85万円/坪です。お客様のご希望される仕様によって変動いたします。詳細なお見積りをご提供いたします。",
            metadata={"source": "price_info", "page": 1}
        ),
        Document(
            page_content="標準仕様は耐震等級3の長期優良住宅基準です。高品質な設備を標準装備しています。詳細は展示場でご確認ください。",
            metadata={"source": "spec_info", "page": 1}
        ),
        Document(
            page_content="高性能な断熱材を使用し、快適な住環境を実現しています。ZEH基準に対応した省エネ性能です。",
            metadata={"source": "performance_info", "page": 1}
        )
    ]
    
    vectorstore = FAISS.from_documents(minimal_docs, embeddings)
    
    os.makedirs(LOCAL_VECTOR_DIR, exist_ok=True)
    vectorstore.save_local(LOCAL_VECTOR_DIR, index_name=INDEX_NAME)
    
    logger.info("✅ Minimal ultra fast vectorstore created")
    return vectorstore

async def async_rag_processing(rag_chain, inputs, timeout_seconds=5):
    """非同期RAG処理（signalの代わりにasyncio.wait_forを使用）"""
    def sync_rag_call():
        try:
            return rag_chain.invoke(inputs)
        except Exception as e:
            logger.error(f"Sync RAG call error: {e}")
            raise
    
    loop = asyncio.get_event_loop()
    
    try:
        # concurrent.futuresで同期処理を非同期化
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = loop.run_in_executor(executor, sync_rag_call)
            result = await asyncio.wait_for(future, timeout=timeout_seconds)
            return result
    except asyncio.TimeoutError:
        logger.warning(f"⏰ RAG processing timeout ({timeout_seconds}s)")
        raise
    except Exception as e:
        logger.error(f"❌ Async RAG processing error: {e}")
        raise

def get_ultra_fast_rag_chain(vectorstore, return_source: bool = True):
    """Cloud Run対応超高速RAGチェーン（signal削除版）"""
    logger.info("Creating Cloud Run compatible ultra fast RAG chain...")
    
    try:
        from llm.llm_runner import load_llm
        llm, _, _ = load_llm()
        
        # 改良されたプロンプト（LINEボットと統一）
        ultra_fast_prompt = """あなたは親切で知識豊富な住宅・建築の専門アドバイザーです。
以下の参考情報を基に、質問に対して自然で分かりやすい回答を提供してください。

【重要な指示】
- 自然で親しみやすい日本語で回答する
- 専門用語は分かりやすく説明する
- 具体的で実用的な情報を含める
- 「〜しましょう」は使用禁止
- 200文字程度で簡潔にまとめる

参考情報: {context}

質問: {question}

回答:"""
        
        prompt = PromptTemplate(
            input_variables=["context", "question"],
            template=ultra_fast_prompt
        )
        
        retriever = vectorstore.as_retriever(search_kwargs={"k": 2})
        
        rag_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=return_source,
            chain_type_kwargs={"prompt": prompt}
        )
        
        # Cloud Run対応ラッパー（signal削除版）
        class CloudRunCompatibleChain:
            def __init__(self, base_chain):
                self.base_chain = base_chain
                self.callbacks = []
            
            def invoke(self, inputs):
                query = inputs.get("query", "")
                
                # 1. 超高速キャッシュチェック
                cached_response = get_ultra_fast_cached_response(query)
                if cached_response:
                    return {
                        "result": cached_response,
                        "source_documents": []
                    }
                
                try:
                    # 2. 非同期タイムアウト処理（signalの代わり）
                    start_time = time.time()
                    
                    # 同期処理のまま、エラー処理を強化
                    try:
                        result = self.base_chain.invoke(inputs)
                        processing_time = time.time() - start_time
                        
                        raw_result = result.get("result", "")
                        logger.info(f"⚡ Raw RAG result ({processing_time:.2f}s): {raw_result[:50]}...")
                        
                        # 自然回答生成（ingested_textと統一）
                        enhanced_result = create_ultra_fast_response(raw_result, query)
                        
                        # キャッシュに保存
                        set_ultra_fast_cached_response(query, enhanced_result)
                        
                        result["result"] = enhanced_result
                        return result
                        
                    except Exception as rag_error:
                        logger.error(f"RAG chain error: {rag_error}")
                        raise
                    
                except Exception as e:
                    logger.error(f"❌ Ultra fast RAG error: {e}")
                    fallback = generate_ultra_quick_fallback(query)
                    set_ultra_fast_cached_response(query, fallback)
                    return {
                        "result": fallback,
                        "source_documents": []
                    }
            
            def __call__(self, inputs, callbacks=None):
                return self.invoke(inputs)
        
        logger.info("✅ Cloud Run compatible ultra fast RAG chain created")
        return CloudRunCompatibleChain(rag_chain)
        
    except Exception as e:
        logger.error(f"Error creating ultra fast RAG chain: {e}")
        return create_emergency_chain_ultra_fast(vectorstore)

def create_emergency_chain_ultra_fast(vectorstore):
    """緊急用超高速チェーン（signal不使用）"""
    logger.info("Creating emergency ultra fast chain...")
    
    class EmergencyCloudRunChain:
        def __init__(self, vectorstore):
            self.vectorstore = vectorstore
            self.retriever = vectorstore.as_retriever(search_kwargs={"k": 1}) if vectorstore else None
            self.callbacks = []
        
        def invoke(self, inputs):
            query = inputs.get("query", "")
            
            # 超高速キャッシュチェック
            cached = get_ultra_fast_cached_response(query)
            if cached:
                return {"result": cached, "source_documents": []}
            
            try:
                if not self.retriever:
                    fallback = generate_ultra_quick_fallback(query)
                    set_ultra_fast_cached_response(query, fallback)
                    return {"result": fallback, "source_documents": []}
                
                # シンプルな検索（タイムアウトなし）
                docs = self.retriever.invoke(query)
                
                if docs:
                    content = docs[0].page_content[:200]
                    enhanced_result = create_ultra_fast_response(content, query)
                else:
                    enhanced_result = generate_ultra_quick_fallback(query)
                
                set_ultra_fast_cached_response(query, enhanced_result)
                
                return {
                    "result": enhanced_result,
                    "source_documents": docs[:1] if docs else []
                }
                    
            except Exception as e:
                logger.error(f"Emergency chain error: {e}")
                fallback = generate_ultra_quick_fallback(query)
                set_ultra_fast_cached_response(query, fallback)
                return {"result": fallback, "source_documents": []}
        
        def __call__(self, inputs, callbacks=None):
            return self.invoke(inputs)
    
    return EmergencyCloudRunChain(vectorstore)

# キャッシュ統計（変更なし）
def get_ultra_fast_cache_stats():
    """超高速キャッシュの統計情報"""
    total_requests = _cache_hits + _cache_misses
    hit_rate = _cache_hits / total_requests if total_requests > 0 else 0
    
    return {
        "cache_size": len(_ultra_fast_cache),
        "max_cache_size": MAX_ULTRA_CACHE_SIZE,
        "cache_hits": _cache_hits,
        "cache_misses": _cache_misses,
        "hit_rate": hit_rate,
        "total_requests": total_requests
    }

def clear_ultra_fast_cache():
    """超高速キャッシュをクリア"""
    global _ultra_fast_cache, _cache_hits, _cache_misses
    _ultra_fast_cache.clear()
    _cache_hits = 0
    _cache_misses = 0
    logger.info("🧹 Ultra fast cache cleared")

# テスト実行部分
if __name__ == "__main__":
    print("🚀 Cloud Run Compatible Ultra Fast RAG Chain Test")
    print("=" * 60)
    
    try:
        vectorstore = load_ultra_fast_vectorstore()
        print("✅ Ultra fast vectorstore loaded")
        
        rag_chain = get_ultra_fast_rag_chain(vectorstore)
        print("✅ Cloud Run compatible RAG chain created")
        
        # テスト
        test_queries = [
            "坪単価について教えて",
            "標準仕様は？",
            "断熱性能について"
        ]
        
        for query in test_queries:
            start_time = time.time()
            response = rag_chain.invoke({"query": query})
            processing_time = time.time() - start_time
            
            result = response.get('result', 'No result')
            print(f"Query: {query}")
            print(f"Response: {result[:100]}...")
            print(f"Time: {processing_time:.2f}s")
            print("-" * 30)
        
        print(f"Cache stats: {get_ultra_fast_cache_stats()}")
        
    except Exception as e:
        print(f"❌ Test error: {e}")
        print(traceback.format_exc())