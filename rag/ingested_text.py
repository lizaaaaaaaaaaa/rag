import os
import logging
from pathlib import Path
from dotenv import load_dotenv

from langchain_community.document_loaders.pdf import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_core.embeddings import Embeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from sentence_transformers import SentenceTransformer

from llm.llm_runner import load_llm

# --- .env読み込み（ローカル用） ---
if Path(".env").exists():
    load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# --- OpenAI APIキー環境変数デバッグ＆未設定時エラーハンドリング ---
import openai
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY
    print("[DEBUG] rag/ingested_text.py: OPENAI_API_KEY =", OPENAI_API_KEY[:5], "****")
else:
    print("[ERROR] rag/ingested_text.py: OPENAI_API_KEYが未設定です！")
    # 必要に応じて強制停止（運用に慣れてきたらアンコメントで有効化）
    # raise RuntimeError("OPENAI_API_KEYが未設定のままです")

VECTOR_DIR = "rag/vectorstore"
INDEX_NAME = "index"

class MyEmbedding(Embeddings):
    def __init__(self, model_name: str):
        self.model = SentenceTransformer(model_name)

    def embed_documents(self, texts):
        return self.model.encode(texts, show_progress_bar=True).tolist()

    def embed_query(self, text):
        return self.model.encode(text).tolist()

def ingest_pdf_to_vectorstore(pdf_path: str):
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
    documents = splitter.split_documents(docs)
    embeddings = MyEmbedding("intfloat/multilingual-e5-small")

    index_path = os.path.join(VECTOR_DIR, f"{INDEX_NAME}.faiss")
    if os.path.exists(index_path):
        vectorstore = FAISS.load_local(
            VECTOR_DIR, embeddings, index_name=INDEX_NAME, allow_dangerous_deserialization=True
        )
        vectorstore.add_documents(documents)
    else:
        vectorstore = FAISS.from_documents(documents, embeddings)

    vectorstore.save_local(VECTOR_DIR, index_name=INDEX_NAME)
    logger.info("✅ %s をベクトルストアに追加保存しました", os.path.basename(pdf_path))

def load_vectorstore():
    embeddings = MyEmbedding("intfloat/multilingual-e5-small")
    index_path = os.path.join(VECTOR_DIR, f"{INDEX_NAME}.faiss")
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"ベクトルストア（{index_path}）が存在しません。PDF取り込みしてください。")
    return FAISS.load_local(
        VECTOR_DIR, embeddings, index_name=INDEX_NAME, allow_dangerous_deserialization=True
    )

def get_rag_chain(vectorstore, return_source: bool = True, question: str = ""):
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
