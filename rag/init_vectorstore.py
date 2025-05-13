import os
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.chains import RetrievalQA
from langchain_community.llms import HuggingFacePipeline
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline

VECTOR_DIR = "rag/vectorstore"
INDEX_NAME = "index"

# 🔹 PDF読み込み→ベクトルストア登録
def ingest_pdf_to_vectorstore(pdf_path: str):
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
    documents = splitter.split_documents(docs)

    embeddings = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small")

    if os.path.exists(os.path.join(VECTOR_DIR, f"{INDEX_NAME}.faiss")):
        vectorstore = FAISS.load_local(VECTOR_DIR, embeddings, index_name=INDEX_NAME, allow_dangerous_deserialization=True)
        vectorstore.add_documents(documents)
    else:
        vectorstore = FAISS.from_documents(documents, embeddings)

    vectorstore.save_local(VECTOR_DIR, index_name=INDEX_NAME)
    print(f"✅ {os.path.basename(pdf_path)} をベクトルストアに保存しました")

# 🔹 ベクトルストア読み込み
def load_vectorstore():
    embeddings = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small")
    return FAISS.load_local(VECTOR_DIR, embeddings, index_name=INDEX_NAME, allow_dangerous_deserialization=True)

# 🔹 RAGチェーン生成（rinnaモデル対応）
def get_rag_chain(vectorstore, return_source=True):
    model_id = "rinna/japanese-gpt-neox-3.6b-instruction-ppo"

    tokenizer = AutoTokenizer.from_pretrained(
        model_id,
        use_fast=False,
        trust_remote_code=True  # ✅ 追加！
    )
    print("✅ Tokenizer loaded:", tokenizer.__class__)  # デバッグ用にログ出力

    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        trust_remote_code=True  # ✅ モデル側にも追加
    )

    pipe = pipeline("text-generation", model=model, tokenizer=tokenizer, max_new_tokens=512)
    llm = HuggingFacePipeline(pipeline=pipe)

    return RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=vectorstore.as_retriever(),
        return_source_documents=return_source,
    )
