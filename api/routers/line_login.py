# api/routers/line_login.py - LINEログイン・LIFF対応（完全修正版）
# 変更点:
#  - /line-login/start を追加（1ボタン導線用）
#  - 認可URLに prompt=consent & bot_prompt=normal を付与
import os
import re
import logging
import jwt
import requests
import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/line-login", tags=["line-login"])

# =========================
# 環境変数
# =========================
LINE_LOGIN_CHANNEL_ID = os.getenv("LINE_LOGIN_CHANNEL_ID")
LINE_LOGIN_CHANNEL_SECRET = os.getenv("LINE_LOGIN_CHANNEL_SECRET")
LINE_LOGIN_REDIRECT_URI = os.getenv("LINE_LOGIN_REDIRECT_URI")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://rag-frontend-190389115361.asia-northeast1.run.app")
JWT_SECRET = os.getenv("JWT_SECRET", "supersecret")

# LIFF ID: v1（liff-...）と v2（{digits}-{alnum}）の両方を許可
LIFF_ID_PATTERN = re.compile(r"^(liff-[\w-]+|[A-Za-z0-9]+-[A-Za-z0-9]+)$")

# =========================
# モデル
# =========================
class LineLoginRequest(BaseModel):
    code: str
    state: Optional[str] = None
    redirect_uri: Optional[str] = None  # 実際に使ったredirect_uri

class LiffInitRequest(BaseModel):
    liff_id: str
    user_id: Optional[str] = None

# =========================
# ヘルパー
# =========================
def _resolve_redirect_uri(redirect_uri: Optional[str]) -> str:
    """
    認可リクエストで使った redirect_uri と
    トークン交換時の redirect_uri は完全一致が必要（invalid_grant対策）
    """
    if redirect_uri and redirect_uri.strip():
        return redirect_uri.strip()
    if LINE_LOGIN_REDIRECT_URI and LINE_LOGIN_REDIRECT_URI.strip():
        return LINE_LOGIN_REDIRECT_URI.strip()
    # 最後の砦（フロントの /line-callback に着地）
    return f"{FRONTEND_URL}/line-callback"

def _build_auth_url(redirect_uri: str, state: str) -> str:
    return (
        "https://access.line.me/oauth2/v2.1/authorize"
        f"?response_type=code"
        f"&client_id={LINE_LOGIN_CHANNEL_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
        f"&scope=profile%20openid"
        f"&prompt=consent"
        f"&bot_prompt=normal"   # ★ ログイン中に友だち追加プロンプトを表示
    )

# =========================
# Web用：1ボタン開始エンドポイント
# =========================
@router.get("/start")
async def line_login_start(redirect_uri: str | None = None):
    """
    /line-login/start にアクセスすると、LINEログイン認可画面へ302。
    bot_prompt=normal を付与して友だち追加プロンプトを同一フローで表示。
    """
    if not LINE_LOGIN_CHANNEL_ID:
        raise HTTPException(status_code=500, detail="LINE Login not configured")

    state = secrets.token_urlsafe(32)
    actual_redirect_uri = _resolve_redirect_uri(redirect_uri)
    auth_url = _build_auth_url(actual_redirect_uri, state)
    return RedirectResponse(url=auth_url)

# =========================
# 認証URLの発行（既存）
# =========================
@router.get("/auth-url")
async def get_line_login_url(redirect_uri: Optional[str] = None):
    """LINEログイン認証URLを生成（JSON）"""
    if not LINE_LOGIN_CHANNEL_ID:
        raise HTTPException(status_code=500, detail="LINE Login not configured")
    state = secrets.token_urlsafe(32)
    actual_redirect_uri = _resolve_redirect_uri(redirect_uri)
    return {
        "auth_url": _build_auth_url(actual_redirect_uri, state),
        "state": state,
        "redirect_uri": actual_redirect_uri,
    }

