# api/routers/line_login.py
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from urllib.parse import urlencode, quote, urlparse, parse_qsl
import os
import secrets
import time
import httpx

router = APIRouter(prefix="/line-login", tags=["line-login"])

# 必要な環境変数
LINE_LOGIN_CHANNEL_ID = os.getenv("LINE_LOGIN_CHANNEL_ID", "")
LINE_LOGIN_CHANNEL_SECRET = os.getenv("LINE_LOGIN_CHANNEL_SECRET", "")
LINE_LOGIN_CALLBACK_URL = os.getenv("LINE_LOGIN_CALLBACK_URL", "")  # 例: https://<domain>/line-login/callback
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
LINE_BASIC_ID = os.getenv("LINE_BASIC_ID", "").lstrip("@")  # "@xxx"でも"xxx"でもOKにする

if not PUBLIC_BASE_URL:
    # Cloud Run で config に入れておく想定
    raise RuntimeError("PUBLIC_BASE_URL is not set")

def _pack_state(qs: dict) -> str:
    """元の state/utm/ab などを安全にエンコードして state に詰める"""
    # state は CSRF 対策も兼ねるため、nonce も足す
    data = dict(qs or {})
    data["_t"] = str(int(time.time()))
    data["_n"] = secrets.token_urlsafe(12)
    return urlencode(data)

def _unpack_state(state: str) -> dict:
    try:
        return dict(parse_qsl(state or ""))
    except Exception:
        return {}

@router.get("/start")
async def start(request: Request):
    """
    Webの「LINEで相談する」ボタンからここへ来る。
    LINEログインに飛ばして、bot_prompt=normal で友だち追加を促す。
    """
    if not (LINE_LOGIN_CHANNEL_ID and LINE_LOGIN_CALLBACK_URL):
        raise HTTPException(500, "LINE Login configs are not set")

    # 既存のクエリ（state/utm_* /ab など）をそのまま保持
    qs = dict(request.query_params)
    state = _pack_state(qs)

    auth_params = {
        "response_type": "code",
        "client_id": LINE_LOGIN_CHANNEL_ID,
        "redirect_uri": LINE_LOGIN_CALLBACK_URL,
        "scope": "openid profile",     # 友だち連携だけならこれで十分
        "state": state,
        "bot_prompt": "normal",        # ← ログイン後に友だち追加のプロンプトを出す
        "ui_locales": "ja",
        "prompt": "consent",           # 同意画面を出す
    }
    url = "https://access.line.me/oauth2/v2.1/authorize?" + urlencode(auth_params)
    return RedirectResponse(url, status_code=302)

@router.get("/callback")
async def callback(request: Request):
    """
    ログイン完了後に戻ってくる。トークン交換は必須ではないが、エラー時は丁寧に返す。
    完了後は公式アカウントの友だち追加／チャットへ遷移させる。
    """
    code = request.query_params.get("code")
    error = request.query_params.get("error")
    state_raw = request.query_params.get("state", "")
    state = _unpack_state(state_raw)

    if error:
        # ユーザーキャンセルなど
        html = f"<h3>LINEログインがキャンセルされました</h3><p>LINEへ戻ってやり直してください。</p>"
        return HTMLResponse(html)

    if not code:
        raise HTTPException(400, "missing code")

    # ここでトークン交換する必要は特にない（bot_prompt が優先）
    # 交換に失敗しても、友だち追加プロンプト自体は出ているので、最後はOA画面へ送ってしまう。
    try:
        token_res = {}
        async with httpx.AsyncClient(timeout=8.0) as client:
            token_res = (await client.post(
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
        token_res = {}

    # 友だち追加 or 追加済みユーザーは OA へ
    # まずは友だち追加画面（確実に開く https ドメイン）へ誘導
    add_url = f"https://line.me/R/ti/p/%40{LINE_BASIC_ID}"
    # すぐチャットを開いて「AI相談」を自動送信したい場合は oaMessage を使う
    ai_text = "AI相談"
    chat_url = f"https://line.me/R/oaMessage/{LINE_BASIC_ID}/{quote(ai_text)}"

    # 友だち未追加なら add_url、追加後の自然遷移でチャットへ。単純に add_url を返してOK。
    return RedirectResponse(add_url, status_code=302)

# （任意）疎通確認
@router.get("/health")
async def health():
    return JSONResponse({"ok": True})
