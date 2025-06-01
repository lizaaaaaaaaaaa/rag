import os
import sys
from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.chains import RetrievalQA
from langchain_community.llms import HuggingFacePipeline
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
from langchain.schema import Document
from sentence_transformers import SentenceTransformer
from langchain_core.embeddings import Embeddings

# GCS設定
try:
    from google.cloud import storage
    GCS_BUCKET = os.environ.get("GCS_BUCKET_NAME", "")
    GCS_VEC_DIR = "vectorstore"
    HAS_GCS = bool(GCS_BUCKET)
except ImportError:
    HAS_GCS = False
    GCS_BUCKET = ""

VECTOR_DIR = "rag/vectorstore"
INDEX_NAME = "index"


class MyEmbedding(Embeddings):
    """ingested_text.pyと同じEmbeddingクラスを使用"""
    def __init__(self, model_name: str):
        self.model = SentenceTransformer(model_name)

    def embed_documents(self, texts):
        return self.model.encode(texts, show_progress_bar=True).tolist()

    def embed_query(self, text):
        return self.model.encode(text).tolist()


def upload_to_gcs(local_dir: str):
    """ベクトルストアをGCSにアップロード"""
    if not HAS_GCS:
        print("GCS設定がないためスキップします")
        return
    
    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        
        for fname in (f"{INDEX_NAME}.faiss", f"{INDEX_NAME}.pkl"):
            local_path = os.path.join(local_dir, fname)
            if os.path.exists(local_path):
                blob_path = f"{GCS_VEC_DIR}/{fname}"
                blob = bucket.blob(blob_path)
                blob.upload_from_filename(local_path)
                print(f"✅ GCSアップロード完了: gs://{GCS_BUCKET}/{blob_path}")
    except Exception as e:
        print(f"⚠️ GCSアップロードエラー: {e}")


def download_from_gcs(local_dir: str):
    """GCSからベクトルストアをダウンロード"""
    if not HAS_GCS:
        return False
    
    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        os.makedirs(local_dir, exist_ok=True)
        
        downloaded = False
        for fname in (f"{INDEX_NAME}.faiss", f"{INDEX_NAME}.pkl"):
            blob_path = f"{GCS_VEC_DIR}/{fname}"
            blob = bucket.blob(blob_path)
            local_path = os.path.join(local_dir, fname)
            
            if blob.exists():
                blob.download_to_filename(local_path)
                print(f"✅ GCSダウンロード完了: {blob_path}")
                downloaded = True
        return downloaded
    except Exception as e:
        print(f"⚠️ GCSダウンロードエラー: {e}")
        return False


def create_initial_vectorstore():
    """初期ベクトルストアを作成"""
    print("🔧 初期ベクトルストアを作成中...")
    
    # ディレクトリ作成
    os.makedirs(VECTOR_DIR, exist_ok=True)
    
    # 埋め込みモデル（ingested_text.pyと同じものを使用）
    embeddings = MyEmbedding("intfloat/multilingual-e5-small")
    
    # ダミードキュメント
    dummy_docs = [
        Document(
            page_content="このシステムはRAG（Retrieval-Augmented Generation）を使用して、アップロードされたPDFドキュメントから関連情報を検索し、質問に回答します。",
            metadata={"source": "system_init.pdf", "page": 1}
        ),
        Document(
            page_content="PDFファイルをアップロードすることで、その内容がベクトルデータベースに保存され、質問応答に活用されます。",
            metadata={"source": "system_init.pdf", "page": 2}
        ),
    ]
    
    # ベクトルストア作成
    vectorstore = FAISS.from_documents(dummy_docs, embeddings)
    vectorstore.save_local(VECTOR_DIR, index_name=INDEX_NAME)
    
    print("✅ 初期ベクトルストアを作成しました")
    
    # GCSにアップロード
    upload_to_gcs(VECTOR_DIR)
    
    return vectorstore


# 🔹 PDF読み込み→ベクトルストア登録
def ingest_pdf_to_vectorstore(pdf_path: str):
    """PDFをベクトルストアに追加"""
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
    documents = splitter.split_documents(docs)

    # MyEmbeddingを使用（ingested_text.pyと統一）
    embeddings = MyEmbedding("intfloat/multilingual-e5-small")

    # ベクトルストアのパス
    index_path = os.path.join(VECTOR_DIR, f"{INDEX_NAME}.faiss")
    
    if os.path.exists(index_path):
        # 既存のベクトルストアに追加
        vectorstore = FAISS.load_local(
            VECTOR_DIR, embeddings, 
            index_name=INDEX_NAME, 
            allow_dangerous_deserialization=True
        )
        vectorstore.add_documents(documents)
    else:
        # 新規作成
        vectorstore = FAISS.from_documents(documents, embeddings)

    # 保存
    vectorstore.save_local(VECTOR_DIR, index_name=INDEX_NAME)
    print(f"✅ {os.path.basename(pdf_path)} をベクトルストアに保存しました")
    
    # GCSにアップロード
    upload_to_gcs(VECTOR_DIR)
    
    return len(documents)


