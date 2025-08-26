# rag/fast_rag_chain.py - 超高速版（応答速度最優先）

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
import hashlib

logger = logging.getLogger(__name__)

LOCAL_VECTOR_DIR = "rag/vectorstore"
INDEX_NAME = "index"

# 🚀 超高速キャッシュ強化（サイズ拡大・永続化）
_ultra_fast_cache = {}
_cache_hits = 0
_cache_misses = 0
MAX_ULTRA_CACHE_SIZE = 500  # 🔧 拡大：200→500
CACHE_EXPIRE_TIME = 7200     # 🔧 2時間キャッシュ

# 🚀 FAQ事前キャッシュ（よくある質問を起動時に登録）
_faq_cache = {
    "坪単価": "坪単価は約70〜85万円/坪です。詳細なお見積りをご提供いたします。",
    "価格": "価格については、仕様により変動いたします。詳細はお問い合わせください。",
    "標準仕様": "標準仕様は耐震等級3の長期優良住宅基準です。詳細は展示場でご確認ください。",
    "断熱": "高性能断熱材使用で、ZEH基準対応の省エネ性能です。",
    "耐震": "耐震等級3を標準とし、地震に強い安心・安全な住まいです。",
    "資料請求": "資料請求を承ります。お名前、ご住所、電話番号をお教えください。",
    "展示場": "展示場見学を承ります。ご希望の日時をお聞かせください。",
    "ai相談": "🤖 AI住まい相談を開始します！何でもお聞きください😊",
    "ai住まいサイト": "🌐 住まい情報サイトをご案内します。詳しくはこちら→ https://kinoe-design.com",
    "資金計画": "💰 資金計画についてご相談承ります。お気軽にお問い合わせください。"
}

