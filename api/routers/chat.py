from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.rag_chain import get_rag_response

router = APIRouter()

class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    result: str
    sources: list[str]

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        result, sources = get_rag_response(request.query)
        return ChatResponse(result=result, sources=sources)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
