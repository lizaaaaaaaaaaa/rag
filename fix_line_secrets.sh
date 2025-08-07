#!/bin/bash
# fix_line_secrets.sh - LINE Bot認証問題を修正するスクリプト

PROJECT_ID="rag-cloud-project"

echo "🔍 LINE Bot 認証設定修正スクリプト"
echo "Project ID: $PROJECT_ID"
echo ""

# 1. 現在のSecret Managerの値を確認
echo "📋 現在のSecret Manager設定を確認中..."
echo ""

# LINE_CHANNEL_ACCESS_TOKENの確認
echo "1. LINE_CHANNEL_ACCESS_TOKEN:"
gcloud secrets versions access latest --secret="LINE_CHANNEL_ACCESS_TOKEN" --project=$PROJECT_ID 2>/dev/null | head -c 30
if [ $? -ne 0 ]; then
    echo "❌ 設定されていません"
else
    echo "... (設定済み)"
fi
echo ""

# LINE_CHANNEL_SECRETの確認
echo "2. LINE_CHANNEL_SECRET:"
gcloud secrets versions access latest --secret="LINE_CHANNEL_SECRET" --project=$PROJECT_ID 2>/dev/null | head -c 20
if [ $? -ne 0 ]; then
    echo "❌ 設定されていません"
else
    echo "... (設定済み)"
fi
echo ""

# 2. LINE Developersから正しい値を設定
echo "🔐 LINE Developersから取得した値で更新します"
echo ""
echo "以下の値をLINE Developersコンソールから確認してください:"
echo "1. Messaging API設定 → チャネルアクセストークン（長期）"
echo "2. チャネル基本設定 → チャネルシークレット"
echo ""

read -p "チャネルアクセストークン（長期）を入力してください: " ACCESS_TOKEN
read -p "チャネルシークレットを入力してください: " CHANNEL_SECRET

# 入力値の確認
echo ""
echo "📝 入力された値:"
echo "ACCESS_TOKEN: ${ACCESS_TOKEN:0:30}..."
echo "CHANNEL_SECRET: ${CHANNEL_SECRET:0:20}..."
echo ""

read -p "これらの値でSecret Managerを更新しますか？ (y/N): " confirm

if [[ $confirm != "y" && $confirm != "Y" ]]; then
    echo "❌ キャンセルしました"
    exit 1
fi

# 3. Secret Managerを更新
echo ""
echo "🔄 Secret Managerを更新中..."

# 既存のSecretを削除
echo "既存のSecretを削除中..."
gcloud secrets delete LINE_CHANNEL_ACCESS_TOKEN --project=$PROJECT_ID --quiet 2>/dev/null || true
gcloud secrets delete LINE_CHANNEL_SECRET --project=$PROJECT_ID --quiet 2>/dev/null || true

# 新しいSecretを作成
echo "新しいSecretを作成中..."

# LINE_CHANNEL_ACCESS_TOKEN
echo -n "$ACCESS_TOKEN" | gcloud secrets create LINE_CHANNEL_ACCESS_TOKEN \
    --data-file=- \
    --project=$PROJECT_ID \
    --replication-policy="automatic"

# LINE_CHANNEL_SECRET  
echo -n "$CHANNEL_SECRET" | gcloud secrets create LINE_CHANNEL_SECRET \
    --data-file=- \
    --project=$PROJECT_ID \
    --replication-policy="automatic"

echo ""
echo "✅ Secret Manager更新完了"

# 4. Cloud Runサービスを再デプロイ
echo ""
echo "🚀 Cloud Runサービスを再デプロイします..."
echo ""

read -p "Cloud Runサービスを再デプロイしますか？ (y/N): " redeploy

if [[ $redeploy == "y" || $redeploy == "Y" ]]; then
    echo "再デプロイ中..."
    
    # cloudbuild.yamlを使用して再デプロイ
    gcloud builds submit --config cloudbuild.yaml
    
    echo "✅ 再デプロイ完了"
else
    echo "⚠️ 手動で再デプロイしてください:"
    echo "gcloud builds submit --config cloudbuild.yaml"
fi

# 5. 動作確認
echo ""
echo "🧪 動作確認..."
echo ""

# APIステータス確認
echo "APIステータスを確認中..."
curl -s https://rag-api-190389115361.asia-northeast1.run.app/line/status | python3 -m json.tool

echo ""
echo "✅ 設定完了！"
echo ""
echo "📋 次のステップ:"
echo "1. LINE公式アカウントマネージャーで確認"
echo "2. リッチメニューが表示されることを確認"
echo "3. ボタンをタップして動作確認"