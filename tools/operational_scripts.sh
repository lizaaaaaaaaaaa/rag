#!/bin/bash
# tools/operational_scripts.sh - 運用スクリプト集

set -euo pipefail

# 設定
PROJECT_ID="rag-cloud-project"
REGION="asia-northeast1"
API_URL="https://rag-api-190389115361.asia-northeast1.run.app"
SERVICE_NAME="rag-api-enhanced"

# 色付きログ
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# =============================================================================
# 1. システム状態確認
# =============================================================================

check_system_health() {
    log_info "🔍 システム全体の健康状態を確認中..."
    
    echo "=== Cloud Run サービス状態 ==="
    gcloud run services describe $SERVICE_NAME --region=$REGION --format="table(
        metadata.name,
        status.conditions[0].type,
        status.conditions[0].status,
        status.traffic[0].percent
    )"
    
    echo -e "\n=== API応答確認 ==="
    if curl -f -s "${API_URL}/healthz" > /dev/null; then
        log_success "API正常応答"
        
        # パフォーマンス詳細取得
        response_time=$(curl -s -w "%{time_total}" -o /dev/null "${API_URL}/healthz")
        echo "応答時間: ${response_time}s"
        
        # システム状態詳細
        curl -s "${API_URL}/system-status" | jq -r '
            "システムバージョン: \(.version)",
            "稼働時間: \(.uptime // "不明")",
            "機能状態:",
            "  - Ultra Fast Mode: \(.features.ultra_fast_mode)",
            "  - Anti-Hallucination: \(.features.anti_hallucination)",
            "  - Auto Update: \(.features.auto_update)",
            "コンポーネント状態:",
            "  - LLM: \(.components.llm)",
            "  - Vectorstore: \(.components.vectorstore)",
            "  - RAG Chain: \(.components.rag_chain)"
        ' 2>/dev/null || log_warning "詳細システム状態の取得に失敗"
        
    else
        log_error "API応答なし"
        return 1
    fi
    
    echo -e "\n=== Cloud Functions状態 ==="
    gcloud functions describe auto-update-function --region=$REGION --format="table(
        name,
        status,
        updateTime
    )" 2>/dev/null || log_warning "Cloud Functions情報取得失敗"
    
    echo -e "\n=== スケジューラー状態 ==="
    gcloud scheduler jobs list --format="table(
        name,
        state,
        schedule,
        lastAttemptTime
    )" 2>/dev/null || log_warning "スケジューラー情報取得失敗"
    
    log_success "システム状態確認完了"
}

# =============================================================================
# 2. パフォーマンス詳細分析
# =============================================================================

