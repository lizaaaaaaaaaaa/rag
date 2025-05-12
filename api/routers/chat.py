from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from langchain_core.documents import Document
from rag.ingested_text import load_vectorstore, get_rag_chain
from fastapi.responses import JSONResponse
import traceback

router = APIRouter()

class ChatRequest(BaseModel):
    query: str

@router.post("/")
async def chat_endpoint(request: ChatRequest):
    try:
        query = request.query

        # ベクトルストアとRAGチェーンを構築
        vectorstore = load_vectorstore()
        rag_chain = get_rag_chain(vectorstore, return_source=True, question=query)
        result = rag_chain.invoke({"query": query})

        # source_documents を JSON化安全なdictへ変換
        sources = []
        for doc in result.get("source_documents", []):
            if isinstance(doc, Document):
                sources.append({
                    "page_content": str(doc.page_content),
                    "metadata": {k: str(v) for k, v in doc.metadata.items()}
                })
            else:
                sources.append(str(doc))

        # 明示的に JSONResponse として返す（__fields_set__ を除去）
        return JSONResponse(content={
            "answer": str(result.get("result", "")),
            "sources": sources
        })

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
