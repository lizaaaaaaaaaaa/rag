# api/routers/liff_pages.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path

router = APIRouter(tags=["liff"])

# プロジェクト直下の web/liff/ を想定（例: RAG-LLM-Project/web/liff/index.html）
BASE = Path(__file__).resolve().parents[2] / "web" / "liff"

def _read_html(filename: str) -> HTMLResponse:
    p = BASE / filename
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
    return HTMLResponse(content=p.read_text(encoding="utf-8"), media_type="text/html; charset=utf-8")

@router.get("/liff", response_class=HTMLResponse)
def liff_root() -> HTMLResponse:
    """LIFFのエンドポイントURL用（/liff）。web/liff/index.html を返す。"""
    return _read_html("index.html")

@router.get("/liff/consent", response_class=HTMLResponse)
def liff_consent() -> HTMLResponse:
    """同意ページ。web/liff/consent.html を返す。"""
    return _read_html("consent.html")
