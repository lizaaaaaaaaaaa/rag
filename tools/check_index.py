# tools/check_index.py
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

vs = FAISS.load_local(
    "rag/vectorstore",
    HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small"),
    index_name="index",
    allow_dangerous_deserialization=True
)

q = "キノエデザイン 施工 できる エリア 対応 地域"
docs = vs.similarity_search(q, k=5)
for i, d in enumerate(docs, 1):
    print(i, d.metadata.get("source"), (d.page_content or "").replace("\n"," ")[:80])
