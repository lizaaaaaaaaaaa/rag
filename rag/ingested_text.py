import os
import logging
import sys
from pathlib import Path

from google.cloud import storage
from langchain_community.document_loaders.pdf import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_core.embeddings import Embeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from sentence_transformers import SentenceTransformer

from llm.llm_runner import load_llm

# 環境変数から GCS バケット名を取得
GCS_BUCKET = os.environ.get("GCS_BUCKET_NAME", "")
# バケット内のディレクトリ（プレフィックス）を固定
GCS_VEC_DIR = "vectorstore"  # バケット直下に "vectorstore/index.faiss" を置く

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ローカルでの一時ベクトルストアフォルダ（コンテナ内のパス）
LOCAL_VECTOR_DIR = "rag/vectorstore"
INDEX_NAME = "index"


def _get_gcs_client():
    """
    GCS クライアントを返すヘルパー。
    Cloud Run 上やローカル .env から
    GOOGLE_APPLICATION_CREDENTIALS が効いていれば、このままで OK。
    """
    return storage.Client()


def upload_vectorstore_to_gcs(local_dir: str):
    """
    local_dir 配下に生成された index.faiss / index.pkl を
    → GCS_BUCKET/vectorstore/index.faiss / index.pkl にアップロードする。
    """
    if not GCS_BUCKET:
        logger.error("GCS_BUCKET_NAME が環境変数に設定されていません。アップロードをスキップします。")
        return

    client = _get_gcs_client()
    bucket = client.bucket(GCS_BUCKET)

    # ベクトルストアを構成するファイル名リスト
    for fname in (f"{INDEX_NAME}.faiss", f"{INDEX_NAME}.pkl"):
        local_path = os.path.join(local_dir, fname)
        if os.path.exists(local_path):
            blob_path = f"{GCS_VEC_DIR}/{fname}"
            blob = bucket.blob(blob_path)
            blob.upload_from_filename(local_path)
            logger.info(f"✅ GCS にアップロード完了: gs://{GCS_BUCKET}/{blob_path}")
        else:
            # *.pkl は存在しないケースもあるのでエラーではなく inform
            logger.debug(f"ローカルに {local_path} が存在しません。スキップします。")


def download_vectorstore_from_gcs(local_dir: str):
    """
    GCS_BUCKET/vectorstore/index.faiss, index.pkl を
    → local_dir 配下にダウンロードする。
    存在しなければ何もしない。（次に load_vectorstore() で例外が発生するように）
    """
    if not GCS_BUCKET:
        logger.error("GCS_BUCKET_NAME が環境変数に設定されていません。ダウンロードをスキップします。")
        return

    client = _get_gcs_client()
    bucket = client.bucket(GCS_BUCKET)

    os.makedirs(local_dir, exist_ok=True)

    for fname in (f"{INDEX_NAME}.faiss", f"{INDEX_NAME}.pkl"):
        blob_path = f"{GCS_VEC_DIR}/{fname}"
        blob = bucket.blob(blob_path)
        local_path = os.path.join(local_dir, fname)

        if blob.exists():
            blob.download_to_filename(local_path)
            logger.info(f"✅ GCS からダウンロード完了: {blob_path} → {local_path}")
        else:
            logger.debug(f"GCS に {blob_path} が存在しません。ダウンロードをスキップします。")


def get_openai_api_key():
    """
    もともとの get_openai_api_key() ログ出力はそのまま。
    """
    print("=== get_openai_api_keyが呼ばれた ===", os.getenv("OPENAI_API_KEY"))
    sys.stdout.flush()
    logger.warning("=== get_openai_api_keyが呼ばれた === %s", os.getenv("OPENAI_API_KEY"))

    key_env = os.environ.get("OPENAI_API_KEY")
    print("[DEBUG] get_openai_api_key: os.environ.get('OPENAI_API_KEY') =", key_env)
    sys.stdout.flush()
    logger.warning(f"[DEBUG] get_openai_api_key: os.environ.get('OPENAI_API_KEY') = {key_env}")

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("[ERROR] rag/ingested_text.py: OPENAI_API_KEYが未設定です！")
        sys.stdout.flush()  
        logger.error("[ERROR] rag/ingested_text.py: OPENAI_API_KEYが未設定です！")
    else:
        print("[DEBUG] rag/ingested_text.py: OPENAI_API_KEY =", key[:5], "****")
        sys.stdout.flush()
        logger.info(f"[DEBUG] rag/ingested_text.py: OPENAI_API_KEY = {key[:5]} ****")
    return key


class MyEmbedding(Embeddings):
    def __init__(self, model_name: str):
        self.model = SentenceTransformer(model_name)

    def embed_documents(self, texts):
        return self.model.encode(texts, show_progress_bar=True).tolist()

    def embed_query(self, text):
        return self.model.encode(text).tolist()


