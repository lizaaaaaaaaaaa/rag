# line_token_fix.py - LINE トークン修正スクリプト

import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

def fix_line_token_normalization(token: Any) -> str:
    """LINE トークンの正規化を修正"""
    if token is None:
        logger.error("LINE_CHANNEL_ACCESS_TOKEN is None")
        return ""
    
    # bytes オブジェクトの処理
    if isinstance(token, bytes):
        try:
            token = token.decode("utf-8")
            logger.info("Decoded token from bytes")
        except UnicodeDecodeError as e:
            logger.error(f"Failed to decode token from bytes: {e}")
            return ""
    
    # 文字列に変換
    token_str = str(token).strip()
    
    # 不要なプレフィックスを削除
    if token_str.startswith("Bearer "):
        token_str = token_str[7:].strip()
        logger.info("Removed 'Bearer ' prefix")
    
    # Python のbytes表現を削除
    if token_str.startswith("b'") and token_str.endswith("'"):
        token_str = token_str[2:-1]
        logger.info("Removed Python bytes notation")
    
    # さらなるクリーンアップ
    token_str = token_str.replace('"', '').replace("'", "")
    
    # トークンの形式検証
    if not token_str:
        logger.error("Token is empty after normalization")
        return ""
    
    # LINE トークンの基本的な形式チェック
    if len(token_str) < 100:  # LINE トークンは通常100文字以上
        logger.warning(f"Token seems too short: {len(token_str)} characters")
    
    # 不正な文字のチェック
    if any(char in token_str for char in ['\n', '\r', '\t', ' ']):
        logger.warning("Token contains whitespace characters")
        token_str = ''.join(token_str.split())  # 全ての空白文字を削除
    
    logger.info(f"Normalized token length: {len(token_str)}")
    return token_str

def validate_line_credentials():
    """LINE 認証情報の検証"""
    
    # 環境変数から取得
    access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    channel_secret = os.getenv("LINE_CHANNEL_SECRET")
    
    print("🔍 LINE 認証情報の検証")
    print("=" * 50)
    
    # ACCESS TOKEN の検証
    print("📝 ACCESS TOKEN:")
    if access_token:
        normalized_token = fix_line_token_normalization(access_token)
        print(f"  元のタイプ: {type(access_token)}")
        print(f"  元の長さ: {len(str(access_token))}")
        print(f"  正規化後の長さ: {len(normalized_token)}")
        print(f"  最初の10文字: {normalized_token[:10]}...")
        print(f"  最後の10文字: ...{normalized_token[-10:]}")
        
        # 正規化されたトークンの検証
        if len(normalized_token) < 100:
            print("  ⚠️ 警告: トークンが短すぎます")
        if not normalized_token.isalnum():
            print("  ⚠️ 警告: 英数字以外の文字が含まれています")
        else:
            print("  ✅ トークン形式OK")
    else:
        print("  ❌ ACCESS TOKEN が設定されていません")
    
    print()
    
    # CHANNEL SECRET の検証
    print("🔐 CHANNEL SECRET:")
    if channel_secret:
        normalized_secret = fix_line_token_normalization(channel_secret)
        print(f"  タイプ: {type(channel_secret)}")
        print(f"  正規化後の長さ: {len(normalized_secret)}")
        print(f"  最初の10文字: {normalized_secret[:10]}...")
        
        if len(normalized_secret) < 30:
            print("  ⚠️ 警告: シークレットが短すぎます")
        else:
            print("  ✅ シークレット形式OK")
    else:
        print("  ❌ CHANNEL SECRET が設定されていません")
    
    print()
    
    # 修正版のトークンを返す
    return (
        fix_line_token_normalization(access_token) if access_token else "",
        fix_line_token_normalization(channel_secret) if channel_secret else ""
    )

def test_line_api_connection(access_token: str):
    """LINE API 接続テスト"""
    import requests
    
    if not access_token:
        print("❌ テスト不可: トークンがありません")
        return False
    
    print("🌐 LINE API 接続テスト")
    
    try:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        # Bot 情報取得
        response = requests.get(
            "https://api.line.me/v2/bot/info",
            headers=headers,
            timeout=10
        )
        
        print(f"  ステータスコード: {response.status_code}")
        
        if response.status_code == 200:
            bot_info = response.json()
            print(f"  ✅ 接続成功!")
            print(f"  Bot名: {bot_info.get('displayName', '不明')}")
            print(f"  Bot ID: {bot_info.get('userId', '不明')}")
            return True
        elif response.status_code == 401:
            print("  ❌ 認証エラー: トークンが無効です")
        else:
            print(f"  ❌ エラー: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"  ❌ 接続エラー: {e}")
    
    return False

if __name__ == "__main__":
    print("🔧 LINE トークン修正ツール")
    print("=" * 50)
    
    # 認証情報検証
    fixed_token, fixed_secret = validate_line_credentials()
    
    # API接続テスト
    if fixed_token:
        test_line_api_connection(fixed_token)
    
    print("\n💡 修正方法:")
    print("1. Secret Manager で正しいトークンを設定")
    print("2. Cloud Run の環境変数を再設定") 
    print("3. サービスを再起動")