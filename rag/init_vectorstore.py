import os
import sys
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
import time

# 基本的なインポート
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document

# ベクトルストア関連
try:
    from langchain_community.vectorstores import FAISS
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    logging.warning("FAISS not available")

# PDF loader
try:
    from langchain_community.document_loaders import PyPDFLoader
    PDF_LOADER_AVAILABLE = True
except ImportError:
    PDF_LOADER_AVAILABLE = False
    logging.warning("PyPDFLoader not available")

# Embeddings
try:
    from sentence_transformers import SentenceTransformer
    from langchain_core.embeddings import Embeddings
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    logging.warning("Embeddings not available")

# GCS設定
try:
    from google.cloud import storage
    GCS_BUCKET = os.environ.get("GCS_BUCKET_NAME", "")
    GCS_VEC_DIR = "vectorstore"
    HAS_GCS = bool(GCS_BUCKET)
except ImportError:
    HAS_GCS = False
    GCS_BUCKET = ""

# 設定
VECTOR_DIR = "rag/vectorstore"
INDEX_NAME = "index"
USE_LOCAL_LLM = os.environ.get("USE_LOCAL_LLM", "false").lower() == "true"  # デフォルトFalse

logger = logging.getLogger(__name__)


class OptimizedEmbedding(Embeddings):
    """最適化版Embeddingクラス（高速・軽量）"""
    
    def __init__(self, model_name: str = None):
        if not EMBEDDINGS_AVAILABLE:
            raise ImportError("SentenceTransformer not available")
        
        # 軽量モデルを優先
        if model_name is None:
            model_name = os.environ.get(
                "EMBEDDING_MODEL",
                "intfloat/multilingual-e5-small"  # 軽量で高速
            )
        
        logger.info(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)
        self.model.max_seq_length = 256  # シーケンス長を制限（高速化）
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """ドキュメントの埋め込み（バッチ処理）"""
        # バッチサイズを調整（メモリと速度のバランス）
        batch_size = int(os.environ.get("EMBEDDING_BATCH_SIZE", "32"))
        
        # テキストの前処理（長さ制限）
        processed_texts = [self._truncate_text(text) for text in texts]
        
        # バッチ処理で埋め込み
        embeddings = self.model.encode(
            processed_texts,
            batch_size=batch_size,
            show_progress_bar=len(texts) > 100,  # 大量の場合のみプログレスバー表示
            convert_to_numpy=True
        )
        
        return embeddings.tolist()
    
    def embed_query(self, text: str) -> List[float]:
        """クエリの埋め込み（単一）"""
        processed_text = self._truncate_text(text)
        embedding = self.model.encode(
            processed_text,
            convert_to_numpy=True
        )
        return embedding.tolist()
    
    def _truncate_text(self, text: str, max_length: int = 256) -> str:
        """テキストを最大長に切り詰め"""
        if len(text) <= max_length:
            return text
        return text[:max_length-3] + "..."


