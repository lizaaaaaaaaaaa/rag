# api/routers/liff_pages.py — HTMLを挟まない超軽量リダイレクト版（最終）
# /liff/add      : Web CTA -> LINE Login に 302（bot_prompt=aggressive で友だち追加促進）
# /liff/callback : Login 後 -> 友だち追加画面に 302
# /liff/consent  : LIFF 同意アプリに 302（state/ab/UTM 等を引き継ぐ）
# /liff[/]       : 互換用。/liff/consent へ 302
#
# ※速度劣化なし：全ルートが 1 回の 302 だけで終わります

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse, Response
from urllib.parse import urlencode
import os

router = APIRouter(prefix="/liff", tags=["liff"])

# --- Env（PUBLIC_BASE_URL が無ければ PUBLIC_API_BASE をフォールバック） ---
PUBLIC_BASE_URL     = (os.getenv("PUBLIC_BASE_URL") or os.getenv("PUBLIC_API_BASE") or "").rstrip("/")
LINE_BASIC_ID       = os.getenv("LINE_BASIC_ID", "").lstrip("@")  # '@abcd' -> 'abcd'
LINE_LOGIN_ID       = os.getenv("LINE_LOGIN_CHANNEL_ID", os.getenv("LINE_LOGIN_CLIENT_ID", ""))
LINE_LOGIN_REDIRECT = os.getenv("LINE_LOGIN_REDIRECT_URI", f"{PUBLIC_BASE_URL}/liff/callback")
LIFF_CONSENT_URL    = (os.getenv("LIFF_CONSENT_URL", "")).rstrip("/")  # 例: https://liff.line.me/2007887876-vMNe74eX

# --- helpers ------------------------------------------------------------
def _pick(q: dict, keys: list[str]) -> dict:
    return {k: q.get(k) for k in keys if q.get(k)}

def _forward_query(req: Request, extra: dict | None = None) -> str:
    """UTM/state/ab と consent API が使う user_token 等を維持"""
    q = dict(req.query_params)
    if extra:
        q.update({k: v for k, v in extra.items() if v is not None})
    return urlencode(_pick(q, [
        "state", "ab",
        "utm_source", "utm_medium", "utm_campaign", "utm_content",
        "user_token", "policy_version", "scope"
    ]))

# --- routes -------------------------------------------------------------
@router.get("")
@router.get("/")
async def liff_root(request: Request):
    """互換: /liff に来たら consent へ 302（絶対URL化）"""
    qs = _forward_query(request)
    dest = "/liff/consent" + (f"?{qs}" if qs else "")
    if PUBLIC_BASE_URL:
        dest = f"{PUBLIC_BASE_URL}{dest}"   # LINE アプリでの相対リンク挙動を避ける
    return RedirectResponse(dest, status_code=302)

@router.get("/add")
async def liff_add(request: Request):
    """Web の「LINEで相談する」CTA -> LINE Login に 302。戻り先は /liff/callback"""
    if not LINE_LOGIN_ID or not LINE_LOGIN_REDIRECT:
        # 設定不足の安全フォールバック：友だち追加画面へ
        if not LINE_BASIC_ID:
            raise HTTPException(500, "LINE settings are missing (LOGIN_ID/BASIC_ID).")
        return RedirectResponse(f"https://line.me/R/ti/p/@{LINE_BASIC_ID}", status_code=302)

    qs_keep = _forward_query(request) or "liff_add"
    authorize = "https://access.line.me/oauth2/v2.1/authorize?" + urlencode({
        "response_type": "code",
        "client_id": LINE_LOGIN_ID,
        "redirect_uri": LINE_LOGIN_REDIRECT,
        "state": qs_keep,               # 元の UTM/state/ab を保持
        "scope": "profile openid",
        "bot_prompt": "aggressive",     # 友だち追加を促す
        "prompt": "consent",
    })
    return RedirectResponse(authorize, status_code=302)

@router.get("/callback")
async def liff_add_callback(_: Request):
    """LINE Login のコールバック：友だち追加（アプリ/Web）へ 302"""
    if not LINE_BASIC_ID:
        return PlainTextResponse("Missing LINE_BASIC_ID", status_code=500)
    return RedirectResponse(f"https://line.me/R/ti/p/@{LINE_BASIC_ID}", status_code=302)

@router.get("/consent")
async def liff_consent_redirect(request: Request):
    """未同意ユーザーを LIFF 同意アプリへ 302（UTM 等はそのまま付与）"""
    # 誤設定防止：必ず liff.line.me に向ける
    if not LIFF_CONSENT_URL or not LIFF_CONSENT_URL.startswith("https://liff.line.me/"):
        # 最低限のフォールバック（自社のポリシーへ）
        fallback = f"{PUBLIC_BASE_URL}/privacy" if PUBLIC_BASE_URL else "/privacy"
        return RedirectResponse(fallback, status_code=302)

    qs = _forward_query(request)
    url = LIFF_CONSENT_URL + (("?" + qs) if qs else "")
    return RedirectResponse(url, status_code=302)

@router.head("/consent")
async def liff_consent_head(request: Request):
    """curl -sI で Location を確認できるよう HEAD でも 302 を返す"""
    if not LIFF_CONSENT_URL or not LIFF_CONSENT_URL.startswith("https://liff.line.me/"):
        return Response(status_code=200)
    qs = _forward_query(request)
    url = LIFF_CONSENT_URL + (("?" + qs) if qs else "")
    resp = Response(status_code=302)
    resp.headers["Location"] = url
    return resp
