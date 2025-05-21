from rag.ingested_text import ingest_pdf_to_vectorstore
from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path
import shutil

router = APIRouter()

UPLOAD_DIR = Path("rag/vectorstore/pdfs")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@router.post("/upload_pdf", summary="PDFファイルのアップロード")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDFファイルのみ対応です。")
    save_path = UPLOAD_DIR / file.filename
    with save_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    # ★ここでベクトル化を即実行！（PDFごとに追加登録される）
    ingest_pdf_to_vectorstore(str(save_path))
    return {"filename": file.filename, "message": "アップロード＆ベクトル化完了"}
