# api/routers/line_proxy.py (指定文面対応修正版)
"""
Cloud Run 経由 LINE API プロキシエンドポイント
ローカル環境の制限を回避してLINE APIにアクセス（指定文面対応版）
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
    """🔧 リッチメニュー作成（指定文面対応版）"""
    request = LineAPIRequest(endpoint="bot/richmenu", method="POST", data=richmenu_data)
    return await proxy_line_api(request)

@router.post("/richmenu-create-specified")
async def create_specified_richmenu():
    """🔧 指定文面対応リッチメニュー作成（定義済み）"""
    
    # 指定文面対応リッチメニュー定義
    specified_richmenu_data = {
        "size": {"width": 2500, "height": 1686},
        "selected": True,
        "name": "キノエデザイン指定文面対応メニュー",
        "chatBarText": "メニュー",
        "areas": [
            {
                # 🤖 AI相談
                "bounds": {"x": 0, "y": 0, "width": 833, "height": 843},
                "action": {"type": "message", "text": "🤖 AI相談"}
            },
            {
                # 🌐 AI住まいサイト
                "bounds": {"x": 833, "y": 0, "width": 834, "height": 843},
                "action": {"type": "message", "text": "🌐 AI住まいサイト"}
            },
            {
                # 📄 資料請求
                "bounds": {"x": 1667, "y": 0, "width": 833, "height": 843},
                "action": {"type": "message", "text": "📄 資料請求"}
            },
            {
                # 📍 展示場来場予約
                "bounds": {"x": 0, "y": 843, "width": 833, "height": 843},
                "action": {"type": "message", "text": "📍 展示場来場　予約"}
            },
            {
                # 💰 資金計画
                "bounds": {"x": 833, "y": 843, "width": 834, "height": 843},
                "action": {"type": "message", "text": "💰 資金計画"}
            },
            {
                # 💬 チャット相談
                "bounds": {"x": 1667, "y": 843, "width": 833, "height": 843},
                "action": {"type": "message", "text": "💬 チャット相談"}
            }
        ]
    }
    
    request = LineAPIRequest(
        endpoint="bot/richmenu", 
        method="POST", 
        data=specified_richmenu_data
    )
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

@router.delete("/richmenu-remove-default")
async def remove_default_richmenu():
    """デフォルトリッチメニュー削除"""
    request = LineAPIRequest(endpoint="bot/user/all/richmenu", method="DELETE")
    return await proxy_line_api(request)

@router.get("/richmenu-validate/{richmenu_id}")
async def validate_richmenu(richmenu_id: str):
    """🔧 リッチメニューの指定文面対応検証"""
    try:
        # リッチメニュー詳細取得
        request = LineAPIRequest(endpoint=f"bot/richmenu/{richmenu_id}", method="GET")
        result = await proxy_line_api(request)
        
        if not result.get("success"):
            return {"valid": False, "error": "Failed to get richmenu details"}
        
        richmenu_data = result.get("data", {})
        areas = richmenu_data.get("areas", [])
        
        # 指定文面対応チェック
        expected_actions = [
            "🤖 AI相談",
            "🌐 AI住まいサイト", 
            "📄 資料請求",
            "📍 展示場来場　予約",
            "💰 資金計画",
            "💬 チャット相談"
        ]
        
        actual_actions = []
        for area in areas:
            action = area.get("action", {})
            if action.get("type") == "message":
                actual_actions.append(action.get("text", ""))
        
        # 期待アクションとの一致確認
        missing_actions = [action for action in expected_actions if action not in actual_actions]
        unexpected_actions = [action for action in actual_actions if action not in expected_actions]
        
        validation_result = {
            "valid": len(missing_actions) == 0 and len(unexpected_actions) == 0,
            "richmenu_id": richmenu_id,
            "name": richmenu_data.get("name", "Unknown"),
            "total_areas": len(areas),
            "expected_actions": expected_actions,
            "actual_actions": actual_actions,
            "missing_actions": missing_actions,
            "unexpected_actions": unexpected_actions,
            "compliance": {
                "specified_content_compliant": len(missing_actions) == 0,
                "no_extra_actions": len(unexpected_actions) == 0,
                "correct_button_count": len(areas) == 6,
                "correct_size": richmenu_data.get("size", {}) == {"width": 2500, "height": 1686}
            }
        }
        
        return validation_result
        
    except Exception as e:
        return {
            "valid": False,
            "error": f"Validation failed: {str(e)}",
            "richmenu_id": richmenu_id
        }

@router.post("/richmenu-batch-setup")
async def batch_setup_specified_richmenu():
    """🔧 指定文面対応リッチメニューのバッチセットアップ"""
    try:
        setup_log = []
        
        # 1. 既存リッチメニュー一覧取得
        list_request = LineAPIRequest(endpoint="bot/richmenu/list", method="GET")
        list_result = await proxy_line_api(list_request)
        
        if list_result.get("success"):
            existing_menus = list_result.get("data", {}).get("richmenus", [])
            setup_log.append(f"Found {len(existing_menus)} existing richmenus")
            
            # 2. 既存メニュー削除
            for menu in existing_menus:
                menu_id = menu.get("richMenuId")
                if menu_id:
                    delete_request = LineAPIRequest(
                        endpoint=f"bot/richmenu/{menu_id}", 
                        method="DELETE"
                    )
                    delete_result = await proxy_line_api(delete_request)
                    if delete_result.get("success"):
                        setup_log.append(f"Deleted richmenu: {menu_id}")
                    else:
                        setup_log.append(f"Failed to delete richmenu: {menu_id}")
        
        # 3. 指定文面対応リッチメニュー作成
        create_result = await create_specified_richmenu()
        
        if create_result.get("success"):
            new_richmenu_id = create_result.get("data", {}).get("richMenuId")
            setup_log.append(f"Created specified richmenu: {new_richmenu_id}")
            
            # 4. デフォルト設定
            if new_richmenu_id:
                default_result = await set_default_richmenu(new_richmenu_id)
                if default_result.get("success"):
                    setup_log.append(f"Set as default: {new_richmenu_id}")
                    
                    # 5. 検証
                    validation_result = await validate_richmenu(new_richmenu_id)
                    
                    return {
                        "success": True,
                        "richmenu_id": new_richmenu_id,
                        "setup_log": setup_log,
                        "validation": validation_result,
                        "message": "指定文面対応リッチメニューのセットアップが完了しました"
                    }
                else:
                    setup_log.append("Failed to set as default")
        
        return {
            "success": False,
            "setup_log": setup_log,
            "message": "Setup failed at some point"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Batch setup failed with exception"
        }

@router.get("/richmenu-compliance-check")
async def check_richmenu_compliance():
    """🔧 全リッチメニューの指定文面コンプライアンスチェック"""
    try:
        # リッチメニュー一覧取得
        list_request = LineAPIRequest(endpoint="bot/richmenu/list", method="GET")
        list_result = await proxy_line_api(list_request)
        
        if not list_result.get("success"):
            return {"success": False, "error": "Failed to get richmenu list"}
        
        richmenus = list_result.get("data", {}).get("richmenus", [])
        compliance_results = []
        
        for menu in richmenus:
            menu_id = menu.get("richMenuId")
            if menu_id:
                validation_result = await validate_richmenu(menu_id)
                compliance_results.append(validation_result)
        
        # サマリー作成
        total_menus = len(compliance_results)
        compliant_menus = len([r for r in compliance_results if r.get("valid", False)])
        
        summary = {
            "total_richmenus": total_menus,
            "compliant_richmenus": compliant_menus,
            "compliance_rate": (compliant_menus / total_menus * 100) if total_menus > 0 else 0,
            "non_compliant_richmenus": total_menus - compliant_menus,
            "recommendations": []
        }
        
        if compliant_menus == 0:
            summary["recommendations"].append("指定文面対応リッチメニューを作成してください")
        elif compliant_menus < total_menus:
            summary["recommendations"].append("非対応のリッチメニューを削除して整理してください")
        else:
            summary["recommendations"].append("全てのリッチメニューが指定文面に対応しています")
        
        return {
            "success": True,
            "summary": summary,
            "detailed_results": compliance_results,
            "timestamp": json.dumps({"timestamp": "now"})  # JSON serializable
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Compliance check failed"
        }

# ==================================================
# ローカル環境用 Cloud Run プロキシクライアント（指定文面対応版）
# ==================================================

# local_line_client.py (ローカル用)
"""
ローカル環境から Cloud Run 経由で LINE API を使用するクライアント（指定文面対応版）
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
    
    def create_specified_richmenu(self) -> Dict:
        """🔧 指定文面対応リッチメニュー作成"""
        try:
            response = requests.post(f"{self.base_url}/richmenu-create-specified", timeout=30)
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
    
    def validate_richmenu(self, richmenu_id: str) -> Dict:
        """🔧 リッチメニュー指定文面対応検証"""
        try:
            response = requests.get(f"{self.base_url}/richmenu-validate/{richmenu_id}", timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def batch_setup_specified_richmenu(self) -> Dict:
        """🔧 指定文面対応リッチメニューバッチセットアップ"""
        try:
            response = requests.post(f"{self.base_url}/richmenu-batch-setup", timeout=60)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e), "success": False}
    
    def check_compliance(self) -> Dict:
        """🔧 指定文面コンプライアンスチェック"""
        try:
            response = requests.get(f"{self.base_url}/richmenu-compliance-check", timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e), "success": False}

