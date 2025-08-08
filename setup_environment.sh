#!/bin/bash
# setup_environment.sh - RAG + LINE Bot完全環境構築スクリプト

set -e  # エラー時に終了

PROJECT_ID="rag-cloud-project"
REGION="asia-northeast1"
SERVICE_ACCOUNT="190389115361-compute@developer.gserviceaccount.com"

echo "🚀 RAG + LINE Bot完全環境構築を開始します"
echo "=============================================="
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION" 
echo "Service Account: $SERVICE_ACCOUNT"
echo ""

# 色付きログ関数
log_info() { echo -e "\033[34m[INFO]\033[0m $1"; }
log_success() { echo -e "\033[32m[SUCCESS]\033[0m $1"; }
log_warning() { echo -e "\033[33m[WARNING]\033[0m $1"; }
log_error() { echo -e "\033[31m[ERROR]\033[0m $1"; }

# エラーハンドリング
error_exit() {
    log_error "Script failed at line $1"
    exit 1
}
trap 'error_exit $LINENO' ERR

# ステップ1: Google Cloud設定確認
log_info "ステップ1: Google Cloud設定確認"
echo "------------------------------"

# プロジェクト設定
gcloud config set project $PROJECT_ID
gcloud config set compute/region $REGION

# 現在の設定を確認
CURRENT_PROJECT=$(gcloud config get-value project)
if [ "$CURRENT_PROJECT" != "$PROJECT_ID" ]; then
    log_error "プロジェクトが正しく設定されていません"
    exit 1
fi

log_success "Google Cloudプロジェクト設定完了"
echo ""

# ステップ2: 必要なAPIを有効化
log_info "ステップ2: 必要なAPIを有効化"
echo "--------------------------------"

APIS=(
    "run.googleapis.com"
    "cloudbuild.googleapis.com"
    "secretmanager.googleapis.com"
    "artifactregistry.googleapis.com"
    "compute.googleapis.com"
    "logging.googleapis.com"
    "monitoring.googleapis.com"
    "cloudresourcemanager.googleapis.com"
    "iam.googleapis.com"
    "storage-api.googleapis.com"
    "storage-component.googleapis.com"
    "vpcaccess.googleapis.com"
)

for api in "${APIS[@]}"; do
    log_info "有効化中: $api"
    gcloud services enable $api --project=$PROJECT_ID
done

log_success "全APIの有効化完了"
echo ""

# ステップ3: Artifact Registry設定
log_info "ステップ3: Artifact Registry設定"
echo "-----------------------------------"

REPOSITORY_NAME="rag-chat-pro"

# リポジトリが存在するかチェック
if gcloud artifacts repositories describe $REPOSITORY_NAME --location=$REGION --project=$PROJECT_ID &>/dev/null; then
    log_success "Artifact Registry repository already exists: $REPOSITORY_NAME"
else
    log_info "Artifact Registry repository作成中: $REPOSITORY_NAME"
    gcloud artifacts repositories create $REPOSITORY_NAME \
        --repository-format=docker \
        --location=$REGION \
        --project=$PROJECT_ID
    log_success "Artifact Registry repository作成完了"
fi
echo ""

# ステップ4: Secret Manager設定
log_info "ステップ4: Secret Manager設定"
echo "-------------------------------"

# 必要なSecretsの定義
declare -A SECRETS=(
    ["OPENAI_API_KEY"]="OpenAI API Key (sk-...で始まる)"
    ["LINE_CHANNEL_ACCESS_TOKEN"]="LINE Messaging API チャネルアクセストークン"
    ["LINE_CHANNEL_SECRET"]="LINE Messaging API チャネルシークレット"
    ["LINE_LOGIN_CHANNEL_ID"]="LINE Login チャネルID"
    ["LINE_LOGIN_CHANNEL_SECRET"]="LINE Login チャネルシークレット"
    ["LINE_LOGIN_REDIRECT_URI"]="LINE Login リダイレクトURI"
    ["LIFF_ID"]="LIFF アプリID"
    ["JWT_SECRET"]="JWT用シークレットキー"
    ["GOOGLE_CLIENT_ID"]="Google OAuth クライアントID"
    ["GOOGLE_CLIENT_SECRET"]="Google OAuth クライアントシークレット"
    ["GOOGLE_REDIRECT_URI"]="Google OAuth リダイレクトURI"
    ["GOOGLE_SEARCH_API_KEY"]="Google Custom Search API Key"
    ["GOOGLE_SEARCH_ENGINE_ID"]="Google Custom Search Engine ID"
    ["LANGSMITH_API_KEY"]="LangSmith API Key (オプション)"
    ["db-name"]="データベース名"
    ["db-user"]="データベースユーザー"
    ["db-password"]="データベースパスワード"
)

