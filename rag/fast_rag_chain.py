# rag/fast_rag_chain.py - 数十秒応答を実現する超高速RAGチェーン

from __future__ import annotations
import os
import logging
import traceback
from pathlib import Path
from langchain_community.vectorstores import FAISS
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from sentence_transformers import SentenceTransformer
from langchain.schema import Document
from langchain_core.embeddings import Embeddings
import asyncio
import signal
import time

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
        # 最大パフォーマンス設定
        self.model.eval()  
        # CPUスレッド最適化
        import torch
        if torch.get_num_threads() > 4:
            torch.set_num_threads(4)  # スレッド数を制限してレイテンシを改善
        logger.info("✅ Ultra fast embedding model loaded")
    
    def embed_documents(self, texts):
        return self.model.encode(texts, show_progress_bar=False, convert_to_tensor=False, batch_size=16).tolist()
    
    def embed_query(self, text):
        return self.model.encode(text, convert_to_tensor=False).tolist()

def ultra_fast_cache_key(query: str) -> str:
    """超高速キャッシュキー生成"""
    return query.lower().strip()[:100]  # 100文字で切り詰め

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
        # 最古のエントリを削除
        oldest_key = next(iter(_ultra_fast_cache))
        del _ultra_fast_cache[oldest_key]
    
    key = ultra_fast_cache_key(query)
    _ultra_fast_cache[key] = response
    logger.info(f"💾 Ultra fast cache SET for: {query[:30]}...")

def create_ultra_fast_response(raw_response: str, query: str) -> str:
    """
    超高速で自然な回答生成（リッチメニュー特化版）
    """
    if not raw_response or len(raw_response.strip()) < 3:
        return generate_ultra_quick_fallback(query)
    
    # 最小限のクリーンアップ
    cleaned = raw_response.strip()
    
    # 〜しましょうを即座に除去
    import re
    cleaned = re.sub(r'[^\s]*しましょう[。！？]*', '', cleaned)
    cleaned = re.sub(r'一緒に[^\s]*', '', cleaned)
    
    # 質問タイプ別の超高速処理
    if "坪単価" in query or "価格" in query:
        if "坪単価" in cleaned or "万円" in cleaned:
            return format_price_ultra_fast(cleaned)
        else:
            return "坪単価については、約70〜85万円/坪が目安です。仕様により変動いたします。詳細はお問い合わせください。"
    
    elif "仕様" in query or "標準" in query:
        if len(cleaned) > 15:
            return format_spec_ultra_fast(cleaned)
        else:
            return "標準仕様は耐震等級3の長期優良住宅基準です。詳細は展示場でご確認いただけます。"
    
    elif "断熱" in query or "性能" in query:
        if len(cleaned) > 15:
            return cleaned[:150] + "。"
        else:
            return "高性能な断熱材で快適な住環境を実現しています。詳細は展示場でご確認ください。"
    
    # 一般回答（超簡潔版）
    if len(cleaned) > 10:
        result = ensure_proper_ending_ultra_fast(cleaned[:200])
        return result
    else:
        return generate_ultra_quick_fallback(query)

def format_price_ultra_fast(content: str) -> str:
    """価格関連の超高速フォーマット"""
    if len(content) > 150:
        content = content[:130]
    return f"坪単価について、{content}詳細なお見積りはお問い合わせください。"

def format_spec_ultra_fast(content: str) -> str:
    """仕様関連の超高速フォーマット"""
    if len(content) > 150:
        content = content[:130]
    return f"{content}詳細は展示場でご確認ください。"

def ensure_proper_ending_ultra_fast(text: str) -> str:
    """適切な文末に調整（超高速版）"""
    # 〜しましょうを確実に除去
    import re
    text = re.sub(r'[^\s]*しましょう[。！？]*', '', text)
    text = re.sub(r'一緒に[^\s]*', '', text)
    
    if not text.endswith(('。', '！', '？')):
        if text.endswith(('です', 'ます')):
            text += '。'
        elif text.endswith('、'):
            text = text[:-1] + '。'
        else:
            text += '。'
    return text

