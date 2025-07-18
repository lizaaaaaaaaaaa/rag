# test_langsmith.py - 接続テスト用
import os
from langsmith import Client

def test_langsmith_connection():
    api_key = os.environ.get("LANGSMITH_API_KEY")
    
    if not api_key:
        print("❌ LANGSMITH_API_KEY が設定されていません")
        return False
    
    try:
        client = Client()
        # プロジェクト一覧を取得してテスト
        projects = client.list_projects()
        print("✅ LangSmith接続成功!")
        print(f"API Key: {api_key[:20]}...")
        return True
    except Exception as e:
        print(f"❌ LangSmith接続エラー: {e}")
        return False

if __name__ == "__main__":
    test_langsmith_connection()