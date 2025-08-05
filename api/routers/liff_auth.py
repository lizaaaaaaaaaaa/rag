# api/routers/liff_auth.py - LIFF認証用エンドポイント

import os
import jwt
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import requests

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/liff", tags=["liff"])

# 環境変数
LINE_LOGIN_CHANNEL_ID = os.getenv("LINE_LOGIN_CHANNEL_ID")
LINE_LOGIN_CHANNEL_SECRET = os.getenv("LINE_LOGIN_CHANNEL_SECRET")
JWT_SECRET = os.getenv("JWT_SECRET", "supersecret")
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_HOURS = 24

class LIFFTokenRequest(BaseModel):
    access_token: str
    id_token: str

class LIFFProfileResponse(BaseModel):
    user_id: str
    display_name: str
    picture_url: str = None
    status_message: str = None

@router.post("/verify-token", summary="LIFF認証トークンの検証")
async def verify_liff_token(request: LIFFTokenRequest):
    """
    LIFFから受け取ったアクセストークンとIDトークンを検証し、
    JWTトークンを発行する
    """
    try:
        # IDトークンの検証
        if not verify_id_token(request.id_token):
            raise HTTPException(status_code=401, detail="Invalid ID token")
        
        # アクセストークンでユーザープロフィールを取得
        user_profile = get_user_profile(request.access_token)
        if not user_profile:
            raise HTTPException(status_code=401, detail="Failed to get user profile")
        
        # JWTトークンを生成
        jwt_payload = {
            "user_id": user_profile["user_id"],
            "display_name": user_profile["display_name"],
            "picture_url": user_profile.get("picture_url"),
            "login_type": "liff",
            "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRES_HOURS),
            "iat": datetime.utcnow()
        }
        
        jwt_token = jwt.encode(jwt_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        
        logger.info(f"LIFF authentication successful for user: {user_profile['user_id']}")
        
        return {
            "success": True,
            "token": jwt_token,
            "user": {
                "user_id": user_profile["user_id"],
                "display_name": user_profile["display_name"],
                "picture_url": user_profile.get("picture_url")
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"LIFF authentication error: {e}")
        raise HTTPException(status_code=500, detail="Authentication failed")

@router.get("/user-profile", summary="認証済みユーザーのプロフィール取得")
async def get_user_profile_endpoint(request: Request):
    """
    JWTトークンから認証済みユーザーのプロフィールを取得
    """
    try:
        # Authorizationヘッダーからトークンを取得
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid token")
        
        token = auth_header.replace("Bearer ", "")
        
        # JWTトークンをデコード
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return {
            "user_id": payload["user_id"],
            "display_name": payload["display_name"],
            "picture_url": payload.get("picture_url"),
            "login_type": payload.get("login_type")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Profile retrieval error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get profile")

def verify_id_token(id_token: str) -> bool:
    """
    LINE IDトークンの検証
    """
    try:
        # LINEのJWKSエンドポイントからキーを取得して検証
        # 簡易版：ヘッダーのチェックのみ
        import base64
        import json
        
        # JWTヘッダーをデコード
        header_b64 = id_token.split('.')[0]
        # パディングを追加
        header_b64 += '=' * (4 - len(header_b64) % 4)
        header = json.loads(base64.urlsafe_b64decode(header_b64))
        
        # 基本的なヘッダーチェック
        if header.get('alg') != 'ES256':
            return False
            
        # 本来はここでLINEの公開鍵で署名を検証する必要がある
        # 現在は簡易版として、トークンの形式チェックのみ
        parts = id_token.split('.')
        if len(parts) != 3:
            return False
            
        return True
        
    except Exception as e:
        logger.error(f"ID token verification failed: {e}")
        return False

def get_user_profile(access_token: str) -> dict:
    """
    LINE Profile APIからユーザープロフィールを取得
    """
    try:
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        response = requests.get(
            "https://api.line.me/v2/profile",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            profile_data = response.json()
            return {
                "user_id": profile_data["userId"],
                "display_name": profile_data["displayName"],
                "picture_url": profile_data.get("pictureUrl"),
                "status_message": profile_data.get("statusMessage")
            }
        else:
            logger.error(f"Failed to get user profile: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        return None

@router.get("/config", summary="LIFF設定情報取得")
async def get_liff_config():
    """
    フロントエンド用のLIFF設定情報を返す
    """
    return {
        "liff_id": os.getenv("LIFF_APP_ID"),
        "api_endpoint": os.getenv("API_URL", "https://rag-api-190389115361.asia-northeast1.run.app")
    }
    

# api/routers/liff_auth.py に追加するデバッグエンドポイント

@router.get("/debug", summary="LIFF設定デバッグ情報")
async def debug_liff_config():
    """
    LIFF設定の詳細なデバッグ情報を返す
    """
    return {
        "environment_variables": {
            "LINE_LOGIN_CHANNEL_ID": os.getenv("LINE_LOGIN_CHANNEL_ID"),
            "LINE_LOGIN_CHANNEL_SECRET_SET": bool(os.getenv("LINE_LOGIN_CHANNEL_SECRET")),
            "LIFF_APP_ID": os.getenv("LIFF_APP_ID"),
            "JWT_SECRET_SET": bool(os.getenv("JWT_SECRET")),
            "API_URL": os.getenv("API_URL"),
            "FRONTEND_URL": os.getenv("FRONTEND_URL")
        },
        "expected_urls": {
            "liff_endpoint": f"{os.getenv('FRONTEND_URL', 'https://rag-frontend-190389115361.asia-northeast1.run.app')}/liff-chat.html",
            "api_verify_token": f"{os.getenv('API_URL', 'https://rag-api-190389115361.asia-northeast1.run.app')}/liff/verify-token",
            "api_config": f"{os.getenv('API_URL', 'https://rag-api-190389115361.asia-northeast1.run.app')}/liff/config"
        },
        "validation": {
            "liff_id_format_valid": _validate_liff_id_format(os.getenv("LIFF_APP_ID")),
            "channel_id_matches": _validate_channel_id_match(),
            "https_urls": _validate_https_urls()
        }
    }

def _validate_liff_id_format(liff_id: str) -> bool:
    """LIFF IDの形式を検証"""
    if not liff_id:
        return False
    
    # 正しい形式: チャネルID-英数字
    import re
    pattern = r'^\d+-[a-zA-Z0-9]+$'
    return bool(re.match(pattern, liff_id))

def _validate_channel_id_match() -> bool:
    """チャネルIDとLIFF IDの一致を確認"""
    channel_id = os.getenv("LINE_LOGIN_CHANNEL_ID")
    liff_id = os.getenv("LIFF_APP_ID")
    
    if not channel_id or not liff_id:
        return False
    
    return liff_id.startswith(channel_id)

def _validate_https_urls() -> dict:
    """URL設定のHTTPS確認"""
    api_url = os.getenv("API_URL", "")
    frontend_url = os.getenv("FRONTEND_URL", "")
    
    return {
        "api_url_https": api_url.startswith("https://"),
        "frontend_url_https": frontend_url.startswith("https://"),
        "api_url": api_url,
        "frontend_url": frontend_url
    }    
        