# 🔹 ベクトルストア読み込み
def load_vectorstore():
    """ベクトルストアを読み込み（なければ作成）"""
    # まずGCSからダウンロードを試みる
    if HAS_GCS:
        download_from_gcs(VECTOR_DIR)
    
    index_path = os.path.join(VECTOR_DIR, f"{INDEX_NAME}.faiss")
    
    if not os.path.exists(index_path):
        print("⚠️ ベクトルストアが見つかりません。初期化します...")
        return create_initial_vectorstore()
    
    # MyEmbeddingを使用
    embeddings = MyEmbedding("intfloat/multilingual-e5-small")
    return FAISS.load_local(
        VECTOR_DIR, embeddings, 
        index_name=INDEX_NAME, 
        allow_dangerous_deserialization=True
    )


# 🔹 RAGチェーン生成
def get_rag_chain(vectorstore, return_source=True):
    """RAGチェーンを生成（OpenAI APIを使用するように修正）"""
    # 環境変数チェック
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    use_local = os.environ.get("USE_LOCAL_LLM", "false").lower() == "true"
    
    if use_local or not openai_api_key:
        # ローカルモデル（Rinna）を使用
        print("🤖 ローカルLLM（Rinna）を使用します...")
        model_id = "rinna/japanese-gpt-neox-3.6b-instruction-ppo"
        
        tokenizer = AutoTokenizer.from_pretrained(
            model_id,
            use_fast=False,
            trust_remote_code=True
        )
        print("✅ Tokenizer loaded:", tokenizer.__class__)
        
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            trust_remote_code=True
        )
        
        pipe = pipeline("text-generation", model=model, tokenizer=tokenizer, max_new_tokens=512)
        llm = HuggingFacePipeline(pipeline=pipe)
    else:
        # OpenAI APIを使用
        print("🤖 OpenAI APIを使用します...")
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model_name="gpt-3.5-turbo-0125",
            temperature=0,
            openai_api_key=openai_api_key
        )
    
    # プロンプトテンプレート
    from langchain.prompts import PromptTemplate
    try:
        with open("rag/prompt_template.txt", encoding="utf-8") as f:
            prompt_str = f.read()
    except:
        prompt_str = """{context}

質問: {question}
AIとして分かりやすく答えてください。"""
    
    prompt = PromptTemplate(
        input_variables=["context", "question"],
        template=prompt_str
    )
    
    return RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=vectorstore.as_retriever(),
        return_source_documents=return_source,
        chain_type_kwargs={"prompt": prompt}
    )


# メイン実行部分（初期化スクリプトとして実行する場合）
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="ベクトルストア初期化・管理ツール")
    parser.add_argument("--init", action="store_true", help="初期ベクトルストアを作成")
    parser.add_argument("--pdf", type=str, help="PDFファイルを追加")
    parser.add_argument("--test", action="store_true", help="ベクトルストアの動作テスト")
    
    args = parser.parse_args()
    
    if args.init:
        # 初期化
        create_initial_vectorstore()
    elif args.pdf:
        # PDF追加
        if os.path.exists(args.pdf):
            ingest_pdf_to_vectorstore(args.pdf)
        else:
            print(f"❌ ファイルが見つかりません: {args.pdf}")
    elif args.test:
        # テスト
        try:
            vectorstore = load_vectorstore()
            print("✅ ベクトルストアの読み込み成功")
            
            # 簡単な検索テスト
            results = vectorstore.similarity_search("システム", k=1)
            if results:
                print(f"📝 検索結果: {results[0].page_content[:100]}...")
            else:
                print("⚠️ 検索結果なし")
        except Exception as e:
            print(f"❌ エラー: {e}")
    else:
        # デフォルト: 初期化チェック
        if not os.path.exists(os.path.join(VECTOR_DIR, f"{INDEX_NAME}.faiss")):
            print("ベクトルストアが存在しません。初期化します...")
            create_initial_vectorstore()
        else:
            print("✅ ベクトルストアは既に存在します")