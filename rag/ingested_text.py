import os
import streamlit as st
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA

# OpenAIとローカルモデル両方対応
from langchain.chat_models import ChatOpenAI
from transformers import GPTNeoXTokenizerFast, AutoModelForCausalLM, pipeline
from langchain_community.llms import HuggingFacePipeline

# .env 読み込み
load_dotenv()
USE_LOCAL_LLM = os.getenv("USE_LOCAL_LLM", "false").lower() == "true"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

VECTOR_DIR = "rag/vectorstore"
INDEX_NAME = "index"


# 🔹 PDF取り込み＆ベクトル化
def ingest_pdf_to_vectorstore(pdf_path: str):
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
    documents = splitter.split_documents(docs)

    embeddings = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small")

    if os.path.exists(os.path.join(VECTOR_DIR, f"{INDEX_NAME}.faiss")):
        vectorstore = FAISS.load_local(
            VECTOR_DIR, embeddings, index_name=INDEX_NAME, allow_dangerous_deserialization=True
        )
        vectorstore.add_documents(documents)
    else:
        vectorstore = FAISS.from_documents(documents, embeddings)

    vectorstore.save_local(VECTOR_DIR, index_name=INDEX_NAME)
    print(f"✅ {os.path.basename(pdf_path)} をベクトルストアに保存しました")


# 🔹 ベクトルストア読み込み
def load_vectorstore():
    embeddings = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small")
    return FAISS.load_local(
        VECTOR_DIR, embeddings, index_name=INDEX_NAME, allow_dangerous_deserialization=True
    )


# 🔹 ローカルLLM読み込み（GPTNeoX対応）
@st.cache_resource(show_spinner="🤖 モデルを準備中...")
def load_local_llm():
    model_id = "rinna/japanese-gpt-neox-3.6b-instruction-ppo"  # ← cyberagent にも変更可

    # ✅ トークナイザーを明示的に指定
    tokenizer = GPTNeoXTokenizerFast.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype="auto", device_map="auto")

    pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=512,
        temperature=0.7,
        top_p=0.95,
        repetition_penalty=1.2,
    )
    return HuggingFacePipeline(pipeline=pipe)


# 🔹 LLM選択（質問に応じて切替）
def choose_llm_by_question(question: str):
    if not USE_LOCAL_LLM:
        if any(kw in question for kw in ["要約", "なぜ", "理由", "仕組み", "背景"]):
            return "openai"
    return "local"


# 🔹 RAGチェーン構築
def get_rag_chain(vectorstore, return_source=True, question=""):
    model_type = choose_llm_by_question(question)

    if model_type == "openai":
        llm = ChatOpenAI(model_name="gpt-3.5-turbo", temperature=0)
        return RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=vectorstore.as_retriever(),
            return_source_documents=return_source,
        )

    # ローカルLLM用プロンプト（prompt_template.txt）
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