analyze_performance() {
    log_info "📊 パフォーマンス詳細分析中..."
    
    echo "=== キャッシュ統計 ==="
    cache_stats=$(curl -s "${API_URL}/chat/performance-stats" | jq -r '
        .cache_performance // {} as $cache |
        "キャッシュサイズ: \($cache.size // 0)/\($cache.max_size // 0)",
        "ヒット率: \(($cache.hit_rate // 0) * 100 | floor)%",
        "総リクエスト: \($cache.total_requests // 0)",
        "ヒット数: \($cache.hits // 0)",
        "ミス数: \($cache.misses // 0)"
    ' 2>/dev/null)
    
    if [[ -n "$cache_stats" ]]; then
        echo "$cache_stats"
        
        # キャッシュヒット率の評価
        hit_rate=$(curl -s "${API_URL}/chat/performance-stats" | jq -r '.cache_performance.hit_rate // 0' 2>/dev/null)
        if (( $(echo "$hit_rate < 0.5" | bc -l) )); then
            log_warning "キャッシュヒット率が低いです (${hit_rate})"
        elif (( $(echo "$hit_rate >= 0.7" | bc -l) )); then
            log_success "キャッシュヒット率良好 (${hit_rate})"
        fi
    else
        log_warning "キャッシュ統計の取得に失敗"
    fi
    
    echo -e "\n=== 応答時間テスト ==="
    test_queries=("坪単価について教えて" "標準仕様について" "資料請求したい")
    
    for query in "${test_queries[@]}"; do
        echo "テスト: $query"
        start_time=$(date +%s.%N)
        
        response=$(curl -s -X POST "${API_URL}/chat/" \
            -H "Content-Type: application/json" \
            -d "{\"question\":\"$query\",\"username\":\"admin_test\"}" \
            --max-time 10 2>/dev/null)
        
        end_time=$(date +%s.%N)
        response_time=$(echo "$end_time - $start_time" | bc)
        
        if [[ -n "$response" ]]; then
            source=$(echo "$response" | jq -r '.performance.source // "unknown"' 2>/dev/null)
            answer_length=$(echo "$response" | jq -r '.answer | length' 2>/dev/null)
            
            echo "  応答時間: ${response_time}s"
            echo "  ソース: $source"
            echo "  回答長: ${answer_length}文字"
            
            # 1秒を超えた場合の警告
            if (( $(echo "$response_time > 1.0" | bc -l) )); then
                log_warning "応答時間が目標(1秒)を超過"
            fi
        else
            log_error "応答なし"
        fi
        echo ""
    done
    
    echo "=== Cloud Runメトリクス ==="
    # 直近1時間のメトリクス取得
    gcloud logging read "
        resource.type=cloud_run_revision AND 
        resource.labels.service_name=$SERVICE_NAME AND 
        timestamp >= \"$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S)Z\"
    " --limit=10 --format="table(
        timestamp,
        severity,
        textPayload
    )" 2>/dev/null || log_warning "ログ取得失敗"
}

# =============================================================================
# 3. トラブルシューティング
# =============================================================================

troubleshoot() {
    local issue_type="$1"
    
    case "$issue_type" in
        "slow-response")
            troubleshoot_slow_response
            ;;
        "high-error-rate")
            troubleshoot_high_error_rate
            ;;
        "cache-issues")
            troubleshoot_cache_issues
            ;;
        "line-bot")
            troubleshoot_line_bot
            ;;
        "auto-update")
            troubleshoot_auto_update
            ;;
        *)
            log_error "未知の問題タイプ: $issue_type"
            echo "利用可能なオプション: slow-response, high-error-rate, cache-issues, line-bot, auto-update"
            ;;
    esac
}

troubleshoot_slow_response() {
    log_info "🐌 応答速度問題のトラブルシューティング..."
    
    echo "=== 現在の応答時間確認 ==="
    response_time=$(curl -s -w "%{time_total}" -o /dev/null "${API_URL}/healthz")
    echo "ヘルスチェック応答時間: ${response_time}s"
    
    if (( $(echo "$response_time > 2.0" | bc -l) )); then
        log_warning "基本応答も遅いです。システム全体の問題の可能性があります。"
        
        echo -e "\n=== Cloud Runリソース使用量確認 ==="
        gcloud run services describe $SERVICE_NAME --region=$REGION --format="value(
            spec.template.spec.containers[0].resources.limits.memory,
            spec.template.spec.containers[0].resources.limits.cpu
        )"
        
        echo -e "\n=== 推奨対処法 ==="
        echo "1. キャッシュクリア実行"
        echo "2. Cloud Runインスタンス数増加"
        echo "3. メモリ/CPU制限値見直し"
        
        read -p "キャッシュをクリアしますか？ (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            clear_cache
        fi
    else
        echo -e "\n=== キャッシュヒット率確認 ==="
        analyze_performance
        
        echo -e "\n=== 推奨対処法 ==="
        echo "1. よく使われるクエリのテンプレート追加"
        echo "2. RAGタイムアウト値の調整"
        echo "3. ベクトルストアの最適化"
    fi
}

