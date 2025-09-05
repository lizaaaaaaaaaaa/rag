from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from urllib.parse import urlencode, quote, parse_qsl
import os
import secrets
import time
import httpx

router = APIRouter(prefix="/line-login", tags=["line-login"])

# ===== 環境変数 =====
LINE_LOGIN_CHANNEL_ID = os.getenv("LINE_LOGIN_CHANNEL_ID", "").strip()
LINE_LOGIN_CHANNEL_SECRET = os.getenv("LINE_LOGIN_CHANNEL_SECRET", "").strip()
LINE_LOGIN_CALLBACK_URL = os.getenv("LINE_LOGIN_CALLBACK_URL", "").strip()  # 例: https://<domain>/line-login/callback
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")  # 未設定でも落とさない（フォールバック運用）
LINE_BASIC_ID = os.getenv("LINE_BASIC_ID", "").lstrip("@")  # "@xxx" でも "xxx" でもOK


# ===== Utility =====
def _pack_state(qs: dict) -> str:
    """元の state/utm/ab などを安全に state に詰める（CSRF nonce 付き）"""
    data = dict(qs or {})
    data["_t"] = str(int(time.time()))
    data["_n"] = secrets.token_urlsafe(12)
    return urlencode(data)


def _unpack_state(state: str) -> dict:
    try:
        return dict(parse_qsl(state or ""))
    except Exception:
        return {}


# ------------------------------------------------------------
# 1) /line-login/start : 友だち追加へ“直行”する最短導線（高速）
#    ※ OAuth を経由せず、公式アカの追加画面へ 302
# ------------------------------------------------------------
@router.get("/start")
async def start(_: Request):
    if not LINE_BASIC_ID:
        raise HTTPException(500, "LINE_BASIC_ID is not set")
    add_url = f"https://line.me/R/ti/p/%40{LINE_BASIC_ID}"
    return RedirectResponse(add_url, status_code=302)


# ------------------------------------------------------------
# 2) /line-login/oauth-start : 既存の OAuth フローを維持
#    - bot_prompt=normal で友だち追加プロンプト
#    - UTM/AB/state を state に保持
# ------------------------------------------------------------
@router.get("/oauth-start")
async def oauth_start(request: Request):
    if not (LINE_LOGIN_CHANNEL_ID and LINE_LOGIN_CALLBACK_URL):
        raise HTTPException(500, "LINE Login configs are not set")

    qs = dict(request.query_params)  # UTM/AB 等を保存
    state = _pack_state(qs)

    auth_params = {
        "response_type": "code",
        "client_id": LINE_LOGIN_CHANNEL_ID,
        "redirect_uri": LINE_LOGIN_CALLBACK_URL,
        "scope": "openid profile",
        "state": state,
        "bot_prompt": "normal",
        "ui_locales": "ja",
        "prompt": "consent",
    }
    url = "https://access.line.me/oauth2/v2.1/authorize?" + urlencode(auth_params)
    return RedirectResponse(url, status_code=302)


# ------------------------------------------------------------
# 3) /line-login/callback : OAuth 後の帰着点（従来どおり）
#    - トークン交換はベストエフォート（失敗しても OA へ誘導）
#    - 友だち追加 or 追加済みなら OA 画面へ 302
# ------------------------------------------------------------
@router.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    state_raw = request.query_params.get("state", "")
    _ = _unpack_state(state_raw)  # いまは使わないが将来のトラッキングに備えて解凍

    if error:
        html = "<h3>LINEログインがキャンセルされました</h3><p>LINEへ戻ってやり直してください。</p>"
        return HTMLResponse(html)

    if not code:
        raise HTTPException(400, "missing code")

    # ベストエフォートのトークン交換（失敗しても OA へ送ってしまう）
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            _token_res = (await client.post(
                "https://api.line.me/oauth2/v2.1/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": LINE_LOGIN_CALLBACK_URL,
                    "client_id": LINE_LOGIN_CHANNEL_ID,
                    "client_secret": LINE_LOGIN_CHANNEL_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )).json()
    except Exception:
        _token_res = {}

    if not LINE_BASIC_ID:
        # 追加先が分からない場合は丁寧に案内
        return HTMLResponse("<h3>設定不足</h3><p>LINE_BASIC_ID が未設定です。</p>", status_code=500)

    add_url = f"https://line.me/R/ti/p/%40{LINE_BASIC_ID}"
    return RedirectResponse(add_url, status_code=302)


# （任意）疎通確認
@router.get("/health")
async def health():
    return JSONResponse({"ok": True})
