from fastapi import APIRouter, Request, HTTPException, Response, Depends
from fastapi.responses import RedirectResponse
import os
import requests
import jwt
from datetime import datetime, timedelta

from utils import auth  # utils/auth.py の verify_google_token を利用
from utils.auth import get_or_create_user

router = APIRouter(prefix="/auth", tags=["auth"])

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

# --- JWT設定 ---
JWT_SECRET = os.getenv("JWT_SECRET", "supersecret")  # 本番は.envやSecret Managerで必ず管理
JWT_ALGORITHM = "HS256"
JWT_EXPIRES = 2  # トークン有効時間（時間）

FRONTEND_URL = "https://rag-frontend-190389115361.asia-northeast1.run.app"

# --- Googleログイン画面へリダイレクト ---
@router.get("/login/google")
def login():
    redirect_uri = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=openid%20email%20profile"
        f"&access_type=offline"
        f"&prompt=consent"
    )
    return RedirectResponse(redirect_uri)

# --- Googleからのコールバック（JWTをクエリでフロントに返す） ---
@router.get("/callback")
def callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        return RedirectResponse(url=f"{FRONTEND_URL}/?login=error&reason=no_code")

    # アクセストークン取得
    token_resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
    )
    token_json = token_resp.json()
    id_token_str = token_json.get("id_token")
    if not id_token_str:
        return RedirectResponse(url=f"{FRONTEND_URL}/?login=error&reason=no_id_token")

    email = auth.verify_google_token(id_token_str, GOOGLE_CLIENT_ID)
    if email:
        user = get_or_create_user(email)
        role = "admin" if email.endswith("@admin.com") else "user"
        payload = {
            "email": email,
            "role": role,
            "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRES)
        }
        jwt_token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

        # ★クエリパラメータでtokenとemailを返す
        return RedirectResponse(url=f"{FRONTEND_URL}/?login=success&token={jwt_token}&email={email}")
    else:
        return RedirectResponse(url=f"{FRONTEND_URL}/?login=error&reason=invalid_token")


# --- JWT認証Depends（API保護用） ---
def get_current_user(request: Request):
    # フロントでCookieじゃなくtokenをAuthorizationヘッダで送る場合はここ修正
    token = request.cookies.get("access_token")
    if not token:
        # Authorizationヘッダも見る
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
        else:
            raise HTTPException(status_code=401, detail="No token")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# --- ユーザー情報API ---
@router.get("/me")
def get_me(user=Depends(get_current_user)):
    return {"email": user["email"], "role": user["role"]}

# --- ログアウトAPI（Cookie即削除） ---
@router.get("/logout")
def logout():
    response = RedirectResponse(url=f"{FRONTEND_URL}/?logout=success")
    response.delete_cookie("access_token")
    return response