troubleshoot_high_error_rate() {
    log_info "❌ エラー率問題のトラブルシューティング..."
    
    echo "=== 最近のエラーログ ==="
    gcloud logging read "
        resource.type=cloud_run_revision AND 
        resource.labels.service_name=$SERVICE_NAME AND 
        severity >= ERROR AND
        timestamp >= \"$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S)Z\"
    " --limit=20 --format="table(
        timestamp,
        severity,
        textPayload
    )" 2>/dev/null || log_warning "エラーログ取得失敗"
    
    echo -e "\n=== API依存関係確認 ==="
    
    # OpenAI API確認
    if [[ -n "${OPENAI_API_KEY:-}" ]]; then
        echo "OpenAI API接続テスト..."
        openai_test=$(curl -s -H "Authorization: Bearer $OPENAI_API_KEY" \
            "https://api.openai.com/v1/models" | jq -r '.data[0].id // "error"' 2>/dev/null)
        
        if [[ "$openai_test" != "error" && -n "$openai_test" ]]; then
            log_success "OpenAI API正常"
        else
            log_error "OpenAI API接続問題"
        fi
    else
        log_warning "OPENAI_API_KEY環境変数未設定"
    fi
    
    # Google Search API確認
    echo "Google Search API接続テスト..."
    # 実際のテストを実装
    
    echo -e "\n=== 推奨対処法 ==="
    echo "1. API認証情報の確認"
    echo "2. 外部サービス接続状態確認"
    echo "3. タイムアウト設定の見直し"
    echo "4. エラーハンドリングの強化"
}

troubleshoot_cache_issues() {
    log_info "💾 キャッシュ問題のトラブルシューティング..."
    
    echo "=== 現在のキャッシュ状態 ==="
    curl -s "${API_URL}/chat/performance-stats" | jq '.cache_performance' 2>/dev/null || log_error "キャッシュ統計取得失敗"
    
    echo -e "\n=== キャッシュテスト ==="
    test_query="坪単価について教えて"
    
    # 1回目（キャッシュミス想定）
    echo "1回目のリクエスト..."
    response1=$(curl -s -X POST "${API_URL}/chat/" \
        -H "Content-Type: application/json" \
        -d "{\"question\":\"$test_query\",\"username\":\"cache_test_1\"}")
    
    source1=$(echo "$response1" | jq -r '.performance.source // "unknown"' 2>/dev/null)
    echo "ソース: $source1"
    
    sleep 1
    
    # 2回目（キャッシュヒット想定）
    echo "2回目のリクエスト..."
    response2=$(curl -s -X POST "${API_URL}/chat/" \
        -H "Content-Type: application/json" \
        -d "{\"question\":\"$test_query\",\"username\":\"cache_test_2\"}")
    
    source2=$(echo "$response2" | jq -r '.performance.source // "unknown"' 2>/dev/null)
    echo "ソース: $source2"
    
    if [[ "$source2" == "cache" ]]; then
        log_success "キャッシュ正常動作"
    else
        log_warning "キャッシュが効いていない可能性"
        echo "推奨対処法:"
        echo "1. キャッシュクリア後再テスト"
        echo "2. キャッシュキー生成ロジック確認"
        echo "3. キャッシュサイズ設定確認"
    fi
}

troubleshoot_line_bot() {
    log_info "📱 LINE Bot問題のトラブルシューティング..."
    
    echo "=== LINE Bot設定確認 ==="
    curl -s "${API_URL}/line-debug" | jq -r '
        "アクセストークン設定: \(.line_credentials.access_token_set)",
        "シークレット設定: \(.line_credentials.channel_secret_set)",
        "Webhook URL: \(.webhook_info.webhook_url)",
        "LIFF URL: \(.webhook_info.liff_url)"
    ' 2>/dev/null || log_error "LINE Debug情報取得失敗"
    
    echo -e "\n=== LINE署名テスト ==="
    curl -s "${API_URL}/test-line-signature" | jq -r '
        "テストボディ: \(.test_body)",
        "生成署名: \(.generated_signature)",
        "署名フォーマット: \(.signature_format)"
    ' 2>/dev/null || log_error "LINE署名テスト失敗"
    
    echo -e "\n=== ハルチネーション対策状態 ==="
    curl -s "${API_URL}/line/anti-hallucination-status" | jq -r '
        "状態: \(.status)",
        "機能: \(.features | join(", "))",
        "信頼度閾値: \(.confidence_threshold)"
    ' 2>/dev/null || log_error "ハルチネーション対策状態取得失敗"
    
    echo -e "\n=== 推奨確認項目 ==="
    echo "1. LINE Developers コンソールでWebhook URL確認"
    echo "2. LINE チャネル設定の確認"
    echo "3. リッチメニュー設定の確認"
    echo "4. LIFF アプリケーション設定の確認"
}

