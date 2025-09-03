# api/routers/liff_pages.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pathlib import Path
from urllib.parse import urlencode
import os

router = APIRouter(prefix="/liff", tags=["liff"])

BASE_DIR = Path(__file__).resolve().parents[2]  # プロジェクト直下
WEB_DIR = BASE_DIR / "web" / "liff"

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
LINE_BASIC_ID = os.getenv("LINE_BASIC_ID", "").lstrip("@")

def _merge_query(request: Request, extra: dict = None) -> str:
    q = dict(request.query_params)
    if extra:
        q.update({k: v for k, v in extra.items() if v is not None})
    return urlencode(q)

@router.get("")
@router.get("/")
async def liff_index(request: Request):
    # 既存の設計を踏襲：/liff は consent へ誘導
    qs = _merge_query(request)
    return RedirectResponse(f"/liff/consent?{qs}" if qs else "/liff/consent")

@router.get("/add", response_class=HTMLResponse)
async def show_add():
    # 友だち追加ページ（HTMLは web/liff/add.html に置く）
    html = (WEB_DIR / "add.html").read_text(encoding="utf-8")
    return HTMLResponse(html)

@router.get("/consent", response_class=HTMLResponse)
async def show_consent():
    # 同意ページ
    html = (WEB_DIR / "consent.html").read_text(encoding="utf-8")
    return HTMLResponse(html)

# 既存の /liff/index.html を残している場合の互換
@router.get("/index.html", response_class=HTMLResponse)
async def legacy_index():
    p = WEB_DIR / "index.html"
    if p.exists():
        return HTMLResponse(p.read_text(encoding="utf-8"))
    # 無ければ consent へ
    return RedirectResponse("/liff/consent")
