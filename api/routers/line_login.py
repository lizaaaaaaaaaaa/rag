# api/routers/line_login.py - LINEログイン（OAuth2.0）コールバック処理

import os
import jwt
import logging
import requests
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode, parse_qs
from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/line-login", tags=["line-login"])

# 環境変数
LINE_LOGIN_CHANNEL_ID = os.getenv("LINE_LOGIN_CHANNEL_ID")
LINE_LOGIN_CHANNEL_SECRET = os.getenv("LINE_LOGIN_CHANNEL_SECRET")
JWT_SECRET = os.getenv("JWT_SECRET", "supersecret")
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_HOURS = 24

# フロントエンドのURL
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://rag-frontend-190389115361.asia-northeast1.run.app")

class LineLoginState:
    """セッション状態管理（本番環境ではRedisなどを使用）"""
    _states = {}
    
    @classmethod
    def create_state(cls, redirect_url: str = None) -> str:
        state = secrets.token_urlsafe(32)
        cls._states[state] = {
            "created_at": datetime.utcnow(),
            "redirect_url": redirect_url or FRONTEND_URL
        }
        return state
    
    @classmethod
    def validate_state(cls, state: str) -> dict:
        if state not in cls._states:
            return None
        
        state_data = cls._states[state]
        # 10分以内の状態のみ有効
        if (datetime.utcnow() - state_data["created_at"]).seconds > 600:
            del cls._states[state]
            return None
        
        return state_data
    
    @classmethod
    def remove_state(cls, state: str):
        if state in cls._states:
            del cls._states[state]

@router.get("/auth", summary="LINEログイン開始")
async def start_line_login(request: Request, redirect_url: str = None):
    """
    LINEログインのURLを生成してリダイレクトする
    """
    try:
        # state生成（CSRF攻撃防止）
        state = LineLoginState.create_state(redirect_url)
        
        # LINEログイン用パラメータ
        auth_params = {
            "response_type": "code",
            "client_id": LINE_LOGIN_CHANNEL_ID,
            "redirect_uri": f"{request.base_url}line-login/callback",
            "state": state,
            "scope": "profile openid email",  # 必要なスコープを指定
            "nonce": secrets.token_urlsafe(16)  # OpenID Connect用
        }
        
        auth_url = f"https://access.line.me/oauth2/v2.1/authorize?{urlencode(auth_params)}"
        
        logger.info(f"LINE login initiated with state: {state}")
        
        return RedirectResponse(url=auth_url)
        
    except Exception as e:
        logger.error(f"Failed to start LINE login: {e}")
        raise HTTPException(status_code=500, detail="Login initialization failed")

@router.get("/callback", summary="LINEログイン コールバック")
async def line_login_callback(request: Request):
    """
    LINEからのコールバックを処理する
    """
    try:
        # クエリパラメータを取得
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        error = request.query_params.get("error")
        
        # エラーチェック
        if error:
            error_description = request.query_params.get("error_description", "Unknown error")
            logger.error(f"LINE login error: {error} - {error_description}")
            return RedirectResponse(url=f"{FRONTEND_URL}?login=error&reason={error}")
        
        if not code or not state:
            logger.error("Missing code or state parameter")
            return RedirectResponse(url=f"{FRONTEND_URL}?login=error&reason=missing_params")
        
        # state検証
        state_data = LineLoginState.validate_state(state)
        if not state_data:
            logger.error(f"Invalid or expired state: {state}")
            return RedirectResponse(url=f"{FRONTEND_URL}?login=error&reason=invalid_state")
        
        # アクセストークン取得
        token_data = await get_access_token(code, str(request.base_url))
        if not token_data:
            return RedirectResponse(url=f"{FRONTEND_URL}?login=error&reason=token_failed")
        
        # ユーザープロフィール取得
        user_profile = await get_user_profile(token_data["access_token"])
        if not user_profile:
            return RedirectResponse(url=f"{FRONTEND_URL}?login=error&reason=profile_failed")
        
        # JWTトークン生成
        jwt_token = create_jwt_token(user_profile)
        
        # state削除
        LineLoginState.remove_state(state)
        
        # 成功時のリダイレクト
        redirect_url = state_data["redirect_url"]
        success_url = f"{redirect_url}?login=success&token={jwt_token}&user_id={user_profile['userId']}"
        
        logger.info(f"LINE login successful for user: {user_profile['userId']}")
        
        return RedirectResponse(url=success_url)
        
    except Exception as e:
        logger.error(f"LINE login callback error: {e}")
        return RedirectResponse(url=f"{FRONTEND_URL}?login=error&reason=callback_error")

