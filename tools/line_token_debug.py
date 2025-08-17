# line_token_debug.py - LINEトークンの状態診断

import os
import logging

def diagnose_line_token():
    """LINEトークンの詳細診断"""
    print("🔍 LINE Token 診断開始")
    print("=" * 50)
    
    # 1. 環境変数から取得
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    
    if not token:
        print("❌ LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
        return False
    
    print("📋 トークン情報:")
    print(f"  型: {type(token)}")
    print(f"  長さ: {len(str(token))}")
    print(f"  最初の10文字: {str(token)[:10]}...")
    print(f"  最後の10文字: ...{repr(str(token)[-10:])}")
    
    # 2. 問題のある文字をチェック
    has_newline = any(char in str(token) for char in ['\r', '\n', '\t'])
    has_bearer = str(token).lower().startswith('bearer ')
    is_bytes = isinstance(token, bytes)
    
    print("\n🔍 問題チェック:")
    print(f"  改行文字あり: {'❌ YES' if has_newline else '✅ NO'}")
    print(f"  Bearer付き: {'⚠️ YES' if has_bearer else '✅ NO'}")
    print(f"  bytes型: {'❌ YES' if is_bytes else '✅ OK'}")
    
    # 3. 修正されたトークンを生成
    fixed_token = fix_token(token)
    
    print("\n🔧 修正後:")
    print(f"  型: {type(fixed_token)}")
    print(f"  長さ: {len(fixed_token)}")
    print(f"  最初の10文字: {fixed_token[:10]}...")
    print(f"  Bearer除去済み: {not fixed_token.startswith('Bearer ')}")
    print(f"  改行除去済み: {not any(char in fixed_token for char in ['\r', '\n'])}")
    
    return True

def fix_token(token):
    """トークンを正規化"""
    if token is None:
        return ""
    
    # bytes -> str
    if isinstance(token, bytes):
        try:
            token = token.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    
    # 文字列に変換
    token_str = str(token).strip()
    
    # Bearer プレフィックス除去
    if token_str.lower().startswith("bearer "):
        token_str = token_str[7:].strip()
    
    # Python bytes表現除去
    if token_str.startswith("b'") and token_str.endswith("'"):
        token_str = token_str[2:-1]
    
    # 改行文字除去
    token_str = token_str.replace('\r', '').replace('\n', '').replace('\t', '')
    
    # 引用符除去
    token_str = token_str.replace('"', '').replace("'", "")
    
    return token_str

if __name__ == "__main__":
    diagnose_line_token()