class SuperFastEmbedding(Embeddings):
    """超高速埋め込みクラス（更なる最適化）"""
    def __init__(self, model_name: str = "intfloat/multilingual-e5-small"):
        logger.info(f"🚀 Loading super fast embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.model.eval()
        
        # 🚀 更なる最適化
        import torch
        torch.set_num_threads(2)  # 🔧 削減：4→2（速度重視）
        
        if hasattr(self.model, 'max_seq_length'):
            self.model.max_seq_length = 256  # 🔧 短縮（速度重視）
            
        logger.info("✅ Super fast embedding model loaded with optimizations")
    
    def embed_documents(self, texts):
        # 🚀 バッチサイズ拡大で効率化
        return self.model.encode(texts, 
                               show_progress_bar=False, 
                               convert_to_tensor=False, 
                               batch_size=32,  # 🔧 拡大：16→32
                               normalize_embeddings=True).tolist()
    
    def embed_query(self, text):
        return self.model.encode(text, 
                               convert_to_tensor=False, 
                               normalize_embeddings=True).tolist()

def super_fast_cache_key(query: str) -> str:
    """超高速キャッシュキー生成（正規化強化）"""
    normalized = query.lower().strip().replace("？", "").replace("?", "").replace("！", "").replace("!", "")
    normalized = normalized.replace("について", "").replace("教えて", "").replace("知りたい", "")
    return hashlib.md5(normalized[:50].encode()).hexdigest()[:8]

def get_faq_response(query: str) -> str | None:
    """🚀 FAQ事前キャッシュから高速回答取得"""
    q_normalized = query.lower().strip()
    
    # 完全一致チェック
    for faq_key, response in _faq_cache.items():
        if faq_key in q_normalized:
            logger.info(f"⚡ FAQ hit: {faq_key}")
            return response
    
    return None

def get_ultra_fast_cached_response(query: str) -> str | None:
    """超高速キャッシュから回答取得（期限チェック付き）"""
    global _cache_hits, _cache_misses
    
    # 🚀 FAQ優先チェック
    faq_response = get_faq_response(query)
    if faq_response:
        _cache_hits += 1
        return faq_response
    
    key = super_fast_cache_key(query)
    current_time = time.time()
    
    if key in _ultra_fast_cache:
        cache_entry = _ultra_fast_cache[key]
        # 🔧 期限チェック
        if current_time - cache_entry['timestamp'] < CACHE_EXPIRE_TIME:
            _cache_hits += 1
            logger.debug(f"⚡ Cache HIT: {query[:25]}...")
            return cache_entry['response']
        else:
            # 期限切れキャッシュ削除
            del _ultra_fast_cache[key]
    
    _cache_misses += 1
    return None

def set_ultra_fast_cached_response(query: str, response: str):
    """超高速キャッシュに応答保存（タイムスタンプ付き）"""
    global _ultra_fast_cache
    
    # キャッシュサイズ管理（LRU的削除）
    if len(_ultra_fast_cache) >= MAX_ULTRA_CACHE_SIZE:
        # 最も古いエントリを削除
        oldest_key = min(_ultra_fast_cache.keys(), 
                        key=lambda k: _ultra_fast_cache[k]['timestamp'])
        del _ultra_fast_cache[oldest_key]
    
    key = super_fast_cache_key(query)
    _ultra_fast_cache[key] = {
        'response': response,
        'timestamp': time.time()
    }
    logger.debug(f"💾 Cache SET: {query[:25]}...")

def ensure_complete_response_super_fast(text: str, query: str = "") -> str:
    """超高速文章完全性確保（最小限処理）"""
    if not text or len(text.strip()) < 3:
        return generate_lightning_fallback(query)
    
    text = text.strip()
    
    # 🚀 最低限の文末チェック
    if not text.endswith(('。', '！', '？', '.', '!', '?')):
        # 最頻出パターンのみ
        if text.endswith(('ます', 'です')):
            text += '。'
        elif text.endswith('、'):
            text = text[:-1] + '。'
        elif len(text) > 15:
            text += '。'
        else:
            text = generate_lightning_fallback(query)
    
    return text

def generate_lightning_fallback(query: str) -> str:
    """超高速フォールバック（最小限キーワードマッチ）"""
    q = query.lower()
    
    # 🚀 最小限のキーワードマッチング
    if any(kw in q for kw in ["坪単価", "価格", "費用"]):
        return "坪単価は約70〜85万円/坪です。詳細はお問い合わせください。"
    elif any(kw in q for kw in ["仕様", "標準"]):
        return "標準仕様は耐震等級3です。詳細は展示場でご確認ください。"
    elif any(kw in q for kw in ["断熱", "性能"]):
        return "高性能断熱材でZEH基準対応です。"
    elif any(kw in q for kw in ["資料", "パンフ"]):
        return "資料請求を承ります。お気軽にお申し付けください。"
    elif any(kw in q for kw in ["展示", "見学"]):
        return "展示場見学を承ります。ご予約をお取りします。"
    else:
        return "住宅に関することでしたらお気軽にお問い合わせください。"

def load_super_fast_vectorstore():
    """超高速ベクトルストア読み込み（軽量化）"""
    try:
        index_path = os.path.join(LOCAL_VECTOR_DIR, f"{INDEX_NAME}.faiss")
        
        if not os.path.exists(index_path):
            logger.warning("Vectorstore not found, creating minimal one...")
            return create_minimal_vectorstore_super_fast()
        
        embeddings = SuperFastEmbedding()
        vectorstore = FAISS.load_local(
            LOCAL_VECTOR_DIR,
            embeddings,
            index_name=INDEX_NAME,
            allow_dangerous_deserialization=True
        )
        
        logger.info("✅ Super fast vectorstore loaded")
        return vectorstore
        
    except Exception as e:
        logger.error(f"Super fast vectorstore load error: {e}")
        return create_minimal_vectorstore_super_fast()

def create_minimal_vectorstore_super_fast():
    """最小限のベクトルストア作成（軽量ドキュメント）"""
    embeddings = SuperFastEmbedding()
    
    # 🚀 軽量ドキュメント（簡潔版）
    minimal_docs = [
        Document(page_content="坪単価約70〜85万円/坪。仕様により変動。", metadata={"source": "price"}),
        Document(page_content="標準仕様は耐震等級3の長期優良住宅基準。", metadata={"source": "spec"}),
        Document(page_content="高性能断熱材使用でZEH基準対応。", metadata={"source": "performance"}),
        Document(page_content="耐震等級3で地震に強い住まい。", metadata={"source": "safety"}),
        Document(page_content="資料請求承ります。3営業日以内送付。", metadata={"source": "contact"}),
        Document(page_content="展示場見学承ります。スタッフが案内。", metadata={"source": "visit"})
    ]
    
    vectorstore = FAISS.from_documents(minimal_docs, embeddings)
    
    os.makedirs(LOCAL_VECTOR_DIR, exist_ok=True)
    vectorstore.save_local(LOCAL_VECTOR_DIR, index_name=INDEX_NAME)
    
    logger.info("✅ Minimal super fast vectorstore created")
    return vectorstore

def get_super_fast_rag_chain(vectorstore, return_source: bool = False):  # 🔧 source無効化
    """超高速RAGチェーン（速度最優先版）"""
    logger.info("Creating super fast RAG chain (speed optimized)...")
    
    try:
        from llm.llm_runner import get_cached_llm_instance  # 🚀 キャッシュ版LLM使用
        llm = get_cached_llm_instance()
        
        # 🚀 超簡潔プロンプト（トークン節約）
        super_fast_prompt = """住宅専門AI。簡潔回答。

参考: {context}
質問: {question}
回答:"""
        
        prompt = PromptTemplate(
            input_variables=["context", "question"],
            template=super_fast_prompt
        )
        
        # 🚀 検索数削減
        retriever = vectorstore.as_retriever(search_kwargs={"k": 1})  # 🔧 削減：2→1
        
        rag_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=return_source,
            chain_type_kwargs={"prompt": prompt}
        )
        
        # 超高速ラッパー
        class SuperFastChain:
            def __init__(self, base_chain):
                self.base_chain = base_chain
                self.callbacks = []
            
            def invoke(self, inputs):
                query = inputs.get("query", "")
                
                # 1) 超高速キャッシュ（FAQ含む）
                cached = get_ultra_fast_cached_response(query)
                if cached:
                    return {"result": cached, "source_documents": []}
                
                try:
                    # 2) RAG実行（タイムアウト短縮）
                    start_time = time.time()
                    
                    # 🚀 タイムアウト付き実行（5秒）
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(self.base_chain.invoke, inputs)
                        try:
                            result = future.result(timeout=5)  # 🔧 短縮：8→5秒
                            processing_time = time.time() - start_time
                            
                            raw_result = result.get("result", "")
                            logger.info(f"⚡ RAG result ({processing_time:.2f}s): {raw_result[:40]}...")
                            
                            # 3) 超高速完全性チェック
                            final_result = ensure_complete_response_super_fast(raw_result, query)
                            
                            # 4) キャッシュ保存
                            set_ultra_fast_cached_response(query, final_result)
                            
                            result["result"] = final_result
                            return result
                            
                        except concurrent.futures.TimeoutError:
                            logger.warning("⏰ RAG timeout (5s), using fallback")
                            raise
                    
                except Exception as e:
                    logger.error(f"❌ Super fast RAG error: {e}")
                    fallback = generate_lightning_fallback(query)
                    complete_fallback = ensure_complete_response_super_fast(fallback, query)
                    set_ultra_fast_cached_response(query, complete_fallback)
                    return {"result": complete_fallback, "source_documents": []}
            
            def __call__(self, inputs, callbacks=None):
                return self.invoke(inputs)
        
        logger.info("✅ Super fast RAG chain created")
        return SuperFastChain(rag_chain)
        
    except Exception as e:
        logger.error(f"Error creating super fast RAG chain: {e}")
        return create_emergency_chain_super_fast(vectorstore)

