# check_env.py - 環境変数確認スクリプト
import os
import json

def check_liff_environment():
    """LIFF関連環境変数の確認"""
    
    print("🔍 LIFF関連環境変数の確認")
    print("=" * 50)
    
    # 必須環境変数
    required_vars = {
        "LIFF_ID": "2007887876-vMNe74eX",
        "LIFF_CONSENT_URL": "https://liff.line.me/2007887876-vMNe74eX", 
        "LINE_BASIC_ID": "487urklv",
        "LINE_CHANNEL_ACCESS_TOKEN": "0AGc1F4u9kPkkpoErOdhG8dmdUeq9nFFxxdG284v5EuET8sekEI6ttCGCL5pKi6ffz2fwptBzNP1+zAYicWnL5xz1VDVtapPNG+42M4igl+aDmRLS2S0Lkeid3ARYcCAGQqTBsFJ483vI5HigJ1/ngdB04t89/1O/w1cDnyilFU=",
        "LINE_CHANNEL_ID": "2007826219",
        "LINE_CHANNEL_SECRET": "8f9b148f7cce65a6df6bc03d4434b929",
        "LINE_LOGIN_CHANNEL_ID": "2007887876", 
        "LINE_LOGIN_CHANNEL_SECRET": "df8851fd3f68ed00084226d18b7a2b19",
        "PUBLIC_API_BASE": "https://rag-api-190389115361.asia-northeast1.run.app",
        "PUBLIC_BASE_URL": "https://rag-api-190389115361.asia-northeast1.run.app",
    }
    
    # 環境変数チェック
    for var_name, expected_value in required_vars.items():
        current_value = os.getenv(var_name, "")
        status = "✅" if current_value == expected_value else "❌"
        print(f"{status} {var_name}")
        if current_value != expected_value:
            print(f"    期待値: {expected_value}")
            print(f"    現在値: {current_value or '(未設定)'}")
    
    print("\n🔍 Cloud Build設定の確認")
    print("=" * 50)
    
    # cloudbuild.yamlに追加すべき環境変数
    cloud_build_additions = """
# cloudbuild.yamlに以下を追加してください：

# 非機密環境変数セクションに追加：
- --set-env-vars=LIFF_ID=2007887876-vMNe74eX

# Secret Manager設定セクションに追加：
- --set-secrets=LIFF_CONSENT_URL=LIFF_CONSENT_URL:latest

# Secret Managerに以下のシークレットを作成してください：
gcloud secrets create LIFF_CONSENT_URL --data-file=- <<EOF
https://liff.line.me/2007887876-vMNe74eX
EOF
"""
    
    print(cloud_build_additions)
    
    print("\n🔍 LIFF設定の確認ポイント")
    print("=" * 50)
    
    liff_checklist = """
1. LINE Developers Consoleでの確認：
   - LIFF ID: 2007887876-vMNe74eX
   - エンドポイントURL: https://rag-api-190389115361.asia-northeast1.run.app/liff
   - サイズ: Full（推奨）
   - スコープ: profile, openid

2. LINE Login Channelでの確認：
   - Channel ID: 2007887876
   - Channel Secret: df8851fd3f68ed00084226d18b7a2b19
   - Callback URL: https://rag-api-190389115361.asia-northeast1.run.app/line-login/callback

3. Messaging API Channelでの確認：
   - Channel ID: 2007826219
   - Channel Secret: 8f9b148f7cce65a6df6bc03d4434b929
   - Webhook URL: https://rag-api-190389115361.asia-northeast1.run.app/line/webhook

4. 重要な設定：
   - LIFFアプリは LINE Login Channel (2007887876) に紐付ける
   - BOT機能は Messaging API Channel (2007826219) を使用
   - この2つのチャネルは連携設定が必要
"""
    
    print(liff_checklist)
    
    return True

if __name__ == "__main__":
    check_liff_environment()