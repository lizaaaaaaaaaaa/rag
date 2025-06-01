import os
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from dotenv import load_dotenv
from langsmith import traceable  # トレース用

load_dotenv()

VECTOR_DIR = "rag/vectorstore"
INDEX_NAME = "index"

@traceable(name="rag_response_trace")
def get_rag_response(query: str):
    # ベクトルストア読み込み
    embeddings = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-small")
    vectorstore = FAISS.load_local(
        VECTOR_DIR, embeddings, index_name=INDEX_NAME, allow_dangerous_deserialization=True
    )

    with open("rag/prompt_template.txt", encoding="utf-8") as f:
        prompt_str = f.read()

    prompt = PromptTemplate(
        input_variables=["context", "question"],
        template=prompt_str
    )

    llm = ChatOpenAI(model_name="gpt-3.5-turbo", temperature=0)
    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        retriever=vectorstore.as_retriever(),
        chain_type="stuff",
        return_source_documents=True,
        chain_type_kwargs={"prompt": prompt}
    )

    result = qa_chain.invoke({"query": query})
    sources = [
        f"{doc.metadata.get('source', '不明')} (p{doc.metadata.get('page', '?')})"
        for doc in result.get("source_documents", [])
    ]
    return result.get("result", "❌ 回答なし"), sources
