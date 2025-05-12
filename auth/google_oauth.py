# ✅ auth/google_oauth.py（APIルーター定義）
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
import os
import requests
from utils import auth  # utils/auth.py の関数を利用

router = APIRouter()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

@router.get("/login")
def login():
    redirect_uri = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=openid%20email"
    )
    return RedirectResponse(redirect_uri)

@router.get("/callback")
def callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Code not found")

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
        raise HTTPException(status_code=400, detail="No ID token returned")

    email = auth.verify_google_token(id_token_str, GOOGLE_CLIENT_ID)
    if email:
        return {"message": "ログイン成功", "email": email}
    else:
        raise HTTPException(status_code=401, detail="無効なトークン")