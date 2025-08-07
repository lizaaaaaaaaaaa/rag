#!/bin/bash
# update_cloudrun_env.sh - Cloud Runの環境変数を直接更新

echo "🔧 Cloud Run環境変数の直接更新"
echo ""

# LINE Developersから値を取得
echo "LINE Developersコンソールから以下の値をコピーしてください:"
echo ""
echo "1. Messaging API設定 → チャネル基本設定"
echo "   → チャネルシークレット"
echo ""
echo "2. Messaging API設定 → Messaging API設定"
echo "   → チャネルアクセストークン（長期）"
echo ""

read -p "チャネルアクセストークン（長期）を貼り付けてください: " ACCESS_TOKEN
read -p "チャネルシークレットを貼り付けてください: " CHANNEL_SECRET

# 値の確認
echo ""
echo "📝 入力された値:"
echo "TOKEN長さ: ${#ACCESS_TOKEN} 文字"
echo "SECRET長さ: ${#CHANNEL_SECRET} 文字"
echo ""

# トークンの長さチェック
if [ ${#ACCESS_TOKEN} -lt 150 ]; then
    echo "⚠️ 警告: トークンが短すぎる可能性があります（通常150文字以上）"
    echo "正しいトークンを取得していることを確認してください。"
    read -p "続行しますか？ (y/N): " continue_anyway
    if [[ $continue_anyway != "y" && $continue_anyway != "Y" ]]; then
        exit 1
    fi
fi

# Option 1: Secret Managerを使用する場合（推奨）
echo ""
echo "📌 方法1: Secret Managerを使用（推奨）"
echo ""

# 既存のシークレットを削除して再作成
echo "Secret Managerを更新中..."

# LINE_CHANNEL_ACCESS_TOKEN
echo -n "$ACCESS_TOKEN" | gcloud secrets create LINE_CHANNEL_ACCESS_TOKEN \
    --data-file=- \
    --project=rag-cloud-project \
    --replication-policy="automatic" 2>/dev/null || \
echo -n "$ACCESS_TOKEN" | gcloud secrets versions add LINE_CHANNEL_ACCESS_TOKEN \
    --data-file=- \
    --project=rag-cloud-project

# LINE_CHANNEL_SECRET
echo -n "$CHANNEL_SECRET" | gcloud secrets create LINE_CHANNEL_SECRET \
    --data-file=- \
    --project=rag-cloud-project \
    --replication-policy="automatic" 2>/dev/null || \
echo -n "$CHANNEL_SECRET" | gcloud secrets versions add LINE_CHANNEL_SECRET \
    --data-file=- \
    --project=rag-cloud-project

echo "✅ Secret Manager更新完了"

# Cloud Runサービスを更新
echo ""
echo "🚀 Cloud Runサービスを更新中..."

gcloud run deploy rag-api \
    --region=asia-northeast1 \
    --update-secrets=LINE_CHANNEL_ACCESS_TOKEN=LINE_CHANNEL_ACCESS_TOKEN:latest,LINE_CHANNEL_SECRET=LINE_CHANNEL_SECRET:latest

echo ""
echo "✅ 環境変数更新完了！"

# 動作確認
echo ""
echo "🧪 動作確認中..."
sleep 5

# APIステータス確認
echo "APIステータス:"
curl -s https://rag-api-190389115361.asia-northeast1.run.app/line/status 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "❌ API接続エラー"

echo ""
echo "LINE Bot情報確認:"
curl -s -H "Authorization: Bearer $ACCESS_TOKEN" https://api.line.me/v2/bot/info 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "❌ LINE API認証エラー"

echo ""
echo "📋 次のステップ:"
echo "1. 上記でボット情報が表示されれば認証成功"
echo "2. リッチメニューを再設定: python scripts/setup_richmenu_with_liff.py"
echo "3. LINE公式アカウントでリッチメニューの動作確認"