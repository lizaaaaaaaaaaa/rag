# -*- coding: utf-8 -*-
import os, csv, pathlib
from typing import List
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.docstore.document import Document
from google.cloud import storage

VECTOR_DIR = os.getenv("VECTOR_DIR", "/tmp/rag/vectorstore")
INDEX_NAME = os.getenv("INDEX_NAME", "index")
BUCKET = os.getenv("GCS_BUCKET_NAME")
FAQ_OBJECT = os.getenv("FAQ_OBJECT", "faq/faq.csv")  # 例: gs://<bucket>/faq/faq.csv

def _load_faq_from_gcs() -> List[Document]:
    client = storage.Client()
    blob = client.bucket(BUCKET).blob(FAQ_OBJECT)
    data = blob.download_as_text(encoding="utf-8")
    rows = list(csv.DictReader(data.splitlines()))
    docs = []
    for r in rows:
        q = (r.get("質問") or r.get("question") or "").strip()
        a = (r.get("回答") or r.get("answer") or "").strip()
        if not q or not a: continue
        docs.append(Document(page_content=f"Q: {q}\nA: {a}", metadata={"source":"faq.csv"}))
    return docs

def main():
    docs = _load_faq_from_gcs()
    emb = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small")
    pathlib.Path(VECTOR_DIR).mkdir(parents=True, exist_ok=True)
    vs = FAISS.from_documents(docs, emb)
    vs.save_local(VECTOR_DIR, index_name=INDEX_NAME)
    print(f"saved -> {VECTOR_DIR}/{INDEX_NAME}.faiss / .pkl")

if __name__ == "__main__":
    main()