# =========================
# コールバック（POST JSON）
# =========================
@router.post("/callback")
async def line_login_callback(request: LineLoginRequest):
    """LINEログインコールバック処理（JSONクライアント想定）"""
    try:
        redirect_uri = _resolve_redirect_uri(request.redirect_uri)
        token_response = await get_line_access_token(request.code, redirect_uri=redirect_uri)

        access_token = token_response.get("access_token")
        if not access_token:
            logger.error(f"token exchange failed: {token_response}")
            raise HTTPException(status_code=400, detail="Failed to get access token")

        user_info = await get_line_user_profile(access_token)

        jwt_payload = {
            "user_id": user_info.get("userId"),
            "display_name": user_info.get("displayName", ""),
            "picture_url": user_info.get("pictureUrl", ""),
            "email": user_info.get("email", ""),
            "provider": "line",
            "exp": datetime.utcnow() + timedelta(hours=24),
        }
        jwt_token = jwt.encode(jwt_payload, JWT_SECRET, algorithm="HS256")

        return {
            "success": True,
            "token": jwt_token,
            "user": {
                "id": user_info.get("userId"),
                "name": user_info.get("displayName", ""),
                "picture": user_info.get("pictureUrl", ""),
                "email": user_info.get("email", ""),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("LINE login callback error")
        raise HTTPException(status_code=500, detail=str(e))

# =========================
# コールバック（GET、ブラウザリダイレクト）
# =========================
@router.get("/callback")
async def line_login_callback_get(request: Request):
    """GET版のコールバック（ブラウザリダイレクト用）"""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")
    redirect_uri_qs = request.query_params.get("redirect_uri")  # 受け取れれば使う

    if error:
        return RedirectResponse(url=f"{FRONTEND_URL}/?login=error&reason={error}")
    if not code:
        return RedirectResponse(url=f"{FRONTEND_URL}/?login=error&reason=no_code")

    try:
        lr = LineLoginRequest(code=code, state=state, redirect_uri=redirect_uri_qs)
        result = await line_login_callback(lr)  # 上と同じ処理
        return RedirectResponse(
            url=f"{FRONTEND_URL}/?login=success&token={result['token']}&provider=line"
        )
    except Exception:
        logger.exception("LINE login GET callback error")
        return RedirectResponse(url=f"{FRONTEND_URL}/?login=error&reason=server_error")

# =========================
# トークン交換 & プロフィール取得
# =========================
async def get_line_access_token(code: str, *, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
    """認証コードからアクセストークンを取得"""
    token_url = "https://api.line.me/oauth2/v2.1/token"
    actual_redirect_uri = _resolve_redirect_uri(redirect_uri)

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": actual_redirect_uri,  # 認可時と完全一致
        "client_id": LINE_LOGIN_CHANNEL_ID,
        "client_secret": LINE_LOGIN_CHANNEL_SECRET,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    resp = requests.post(token_url, data=data, headers=headers, timeout=15)
    if not resp.ok:
        try:
            logger.error("token exchange error %s: %s", resp.status_code, resp.text)
        except Exception:
            logger.error("token exchange http %s", resp.status_code)
        resp.raise_for_status()
    return resp.json()

async def get_line_user_profile(access_token: str) -> Dict[str, Any]:
    """アクセストークンからユーザープロフィールを取得"""
    profile_url = "https://api.line.me/v2/profile"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(profile_url, headers=headers, timeout=10)
    if not resp.ok:
        try:
            logger.error("profile error %s: %s", resp.status_code, resp.text)
        except Exception:
            logger.error("profile http %s", resp.status_code)
        resp.raise_for_status()
    return resp.json()

# =========================
# LIFF 初期化
# =========================
@router.post("/liff/init")
async def liff_initialize(request: LiffInitRequest):
    """
    LIFF初期化処理
    - v1: liff-xxxx
    - v2: 2007887876-vMNe74eX のような形式
    """
    try:
        liff_id = (request.liff_id or "").strip()
        if not LIFF_ID_PATTERN.match(liff_id):
            raise HTTPException(status_code=400, detail="Invalid LIFF ID format")

        user_info = None
        if request.user_id:
            user_info = await get_user_by_line_id(request.user_id)

        return {
            "success": True,
            "liff_id": liff_id,
            "user": user_info,
            "config": {"api_endpoint": "https://rag-api-190389115361.asia-northeast1.run.app"},
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("LIFF initialization error")
        raise HTTPException(status_code=500, detail="LIFF init failed")

@router.get("/liff/config/{liff_id}")
async def get_liff_config(liff_id: str):
    """LIFF設定情報を取得（形式が不正なら 400）"""
    if not LIFF_ID_PATTERN.match((liff_id or "").strip()):
        raise HTTPException(status_code=400, detail="Invalid LIFF ID format")
    return {
        "liff_id": liff_id,
        "api_endpoint": "https://rag-api-190389115361.asia-northeast1.run.app",
        "features": {"chat": True, "file_upload": True, "rich_menu": True},
    }

# =========================
# ダミー：ユーザー取得 & JWT検証
# =========================
async def get_user_by_line_id(line_user_id: str) -> Optional[dict]:
    try:
        return {"id": line_user_id, "name": "LINE User", "is_registered": True}
    except Exception as e:
        logger.error(f"Failed to get user: {e}")
        return None

def verify_jwt_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

@router.get("/verify")
async def verify_login_token(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No valid token")
    token = auth_header.replace("Bearer ", "")
    payload = verify_jwt_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {
        "valid": True,
        "user": {
            "id": payload.get("user_id"),
            "name": payload.get("display_name"),
            "provider": payload.get("provider"),
        },
    }
