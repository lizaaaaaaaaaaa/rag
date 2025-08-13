# api/routers/line_proxy.py (新規作成)
"""
Cloud Run 経由 LINE API プロキシエンドポイント
ローカル環境の制限を回避してLINE APIにアクセス
"""

import os
import requests
import json
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Dict, Any, Optional

router = APIRouter(prefix="/line-proxy", tags=["line-proxy"])

# Secret Manager から LINE トークンを取得
def get_line_token_from_secret():
    """Secret Manager から LINE トークンを取得"""
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "rag-cloud-project")
        
        secret_name = f"projects/{project_id}/secrets/LINE_CHANNEL_ACCESS_TOKEN/versions/latest"
        response = client.access_secret_version(request={"name": secret_name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        print(f"Secret Manager error: {e}")
        return os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

class LineAPIRequest(BaseModel):
    endpoint: str  # 例: "bot/info", "bot/richmenu/list"
    method: str = "GET"
    data: Optional[Dict[Any, Any]] = None

@router.post("/call-api")
async def proxy_line_api(request: LineAPIRequest):
    """
    Cloud Run経由でLINE APIを呼び出す
    ローカル環境の制限を回避
    """
    try:
        # トークン取得
        line_token = get_line_token_from_secret()
        if not line_token:
            raise HTTPException(status_code=500, detail="LINE token not available")
        
        # LINE API URL構築
        base_url = "https://api.line.me/v2"
        full_url = f"{base_url}/{request.endpoint.lstrip('/')}"
        
        # ヘッダー設定
        headers = {
            "Authorization": f"Bearer {line_token}",
            "Content-Type": "application/json"
        }
        
        # リクエスト実行
        if request.method.upper() == "GET":
            response = requests.get(full_url, headers=headers, timeout=15)
        elif request.method.upper() == "POST":
            response = requests.post(full_url, headers=headers, json=request.data, timeout=15)
        elif request.method.upper() == "DELETE":
            response = requests.delete(full_url, headers=headers, timeout=15)
        else:
            raise HTTPException(status_code=400, detail="Unsupported HTTP method")
        
        # レスポンス返却
        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "data": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
            "success": 200 <= response.status_code < 300
        }
        
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"LINE API request failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Proxy error: {str(e)}")

@router.get("/bot-info")
async def get_bot_info():
    """Bot情報取得（簡易版）"""
    request = LineAPIRequest(endpoint="bot/info", method="GET")
    return await proxy_line_api(request)

@router.get("/richmenu-list")
async def get_richmenu_list():
    """リッチメニュー一覧取得"""
    request = LineAPIRequest(endpoint="bot/richmenu/list", method="GET")
    return await proxy_line_api(request)

@router.post("/richmenu-create")
async def create_richmenu(richmenu_data: Dict[Any, Any]):
    """リッチメニュー作成"""
    request = LineAPIRequest(endpoint="bot/richmenu", method="POST", data=richmenu_data)
    return await proxy_line_api(request)

@router.delete("/richmenu-delete/{richmenu_id}")
async def delete_richmenu(richmenu_id: str):
    """リッチメニュー削除"""
    request = LineAPIRequest(endpoint=f"bot/richmenu/{richmenu_id}", method="DELETE")
    return await proxy_line_api(request)

@router.post("/richmenu-set-default/{richmenu_id}")
async def set_default_richmenu(richmenu_id: str):
    """デフォルトリッチメニュー設定"""
    request = LineAPIRequest(endpoint=f"bot/user/all/richmenu/{richmenu_id}", method="POST")
    return await proxy_line_api(request)

# ==================================================
# ローカル環境用 Cloud Run プロキシクライアント
# ==================================================

# local_line_client.py (ローカル用)
"""
ローカル環境から Cloud Run 経由で LINE API を使用するクライアント
"""

import requests
from typing import Dict, Any, Optional

