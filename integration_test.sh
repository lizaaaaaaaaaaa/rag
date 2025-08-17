#!/bin/bash
# integration_test.sh - 統合テストスクリプト

set -e

API_URL="https://rag-api-190389115361.asia-northeast1.run.app"
REGION="asia-northeast1"

echo "🔍 RAG システム統合テスト開始"
echo "================================"

# 1. API基本動作確認
echo "1️⃣ API基本動作確認..."
curl -f "$API_URL/healthz" > /dev/null && echo "✅ ヘルスチェック: OK" || echo "❌ ヘルスチェック: NG"

# 2. ハルチネーション対策状態確認
echo "2️⃣ ハルチネーション対策確認..."
curl -s "$API_URL/line/anti-hallucination-status" | jq -r '"✅ ハルチネーション対策: " + .status' 2>/dev/null || echo "❌ ハルチネーション対策: 取得失敗"

# 3. パフォーマンス統計確認
echo "3️⃣ パフォーマンス統計確認..."
curl -s "$API_URL/chat/performance-stats" | jq -r '"✅ キャッシュサイズ: " + (.cache_performance.size | tostring) + "/" + (.cache_performance.max_size | tostring)' 2>/dev/null || echo "❌ パフォーマンス統計: 取得失敗"

# 4. キャッシュクリアテスト
echo "4️⃣ キャッシュクリアテスト..."
curl -s -X POST "$API_URL/chat/clear-cache" -H "Content-Type: application/json" -d "{}" | jq -r '"✅ キャッシュクリア: " + .status' 2>/dev/null || echo "❌ キャッシュクリア: 失敗"

# 5. チャット応答テスト
echo "5️⃣ チャット応答テスト..."
response=$(curl -s -X POST "$API_URL/chat/" \
  -H "Content-Type: application/json" \
  -d '{"question":"坪単価について教えて","username":"test_user"}')

if echo "$response" | jq -e .answer > /dev/null 2>&1; then
  answer_length=$(echo "$response" | jq -r '.answer | length')
  echo "✅ チャット応答: OK (${answer_length}文字)"
else
  echo "❌ チャット応答: 失敗"
fi

# 6. Cloud Functions確認
echo "6️⃣ Cloud Functions確認..."
gcloud functions describe auto-update-function --region=$REGION --format="value(status)" 2>/dev/null && echo "✅ Cloud Functions: 存在" || echo "⚠️ Cloud Functions: 未デプロイ"

# 7. スケジューラー確認
echo "7️⃣ スケジューラー確認..."
gcloud scheduler jobs describe weekly-update --location=$REGION --format="value(state)" 2>/dev/null && echo "✅ スケジューラー: 存在" || echo "⚠️ スケジューラー: 未作成"

# 8. Pub/Sub確認
echo "8️⃣ Pub/Sub確認..."
gcloud pubsub topics describe update-trigger --format="value(name)" 2>/dev/null && echo "✅ Pub/Subトピック: 存在" || echo "❌ Pub/Subトピック: 未作成"

echo "================================"
echo "🎯 統合テスト完了"