# test_cloud_run_proxy.py (テスト用) - 指定文面対応版
"""
Cloud Run プロキシ経由での LINE API テスト（指定文面対応版）
"""

def test_specified_cloud_run_proxy():
    print("🌐 Cloud Run プロキシ経由 LINE API テスト（指定文面対応版）")
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
    
    # 2. 指定文面対応リッチメニューバッチセットアップ
    print("\n2️⃣ 指定文面対応リッチメニューバッチセットアップ...")
    batch_result = client.batch_setup_specified_richmenu()
    
    if batch_result.get("success"):
        print("✅ バッチセットアップ成功！")
        richmenu_id = batch_result.get("richmenu_id")
        validation = batch_result.get("validation", {})
        print(f"   リッチメニューID: {richmenu_id}")
        print(f"   検証結果: {'✅ 合格' if validation.get('valid') else '❌ 不合格'}")
        
        if validation.get("compliance"):
            compliance = validation["compliance"]
            print(f"   指定文面対応: {'✅' if compliance.get('specified_content_compliant') else '❌'}")
            print(f"   ボタン数正常: {'✅' if compliance.get('correct_button_count') else '❌'}")
            print(f"   サイズ正常: {'✅' if compliance.get('correct_size') else '❌'}")
    else:
        print(f"❌ バッチセットアップ失敗: {batch_result.get('error')}")
    
    # 3. コンプライアンスチェック
    print("\n3️⃣ 指定文面コンプライアンスチェック...")
    compliance_result = client.check_compliance()
    
    if compliance_result.get("success"):
        summary = compliance_result.get("summary", {})
        print("✅ コンプライアンスチェック成功！")
        print(f"   総リッチメニュー数: {summary.get('total_richmenus')}")
        print(f"   指定文面対応数: {summary.get('compliant_richmenus')}")
        print(f"   対応率: {summary.get('compliance_rate', 0):.1f}%")
        
        recommendations = summary.get("recommendations", [])
        if recommendations:
            print(f"   推奨事項:")
            for rec in recommendations:
                print(f"     • {rec}")
    else:
        print(f"❌ コンプライアンスチェック失敗: {compliance_result.get('error')}")
    
    print("\n🎉 指定文面対応 Cloud Run プロキシテスト完了！")
    print("📱 LINEアプリでリッチメニューの動作を確認してください")
    
    return True

if __name__ == "__main__":
    test_specified_cloud_run_proxy()