# rag/fast_rag_chain.py - LINE Bot用高速RAGチェーン

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

logger = logging.getLogger(__name__)

LOCAL_VECTOR_DIR = "rag/vectorstore"
INDEX_NAME = "index"

class FastEmbedding(Embeddings):
    """高速埋め込みクラス（軽量版）"""
    def __init__(self, model_name: str = "intfloat/multilingual-e5-small"):
        self.model = SentenceTransformer(model_name)
        # パフォーマンス最適化
        self.model.eval()  # 評価モードで高速化
    
    def embed_documents(self, texts):
        return self.model.encode(texts, show_progress_bar=False, convert_to_tensor=False).tolist()
    
    def embed_query(self, text):
        return self.model.encode(text, convert_to_tensor=False).tolist()

def create_fast_response(raw_response: str, query: str) -> str:
    """
    高速で自然な回答生成（LINE Bot最適化版）
    """
    if not raw_response or len(raw_response.strip()) < 3:
        return generate_quick_fallback(query)
    
    # 基本クリーンアップ（最小限）
    cleaned = raw_response.strip()
    
    # 「〜しましょう」を除去
    import re
    cleaned = re.sub(r'[^\s]*しましょう[。！？]*', '', cleaned)
    cleaned = re.sub(r'一緒に[^\s]*', '', cleaned)
    
    # 質問タイプ別の高速処理
    if "坪単価" in query or "価格" in query:
        if "坪単価" in cleaned or "万円" in cleaned:
            return format_price_fast(cleaned)
        else:
            return "坪単価については、仕様によって約70〜85万円/坪が目安です。詳細はお問い合わせください。"
    
    elif "仕様" in query or "標準" in query:
        if len(cleaned) > 20:
            return format_spec_fast(cleaned)
        else:
            return "標準仕様は耐震等級3の長期優良住宅基準です。詳細は展示場でご確認いただけます。"
    
    elif "断熱" in query or "性能" in query:
        if len(cleaned) > 20:
            return cleaned[:200] + "。"
        else:
            return "高性能な断熱材で快適な住環境を実現しています。詳細は展示場でご確認ください。"
    
    # 一般回答（簡潔版）
    if len(cleaned) > 15:
        return ensure_proper_ending(cleaned[:250])
    else:
        return generate_quick_fallback(query)

def format_price_fast(content: str) -> str:
    """価格関連の高速フォーマット"""
    if len(content) > 200:
        content = content[:180]
    return f"坪単価について、{content}お見積りはお気軽にお問い合わせください。"

def format_spec_fast(content: str) -> str:
    """仕様関連の高速フォーマット"""
    if len(content) > 200:
        content = content[:180]
    return f"住宅仕様について、{content}詳細は展示場でご確認ください。"

def ensure_proper_ending(text: str) -> str:
    """適切な文末に調整（高速版）"""
    # 「〜しましょう」を確実に除去
    import re
    text = re.sub(r'[^\s]*しましょう[。！？]*', '', text)
    text = re.sub(r'一緒に[^\s]*', '', text)
    
    if not text.endswith(('。', '！', '？')):
        if text.endswith('です') or text.endswith('ます'):
            text += '。'
        elif text.endswith('、'):
            text = text[:-1] + '。'
        else:
            text += '。'
    return text

def generate_quick_fallback(query: str) -> str:
    """高速フォールバック回答"""
    if "坪単価" in query:
        return "坪単価については、約70〜85万円/坪が目安です。詳細はお問い合わせください。"
    elif "仕様" in query:
        return "住宅仕様について詳しくご案内いたします。展示場でご確認ください。"
    else:
        return "お尋ねの件について、詳しくは直接お問い合わせください。"

def load_fast_vectorstore():
    """高速ベクトルストア読み込み"""
    try:
        index_path = os.path.join(LOCAL_VECTOR_DIR, f"{INDEX_NAME}.faiss")
        
        if not os.path.exists(index_path):
            logger.warning("Vectorstore not found, creating minimal one...")
            return create_minimal_vectorstore()
        
        embeddings = FastEmbedding()
        vectorstore = FAISS.load_local(
            LOCAL_VECTOR_DIR,
            embeddings,
            index_name=INDEX_NAME,
            allow_dangerous_deserialization=True
        )
        
        logger.info("✅ Fast vectorstore loaded")
        return vectorstore
        
    except Exception as e:
        logger.error(f"Fast vectorstore load error: {e}")
        return create_minimal_vectorstore()

def create_minimal_vectorstore():
    """最小限のベクトルストア作成"""
    embeddings = FastEmbedding()
    
    minimal_docs = [
        Document(
            page_content="キノエデザインの坪単価は約70〜85万円/坪です。仕様によって変動します。",
            metadata={"source": "price_info", "page": 1}
        ),
        Document(
            page_content="標準仕様は耐震等級3の長期優良住宅基準です。高品質な設備を標準装備しています。",
            metadata={"source": "spec_info", "page": 1}
        )
    ]
    
    vectorstore = FAISS.from_documents(minimal_docs, embeddings)
    
    os.makedirs(LOCAL_VECTOR_DIR, exist_ok=True)
    vectorstore.save_local(LOCAL_VECTOR_DIR, index_name=INDEX_NAME)
    
    logger.info("✅ Minimal vectorstore created")
    return vectorstore

