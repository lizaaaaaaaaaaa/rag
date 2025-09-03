from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path

router = APIRouter(tags=["liff"])

# プロジェクト直下の web/liff/ を想定
BASE = Path(__file__).resolve().parents[2] / "web" / "liff"

def _read_html(name: str) -> HTMLResponse:
    p = BASE / name
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
    # UTF-8 を明示
    return HTMLResponse(p.read_text(encoding="utf-8"),
                        media_type="text/html; charset=utf-8")

@router.get("/liff", response_class=HTMLResponse)
def liff_root():
    """/liff に直アクセスされた場合は index.html を返す（開発・運用両対応）"""
    return _read_html("index.html")

@router.get("/liff/index", response_class=HTMLResponse)
def liff_index():
    """開発・デバッグ用に index.html を明示で返す"""
    return _read_html("index.html")

@router.get("/liff/consent", response_class=HTMLResponse)
def liff_consent():
    """同意のみ（友だち追加はしない）"""
    return _read_html("consent.html")

@router.get("/liff/add", response_class=HTMLResponse)
def liff_add():
    """友だち追加のみ（同意はしない）"""
    return _read_html("add.html")

# 互換用：もし旧リンクで /liff/consent_form が来ても同一ページを返す
@router.get("/liff/consent_form", response_class=HTMLResponse)
def liff_consent_form():
    return _read_html("consent.html")
