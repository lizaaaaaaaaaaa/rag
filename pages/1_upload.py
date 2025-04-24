# ✅ rinna用に調整されたRAG完成版
# ファイル1：rag/ingested_text.py
import os
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
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

# 🔹 RAGチェーン生成（rinnaモデルに対応）
def get_rag_chain(vectorstore, return_source=True):
    model_id = "rinna/japanese-gpt-neox-3.6b-instruction-ppo"
    tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=False)
    model = AutoModelForCausalLM.from_pretrained(model_id)

    pipe = pipeline("text-generation", model=model, tokenizer=tokenizer, max_new_tokens=512)
    llm = HuggingFacePipeline(pipeline=pipe)

    return RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=vectorstore.as_retriever(),
        return_source_documents=return_source,
    )


# ファイル2：pages/1_upload.py
import streamlit as st
import os
from rag.ingested_text import ingest_pdf_to_vectorstore, load_vectorstore, get_rag_chain
from tempfile import NamedTemporaryFile

st.set_page_config(page_title="アップロード & RAG質問", layout="wide")

st.title("📤 PDFアップロード & 💬 RAG質問")
st.write("アップロードしたPDFの内容から質問できます")

# ファイルアップロード
uploaded_file = st.file_uploader("PDFファイルを選択", type=["pdf"])

if uploaded_file is not None:
    with NamedTemporaryFile(delete=False, suffix=".pdf", dir="uploaded_docs") as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name

    st.success("✅ アップロード成功！")

    try:
        ingest_pdf_to_vectorstore(tmp_path)
        st.success("✅ ベクトルストア取り込み完了！")
    except Exception as e:
        st.error(f"❌ ベクトル化に失敗しました: {e}")
        st.stop()

    st.subheader("💬 質問してみよう！")
    question = st.text_input("アップロードしたPDFの内容について質問")

    if question:
        try:
            vectorstore = load_vectorstore()
            rag_chain = get_rag_chain(vectorstore, return_source=True)
            result = rag_chain.invoke({"query": question})

            st.write(f"📘 回答: {result.get('result', '❌ 回答が見つかりませんでした')}")

            if result.get("source_documents"):
                st.write("📎 出典:")
                for doc in result["source_documents"]:
                    source = doc.metadata.get("source", "不明")
                    page = doc.metadata.get("page", "?")
                    st.write(f"- {source} (p{page})")
        except Exception as e:
            st.error(f"RAG応答エラー: {e}")