troubleshoot_auto_update() {
    log_info "🔄 自動更新問題のトラブルシューティング..."
    
    echo "=== Cloud Functions状態 ==="
    gcloud functions describe auto-update-function --region=$REGION \
        --format="table(name,status,updateTime,sourceArchiveUrl)" 2>/dev/null || log_error "Cloud Functions情報取得失敗"
    
    echo -e "\n=== スケジューラー状態 ==="
    gcloud scheduler jobs list --format="table(
        name,
        state,
        schedule,
        lastAttemptTime,
        lastAttemptResult
    )" 2>/dev/null || log_error "スケジューラー情報取得失敗"
    
    echo -e "\n=== 最近の実行ログ ==="
    gcloud functions logs read auto-update-function --region=$REGION --limit=10 2>/dev/null || log_warning "Functions ログ取得失敗"
    
    echo -e "\n=== 手動更新テスト ==="
    read -p "手動で自動更新を実行しますか？ (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "手動更新実行中..."
        result=$(curl -s -X POST "${API_URL}/trigger-auto-update" | jq -r '.status // "error"' 2>/dev/null)
        
        if [[ "$result" == "completed" ]]; then
            log_success "手動更新成功"
        else
            log_error "手動更新失敗"
        fi
    fi
    
    echo -e "\n=== 推奨確認項目 ==="
    echo "1. Cloud Functions の実行権限確認"
    echo "2. Pub/Sub トピック・サブスクリプション確認"
    echo "3. 外部API接続状況確認（Google Search等）"
    echo "4. Firestore データベース接続確認"
}

# =============================================================================
# 4. 修復アクション
# =============================================================================

clear_cache() {
    log_info "🧹 キャッシュクリア実行中..."
    
    result=$(curl -s -X POST "${API_URL}/chat/clear-cache" | jq -r '.status // "error"' 2>/dev/null)
    
    if [[ "$result" == "cache_cleared" ]]; then
        log_success "キャッシュクリア完了"
    else
        log_error "キャッシュクリア失敗"
    fi
}

restart_service() {
    log_info "🔄 サービス再起動中..."
    
    # 新しいリビジョンのデプロイで実質的な再起動
    gcloud run deploy $SERVICE_NAME \
        --image="asia-northeast1-docker.pkg.dev/${PROJECT_ID}/rag-chat-pro/rag-api-enhanced:latest" \
        --region=$REGION \
        --quiet
    
    if [[ $? -eq 0 ]]; then
        log_success "サービス再起動完了"
        
        # 起動待機
        echo "サービス起動待機中..."
        sleep 30
        
        # ヘルスチェック
        if curl -f -s "${API_URL}/healthz" > /dev/null; then
            log_success "サービス正常起動確認"
        else
            log_error "サービス起動確認失敗"
        fi
    else
        log_error "サービス再起動失敗"
    fi
}

scale_service() {
    local min_instances="${1:-3}"
    local max_instances="${2:-20}"
    
    log_info "📈 サービススケール調整中... (min: $min_instances, max: $max_instances)"
    
    gcloud run services update $SERVICE_NAME \
        --region=$REGION \
        --min-instances=$min_instances \
        --max-instances=$max_instances \
        --quiet
    
    if [[ $? -eq 0 ]]; then
        log_success "スケール調整完了"
    else
        log_error "スケール調整失敗"
    fi
}