async def get_access_token(code: str, base_url: str) -> dict:
    """
    認可コードからアクセストークンを取得
    """
    try:
        token_url = "https://api.line.me/oauth2/v2.1/token"
        
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": f"{base_url}line-login/callback",
            "client_id": LINE_LOGIN_CHANNEL_ID,
            "client_secret": LINE_LOGIN_CHANNEL_SECRET
        }
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        response = requests.post(
            token_url,
            data=token_data,
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Token request failed: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Failed to get access token: {e}")
        return None

async def get_user_profile(access_token: str) -> dict:
    """
    アクセストークンからユーザープロフィールを取得
    """
    try:
        profile_url = "https://api.line.me/v2/profile"
        
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        response = requests.get(
            profile_url,
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Profile request failed: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Failed to get user profile: {e}")
        return None

def create_jwt_token(user_profile: dict) -> str:
    """
    ユーザープロフィールからJWTトークンを生成
    """
    try:
        payload = {
            "user_id": user_profile["userId"],
            "display_name": user_profile["displayName"],
            "picture_url": user_profile.get("pictureUrl"),
            "status_message": user_profile.get("statusMessage"),
            "login_type": "line_oauth",
            "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRES_HOURS),
            "iat": datetime.utcnow()
        }
        
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        
    except Exception as e:
        logger.error(f"Failed to create JWT token: {e}")
        raise

@router.get("/login-page", summary="LINEログインページ")
async def login_page():
    """
    シンプルなLINEログインページを提供
    """
    html_content = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>LINEログイン</title>
        <style>
            body {
                font-family: 'Segoe UI', Arial, sans-serif;
                background: linear-gradient(135deg, #00B900, #00C300);
                margin: 0;
                padding: 0;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
            }
            .login-container {
                background: white;
                border-radius: 20px;
                padding: 40px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                text-align: center;
                max-width: 400px;
                width: 90%;
            }
            .logo {
                font-size: 2.5rem;
                margin-bottom: 20px;
            }
            .title {
                font-size: 1.5rem;
                color: #333;
                margin-bottom: 10px;
            }
            .subtitle {
                color: #666;
                margin-bottom: 30px;
            }
            .line-login-btn {
                background: #00B900;
                color: white;
                border: none;
                padding: 15px 30px;
                border-radius: 50px;
                font-size: 1.1rem;
                font-weight: bold;
                cursor: pointer;
                transition: all 0.3s ease;
                width: 100%;
                max-width: 250px;
            }
            .line-login-btn:hover {
                background: #009A00;
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(0,185,0,0.3);
            }
        </style>
    </head>
    <body>
        <div class="login-container">
            <div class="logo">🤖</div>
            <div class="title">RAG AI Chat</div>
            <div class="subtitle">LINEでログインしてチャットを始めましょう</div>
            <button class="line-login-btn" onclick="startLineLogin()">
                LINEでログイン
            </button>
        </div>
        
        <script>
            function startLineLogin() {
                // 現在のページをリダイレクト先として設定
                const currentUrl = encodeURIComponent(window.location.origin);
                window.location.href = '/line-login/auth?redirect_url=' + currentUrl;
            }
            
            // URLパラメータをチェックしてログイン結果を表示
            window.onload = function() {
                const urlParams = new URLSearchParams(window.location.search);
                const loginStatus = urlParams.get('login');
                const token = urlParams.get('token');
                const userId = urlParams.get('user_id');
                const reason = urlParams.get('reason');
                
                if (loginStatus === 'success' && token) {
                    // ログイン成功時の処理
                    localStorage.setItem('auth_token', token);
                    localStorage.setItem('user_id', userId);
                    
                    alert('ログインに成功しました！');
                    // チャットページにリダイレクト
                    window.location.href = '/chat.html';
                    
                } else if (loginStatus === 'error') {
                    // エラー時の処理
                    alert('ログインに失敗しました: ' + (reason || 'Unknown error'));
                }
            }
        </script>
    </body>
    </html>
    """
    
    return HTMLResponse(content=html_content)

@router.get("/user-info", summary="認証済みユーザー情報取得")
async def get_user_info(request: Request):
    """
    JWTトークンから認証済みユーザー情報を取得
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
            "status_message": payload.get("status_message"),
            "login_type": payload.get("login_type")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"User info retrieval error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user info")

@router.post("/logout", summary="ログアウト")
async def logout():
    """
    ログアウト処理（トークン無効化）
    """
    # 実際の実装では、トークンをブラックリストに追加するなどの処理が必要
    return {"message": "Logged out successfully"}

@router.get("/status", summary="LINEログイン設定状況確認")
async def line_login_status():
    """
    LINEログインの設定状況を確認
    """
    return {
        "line_login_channel_id_set": bool(LINE_LOGIN_CHANNEL_ID),
        "line_login_channel_secret_set": bool(LINE_LOGIN_CHANNEL_SECRET),
        "jwt_secret_set": bool(JWT_SECRET),
        "callback_url": f"{os.getenv('API_URL', 'https://rag-api-190389115361.asia-northeast1.run.app')}/line-login/callback",
        "auth_url": f"{os.getenv('API_URL', 'https://rag-api-190389115361.asia-northeast1.run.app')}/line-login/auth",
        "login_page_url": f"{os.getenv('API_URL', 'https://rag-api-190389115361.asia-northeast1.run.app')}/line-login/login-page"
    }