def generate_ultra_quick_fallback(query: str) -> str:
    """超高速フォールバック回答"""
    if "坪単価" in query:
        return "坪単価については、約70〜85万円/坪が目安です。詳細はお問い合わせください。"
    elif "仕様" in query:
        return "住宅仕様について詳しくご案内いたします。展示場でご確認ください。"
    elif "資料" in query:
        return "資料請求を承ります。お名前、ご住所、お電話番号をお教えください。"
    elif "見学" in query or "展示" in query:
        return "展示場見学を承ります。ご希望日時をお聞かせください。"
    else:
        return "お尋ねの件について、詳しくは直接お問い合わせください。"

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
    """最小限のベクトルストア作成（超高速版）"""
    embeddings = UltraFastEmbedding()
    
    minimal_docs = [
        Document(
            page_content="キノエデザインの坪単価は約70〜85万円/坪です。仕様によって変動します。詳細なお見積りをご提供いたします。",
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

def get_ultra_fast_rag_chain(vectorstore, return_source: bool = True):
    """超高速RAGチェーン（数十秒応答対応）"""
    logger.info("Creating ultra fast RAG chain for sub-30-second response...")
    
    try:
        from llm.llm_runner import load_llm
        llm, _, _ = load_llm()
        
        # 超高速プロンプト（最小限）
        ultra_fast_prompt = """住宅専門アドバイザーとして簡潔に回答してください。

【超重要】
- 100文字以内で簡潔に
- 「〜しましょう」は絶対禁止
- 「です・ます」調で丁寧に
- 具体的で実用的に

参考: {context}
質問: {question}
回答:"""
        
        prompt = PromptTemplate(
            input_variables=["context", "question"],
            template=ultra_fast_prompt
        )
        
        # 超高速リトリーバー（検索件数を最小限に）
        retriever = vectorstore.as_retriever(search_kwargs={"k": 1})  # 2→1に削減
        
        rag_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=return_source,
            chain_type_kwargs={"prompt": prompt}
        )
        
        # 超高速ラッパー
        class UltraFastResponseChain:
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
                    # 2. 超厳格タイムアウト付きで実行
                    def timeout_handler(signum, frame):
                        raise TimeoutError("Ultra fast RAG processing timeout")
                    
                    signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(4)  # 10秒→4秒に大幅短縮
                    
                    try:
                        start_time = time.time()
                        result = self.base_chain.invoke(inputs)
                        processing_time = time.time() - start_time
                        
                        raw_result = result.get("result", "")
                        logger.info(f"⚡ Raw RAG result ({processing_time:.2f}s): {raw_result[:50]}...")
                        
                        # 超高速レスポンス生成
                        ultra_fast_result = create_ultra_fast_response(raw_result, query)
                        
                        # キャッシュに保存
                        set_ultra_fast_cached_response(query, ultra_fast_result)
                        
                        result["result"] = ultra_fast_result
                        return result
                    finally:
                        signal.alarm(0)  # タイムアウト解除
                    
                except TimeoutError:
                    logger.warning(f"⏰ Ultra fast RAG timeout for query: {query}")
                    fallback = generate_ultra_quick_fallback(query)
                    set_ultra_fast_cached_response(query, fallback)
                    return {
                        "result": fallback,
                        "source_documents": []
                    }
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
        
        logger.info("✅ Ultra fast RAG chain created successfully")
        return UltraFastResponseChain(rag_chain)
        
    except Exception as e:
        logger.error(f"Error creating ultra fast RAG chain: {e}")
        return create_emergency_chain_ultra_fast(vectorstore)

def create_emergency_chain_ultra_fast(vectorstore):
    """緊急用超超高速チェーン"""
    logger.info("Creating emergency ultra fast chain...")
    
    class EmergencyUltraFastChain:
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
                
                # 超高速検索（タイムアウト2秒）
                signal.signal(signal.SIGALRM, lambda s, f: (_ for _ in ()).throw(TimeoutError()))
                signal.alarm(2)
                
                try:
                    docs = self.retriever.invoke(query)
                    signal.alarm(0)
                    
                    if docs:
                        content = docs[0].page_content[:100]  # 200→100文字に短縮
                        ultra_fast_result = create_ultra_fast_response(content, query)
                    else:
                        ultra_fast_result = generate_ultra_quick_fallback(query)
                    
                    set_ultra_fast_cached_response(query, ultra_fast_result)
                    
                    return {
                        "result": ultra_fast_result,
                        "source_documents": docs[:1] if docs else []
                    }
                except TimeoutError:
                    signal.alarm(0)
                    fallback = generate_ultra_quick_fallback(query)
                    set_ultra_fast_cached_response(query, fallback)
                    return {"result": fallback, "source_documents": []}
                    
            except Exception as e:
                logger.error(f"Emergency ultra fast chain error: {e}")
                fallback = "申し訳ございません。再度お試しください。"
                set_ultra_fast_cached_response(query, fallback)
                return {"result": fallback, "source_documents": []}
        
        def __call__(self, inputs, callbacks=None):
            return self.invoke(inputs)
    
    return EmergencyUltraFastChain(vectorstore)

# ===== パフォーマンス監視機能 =====
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

# ===== メイン実行部分（テスト用） =====
if __name__ == "__main__":
    print("🚀 Ultra Fast RAG Chain Test")
    print("=" * 50)
    
    # 超高速ヘルスチェック
    try:
        vectorstore = load_ultra_fast_vectorstore()
        print("✅ Ultra fast vectorstore loaded")
        
        rag_chain = get_ultra_fast_rag_chain(vectorstore)
        print("✅ Ultra fast RAG chain created")
        
        # 超高速テスト
        test_queries = [
            "坪単価について教えて",
            "標準仕様は？",
            "断熱性能について",
            "資料請求したい"
        ]
        
        total_time = 0
        for query in test_queries:
            start_time = time.time()
            response = rag_chain.invoke({"query": query})
            processing_time = time.time() - start_time
            total_time += processing_time
            
            result = response.get('result', 'No result')
            print(f"Query: {query}")
            print(f"Response: {result[:100]}...")
            print(f"Time: {processing_time:.2f}s")
            print("-" * 30)
        
        print(f"Average time: {total_time/len(test_queries):.2f}s")
        print(f"Cache stats: {get_ultra_fast_cache_stats()}")
        
    except Exception as e:
        print(f"❌ Ultra fast RAG test error: {e}")
        print(traceback.format_exc())