optimize_performance() {
    log_info "⚡ パフォーマンス最適化実行中..."
    
    echo "1. キャッシュクリア"
    clear_cache
    
    echo -e "\n2. 頻出クエリのテンプレート確認"
    # よく使われるクエリの統計を表示
    echo "以下のクエリをテンプレート化することを検討してください:"
    echo "- 坪単価に関する質問"
    echo "- 標準仕様に関する質問"
    echo "- 資料請求・見学予約"
    
    echo -e "\n3. ベクトルストア最適化"
    echo "ベクトルストアの再構築を検討してください"
    
    echo -e "\n4. タイムアウト値最適化"
    echo "現在の設定:"
    echo "- RAGタイムアウト: 2秒"
    echo "- Webサーチタイムアウト: 3秒"
    echo "- LINEレスポンスタイムアウト: 3秒"
    
    log_success "パフォーマンス最適化提案完了"
}

# =============================================================================
# 5. バックアップ・復旧
# =============================================================================

backup_system() {
    log_info "💾 システムバックアップ実行中..."
    
    backup_dir="backup_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$backup_dir"
    
    echo "1. ベクトルストアバックアップ"
    gsutil -m cp -r "gs://run-sources-rag-cloud-project-asia-northeast1/vectorstore" "$backup_dir/" 2>/dev/null || log_warning "ベクトルストアバックアップ失敗"
    
    echo "2. Firestoreエクスポート"
    gcloud firestore export "gs://run-sources-rag-cloud-project-asia-northeast1/firestore-backup-$(date +%Y%m%d)" 2>/dev/null || log_warning "Firestoreバックアップ失敗"
    
    echo "3. 設定ファイルバックアップ"
    # Cloud Run設定
    gcloud run services describe $SERVICE_NAME --region=$REGION --format="export" > "$backup_dir/cloud-run-config.yaml"
    
    # Cloud Functions設定
    gcloud functions describe auto-update-function --region=$REGION --format="export" > "$backup_dir/cloud-function-config.yaml" 2>/dev/null || log_warning "Cloud Functions設定バックアップ失敗"
    
    # スケジューラー設定
    gcloud scheduler jobs list --format="export" > "$backup_dir/scheduler-config.yaml" 2>/dev/null || log_warning "スケジューラー設定バックアップ失敗"
    
    log_success "バックアップ完了: $backup_dir"
}

# =============================================================================
# 6. メイン処理
# =============================================================================

show_help() {
    echo "RAG システム運用スクリプト"
    echo ""
    echo "使用法: $0 [コマンド] [オプション]"
    echo ""
    echo "コマンド:"
    echo "  health                   - システム健康状態確認"
    echo "  performance             - パフォーマンス分析"
    echo "  troubleshoot <type>     - トラブルシューティング"
    echo "    types: slow-response, high-error-rate, cache-issues, line-bot, auto-update"
    echo "  clear-cache             - キャッシュクリア"
    echo "  restart                 - サービス再起動"
    echo "  scale <min> <max>       - サービススケール調整"
    echo "  optimize                - パフォーマンス最適化"
    echo "  backup                  - システムバックアップ"
    echo "  help                    - このヘルプを表示"
    echo ""
    echo "例:"
    echo "  $0 health"
    echo "  $0 troubleshoot slow-response"
    echo "  $0 scale 5 25"
}

main() {
    case "${1:-help}" in
        "health")
            check_system_health
            ;;
        "performance")
            analyze_performance
            ;;
        "troubleshoot")
            if [[ $# -lt 2 ]]; then
                log_error "トラブルシューティングタイプを指定してください"
                show_help
                exit 1
            fi
            troubleshoot "$2"
            ;;
        "clear-cache")
            clear_cache
            ;;
        "restart")
            restart_service
            ;;
        "scale")
            scale_service "${2:-3}" "${3:-20}"
            ;;
        "optimize")
            optimize_performance
            ;;
        "backup")
            backup_system
            ;;
        "help"|*)
            show_help
            ;;
    esac
}

# スクリプト実行
main "$@"