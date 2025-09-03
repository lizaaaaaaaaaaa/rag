# api/routers/liff_pages.py
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pathlib import Path
from urllib.parse import urlencode

router = APIRouter(tags=["liff"])

# プロジェクト直下の web/liff/ ディレクトリを想定
# 例: RAG-LLM-Project/web/liff/{index.html, consent.html, add.html}
BASE = Path(__file__).resolve().parents[2] / "web" / "liff"


def _read_html(filename: str) -> HTMLResponse:
    """web/liff/ 配下のHTMLを返す（存在しなければ 404）"""
    p = BASE / filename
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
    return HTMLResponse(
        content=p.read_text(encoding="utf-8"),
        media_type="text/html; charset=utf-8",
    )


@router.get("/liff")
def liff_root(request: Request):
    """
    LIFF エンドポイントURL想定（/liff）
    - 端末/埋め込みブラウザでJSが動かなくても確実に同意ページへ遷移させるため、
      サーバー側で /liff/consent にリダイレクトする。
    - 受け取ったクエリ（例: liff.state, state, ab, utm_*）はそのまま引き継ぐ。
    """
    # 元のクエリをそのまま付け替え
    qs = urlencode(list(request.query_params.multi_items()), doseq=True)
    url = "/liff/consent" + (f"?{qs}" if qs else "")
    return RedirectResponse(url, status_code=302)  # GET想定なので 302 でOK


@router.get("/liff/consent", response_class=HTMLResponse)
def liff_consent() -> HTMLResponse:
    """同意ページ（web/liff/consent.html）"""
    return _read_html("consent.html")


@router.get("/liff/add", response_class=HTMLResponse)
def liff_add() -> HTMLResponse:
    """友だち追加用ページ（web/liff/add.html）"""
    return _read_html("add.html")
