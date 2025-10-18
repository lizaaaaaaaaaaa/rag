# scripts/bulk_ingest.py
"""
PDF を一括でベクトル化して FAISS に保存するスクリプト。
python scripts/bulk_ingest.py --pdf_dir data/pdfs
"""

import argparse
import glob
import os
import pathlib
from typing import List

from langchain.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import HuggingFaceBgeEmbeddings
from langchain.vectorstores import FAISS
from langchain.document_loaders import PyPDFLoader


# ---------- CLI ----------
parser = argparse.ArgumentParser()
parser.add_argument("--pdf_dir", default="data/pdfs", help="PDF フォルダ")
parser.add_argument("--out", default="rag/vectorstore", help="FAISS 保存先")
args = parser.parse_args()

pdf_paths = sorted(glob.glob(os.path.join(args.pdf_dir, "*.pdf")))
if not pdf_paths:
    raise SystemExit(f"No PDF found in {args.pdf_dir}")

documents: List[Document] = []

# 元の設定を踏襲
splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)

for pdf_path in pdf_paths:
    loader = PyPDFLoader(pdf_path)
    pages = loader.load()  # 1 ページ = 1 Document（loader が page を付与する場合あり）
    chunks = splitter.split_documents(pages)

    for idx, chunk in enumerate(chunks, start=1):
        # ★ 修正: 既存メタを尊重し、無いときのみ補完（上書き防止）
        md = dict(chunk.metadata) if chunk.metadata else {}

        # 可能性のあるページキーを優先採用（存在しない時だけ idx を使う）
        existing_page = md.get("page")
        if existing_page is None:
            page_fallback = md.get("page_number") or md.get("pageIndex")
            md["page"] = page_fallback if page_fallback is not None else idx

        # source も既存があれば優先し、無ければファイル名で補完
        md.setdefault("source", pathlib.Path(pdf_path).name)

        chunk.metadata = md
        documents.append(chunk)

print(f"Loaded {len(documents)} chunks from {len(pdf_paths)} PDFs")

# ---------- ベクトル化 ----------
emb = HuggingFaceBgeEmbeddings(
    model_name="intfloat/multilingual-e5-small"
)
faiss = FAISS.from_documents(documents, emb)
faiss.save_local(args.out)

print(f"Saved FAISS index to {args.out}")