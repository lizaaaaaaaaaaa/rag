import os
from rag.ingested_text import ingest_pdf_to_vectorstore

pdf_dir = "rag/data"

for filename in os.listdir(pdf_dir):
    if filename.endswith(".pdf"):
        filepath = os.path.join(pdf_dir, filename)
        print(f"📄 処理中: {filepath}")
        ingest_pdf_to_vectorstore(filepath)
