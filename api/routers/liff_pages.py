# api/routers/liff_pages.py
# LIFF ランディング：/liff → /liff/consent に誘導（クエリは引き継ぎ）
# - web/liff/add.html / consent.html / index.html を返却
# - __LINE_BASIC_ID__ / __LIFF_ID__ を環境変数からプレーン置換（超軽量）
# - 既存の設計を維持し、処理を増やさず速度を落とさない

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pathlib import Path
from urllib.parse import urlencode
import os

router = APIRouter(prefix="/liff", tags=["liff"])

BASE_DIR = Path(__file__).resolve().parents[2]  # プロジェクト直下
WEB_DIR = BASE_DIR / "web" / "liff"

# テンプレ差し込みに使用
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
LINE_BASIC_ID = os.getenv("LINE_BASIC_ID", "").lstrip("@")  # @はここで付与するので除去
LIFF_ID = os.getenv("LIFF_ID", "")

def _merge_query(request: Request, extra: dict | None = None) -> str:
    """受け取ったクエリをそのまま引き継ぎ、必要に応じて上書き結合"""
    q = dict(request.query_params)
    if extra:
        q.update({k: v for k, v in extra.items() if v is not None})
    return urlencode(q)

def _inject_vars(html: str) -> str:
    """静的HTMLに最低限の環境値を差し込む（文字列置換のみで超軽量）"""
    return (
        html.replace("__LINE_BASIC_ID__", f"@{LINE_BASIC_ID}" if LINE_BASIC_ID else "@unknown")
            .replace("__LIFF_ID__", LIFF_ID or "")
            .replace("__PUBLIC_BASE_URL__", PUBLIC_BASE_URL)
    )

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
    """友だち追加ページ（静的 + 置換）"""
    html = (WEB_DIR / "add.html").read_text(encoding="utf-8")
    return HTMLResponse(_inject_vars(html))

@router.get("/consent", response_class=HTMLResponse)
async def show_consent():
    """同意ページ（静的 + 置換）"""
    html = (WEB_DIR / "consent.html").read_text(encoding="utf-8")
    return HTMLResponse(_inject_vars(html))

# 既存の /liff/index.html を残している場合の互換
@router.get("/index.html", response_class=HTMLResponse)
async def legacy_index():
    p = WEB_DIR / "index.html"
    if p.exists():
        return HTMLResponse(_inject_vars(p.read_text(encoding="utf-8")))
    # 無ければ consent へ
    return RedirectResponse("/liff/consent")
