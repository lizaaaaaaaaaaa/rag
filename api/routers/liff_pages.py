# api/routers/liff_pages.py
# LIFF ランディング：/liff → /liff/consent に誘導（クエリは引き継ぎ）
# - web/liff/add.html / consent.html / index.html を返却
# - 既存の設計を維持し、処理を増やさず速度を落とさない

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pathlib import Path
from urllib.parse import urlencode
import os

router = APIRouter(prefix="/liff", tags=["liff"])

BASE_DIR = Path(__file__).resolve().parents[2]  # プロジェクト直下
WEB_DIR = BASE_DIR / "web" / "liff"

# いまは使わないが互換のため残す（テンプレ差し込み等で利用する可能性あり）
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
LINE_BASIC_ID = os.getenv("LINE_BASIC_ID", "").lstrip("@")

def _merge_query(request: Request, extra: dict | None = None) -> str:
    """受け取ったクエリをそのまま引き継ぎ、必要に応じて上書き結合"""
    q = dict(request.query_params)
    if extra:
        q.update({k: v for k, v in extra.items() if v is not None})
    return urlencode(q)

@router.get("")
@router.get("/")
async def liff_index(request: Request):
    """
    /liff に来たら /liff/consent へリダイレクト。
    state / utm / user_token / policy_version 等はそのまま引き継ぐ。
    """
    qs = _merge_query(request)
    return RedirectResponse(f"/liff/consent?{qs}" if qs else "/liff/consent")

@router.get("/add", response_class=HTMLResponse)
async def show_add():
    """友だち追加ページ（静的）"""
    html = (WEB_DIR / "add.html").read_text(encoding="utf-8")
    return HTMLResponse(html)

@router.get("/consent", response_class=HTMLResponse)
async def show_consent():
    """同意ページ（静的）"""
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
