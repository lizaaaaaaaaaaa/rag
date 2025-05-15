import os
import logging
from functools import lru_cache

from dotenv import load_dotenv
from langchain_community.document_loaders.pdf import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_openai import ChatOpenAI
from langchain_community.llms import HuggingFacePipeline
from langchain_core.embeddings import Embeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from sentence_transformers import SentenceTransformer
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    GPTNeoXTokenizer,
    pipeline,
)

# ✅ ローカル用 .env 読み込み（Cloud Runでは不要）
if os.path.exists(".env"):
    load_dotenv()

# ✅ ロギング初期化
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ✅ OpenAI APIキーの安全設定
import openai
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

USE_LOCAL_LLM = os.getenv("USE_LOCAL_LLM", "true").lower() == "true"
logger.info("✅ USE_LOCAL_LLM = %s", USE_LOCAL_LLM)

VECTOR_DIR = "rag/vectorstore"
INDEX_NAME = "index"

class MyEmbedding(Embeddings):
    def __init__(self, model_name):
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
    return FAISS.load_local(
        VECTOR_DIR, embeddings, index_name=INDEX_NAME, allow_dangerous_deserialization=True
    )

_local_llm = None

def load_local_llm():
    global _local_llm
    if _local_llm is not None:
        return _local_llm

    logger.info("🧠 Loading local LLM...")

    model_id = "rinna/japanese-gpt-neox-3.6b-instruction-ppo"
    cache_dir = "/tmp/huggingface"

    tokenizer = AutoTokenizer.from_pretrained(
        model_id,
        trust_remote_code=True,
        use_fast=False,
        cache_dir=cache_dir,
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype="auto",
        device_map="auto",
        trust_remote_code=True,
        cache_dir=cache_dir,
    )

    pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=512,
        temperature=0.7,
        top_p=0.95,
        repetition_penalty=1.1,
    )

    _local_llm = HuggingFacePipeline(pipeline=pipe)
    return _local_llm

def choose_llm_by_question(question: str):
    summary_keywords = ["要約", "まとめ", "なぜ", "理由", "背景", "仕組み", "ポイント", "問題点", "改善"]
    return "openai" if any(kw in question for kw in summary_keywords) else "local"

def get_rag_chain(vectorstore, return_source=True, question=""):
    logger.info("🔍 get_rag_chain - USE_LOCAL_LLM = %s", USE_LOCAL_LLM)

    if not USE_LOCAL_LLM:
        logger.info("🧠 OpenAI LLM selected")
        llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0)
        return RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=vectorstore.as_retriever(),
            return_source_documents=return_source,
        )

    logger.info("🧠 Local LLM selected")
    llm = load_local_llm()
    with open("rag/prompt_template.txt", encoding="utf-8") as f:
        prompt_str = f.read()

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
