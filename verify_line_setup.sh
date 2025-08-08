#!/bin/bash
# verify_line_setup.sh - LINE Bot + RAG システムの完全性確認

PROJECT_ID="rag-cloud-project"
SERVICE_NAME="rag-api"
REGION="asia-northeast1"

echo "🔍 LINE Bot + RAG システム設定確認"
echo "======================================"
echo

# 1. Secret Manager確認
echo "📋 Step 1: Secret Manager確認"
echo "------------------------------"

SECRETS=(
    "LINE_CHANNEL_ACCESS_TOKEN"
    "LINE_CHANNEL_SECRET"
    "LINE_LOGIN_CHANNEL_ID"
    "LINE_LOGIN_CHANNEL_SECRET"
    "LIFF_ID"
    "OPENAI_API_KEY"
    "GOOGLE_SEARCH_API_KEY"
    "GOOGLE_SEARCH_ENGINE_ID"
)

for secret in "${SECRETS[@]}"; do
    if gcloud secrets describe $secret --project=$PROJECT_ID &>/dev/null; then
        echo "✅ $secret: 設定済み"
    else
        echo "❌ $secret: 未設定"
    fi
done

echo

# 2. Cloud Run サービス確認
echo "📋 Step 2: Cloud Run サービス確認"
echo "----------------------------------"

SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
    --region=$REGION \
    --project=$PROJECT_ID \
    --format="value(status.url)" 2>/dev/null)

if [ -n "$SERVICE_URL" ]; then
    echo "✅ Cloud Run サービス URL: $SERVICE_URL"
    
    # ヘルスチェック
    HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL/healthz")
    if [ "$HEALTH_STATUS" = "200" ]; then
        echo "✅ ヘルスチェック: 正常 (HTTP $HEALTH_STATUS)"
    else
        echo "❌ ヘルスチェック: 異常 (HTTP $HEALTH_STATUS)"
    fi
    
    # LINE Bot状態確認
    LINE_STATUS=$(curl -s "$SERVICE_URL/line/status" 2>/dev/null)
    if echo "$LINE_STATUS" | grep -q '"line_bot_configured":true'; then
        echo "✅ LINE Bot: 設定済み"
    else
        echo "❌ LINE Bot: 未設定または設定エラー"
    fi
else
    echo "❌ Cloud Run サービスが見つかりません"
fi

echo

# 3. LINE API接続テスト
echo "📋 Step 3: LINE API接続テスト"
echo "-----------------------------"

# Secret Managerから TOKEN を取得
ACCESS_TOKEN=$(gcloud secrets versions access latest \
    --secret="LINE_CHANNEL_ACCESS_TOKEN" \
    --project=$PROJECT_ID 2>/dev/null)

if [ -n "$ACCESS_TOKEN" ]; then
    # LINE Bot情報取得
    BOT_INFO=$(curl -s -H "Authorization: Bearer $ACCESS_TOKEN" \
        "https://api.line.me/v2/bot/info" 2>/dev/null)
    
    if echo "$BOT_INFO" | grep -q "displayName"; then
        BOT_NAME=$(echo "$BOT_INFO" | grep -o '"displayName":"[^"]*"' | cut -d'"' -f4)
        echo "✅ LINE Bot接続成功: $BOT_NAME"
    else
        echo "❌ LINE Bot接続失敗"
    fi
else
    echo "❌ LINE_CHANNEL_ACCESS_TOKEN が取得できません"
fi

echo

# 4. リッチメニュー確認
echo "📋 Step 4: リッチメニュー確認"
echo "-----------------------------"

if [ -n "$ACCESS_TOKEN" ]; then
    RICHMENU_LIST=$(curl -s -H "Authorization: Bearer $ACCESS_TOKEN" \
        "https://api.line.me/v2/bot/richmenu/list" 2>/dev/null)
    
    MENU_COUNT=$(echo "$RICHMENU_LIST" | grep -o '"richMenuId"' | wc -l)
    
    if [ "$MENU_COUNT" -gt 0 ]; then
        echo "✅ リッチメニュー数: $MENU_COUNT"
        
        # デフォルトメニューの確認
        if echo "$RICHMENU_LIST" | grep -q '"selected":true'; then
            echo "✅ デフォルトメニュー: 設定済み"
        else
            echo "⚠️ デフォルトメニュー: 未設定"
        fi
    else
        echo "❌ リッチメニューが設定されていません"
    fi
fi

echo

# 5. RAGシステム確認
echo "📋 Step 5: RAGシステム確認"
echo "--------------------------"

# ステータス確認
STATUS_RESPONSE=$(curl -s "$SERVICE_URL/status" 2>/dev/null)

if echo "$STATUS_RESPONSE" | grep -q '"llm_loaded":true'; then
    echo "✅ LLM: ロード済み"
else
    echo "❌ LLM: 未ロード"
fi

if echo "$STATUS_RESPONSE" | grep -q '"vectorstore_loaded":true'; then
    echo "✅ VectorStore: ロード済み"
else
    echo "❌ VectorStore: 未ロード"
fi

if echo "$STATUS_RESPONSE" | grep -q '"rag_chain_loaded":true'; then
    echo "✅ RAG Chain: ロード済み"
else
    echo "❌ RAG Chain: 未ロード"
fi

echo

# 6. 推奨事項
echo "📋 推奨アクション"
echo "----------------"

echo "1. リッチメニューの再設定:"
echo "   python scripts/setup_fixed_richmenu.py"
echo ""
echo "2. Cloud Runサービスの再デプロイ:"
echo "   gcloud builds submit --config cloudbuild.yaml"
echo ""
echo "3. ログの確認:"
echo "   gcloud logging read 'resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"rag-api\"' --limit=50"
echo ""
echo "4. LINE公式アカウントでの動作確認:"
echo "   - リッチメニューが正しく表示されるか"