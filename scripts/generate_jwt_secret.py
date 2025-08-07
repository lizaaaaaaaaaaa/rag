#!/usr/bin/env python3
"""
JWT Secret生成スクリプト
python generate_jwt_secret.py
"""

import secrets
import string

def generate_jwt_secret(length=64):
    """安全なJWT Secretを生成"""
    # 英数字と記号を組み合わせた文字セット
    charset = string.ascii_letters + string.digits + "!@#$%^&*()_+-="
    
    # 暗号学的に安全な乱数でSecretを生成
    jwt_secret = ''.join(secrets.choice(charset) for _ in range(length))
    
    return jwt_secret

if __name__ == "__main__":
    print("🔐 JWT Secret生成中...")
    
    # 複数の長さで生成
    secrets_data = {
        "推奨 (64文字)": generate_jwt_secret(64),
        "短め (32文字)": generate_jwt_secret(32),
        "長め (128文字)": generate_jwt_secret(128)
    }
    
    print("\n📋 生成されたJWT Secret:")
    print("=" * 80)
    
    for label, secret in secrets_data.items():
        print(f"{label}:")
        print(f"  {secret}")
        print()
    
    print("⚠️ 注意事項:")
    print("- JWT Secretは絶対に公開しないでください")
    print("- 本番環境では必ず64文字以上を使用してください")
    print("- Secret ManagerやCloud Runの環境変数に保存してください")
    print()
    
    print("💡 推奨:")
    recommended = secrets_data["推奨 (64文字)"]
    print(f"本番用JWT Secret: {recommended}")