def create_emergency_chain_super_fast(vectorstore):
    """緊急用超高速チェーン（FAQベース）"""
    logger.info("Creating emergency super fast chain...")
    
    class EmergencyFastChain:
        def __init__(self, vectorstore):
            self.vectorstore = vectorstore
            self.callbacks = []
        
        def invoke(self, inputs):
            query = inputs.get("query", "")
            
            # FAQキャッシュ優先
            cached = get_ultra_fast_cached_response(query)
            if cached:
                return {"result": cached, "source_documents": []}
            
            # 緊急フォールバック
            fallback = generate_lightning_fallback(query)
            final_result = ensure_complete_response_super_fast(fallback, query)
            set_ultra_fast_cached_response(query, final_result)
            
            return {"result": final_result, "source_documents": []}
        
        def __call__(self, inputs, callbacks=None):
            return self.invoke(inputs)
    
    return EmergencyFastChain(vectorstore)

def get_super_fast_cache_stats():
    """超高速キャッシュ統計"""
    total_requests = _cache_hits + _cache_misses
    hit_rate = _cache_hits / total_requests if total_requests > 0 else 0
    
    return {
        "cache_size": len(_ultra_fast_cache),
        "max_cache_size": MAX_ULTRA_CACHE_SIZE,
        "faq_cache_size": len(_faq_cache),
        "cache_hits": _cache_hits,
        "cache_misses": _cache_misses,
        "hit_rate": hit_rate * 100,
        "total_requests": total_requests,
        "expire_time": CACHE_EXPIRE_TIME,
        "speed_optimizations": [
            "FAQ pre-cache enabled",
            "Extended cache size (500)",
            "Cache expiration (2h)",
            "Reduced search results (k=1)",
            "5s timeout",
            "Lightweight embeddings"
        ]
    }

