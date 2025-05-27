from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import RedirectResponse
import os
import requests
from utils import auth  # utils/auth.py の verify_google_token を利用
from utils.auth import get_or_create_user, get_user_role  # 追加

router = APIRouter(prefix="/auth", tags=["auth"])

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

# Googleログイン画面へリダイレクト
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

# Googleからのコールバック
@router.get("/callback")
def callback(request: Request, response: Response):
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Code not found")

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
        raise HTTPException(status_code=400, detail="No ID token returned")

    # Google IDトークン検証 → emailを取得
    email = auth.verify_google_token(id_token_str, GOOGLE_CLIENT_ID)
    if email:
        # [1] ユーザーDB連携（初回なら自動登録、既存なら取得）
        user = get_or_create_user(email)  # utils.auth 側で実装
        # [2] ロール分岐（例：@admin.comは管理者）
        if email.endswith("@admin.com"):
            role = "admin"
        else:
            role = "user"
        # [3] ロールもDBに保存しておく場合はここで更新
        # user["role"] = role  # 保存処理も必要なら追加

        # [4] レスポンス
        return {"message": "ログイン成功", "email": email, "role": role}
    else:
        raise HTTPException(status_code=401, detail="無効なトークン")
