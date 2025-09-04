# api/routers/liff_pages.py
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from urllib.parse import urlencode
import os
from pathlib import Path

router = APIRouter()

# ---- 環境変数 ----
LIFF_CONSENT_URL = os.getenv("LIFF_CONSENT_URL", "").strip()  # 例: https://liff.line.me/2007887876-vMNe74eX
LINE_BASIC_ID = os.getenv("LINE_BASIC_ID", "").strip()        # 例: @487urklv（@はあってもなくてもOK）
POLICY_VERSION = os.getenv("POLICY_VERSION", "1.0.0").strip()

# consent.html を読み込み（なければ最小ページを返す）
CONSENT_HTML_PATH = Path(__file__).resolve().parents[2] / "web" / "liff" / "consent.html"
_fallback_html = """<!doctype html><meta charset="utf-8"><title>Consent</title><p>このウィンドウを閉じてください。</p>"""

def load_consent_html() -> str:
    try:
        html = CONSENT_HTML_PATH.read_text(encoding="utf-8")
    except Exception:
        html = _fallback_html
    # 置換：Basic ID と ポリシーバージョン
    basic = LINE_BASIC_ID.lstrip("@")
    html = html.replace("__LINE_BASIC_ID__", f"@{basic}")
    # window.__POLICY_VERSION__ を埋め込む（なければ追加）
    inject = f'<script>window.__POLICY_VERSION__="{POLICY_VERSION}";</script>'
    if "</body>" in html:
        html = html.replace("</body>", inject + "</body>")
    else:
        html += inject
    return html

def is_from_liff(request: Request) -> bool:
    # 1) Referer が liff.line.me
    ref = request.headers.get("referer", "")
    if "liff.line.me" in ref:
        return True
    # 2) UA ヒューリスティック
    ua = request.headers.get("user-agent", "").lower()
    if "line" in ua or "liff" in ua:
        return True
    # 3) LIFF 由来の典型的なクエリ
    qs = request.query_params
    if "liffClientId" in qs or "liff.state" in qs or "liffRedirectUri" in qs:
        return True
    return False

def build_external_liff_url(request: Request) -> str:
    if not LIFF_CONSENT_URL:
        # 設定漏れ時は 500 を避け、最低限ウィンドウを閉じさせる
        return "/liff"  # ダミー（実際は下の HTML を返すので使われない想定）
    # 元のクエリ（user_token, utm, state, ab 等）を付け替え
    return f"{LIFF_CONSENT_URL}?{request.query_params._dict and urlencode(list(request.query_params.multi_items()))}"

def no_store_headers(resp: Response):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"

# --- ルート（LIFF の「エンドポイント URL」に設定している想定） ---
@router.get("/liff", response_class=HTMLResponse)
async def liff_root(request: Request):
    if is_from_liff(request):
        # ✅ LIFF 内：HTML をそのまま返す（リダイレクトしない）
        html = load_consent_html()
        resp = HTMLResponse(content=html, status_code=200)
        no_store_headers(resp)
        return resp
    # 🌐 外部：LIFF へ 302
    url = build_external_liff_url(request)
    return RedirectResponse(url=url, status_code=302)

# 互換：/liff/consent でも同じ動作にしておく
@router.get("/liff/consent", response_class=HTMLResponse)
async def liff_consent(request: Request):
    if is_from_liff(request):
        html = load_consent_html()
        resp = HTMLResponse(content=html, status_code=200)
        no_store_headers(resp)
        return resp
    url = build_external_liff_url(request)
    return RedirectResponse(url=url, status_code=302)

# HEAD リクエスト（疎通テストや監視向け）
@router.head("/liff")
async def liff_head(request: Request):
    if is_from_liff(request):
        return Response(status_code=200)
    url = build_external_liff_url(request)
    resp = Response(status_code=302)
    resp.headers["Location"] = url
    return resp

@router.head("/liff/consent")
async def liff_consent_head(request: Request):
    if is_from_liff(request):
        return Response(status_code=200)
    url = build_external_liff_url(request)
    resp = Response(status_code=302)
    resp.headers["Location"] = url
    return resp
