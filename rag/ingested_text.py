import os
import streamlit as st
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain.prompts import PromptTemplate

# .env 読み込みと切り替えフラグ
load_dotenv()
USE_LOCAL_LLM = os.getenv("USE_LOCAL_LLM", "false").lower() == "true"

# 保存ディレクトリ指定
VECTOR_DIR = "rag/vectorstore"
INDEX_NAME = "index"

# 🔹 PDF → ベクトルストア構築
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

# 🔹 ベクトルストアの読み込み
def load_vectorstore():
    embeddings = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small")
    return FAISS.load_local(
        VECTOR_DIR, embeddings, index_name=INDEX_NAME, allow_dangerous_deserialization=True
    )

# 🔹 モデル読み込みをキャッシュ（初回のみロード）
@st.cache_resource(show_spinner="🤖 rinnaモデルを読み込んでいます...")
def load_rinna_model():
    from transformers import AutoTokenizer, AutoModelForCausalLM
    model_id = "rinna/japanese-gpt-neox-3.6b-instruction-ppo"
    tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=False)
    model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype="auto", device_map="auto")
    return tokenizer, model

# 🔹 RAGチェーン構築（LLM切替 & キャッシュ対応）
def get_rag_chain(vectorstore, return_source=True):
    if not USE_LOCAL_LLM:
        # クラウド用の軽量モード（ダミーLLM）
        from langchain.chains import LLMChain
        from langchain.prompts import PromptTemplate
        from langchain.llms.fake import FakeListLLM

        dummy_prompt = PromptTemplate.from_template("質問: {query}\n\n回答: この環境ではRAG応答は利用できません。")
        dummy_llm = FakeListLLM(responses=["この環境ではRAG応答は利用できません。"])
        return LLMChain(llm=dummy_llm, prompt=dummy_prompt)

    # ローカルLLM（rinna）をキャッシュ経由で読み込み
    from transformers import pipeline
    from langchain_community.llms import HuggingFacePipeline
    from langchain.chains import RetrievalQA

    tokenizer, model = load_rinna_model()

    pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=512,
        temperature=0.7,
        top_p=0.95,
        repetition_penalty=1.2,
    )

    llm = HuggingFacePipeline(pipeline=pipe)

    # プロンプトテンプレート読み込み
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