class OptimizedVectorStoreManager:
    """最適化版ベクトルストア管理クラス"""
    
    def __init__(self):
        self.vector_dir = VECTOR_DIR
        self.index_name = INDEX_NAME
        self.embeddings = None
        self.vectorstore = None
        self._init_count = 0
        
    def get_embeddings(self) -> OptimizedEmbedding:
        """埋め込みモデルの取得（遅延ロード）"""
        if self.embeddings is None:
            self.embeddings = OptimizedEmbedding()
        return self.embeddings
    
    def upload_to_gcs(self, local_dir: str) -> bool:
        """ベクトルストアをGCSにアップロード"""
        if not HAS_GCS:
            logger.debug("GCS not configured, skipping upload")
            return False
        
        try:
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET)
            
            uploaded_files = []
            for fname in (f"{self.index_name}.faiss", f"{self.index_name}.pkl"):
                local_path = os.path.join(local_dir, fname)
                if os.path.exists(local_path):
                    blob_path = f"{GCS_VEC_DIR}/{fname}"
                    blob = bucket.blob(blob_path)
                    blob.upload_from_filename(local_path)
                    uploaded_files.append(blob_path)
                    logger.info(f"✅ Uploaded to GCS: gs://{GCS_BUCKET}/{blob_path}")
            
            return len(uploaded_files) > 0
            
        except Exception as e:
            logger.error(f"GCS upload error: {e}")
            return False
    
    def download_from_gcs(self, local_dir: str) -> bool:
        """GCSからベクトルストアをダウンロード"""
        if not HAS_GCS:
            return False
        
        try:
            client = storage.Client()
            bucket = client.bucket(GCS_BUCKET)
            os.makedirs(local_dir, exist_ok=True)
            
            downloaded_files = []
            for fname in (f"{self.index_name}.faiss", f"{self.index_name}.pkl"):
                blob_path = f"{GCS_VEC_DIR}/{fname}"
                blob = bucket.blob(blob_path)
                local_path = os.path.join(local_dir, fname)
                
                if blob.exists():
                    blob.download_to_filename(local_path)
                    downloaded_files.append(fname)
                    logger.info(f"✅ Downloaded from GCS: {blob_path}")
            
            return len(downloaded_files) == 2  # 両方のファイルが必要
            
        except Exception as e:
            logger.error(f"GCS download error: {e}")
            return False
    
    def create_initial_vectorstore(self) -> Optional[FAISS]:
        """初期ベクトルストアを作成（最小限）"""
        if not FAISS_AVAILABLE:
            logger.error("FAISS not available")
            return None
        
        logger.info("Creating initial vectorstore...")
        
        # ディレクトリ作成
        os.makedirs(self.vector_dir, exist_ok=True)
        
        # 埋め込みモデル
        embeddings = self.get_embeddings()
        
        # 最小限のダミードキュメント
        dummy_docs = [
            Document(
                page_content="システム初期化完了",
                metadata={"source": "system", "type": "init"}
            )
        ]
        
        # ベクトルストア作成
        vectorstore = FAISS.from_documents(dummy_docs, embeddings)
        vectorstore.save_local(self.vector_dir, index_name=self.index_name)
        
        logger.info("✅ Initial vectorstore created")
        
        # GCSにアップロード（非同期的に）
        self.upload_to_gcs(self.vector_dir)
        
        return vectorstore
    
    def ingest_pdf_to_vectorstore(self, pdf_path: str) -> int:
        """PDFをベクトルストアに追加（最適化版）"""
        if not PDF_LOADER_AVAILABLE:
            logger.error("PyPDFLoader not available")
            return 0
        
        start_time = time.time()
        
        # PDF読み込み
        loader = PyPDFLoader(pdf_path)
        docs = loader.load()
        
        # テキスト分割（チャンクサイズを小さく）
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=300,  # 削減: 500→300
            chunk_overlap=50,  # 削減: 100→50
            length_function=len,
            separators=["\n\n", "\n", "。", "、", " ", ""]
        )
        documents = splitter.split_documents(docs)
        
        # 埋め込みモデル
        embeddings = self.get_embeddings()
        
        # ベクトルストアのパス
        index_path = os.path.join(self.vector_dir, f"{self.index_name}.faiss")
        
        if os.path.exists(index_path):
            # 既存のベクトルストアに追加
            vectorstore = FAISS.load_local(
                self.vector_dir, 
                embeddings,
                index_name=self.index_name,
                allow_dangerous_deserialization=True
            )
            vectorstore.add_documents(documents)
        else:
            # 新規作成
            vectorstore = FAISS.from_documents(documents, embeddings)
        
        # 保存
        vectorstore.save_local(self.vector_dir, index_name=self.index_name)
        
        elapsed_time = time.time() - start_time
        logger.info(f"✅ Ingested {len(documents)} chunks from {os.path.basename(pdf_path)} in {elapsed_time:.2f}s")
        
        # GCSにアップロード（バックグラウンド）
        self.upload_to_gcs(self.vector_dir)
        
        return len(documents)
    
    def load_vectorstore(self, force_download: bool = False) -> Optional[FAISS]:
        """ベクトルストアを読み込み（キャッシュ付き）"""
        if not FAISS_AVAILABLE:
            logger.error("FAISS not available")
            return None
        
        # キャッシュチェック
        if self.vectorstore is not None and not force_download:
            return self.vectorstore
        
        # GCSからダウンロード試行
        if HAS_GCS and (force_download or not os.path.exists(os.path.join(self.vector_dir, f"{self.index_name}.faiss"))):
            logger.info("Attempting to download vectorstore from GCS...")
            self.download_from_gcs(self.vector_dir)
        
        index_path = os.path.join(self.vector_dir, f"{self.index_name}.faiss")
        
        if not os.path.exists(index_path):
            logger.warning("Vectorstore not found. Creating initial store...")
            self.vectorstore = self.create_initial_vectorstore()
            return self.vectorstore
        
        # 埋め込みモデル
        embeddings = self.get_embeddings()
        
        # ベクトルストア読み込み
        try:
            self.vectorstore = FAISS.load_local(
                self.vector_dir,
                embeddings,
                index_name=self.index_name,
                allow_dangerous_deserialization=True
            )
            logger.info("✅ Vectorstore loaded successfully")
            return self.vectorstore
            
        except Exception as e:
            logger.error(f"Failed to load vectorstore: {e}")
            logger.info("Creating new vectorstore...")
            self.vectorstore = self.create_initial_vectorstore()
            return self.vectorstore
    
    def get_rag_chain(self, vectorstore=None, return_source: bool = True):
        """RAGチェーンを生成（OpenAI優先）"""
        if vectorstore is None:
            vectorstore = self.load_vectorstore()
            if vectorstore is None:
                raise ValueError("Failed to load vectorstore")
        
        # 環境変数チェック
        openai_api_key = os.environ.get("OPENAI_API_KEY")
        
        # OpenAI APIを優先（USE_LOCAL_LLM=falseがデフォルト）
        if not USE_LOCAL_LLM and openai_api_key:
            logger.info("🚀 Using OpenAI API (fast mode)")
            try:
                from langchain_openai import ChatOpenAI
                llm = ChatOpenAI(
                    model_name="gpt-3.5-turbo-0125",
                    temperature=0,
                    openai_api_key=openai_api_key,
                    max_tokens=500,  # 制限
                    request_timeout=10  # タイムアウト
                )
            except ImportError:
                logger.error("langchain_openai not available")
                return None
        else:
            # ローカルLLMは使用しない（速度優先）
            logger.warning("OpenAI API key not found and USE_LOCAL_LLM=false")
            return None
        
        # プロンプトテンプレート（簡潔版）
        from langchain.prompts import PromptTemplate
        
        prompt_str = """以下の情報を基に質問に答えてください。

{context}

質問: {question}
回答:"""
        
        prompt = PromptTemplate(
            input_variables=["context", "question"],
            template=prompt_str
        )
        
        # RAGチェーン作成
        from langchain.chains import RetrievalQA
        
        return RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=vectorstore.as_retriever(
                search_kwargs={"k": 3}  # 検索数を制限
            ),
            return_source_documents=return_source,
            chain_type_kwargs={"prompt": prompt}
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """統計情報取得"""
        index_path = os.path.join(self.vector_dir, f"{self.index_name}.faiss")
        
        stats = {
            "vectorstore_exists": os.path.exists(index_path),
            "vectorstore_size": 0,
            "gcs_enabled": HAS_GCS,
            "use_local_llm": USE_LOCAL_LLM,
            "embeddings_loaded": self.embeddings is not None,
            "vectorstore_cached": self.vectorstore is not None
        }
        
        if os.path.exists(index_path):
            stats["vectorstore_size"] = os.path.getsize(index_path)
        
        return stats