def ingest_pdf_to_vectorstore(pdf_path: str):
    """
    1) PDF をローカルでベクトル化して FAISS を作成：
       → 'rag/vectorstore/index.faiss' & 'index.pkl' が生成される。
    2) ローカル配下のファイルを GCS にアップロード。
    """
    # ── PDF読み込み→ドキュメント分割
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
    documents = splitter.split_documents(docs)

    # ── 埋め込みモデル
    embeddings = MyEmbedding("intfloat/multilingual-e5-small")

    # ── ローカルの vectorstore ディレクトリを作成／確認
    os.makedirs(LOCAL_VECTOR_DIR, exist_ok=True)
    index_path = os.path.join(LOCAL_VECTOR_DIR, f"{INDEX_NAME}.faiss")

    if os.path.exists(index_path):
        # 既存インデックスがあれば読み込んで追加
        # allow_dangerous_deserializationを明示的にTrueに設定
        vectorstore = FAISS.load_local(
            LOCAL_VECTOR_DIR, embeddings,
            index_name=INDEX_NAME,
            allow_dangerous_deserialization=True
        )
        vectorstore.add_documents(documents)
    else:
        # 新規作成
        vectorstore = FAISS.from_documents(documents, embeddings)

    # ── 保存（ローカルに index.faiss & index.pkl が生成される）
    vectorstore.save_local(LOCAL_VECTOR_DIR, index_name=INDEX_NAME)
    logger.info("✅ %s をベクトルストアに追加保存しました", os.path.basename(pdf_path))

    # ── ローカルにできたインデックスを GCS へアップロード
    try:
        upload_vectorstore_to_gcs(LOCAL_VECTOR_DIR)
    except Exception as e:
        logger.error("❌ GCS へのアップロード中に例外: %s", e)
        # 失敗しても処理を止めずにローカルのままにしておく

    # 追加したドキュメント数を返す
    return len(documents)


def load_vectorstore():
    """
    1) まず GCS から最新のインデックスをローカルにダウンロード（存在すれば）。
    2) ローカルに index.faiss がなければ例外を投げる。
    3) FAISS.load_local(... ) して VectorStore を返す。
    """
    # ── 最新インデックスを GCS からダウンロード
    try:
        download_vectorstore_from_gcs(LOCAL_VECTOR_DIR)
    except Exception as e:
        logger.error("❌ GCS からのダウンロード中に例外: %s", e)
        # ここで止めずに続行し、ローカルの有無に任せる

    # ── 存在チェック
    index_path = os.path.join(LOCAL_VECTOR_DIR, f"{INDEX_NAME}.faiss")
    if not os.path.exists(index_path):
        # 初回起動時はベクトルストアが存在しないので、空のベクトルストアを作成
        logger.warning("ベクトルストアが見つかりません。空のベクトルストアを作成します。")
        embeddings = MyEmbedding("intfloat/multilingual-e5-small")
        from langchain.schema import Document
        dummy_doc = Document(page_content="初期化用ダミーテキスト", metadata={"source": "init", "page": 0})
        vectorstore = FAISS.from_documents([dummy_doc], embeddings)
        vectorstore.save_local(LOCAL_VECTOR_DIR, index_name=INDEX_NAME)
        # GCSにもアップロード
        try:
            upload_vectorstore_to_gcs(LOCAL_VECTOR_DIR)
        except Exception as e:
            logger.error("初期ベクトルストアのGCSアップロードに失敗: %s", e)
        return vectorstore

    # ── Embeddings を再構築
    embeddings = MyEmbedding("intfloat/multilingual-e5-small")
    # allow_dangerous_deserializationを明示的にTrueに設定（重要！）
    return FAISS.load_local(
        LOCAL_VECTOR_DIR, embeddings,
        index_name=INDEX_NAME,
        allow_dangerous_deserialization=True
    )


def get_rag_chain(vectorstore, return_source: bool = True, question: str = ""):
    """
    RAG チェーンを作成して返す。もともとの実装をそのまま使う。
    """
    print("=== get_rag_chainが呼ばれた ===")
    sys.stdout.flush()
    logger.warning("=== get_rag_chainが呼ばれた ===")

    try:
        import openai
        openai.api_key = get_openai_api_key()
    except Exception as e:
        print("!!! get_rag_chain内で例外:", e)
        sys.stdout.flush()
        logger.error("get_rag_chain内で例外: %s", e)
        raise

    llm, tokenizer, max_tokens = load_llm()
    logger.info("🔍 get_rag_chain - preset LLM = %s", type(llm).__name__)

    try:
        with open("rag/prompt_template.txt", encoding="utf-8") as f:
            prompt_str = f.read()
    except Exception:
        prompt_str = """\
{context}

質問: {question}
AIとして分かりやすく答えてください。
"""

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