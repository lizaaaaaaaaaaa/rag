#!/usr/bin/env python3
"""
起動テストスクリプト - Pythonの構文エラーや依存関係の問題を事前に検出
"""
import sys
import subprocess

def test_syntax():
    """全てのPythonファイルの構文をチェック"""
    print("=== Pythonファイルの構文チェック ===")
    
    python_files = subprocess.run(
        ["find", ".", "-name", "*.py", "-type", "f"],
        capture_output=True,
        text=True
    ).stdout.strip().split('\n')
    
    errors = []
    for file in python_files:
        if file and not file.startswith('./venv'):
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", file],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                errors.append(f"{file}: {result.stderr}")
            else:
                print(f"✓ {file}")
    
    if errors:
        print("\n❌ 構文エラーが見つかりました:")
        for error in errors:
            print(error)
        return False
    else:
        print("\n✅ 全てのファイルの構文チェックOK")
        return True

def test_imports():
    """主要なモジュールのインポートをテスト"""
    print("\n=== インポートテスト ===")
    
    test_modules = [
        "main",
        "utils.web_search",
        "api.routers.chat",
        "rag.ingested_text",
        "llm.llm_runner"
    ]
    
    errors = []
    for module in test_modules:
        try:
            __import__(module)
            print(f"✓ {module}")
        except Exception as e:
            errors.append(f"{module}: {e}")
    
    if errors:
        print("\n❌ インポートエラー:")
        for error in errors:
            print(error)
        return False
    else:
        print("\n✅ 全てのモジュールのインポートOK")
        return True

def test_server_startup():
    """FastAPIサーバーの起動テスト（5秒間）"""
    print("\n=== FastAPIサーバー起動テスト ===")
    
    import time
    import threading
    
    def run_server():
        subprocess.run([sys.executable, "main.py"])
    
    # サーバーを別スレッドで起動
    server_thread = threading.Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    
    # 5秒待機
    print("サーバー起動中...")
    time.sleep(5)
    
    # ポート8080をチェック
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('localhost', 8080))
    sock.close()
    
    if result == 0:
        print("✅ サーバーがポート8080で正常に起動しました")
        return True
    else:
        print("❌ サーバーがポート8080で起動していません")
        return False

if __name__ == "__main__":
    print("RAGアプリケーション起動テスト\n")
    
    # 1. 構文チェック
    if not test_syntax():
        sys.exit(1)
    
    # 2. インポートチェック
    if not test_imports():
        sys.exit(1)
    
    # 3. サーバー起動チェック（オプション）
    # test_server_startup()
    
    print("\n✅ 全てのテストが完了しました！")