def get_fast_rag_chain(vectorstore, return_source: bool = True):
    """LINE Bot用高速RAGチェーン"""
    logger.info("Creating fast RAG chain for LINE Bot...")
    
    try:
        from llm.llm_runner import load_llm
        llm, _, _ = load_llm()
        
        # 高速プロンプト（簡潔版）
        fast_prompt = """住宅の専門アドバイザーとして回答してください。

【重要】
- 150文字以内で簡潔に
- 「〜しましょう」は絶対に使わない
- 「です・ます」調で丁寧に
- 実用的な情報を含める

参考情報: {context}

質問: {question}

回答:"""
        
        prompt = PromptTemplate(
            input_variables=["context", "question"],
            template=fast_prompt
        )
        
        # 高速リトリーバー（検索件数を削減）
        retriever = vectorstore.as_retriever(search_kwargs={"k": 2})  # 3→2に削減
        
        rag_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=return_source,
            chain_type_kwargs={"prompt": prompt}
        )
        
        # 高速ラッパー
        class FastResponseChain:
            def __init__(self, base_chain):
                self.base_chain = base_chain
                self.callbacks = []
            
            def invoke(self, inputs):
                query = inputs.get("query", "")
                
                try:
                    # タイムアウト付きで実行
                    import signal
                    
                    def timeout_handler(signum, frame):
                        raise TimeoutError("RAG processing timeout")
                    
                    signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(10)  # 10秒でタイムアウト
                    
                    try:
                        result = self.base_chain.invoke(inputs)
                        raw_result = result.get("result", "")
                        
                        # 高速レスポンス生成
                        fast_result = create_fast_response(raw_result, query)
                        
                        result["result"] = fast_result
                        return result
                    finally:
                        signal.alarm(0)  # タイムアウト解除
                    
                except TimeoutError:
                    logger.warning(f"RAG timeout for query: {query}")
                    return {
                        "result": generate_quick_fallback(query),
                        "source_documents": []
                    }
                except Exception as e:
                    logger.error(f"Fast RAG error: {e}")
                    return {
                        "result": generate_quick_fallback(query),
                        "source_documents": []
                    }
            
            def __call__(self, inputs, callbacks=None):
                return self.invoke(inputs)
        
        logger.info("✅ Fast RAG chain created successfully")
        return FastResponseChain(rag_chain)
        
    except Exception as e:
        logger.error(f"Error creating fast RAG chain: {e}")
        return create_emergency_chain(vectorstore)

def create_emergency_chain(vectorstore):
    """緊急用超高速チェーン"""
    logger.info("Creating emergency fast chain...")
    
    class EmergencyChain:
        def __init__(self, vectorstore):
            self.vectorstore = vectorstore
            self.retriever = vectorstore.as_retriever(search_kwargs={"k": 1}) if vectorstore else None
            self.callbacks = []
        
        def invoke(self, inputs):
            query = inputs.get("query", "")
            
            try:
                if not self.retriever:
                    return {
                        "result": generate_quick_fallback(query),
                        "source_documents": []
                    }
                
                # 超高速検索
                docs = self.retriever.invoke(query)
                
                if docs:
                    content = docs[0].page_content[:200]  # 最初の200文字のみ
                    fast_result = create_fast_response(content, query)
                else:
                    fast_result = generate_quick_fallback(query)
                
                return {
                    "result": fast_result,
                    "source_documents": docs[:1]
                }
                
            except Exception as e:
                logger.error(f"Emergency chain error: {e}")
                return {
                    "result": "申し訳ございません。再度お試しください。",
                    "source_documents": []
                }
        
        def __call__(self, inputs, callbacks=None):
            return self.invoke(inputs)
    
    return EmergencyChain(vectorstore)

# キャッシュ機能（メモリベース）
_cache = {}

def get_cached_response(query: str):
    """キャッシュから高速回答取得"""
    return _cache.get(query)

def cache_response(query: str, response: str):
    """回答をキャッシュ（最大100件）"""
    if len(_cache) > 100:
        # 古いキャッシュを削除
        old_key = next(iter(_cache))
        del _cache[old_key]
    _cache[query] = response

if __name__ == "__main__":
    print("🚀 Fast RAG Chain Test")
    
    # 高速ヘルスチェック
    try:
        vectorstore = load_fast_vectorstore()
        print("✅ Fast vectorstore loaded")
        
        rag_chain = get_fast_rag_chain(vectorstore)
        print("✅ Fast RAG chain created")
        
        # 高速テスト
        test_query = "坪単価について教えて"
        response = rag_chain.invoke({"query": test_query})
        print(f"Query: {test_query}")
        print(f"Response: {response.get('result', 'No result')}")
        
    except Exception as e:
        print(f"❌ Fast RAG test error: {e}")