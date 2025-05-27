# api.py

import os
from dotenv import load_dotenv
import requests

# ローカル時のみ .env を読む
load_dotenv()

API_URL = os.getenv("API_URL", "http://localhost:8000")

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