# グローバルインスタンス
_global_manager = None

def get_vectorstore_manager() -> OptimizedVectorStoreManager:
    """グローバルマネージャー取得"""
    global _global_manager
    if _global_manager is None:
        _global_manager = OptimizedVectorStoreManager()
    return _global_manager

# 簡易関数（後方互換性）
def load_vectorstore():
    """ベクトルストア読み込み"""
    manager = get_vectorstore_manager()
    return manager.load_vectorstore()

def create_initial_vectorstore():
    """初期ベクトルストア作成"""
    manager = get_vectorstore_manager()
    return manager.create_initial_vectorstore()

def ingest_pdf_to_vectorstore(pdf_path: str) -> int:
    """PDF追加"""
    manager = get_vectorstore_manager()
    return manager.ingest_pdf_to_vectorstore(pdf_path)

def get_rag_chain(vectorstore=None, return_source=True):
    """RAGチェーン取得"""
    manager = get_vectorstore_manager()
    return manager.get_rag_chain(vectorstore, return_source)

def upload_to_gcs(local_dir: str):
    """GCSアップロード"""
    manager = get_vectorstore_manager()
    return manager.upload_to_gcs(local_dir)

def download_from_gcs(local_dir: str):
    """GCSダウンロード"""
    manager = get_vectorstore_manager()
    return manager.download_from_gcs(local_dir)


