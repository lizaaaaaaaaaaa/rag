from langchain.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.vectorstores import FAISS
from pathlib import Path
import os

VECTORSTORE_PATH = "rag/vectorstore"


def ingest_pdf_to_vectorstore(pdf_path: str):
    """
    1つのPDFだけベクトル化して既存ベクトルストアに追記。
    - pdf_path: ローカルのPDFファイルパス
    """
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    split_docs = splitter.split_documents(docs)

    embeddings = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small")

    faiss_index_path = Path(VECTORSTORE_PATH) / "index.faiss"
    if faiss_index_path.exists():
        vectordb = FAISS.load_local(VECTORSTORE_PATH, embeddings)
        vectordb.add_documents(split_docs)
    else:
        vectordb = FAISS.from_documents(split_docs, embeddings)
    vectordb.save_local(VECTORSTORE_PATH)

    return len(split_docs)


def main():
    """
    PDFディレクトリ内のすべてのPDFをベクトルストアに再構築
    """
    PDF_DIR = Path("rag/vectorstore/pdfs")
    docs = []
    for pdf_path in PDF_DIR.glob("*.pdf"):
        loader = PyPDFLoader(str(pdf_path))
        pdf_docs = loader.load()
        docs.extend(pdf_docs)

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    split_docs = splitter.split_documents(docs)
    embeddings = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small")
    vectordb = FAISS.from_documents(split_docs, embeddings)
    vectordb.save_local(VECTORSTORE_PATH)


if __name__ == "__main__":
    main()
