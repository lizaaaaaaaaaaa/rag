# api/routers/liff_pages.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path

router = APIRouter(tags=["liff"])

BASE = Path(__file__).resolve().parents[2] / "web" / "liff"


def _read_html(filename: str) -> HTMLResponse:
    """
    web/liff/<filename> を読み込んで HTML を返す。
    見つからなければ 404 を返す。
    """
    p = BASE / filename
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
    body = p.read_text(encoding="utf-8")
    return HTMLResponse(content=body)  # text/html; charset=utf-8


@router.get("/liff/consent", response_class=HTMLResponse)
def liff_consent() -> HTMLResponse:
    return _read_html("consent.html")