# メイン実行部分
if __name__ == "__main__":
    import argparse
    
    # ロギング設定
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    parser = argparse.ArgumentParser(description="最適化版ベクトルストア管理ツール")
    parser.add_argument("--init", action="store_true", help="初期ベクトルストアを作成")
    parser.add_argument("--pdf", type=str, help="PDFファイルを追加")
    parser.add_argument("--test", action="store_true", help="動作テスト")
    parser.add_argument("--stats", action="store_true", help="統計情報表示")
    parser.add_argument("--download", action="store_true", help="GCSからダウンロード")
    parser.add_argument("--upload", action="store_true", help="GCSにアップロード")
    
    args = parser.parse_args()
    
    manager = get_vectorstore_manager()
    
    if args.init:
        # 初期化
        vectorstore = manager.create_initial_vectorstore()
        if vectorstore:
            print("✅ 初期ベクトルストア作成完了")
        else:
            print("❌ 初期化失敗")
            
    elif args.pdf:
        # PDF追加
        if os.path.exists(args.pdf):
            count = manager.ingest_pdf_to_vectorstore(args.pdf)
            print(f"✅ {count} チャンクを追加しました")
        else:
            print(f"❌ ファイルが見つかりません: {args.pdf}")
            
    elif args.test:
        # テスト
        try:
            vectorstore = manager.load_vectorstore()
            if vectorstore:
                print("✅ ベクトルストア読み込み成功")
                
                # 検索テスト
                results = vectorstore.similarity_search("システム", k=1)
                if results:
                    print(f"📝 検索結果: {results[0].page_content[:100]}...")
                else:
                    print("⚠️ 検索結果なし")
            else:
                print("❌ ベクトルストア読み込み失敗")
                
        except Exception as e:
            print(f"❌ テストエラー: {e}")
            
    elif args.stats:
        # 統計情報
        stats = manager.get_stats()
        print("📊 ベクトルストア統計:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
            
    elif args.download:
        # GCSダウンロード
        if manager.download_from_gcs(VECTOR_DIR):
            print("✅ GCSからダウンロード完了")
        else:
            print("❌ GCSダウンロード失敗")
            
    elif args.upload:
        # GCSアップロード
        if manager.upload_to_gcs(VECTOR_DIR):
            print("✅ GCSにアップロード完了")
        else:
            print("❌ GCSアップロード失敗")
            
    else:
        # デフォルト: ステータス確認
        stats = manager.get_stats()
        if stats["vectorstore_exists"]:
            print(f"✅ ベクトルストア存在 (サイズ: {stats['vectorstore_size']} bytes)")
        else:
            print("⚠️ ベクトルストアが存在しません")
            print("初期化するには: python init_vectorstore.py --init")
