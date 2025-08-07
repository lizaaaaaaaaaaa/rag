#!/bin/bash
# scripts/setup_actual_line_secrets.sh - 実際の値でSecret Manager設定

PROJECT_ID="rag-cloud-project"

echo "🔐 LINEログイン用Secret Manager設定（実際の値）..."
echo "Project ID: $PROJECT_ID"
echo

# 実際の値を設定
LINE_LOGIN_CHANNEL_ID="2007887876"
LINE_LOGIN_CHANNEL_SECRET="df8851fd3f68ed00084226d18b7a2b19"
LIFF_ID="2007887876-vMNe74eX"
LINE_LOGIN_REDIRECT_URI="https://rag-api-190389115361.asia-northeast1.run.app/line-login/callback"

# JWT Secretを生成（または手動で設定）
echo "🔐 JWT Secret生成中..."
JWT_SECRET=$(openssl rand -base64 48 | tr -d '\n')

echo
echo "🔍 設定確認:"
echo "LINE_LOGIN_CHANNEL_ID: $LINE_LOGIN_CHANNEL_ID"
echo "LINE_LOGIN_CHANNEL_SECRET: ${LINE_LOGIN_CHANNEL_SECRET:0:10}..."
echo "LIFF_ID: $LIFF_ID"
echo "LINE_LOGIN_REDIRECT_URI: $LINE_LOGIN_REDIRECT_URI"
echo "JWT_SECRET: ${JWT_SECRET:0:10}..."
echo

read -p "この設定でSecret Managerに保存しますか？ (y/N): " confirm

if [[ $confirm != "y" && $confirm != "Y" ]]; then
    echo "❌ キャンセルしました"
    exit 1
fi

echo
echo "📝 Secret Manager に保存中..."

# 既存のSecretを削除（エラーは無視）
echo "既存のSecretを削除中..."
gcloud secrets delete LINE_LOGIN_CHANNEL_ID --project=$PROJECT_ID --quiet 2>/dev/null || true
gcloud secrets delete LINE_LOGIN_CHANNEL_SECRET --project=$PROJECT_ID --quiet 2>/dev/null || true
gcloud secrets delete LINE_LOGIN_REDIRECT_URI --project=$PROJECT_ID --quiet 2>/dev/null || true
gcloud secrets delete LIFF_ID --project=$PROJECT_ID --quiet 2>/dev/null || true
gcloud secrets delete JWT_SECRET --project=$PROJECT_ID --quiet 2>/dev/null || true

# 新しいSecretを作成
echo
echo "新しいSecretを作成中..."

# 1. LINE_LOGIN_CHANNEL_ID
echo "LINE_LOGIN_CHANNEL_ID を作成中..."
echo "$LINE_LOGIN_CHANNEL_ID" | gcloud secrets create LINE_LOGIN_CHANNEL_ID \
    --data-file=- \
    --project=$PROJECT_ID

# 2. LINE_LOGIN_CHANNEL_SECRET
echo "LINE_LOGIN_CHANNEL_SECRET を作成中..."
echo "$LINE_LOGIN_CHANNEL_SECRET" | gcloud secrets create LINE_LOGIN_CHANNEL_SECRET \
    --data-file=- \
    --project=$PROJECT_ID

# 3. LINE_LOGIN_REDIRECT_URI
echo "LINE_LOGIN_REDIRECT_URI を作成中..."
echo "$LINE_LOGIN_REDIRECT_URI" | gcloud secrets create LINE_LOGIN_REDIRECT_URI \
    --data-file=- \
    --project=$PROJECT_ID

# 4. LIFF_ID
echo "LIFF_ID を作成中..."
echo "$LIFF_ID" | gcloud secrets create LIFF_ID \
    --data-file=- \
    --project=$PROJECT_ID

# 5. JWT_SECRET
echo "JWT_SECRET を作成中..."
echo "$JWT_SECRET" | gcloud secrets create JWT_SECRET \
    --data-file=- \
    --project=$PROJECT_ID

echo
echo "✅ Secret Manager設定完了！"
echo
echo "📋 作成されたSecret:"
echo "- LINE_LOGIN_CHANNEL_ID: $LINE_LOGIN_CHANNEL_ID"
echo "- LINE_LOGIN_CHANNEL_SECRET: ${LINE_LOGIN_CHANNEL_SECRET:0:10}..."
echo "- LINE_LOGIN_REDIRECT_URI: $LINE_LOGIN_REDIRECT_URI"
echo "- LIFF_ID: $LIFF_ID"
echo "- JWT_SECRET: ${JWT_SECRET:0:10}..."
echo
echo "🔍 確認コマンド:"
echo "gcloud secrets list --project=$PROJECT_ID | grep -E '(LINE_LOGIN|LIFF|JWT)'"
echo
echo "🚀 次のステップ:"
echo "1. cloudbuild.yamlを更新"
echo "2. gcloud builds submit --config cloudbuild.yaml"
echo "3. LIFF対応リッチメニューを設定"