# 対話的にSecretを設定
setup_secrets() {
    echo ""
    log_info "Secret Manager設定を開始します"
    echo "空白のまま Enter を押すとそのSecretをスキップします"
    echo ""

    for secret_name in "${!SECRETS[@]}"; do
        description="${SECRETS[$secret_name]}"
        
        # 既存のSecretをチェック
        if gcloud secrets describe $secret_name --project=$PROJECT_ID &>/dev/null; then
            log_warning "Secret already exists: $secret_name"
            read -p "上書きしますか？ (y/N): " overwrite
            if [[ $overwrite != "y" && $overwrite != "Y" ]]; then
                continue
            fi
        fi
        
        echo ""
        echo "設定: $secret_name"
        echo "説明: $description"
        
        if [[ $secret_name == *"PASSWORD"* ]] || [[ $secret_name == *"SECRET"* ]] || [[ $secret_name == *"TOKEN"* ]]; then
            read -s -p "値を入力してください (非表示): " secret_value
            echo ""
        else
            read -p "値を入力してください: " secret_value
        fi
        
        if [ -n "$secret_value" ]; then
            # Secretを作成または更新
            if gcloud secrets describe $secret_name --project=$PROJECT_ID &>/dev/null; then
                echo -n "$secret_value" | gcloud secrets versions add $secret_name \
                    --data-file=- --project=$PROJECT_ID
                log_success "Secret updated: $secret_name"
            else
                echo -n "$secret_value" | gcloud secrets create $secret_name \
                    --data-file=- --project=$PROJECT_ID --replication-policy="automatic"
                log_success "Secret created: $secret_name"
            fi
        else
            log_warning "Skipped: $secret_name"
        fi
    done
}

# デフォルトSecretsの設定
setup_default_secrets() {
    log_info "デフォルトSecretsの設定中..."
    
    # JWT Secretの自動生成
    if ! gcloud secrets describe JWT_SECRET --project=$PROJECT_ID &>/dev/null; then
        JWT_SECRET=$(openssl rand -base64 64 | tr -d '\n')
        echo -n "$JWT_SECRET" | gcloud secrets create JWT_SECRET \
            --data-file=- --project=$PROJECT_ID --replication-policy="automatic"
        log_success "JWT_SECRET generated and stored"
    fi
    
    # LINE Login リダイレクトURIのデフォルト設定
    if ! gcloud secrets describe LINE_LOGIN_REDIRECT_URI --project=$PROJECT_ID &>/dev/null; then
        DEFAULT_REDIRECT_URI="https://rag-api-190389115361.asia-northeast1.run.app/line-login/callback"
        echo -n "$DEFAULT_REDIRECT_URI" | gcloud secrets create LINE_LOGIN_REDIRECT_URI \
            --data-file=- --project=$PROJECT_ID --replication-policy="automatic"
        log_success "LINE_LOGIN_REDIRECT_URI set to default"
    fi
    
    # Google OAuth リダイレクトURIのデフォルト設定
    if ! gcloud secrets describe GOOGLE_REDIRECT_URI --project=$PROJECT_ID &>/dev/null; then
        DEFAULT_GOOGLE_REDIRECT="https://rag-api-190389115361.asia-northeast1.run.app/auth/callback"
        echo -n "$DEFAULT_GOOGLE_REDIRECT" | gcloud secrets create GOOGLE_REDIRECT_URI \
            --data-file=- --project=$PROJECT_ID --replication-policy="automatic"
        log_success "GOOGLE_REDIRECT_URI set to default"
    fi
    
    # デフォルトDB設定
    DEFAULT_SECRETS=(
        ["db-name"]="rag_db"
        ["db-user"]="raguser"
        ["db-password"]=$(openssl rand -base64 32 | tr -d '\n')
    )
    
    for secret_name in "${!DEFAULT_SECRETS[@]}"; do
        if ! gcloud secrets describe $secret_name --project=$PROJECT_ID &>/dev/null; then
            echo -n "${DEFAULT_SECRETS[$secret_name]}" | gcloud secrets create $secret_name \
                --data-file=- --project=$PROJECT_ID --replication-policy="automatic"
            log_success "Default secret created: $secret_name"
        fi
    done
}

# ユーザーに選択肢を提供
echo "Secret Managerの設定方法を選択してください："
echo "1) 対話的に設定（推奨）"
echo "2) デフォルト値のみ設定"
echo "3) スキップ"
read -p "選択 (1-3): " secret_choice

case $secret_choice in
    1)
        setup_secrets
        ;;
    2)
        setup_default_secrets
        ;;
    3)
        log_warning "Secret Manager設定をスキップしました"
        ;;
    *)
        log_warning "無効な選択です。デフォルト値を設定します。"
        setup_default_secrets
        ;;
esac

echo ""

# ステップ5: VPC設定（Cloud SQL接続用）
log_info "ステップ5: VPC設定"
echo "----------------------"

VPC_CONNECTOR_NAME="cloudrun-to-sql"

# VPCコネクタが存在するかチェック
if gcloud compute networks vpc-access connectors describe $VPC_CONNECTOR_NAME \
    --region=$REGION --project=$PROJECT_ID &>/dev/null; then
    log_success "VPC connector already exists: $VPC_CONNECTOR_NAME"
else
    log_info "VPC connector作成中: $VPC_CONNECTOR_NAME"
    gcloud compute networks vpc-access connectors create $VPC_CONNECTOR_NAME \
        --region=$REGION \
        --subnet-project=$PROJECT_ID \
        --subnet=default \
        --min-instances=2 \
        --max-instances=3 \
        --machine-type=e2-micro \
        --project=$PROJECT_ID
    log_success "VPC connector作成完了"
