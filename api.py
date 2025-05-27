# api.py

import os
import requests

# Cloud Run本番環境なら --set-env-vars でAPI_URLを注入するので .env不要
API_URL = os.environ.get("API_URL", "http://localhost:8000")

def post_chat(question, user):
    """チャットAPI（/chat）にPOSTリクエストして返却"""
    try:
        response = requests.post(
            f"{API_URL}/chat",
            json={"question": question, "user": user},
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"result": f"❌ APIエラー: {e}"}
