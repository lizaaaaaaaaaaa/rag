# api/routers/line_login.py - LINEログイン・LIFF対応

import os
import logging
import jwt
import requests
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/line-login", tags=["line-login"])

# 環境変数
LINE_LOGIN_CHANNEL_ID = os.getenv("LINE_LOGIN_CHANNEL_ID")
LINE_LOGIN_CHANNEL_SECRET = os.getenv("LINE_LOGIN_CHANNEL_SECRET")
LINE_LOGIN_REDIRECT_URI = os.getenv("LINE_LOGIN_REDIRECT_URI")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://rag-frontend-190389115361.asia-northeast1.run.app")
JWT_SECRET = os.getenv("JWT_SECRET", "supersecret")

class LineLoginRequest(BaseModel):
    code: str
    state: Optional[str] = None

class LiffInitRequest(BaseModel):
    liff_id: str
    user_id: Optional[str] = None

@router.get("/auth-url")
async def get_line_login_url(redirect_uri: Optional[str] = None):
    """LINEログイン認証URLを生成"""
    if not LINE_LOGIN_CHANNEL_ID:
        raise HTTPException(status_code=500, detail="LINE Login not configured")
    
    # リダイレクトURIの設定
    actual_redirect_uri = redirect_uri or LINE_LOGIN_REDIRECT_URI
    if not actual_redirect_uri:
        actual_redirect_uri = f"{FRONTEND_URL}/line-callback"
    
    # ランダムなstate生成（CSRF対策）
    import secrets
    state = secrets.token_urlsafe(32)
    
    auth_url = (
        f"https://access.line.me/oauth2/v2.1/authorize"
        f"?response_type=code"
        f"&client_id={LINE_LOGIN_CHANNEL_ID}"
        f"&redirect_uri={actual_redirect_uri}"
        f"&state={state}"
        f"&scope=profile%20openid"
    )
    
    return {
        "auth_url": auth_url,
        "state": state,
        "redirect_uri": actual_redirect_uri
    }

@router.post("/callback")
async def line_login_callback(request: LineLoginRequest):
    """LINEログインコールバック処理"""
    try:
        # アクセストークンを取得
        token_response = await get_line_access_token(request.code)
        
        if not token_response.get("access_token"):
            raise HTTPException(status_code=400, detail="Failed to get access token")
        
        # ユーザー情報を取得
        user_info = await get_line_user_profile(token_response["access_token"])
        
        # JWTトークンを生成
        jwt_payload = {
            "user_id": user_info["userId"],
            "display_name": user_info.get("displayName", ""),
            "picture_url": user_info.get("pictureUrl", ""),
            "email": user_info.get("email", ""),
            "provider": "line",
            "exp": datetime.utcnow() + timedelta(hours=24)
        }
        
        jwt_token = jwt.encode(jwt_payload, JWT_SECRET, algorithm="HS256")
        
        return {
            "success": True,
            "token": jwt_token,
            "user": {
                "id": user_info["userId"],
                "name": user_info.get("displayName", ""),
                "picture": user_info.get("pictureUrl", ""),
                "email": user_info.get("email", "")
            }
        }
        
    except Exception as e:
        logger.error(f"LINE login callback error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/callback")
async def line_login_callback_get(request: Request):
    """GET版のコールバック（ブラウザリダイレクト用）"""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")
    
    if error:
        return RedirectResponse(url=f"{FRONTEND_URL}/?login=error&reason={error}")
    
    if not code:
        return RedirectResponse(url=f"{FRONTEND_URL}/?login=error&reason=no_code")
    
    try:
        # POSTと同じ処理
        login_request = LineLoginRequest(code=code, state=state)
        result = await line_login_callback(login_request)
        
        # フロントエンドにリダイレクト
        return RedirectResponse(
            url=f"{FRONTEND_URL}/?login=success&token={result['token']}&provider=line"
        )
        
    except Exception as e:
        logger.error(f"LINE login GET callback error: {e}")
        return RedirectResponse(url=f"{FRONTEND_URL}/?login=error&reason=server_error")

async def get_line_access_token(code: str) -> dict:
    """認証コードからアクセストークンを取得"""
    token_url = "https://api.line.me/oauth2/v2.1/token"
    
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": LINE_LOGIN_REDIRECT_URI,
        "client_id": LINE_LOGIN_CHANNEL_ID,
        "client_secret": LINE_LOGIN_CHANNEL_SECRET,
    }
    
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    
    response = requests.post(token_url, data=data, headers=headers)
    response.raise_for_status()
    
    return response.json()

async def get_line_user_profile(access_token: str) -> dict:
    """アクセストークンからユーザープロフィールを取得"""
    profile_url = "https://api.line.me/v2/profile"
    
    headers = {"Authorization": f"Bearer {access_token}"}
    
    response = requests.get(profile_url, headers=headers)
    response.raise_for_status()
    
    return response.json()

# LIFF関連のエンドポイント
@router.post("/liff/init")
async def liff_initialize(request: LiffInitRequest):
    """LIFF初期化処理"""
    try:
        # LIFF IDの検証
        liff_id = request.liff_id
        if not liff_id.startswith("liff-"):
            raise HTTPException(status_code=400, detail="Invalid LIFF ID")
        
        # ユーザー情報があれば取得
        user_info = None
        if request.user_id:
            # ここでユーザー情報を取得（データベースから）
            user_info = await get_user_by_line_id(request.user_id)
        
        return {
            "success": True,
            "liff_id": liff_id,
            "user": user_info,
            "config": {
                "api_endpoint": f"https://rag-api-190389115361.asia-northeast1.run.app"
            }
        }
        
    except Exception as e:
        logger.error(f"LIFF initialization error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/liff/config/{liff_id}")
async def get_liff_config(liff_id: str):
    """LIFF設定情報を取得"""
    return {
        "liff_id": liff_id,
        "api_endpoint": "https://rag-api-190389115361.asia-northeast1.run.app",
        "features": {
            "chat": True,
            "file_upload": True,
            "rich_menu": True
        }
    }

async def get_user_by_line_id(line_user_id: str) -> Optional[dict]:
    """LINE User IDからユーザー情報を取得"""
    # データベースからユーザー情報を取得
    # 実際の実装では、PostgreSQLやFirestoreを使用
    try:
        # 簡単な例（実際はDBアクセス）
        return {
            "id": line_user_id,
            "name": "LINE User",
            "is_registered": True
        }
    except Exception as e:
        logger.error(f"Failed to get user: {e}")
        return None

# JWT認証のためのヘルパー関数
def verify_jwt_token(token: str) -> Optional[dict]:
    """JWTトークンを検証"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

@router.get("/verify")
async def verify_login_token(request: Request):
    """ログイントークンの検証"""
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
            "provider": payload.get("provider")
        }
    }