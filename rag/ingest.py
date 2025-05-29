from langchain.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.vectorstores import FAISS
from pathlib import Path
import os

PDF_DIR = Path("rag/vectorstore/pdfs")
VECTORSTORE_PATH = "rag/vectorstore/index.faiss"

def ingest_pdf_to_vectorstore(pdf_path: str):
    """
    単一のPDFファイルをベクトルストアに取り込み・保存
    - pdf_path: ローカルのPDFファイルパス
    """
    # 1. PDFファイルを読み込み
    loader = PyPDFLoader(str(pdf_path))
    docs = loader.load()

    # 2. チャンク分割
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    split_docs = splitter.split_documents(docs)

    # 3. 埋め込みモデル準備
    embeddings = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small")

    # 4. 既存ベクトルストアがあればロードしてマージ、なければ新規作成
    if os.path.exists(VECTORSTORE_PATH):
        vectordb = FAISS.load_local("rag/vectorstore", embeddings)
        vectordb.add_documents(split_docs)
    else:
        vectordb = FAISS.from_documents(split_docs, embeddings)
    vectordb.save_local("rag/vectorstore")

    return len(split_docs)  # 追加したドキュメント数など返すと便利

def main():
    """
    PDFディレクトリ内のすべてのPDFをベクトルストアに再構築
    """
    docs = []
    for pdf_path in PDF_DIR.glob("*.pdf"):
        loader = PyPDFLoader(str(pdf_path))
        pdf_docs = loader.load()
        docs.extend(pdf_docs)

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    split_docs = splitter.split_documents(docs)
    embeddings = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small")
    vectordb = FAISS.from_documents(split_docs, embeddings)
    vectordb.save_local("rag/vectorstore")

if __name__ == "__main__":
    main()