class CloudRunLineClient:
    def __init__(self, cloud_run_url: str = "https://rag-api-190389115361.asia-northeast1.run.app"):
        self.base_url = f"{cloud_run_url}/line-proxy"
    
    def call_line_api(self, endpoint: str, method: str = "GET", data: Optional[Dict] = None) -> Dict:
        """Cloud Run経由でLINE APIを呼び出し"""
        try:
            response = requests.post(
                f"{self.base_url}/call-api",
                json={
                    "endpoint": endpoint,
                    "method": method,
                    "data": data
                },
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def get_bot_info(self) -> Dict:
        """Bot情報取得"""
        try:
            response = requests.get(f"{self.base_url}/bot-info", timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def get_richmenu_list(self) -> Dict:
        """リッチメニュー一覧取得"""
        try:
            response = requests.get(f"{self.base_url}/richmenu-list", timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def create_richmenu(self, richmenu_data: Dict) -> Dict:
        """リッチメニュー作成"""
        try:
            response = requests.post(
                f"{self.base_url}/richmenu-create",
                json=richmenu_data,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def delete_richmenu(self, richmenu_id: str) -> Dict:
        """リッチメニュー削除"""
        try:
            response = requests.delete(f"{self.base_url}/richmenu-delete/{richmenu_id}", timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def set_default_richmenu(self, richmenu_id: str) -> Dict:
        """デフォルトリッチメニュー設定"""
        try:
            response = requests.post(f"{self.base_url}/richmenu-set-default/{richmenu_id}", timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e), "success": False}

# test_cloud_run_proxy.py (テスト用)
"""
Cloud Run プロキシ経由での LINE API テスト
"""

def test_cloud_run_proxy():
    print("🌐 Cloud Run プロキシ経由 LINE API テスト")
    print("=" * 50)
    
    client = CloudRunLineClient()
    
    # 1. Bot情報取得テスト
    print("1️⃣ Bot情報取得テスト...")
    bot_info = client.get_bot_info()
    
    if bot_info.get("success"):
        print("✅ Bot情報取得成功！")
        data = bot_info.get("data", {})
        print(f"   ボット名: {data.get('displayName', '不明')}")
        print(f"   ボットID: {data.get('userId', '不明')}")
    else:
        print(f"❌ Bot情報取得失敗: {bot_info.get('error')}")
        return False
    
    # 2. リッチメニュー一覧取得テスト
    print("\n2️⃣ リッチメニュー一覧取得テスト...")
    richmenu_list = client.get_richmenu_list()
    
    if richmenu_list.get("success"):
        print("✅ リッチメニュー一覧取得成功！")
        richmenus = richmenu_list.get("data", {}).get("richmenus", [])
        print(f"   登録済みメニュー数: {len(richmenus)}")
        
        # 既存メニューを削除
        for menu in richmenus:
            menu_id = menu.get("richMenuId")
            if menu_id:
                delete_result = client.delete_richmenu(menu_id)
                if delete_result.get("success"):
                    print(f"   ✅ メニュー削除: {menu_id}")
                else:
                    print(f"   ❌ メニュー削除失敗: {menu_id}")
    else:
        print(f"❌ リッチメニュー一覧取得失敗: {richmenu_list.get('error')}")
    
    # 3. 新しいリッチメニュー作成テスト
    print("\n3️⃣ リッチメニュー作成テスト...")
    richmenu_data = {
        "size": {"width": 2500, "height": 1686},
        "selected": True,
        "name": "CloudRunプロキシ経由メニュー",
        "chatBarText": "メニュー",
        "areas": [
            {
                "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
                "action": {"type": "message", "text": "AI相談"}
            },
            {
                "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
                "action": {"type": "message", "text": "AI住まいサイト"}
            },
            {
                "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                "action": {"type": "message", "text": "資料請求"}
            },
            {
                "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
                "action": {"type": "message", "text": "展示場予約"}
            },
            {
                "bounds": {"x": 833, "y": 843, "width": 834, "height": 843},
                "action": {"type": "message", "text": "資金計画"}
            },
            {
                "bounds": {"x": 1667, "y": 843, "width": 833, "height": 843},
                "action": {"type": "message", "text": "チャット相談"}
            }
        ]
    }
    
    create_result = client.create_richmenu(richmenu_data)
    
    if create_result.get("success"):
        print("✅ リッチメニュー作成成功！")
        richmenu_id = create_result.get("data", {}).get("richMenuId")
        print(f"   メニューID: {richmenu_id}")
        
        # 4. デフォルト設定
        if richmenu_id:
            print("\n4️⃣ デフォルト設定テスト...")
            default_result = client.set_default_richmenu(richmenu_id)
            
            if default_result.get("success"):
                print("✅ デフォルト設定成功！")
                print("\n🎉 Cloud Run プロキシ経由でのリッチメニュー修復完了！")
                print("📱 LINEアプリでリッチメニューを確認してください")
                return True
            else:
                print(f"❌ デフォルト設定失敗: {default_result.get('error')}")
    else:
        print(f"❌ リッチメニュー作成失敗: {create_result.get('error')}")
    
    return False

if __name__ == "__main__":
    test_cloud_run_proxy()