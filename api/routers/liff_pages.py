# api/routers/liff_pages.py（完全置き換え）
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pathlib import Path

router = APIRouter(tags=["liff"])

# プロジェクト直下の web/liff/ を想定
BASE = Path(__file__).resolve().parents[2] / "web" / "liff"

def _read_html(filename: str) -> HTMLResponse:
    p = BASE / filename
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
    return HTMLResponse(content=p.read_text(encoding="utf-8"),
                        media_type="text/html; charset=utf-8")

@router.get("/liff", response_class=HTMLResponse)
def liff_root():
    """誤リンク対策：/liff は consent に統一"""
    return RedirectResponse("/liff/consent", status_code=302)

@router.get("/liff/index", response_class=HTMLResponse)
def liff_index():
    """開発・デバッグ用に index.html も残す"""
    return _read_html("index.html")

@router.get("/liff/consent", response_class=HTMLResponse)
def liff_consent():
    """同意＆友だち追加（インラインフォーム同梱）"""
    return _read_html("consent.html")

# 互換用（もし /liff/consent_form で呼ばれても同じものを返す）
@router.get("/liff/consent_form", response_class=HTMLResponse)
def liff_consent_form():
    return _read_html("consent.html")
