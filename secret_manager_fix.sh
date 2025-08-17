#!/bin/bash
# secret_manager_fix.sh - Secret Manager のトークン修正

PROJECT_ID="rag-cloud-project"

echo "🔧 Secret Manager トークン修正スクリプト"
echo "=========================================="

# 現在のSecret値を確認（マスク表示）
echo "📋 現在のSecret状態確認..."

# Access Token の確認
echo "1. LINE_CHANNEL_ACCESS_TOKEN:"
gcloud secrets versions access latest --secret="LINE_CHANNEL_ACCESS_TOKEN" --project="$PROJECT_ID" | wc -c | xargs echo "  バイト数:"
gcloud secrets versions access latest --secret="LINE_CHANNEL_ACCESS_TOKEN" --project="$PROJECT_ID" | tail -c 10 | od -c | head -1

# Channel Secret の確認
echo "2. LINE_CHANNEL_SECRET:"
gcloud secrets versions access latest --secret="LINE_CHANNEL_SECRET" --project="$PROJECT_ID" | wc -c | xargs echo "  バイト数:"
gcloud secrets versions access latest --secret="LINE_CHANNEL_SECRET" --project="$PROJECT_ID" | tail -c 10 | od -c | head -1

echo ""
echo "⚠️ 上記で 'ん' や 'た' などの文字が見える場合、末尾に改行が含まれています"
echo ""

# 修正の提案
cat << 'EOF'
🔧 修正方法:

1. 新しいバージョンを作成（改行なし）:
   echo -n "YOUR_ACTUAL_TOKEN_HERE" | gcloud secrets versions add LINE_CHANNEL_ACCESS_TOKEN --data-file=-
   echo -n "YOUR_ACTUAL_SECRET_HERE" | gcloud secrets versions add LINE_CHANNEL_SECRET --data-file=-

2. Cloud Run 再デプロイ:
   gcloud run deploy rag-api --region=asia-northeast1

3. ログ確認:
   gcloud run logs read rag-api --region=asia-northeast1 --limit=50

📋 確認すべきログ:
- "✅ LINE Bot API v3 initialized successfully"
- "🚀 Using normalized token: len=XXX"
- "❌" や "Invalid header value" が出ていないか

EOF

echo ""
read -p "Secret Manager を自動修正しますか？ (現在のトークンを取得して改行除去版を作成) [y/N]: " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🔄 自動修正を実行中..."
    
    # Access Token の修正
    echo "1. Access Token を修正中..."
    CURRENT_TOKEN=$(gcloud secrets versions access latest --secret="LINE_CHANNEL_ACCESS_TOKEN" --project="$PROJECT_ID")
    CLEANED_TOKEN=$(echo -n "$CURRENT_TOKEN" | tr -d '\r\n\t' | sed 's/^Bearer //' | sed 's/^b'\''//;s/'\''$//' | tr -d '"'"'"'')
    
    if [ ${#CLEANED_TOKEN} -gt 50 ]; then
        echo -n "$CLEANED_TOKEN" | gcloud secrets versions add LINE_CHANNEL_ACCESS_TOKEN --data-file=- --project="$PROJECT_ID"
        echo "  ✅ Access Token 修正完了"
    else
        echo "  ❌ Access Token が短すぎます: ${#CLEANED_TOKEN} 文字"
    fi
    
    # Channel Secret の修正
    echo "2. Channel Secret を修正中..."
    CURRENT_SECRET=$(gcloud secrets versions access latest --secret="LINE_CHANNEL_SECRET" --project="$PROJECT_ID")
    CLEANED_SECRET=$(echo -n "$CURRENT_SECRET" | tr -d '\r\n\t' | sed 's/^Bearer //' | sed 's/^b'\''//;s/'\''$//' | tr -d '"'"'"'')
    
    if [ ${#CLEANED_SECRET} -gt 20 ]; then
        echo -n "$CLEANED_SECRET" | gcloud secrets versions add LINE_CHANNEL_SECRET --data-file=- --project="$PROJECT_ID"
        echo "  ✅ Channel Secret 修正完了"
    else
        echo "  ❌ Channel Secret が短すぎます: ${#CLEANED_SECRET} 文字"
    fi
    
    echo ""
    echo "🚀 Cloud Run 再デプロイを実行しますか？"
    read -p "[y/N]: " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "📦 Cloud Run 再デプロイ中..."
        gcloud run deploy rag-api \
            --image="asia-northeast1-docker.pkg.dev/rag-cloud-project/rag-chat-pro/rag-api:latest" \
            --region=asia-northeast1 \
            --quiet
        
        echo "✅ 再デプロイ完了!"
        echo ""
        echo "📋 確認コマンド:"
        echo "gcloud run logs read rag-api --region=asia-northeast1 --limit=20"
        echo ""
        echo "🧪 テスト方法:"
        echo "LINEでリッチメニューを押して応答があるか確認してください"
    fi
else
    echo "手動修正を選択しました"
fi