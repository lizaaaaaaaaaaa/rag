from langchain.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.vectorstores import FAISS
from pathlib import Path

PDF_DIR = Path("rag/vectorstore/pdfs")
VECTORSTORE_PATH = "rag/vectorstore/index.faiss"

def main():
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
