# api/routers/liff_pages.py — HTMLを挟まない超軽量版 + 誤設定ガード入り
# /liff/add      : Web CTA → LINE Login に 302（bot_prompt=aggressive で友だち追加促進）
# /liff/callback : Login 後 → 友だち追加 URL に 302
# /liff/consent  : LIFF 同意アプリに 302（state/ab/UTM 等を引き継ぐ）
# /liff[/]       : 互換用。/liff/consent へ 302

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse
from urllib.parse import urlencode
import os

router = APIRouter(prefix="/liff", tags=["liff"])

# 環境値（PUBLIC_BASE_URL は設定推奨。無い場合は PUBLIC_API_BASE をフォールバック）
PUBLIC_BASE_URL     = (os.getenv("PUBLIC_BASE_URL") or os.getenv("PUBLIC_API_BASE") or "").rstrip("/")
LINE_BASIC_ID       = os.getenv("LINE_BASIC_ID", "").lstrip("@")  # '@abcd' → 'abcd'
LINE_LOGIN_ID       = os.getenv("LINE_LOGIN_CHANNEL_ID", os.getenv("LINE_LOGIN_CLIENT_ID", ""))
LINE_LOGIN_REDIRECT = os.getenv("LINE_LOGIN_REDIRECT_URI", f"{PUBLIC_BASE_URL}/liff/callback")
LIFF_CONSENT_URL    = os.getenv("LIFF_CONSENT_URL", "").rstrip("/")  # 例: https://liff.line.me/165xxxxxxxxx-xxxxx

# ---- helpers -----------------------------------------------------------
def _pick(q: dict, keys: list[str]) -> dict:
    return {k: q.get(k) for k in keys if q.get(k)}

def _forward_query(req: Request, extra: dict | None = None) -> str:
    # UTM/state/ab は計測で使用。互換のため user_token/policy_version/scope も温存。
    q = dict(req.query_params)
    if extra:
        q.update({k: v for k, v in extra.items() if v is not None})
    return urlencode(_pick(q, [
        "state", "ab",
        "utm_source", "utm_medium", "utm_campaign", "utm_content",
        "user_token", "policy_version", "scope"
    ]))

# ---- routes ------------------------------------------------------------
@router.get("")
@router.get("/")
async def liff_root(request: Request):
    # 互換: /liff に来たら consent へ 302
    qs = _forward_query(request)
    dest = "/liff/consent" + (f"?{qs}" if qs else "")
    # 相対 → 完全URL へ（LINEアプリでのタップ不可を避ける）
    if PUBLIC_BASE_URL:
        dest = f"{PUBLIC_BASE_URL}{dest}"
    return RedirectResponse(dest, status_code=302)

@router.get("/add")
async def liff_add(request: Request):
    """Web CTA：LINE Login へ 302。ログイン後は /liff/callback へ戻す。"""
    if not LINE_LOGIN_ID or not LINE_LOGIN_REDIRECT:
        # 最小フォールバック：設定不足時は友だち追加画面に直送
        if not LINE_BASIC_ID:
            raise HTTPException(500, "LINE settings are missing (LOGIN_ID/BASIC_ID).")
        return RedirectResponse(f"https://line.me/R/ti/p/@{LINE_BASIC_ID}", status_code=302)

    qs_keep = _forward_query(request) or "liff_add"
    authorize = "https://access.line.me/oauth2/v2.1/authorize?" + urlencode({
        "response_type": "code",
        "client_id": LINE_LOGIN_ID,
        "redirect_uri": LINE_LOGIN_REDIRECT,
        "state": qs_keep,               # 元の UTM/state/ab をまるごと保持
        "scope": "profile openid",
        "bot_prompt": "aggressive",     # 友だち追加を促す
        "prompt": "consent",
    })
    return RedirectResponse(authorize, status_code=302)

@router.get("/callback")
async def liff_add_callback(_: Request):
    """LINE Login のコールバック：友だち追加ページ/アプリに 302。"""
    if not LINE_BASIC_ID:
        return PlainTextResponse("Missing LINE_BASIC_ID", status_code=500)
    # モバイルはアプリ遷移、PCはWeb画面
    return RedirectResponse(f"https://line.me/R/ti/p/@{LINE_BASIC_ID}", status_code=302)

@router.get("/consent")
async def liff_consent_redirect(request: Request):
    """未同意ユーザーを LIFF 同意アプリへ 302（UTM 等はそのまま付与）。"""
    if not LIFF_CONSENT_URL:
        # 未設定時は最低限のフォールバック（自社のポリシーへ）
        fallback = f"{PUBLIC_BASE_URL}/privacy" if PUBLIC_BASE_URL else "/privacy"
        return RedirectResponse(fallback, status_code=302)

    # ▼誤設定防止：必ず https の LIFF URL を要求（line://app や自サービスURLは不可）
    if not LIFF_CONSENT_URL.startswith("https://liff.line.me/"):
        return PlainTextResponse(
            "LIFF_CONSENT_URL is misconfigured (must start with https://liff.line.me/).",
            status_code=500
        )

    qs = _forward_query(request)
    url = LIFF_CONSENT_URL + (("?" + qs) if qs else "")
    return RedirectResponse(url, status_code=302)