fi

echo ""

# ステップ6: Service Account権限設定
log_info "ステップ6: Service Account権限設定"
echo "-------------------------------------"

# 必要な権限のリスト
ROLES=(
    "roles/secretmanager.secretAccessor"
    "roles/storage.objectViewer"
    "roles/storage.objectCreator"
    "roles/cloudsql.client"
    "roles/logging.logWriter"
    "roles/monitoring.metricWriter"
    "roles/cloudtrace.agent"
)

for role in "${ROLES[@]}"; do
    log_info "権限付与中: $role"
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:$SERVICE_ACCOUNT" \
        --role="$role" \
        --condition=None
done

log_success "Service Account権限設定完了"
echo ""

# ステップ7: Cloud Storage設定
log_info "ステップ7: Cloud Storage設定"
echo "-------------------------------"

BUCKET_NAME="run-sources-$PROJECT_ID-$REGION"

# バケットが存在するかチェック
if gsutil ls -b gs://$BUCKET_NAME &>/dev/null; then
    log_success "Cloud Storage bucket already exists: $BUCKET_NAME"
else
    log_info "Cloud Storage bucket作成中: $BUCKET_NAME"
    gsutil mb -p $PROJECT_ID -c STANDARD -l $REGION gs://$BUCKET_NAME
    log_success "Cloud Storage bucket作成完了"
fi

echo ""

# ステップ8: 初回ビルドとデプロイ
log_info "ステップ8: 初回ビルドとデプロイ"
echo "--------------------------------"

read -p "初回ビルドとデプロイを実行しますか？ (y/N): " deploy_choice
if [[ $deploy_choice == "y" || $deploy_choice == "Y" ]]; then
    log_info "Cloud Build実行中..."
    
    # cloudbuild.yamlが存在するかチェック
    if [ ! -f "cloudbuild.yaml" ]; then
        log_error "cloudbuild.yamlが見つかりません"
        exit 1
    fi
    
    # ビルドを実行
    gcloud builds submit --config cloudbuild.yaml --project=$PROJECT_ID
    
    log_success "初回デプロイ完了"
else
    log_warning "初回デプロイをスキップしました"
fi

echo ""

# ステップ9: 環境確認
log_info "ステップ9: 環境確認"
echo "---------------------"

log_info "デプロイされたサービスを確認中..."

# APIサービスの確認
API_URL="https://rag-api-190389115361.asia-northeast1.run.app"
FRONTEND_URL="https://rag-frontend-190389115361.asia-northeast1.run.app"

echo ""
echo "📊 環境確認結果:"
echo "=================="

# API Health Check
if curl -f -s -m 10 "$API_URL/system-health" > /dev/null 2>&1; then
    log_success "API Server: 正常"
else
    log_warning "API Server: 応答なしまたは未デプロイ"
fi

# Frontend Check
if curl -f -s -m 10 "$FRONTEND_URL" > /dev/null 2>&1; then
    log_success "Frontend: 正常"
else
    log_warning "Frontend: 応答なしまたは未デプロイ"
fi

echo ""
echo "🔗 重要なURL:"
echo "=============="
echo "API Server: $API_URL"
echo "Frontend: $FRONTEND_URL"
echo "Health Check: $API_URL/system-health"
echo "LINE Bot Diagnostics: $API_URL/line-bot-diagnostics"
echo "Quick Diagnosis: $API_URL/quick-diagnosis"
echo "LIFF App: $API_URL/liff"

echo ""

# ステップ10: 次のステップのガイダンス
log_info "ステップ10: 次のステップ"
echo "--------------------------"

echo ""
echo "🎉 環境構築が完了しました！"
echo ""
echo "📋 次に実行すべき作業:"
echo "========================"
echo ""
echo "1. LINE Developers設定:"
echo "   - Webhook URL: $API_URL/line/webhook"
echo "   - LINE Login Callback URL: $API_URL/line-login/callback"
echo "   - LIFF Endpoint URL: $API_URL/liff"
echo ""
echo "2. リッチメニュー設定:"
echo "   python scripts/setup_fixed_richmenu.py"
echo ""
echo "3. システム監視の確認:"
echo "   curl $API_URL/system-health | jq"
echo ""
echo "4. LINE Bot診断:"
echo "   curl $API_URL/line-bot-diagnostics | jq"
echo ""
echo "5. 本格運用前のテスト:"
echo "   - LINE公式アカウント友だち追加"
echo "   - リッチメニュー動作確認"
echo "   - AI相談機能テスト"
echo ""
echo "🔧 トラブルシューティング用コマンド:"
echo "===================================="
echo "# ログ確認"
echo "gcloud logging read 'resource.type=\"cloud_run_revision\"' --limit=50"
echo ""
echo "# サービス再起動"
echo "gcloud builds submit --config cloudbuild.yaml"
echo ""
echo "# Secret確認"
echo "gcloud secrets list --project=$PROJECT_ID"
echo ""

log_success "セットアップスクリプト完了！"