def clear_super_fast_cache():
    """超高速キャッシュクリア"""
    global _ultra_fast_cache, _cache_hits, _cache_misses
    _ultra_fast_cache.clear()
    _cache_hits = 0
    _cache_misses = 0
    logger.info("🧹 Super fast cache cleared (FAQ cache preserved)")

# 🚀 FAQ事前ロード（アプリ起動時実行）
def preload_faq_cache():
    """FAQ事前キャッシュロード"""
    logger.info(f"🚀 FAQ pre-cache loaded: {len(_faq_cache)} entries")
    for key, response in _faq_cache.items():
        logger.debug(f"   - {key}: {response[:30]}...")

# 起動時FAQ初期化
preload_faq_cache()

if __name__ == "__main__":
    print("🚀 Super Fast RAG Chain Test (Speed Optimized)")
    print("=" * 60)
    
    try:
        vectorstore = load_super_fast_vectorstore()
        print("✅ Super fast vectorstore loaded")
        
        rag_chain = get_super_fast_rag_chain(vectorstore)
        print("✅ Super fast RAG chain created")
        
        # スピードテスト
        test_queries = [
            "坪単価",      # FAQ hit expected
            "標準仕様",    # FAQ hit expected
            "断熱性能について教えて",  # RAG or FAQ hit
            "ai相談",      # FAQ hit expected
            "複雑な住宅設計について詳しく知りたい"  # RAG処理
        ]
        
        print("\n🏃‍♂️ Speed Test Results:")
        for query in test_queries:
            start_time = time.time()
            response = rag_chain.invoke({"query": query})
            processing_time = time.time() - start_time
            
            result = response.get('result', 'No result')
            print(f"Query: {query}")
            print(f"Response: {result[:80]}...")
            print(f"Speed: {processing_time:.3f}s {'🚀' if processing_time < 0.5 else '⚡' if processing_time < 2 else '🐌'}")
            print("-" * 40)
        
        stats = get_super_fast_cache_stats()
        print(f"\n📊 Cache Performance:")
        print(f"   Hit Rate: {stats['hit_rate']:.1f}%")
        print(f"   Cache Size: {stats['cache_size']}")
        print(f"   FAQ Entries: {stats['faq_cache_size']}")
        
    except Exception as e:
        print(f"❌ Test error: {e}")
        print(traceback.format_exc())