# scripts/deploy.sh - デプロイスクリプト

#!/bin/bash

# デプロイスクリプト（本番環境用）
set -e

ENVIRONMENT=${1:-production}
echo "🚀 Deploying Unified Chat System to $ENVIRONMENT..."

# 設定の検証
if [ "$ENVIRONMENT" = "production" ] && [ ! -f ".env.production" ]; then
    echo "❌ .env.production file is required for production deployment"
    exit 1
fi

# Docker Compose プロファイルの設定
case $ENVIRONMENT in
    "development"|"dev")
        COMPOSE_PROFILES="dev"
        ENV_FILE=".env"
        ;;
    "staging")
        COMPOSE_PROFILES="staging,monitoring"
        ENV_FILE=".env.staging"
        ;;
    "production"|"prod")
        COMPOSE_PROFILES="production,monitoring"
        ENV_FILE=".env.production"
        ;;
    *)
        echo "❌ Unknown environment: $ENVIRONMENT"
        exit 1
        ;;
esac

# 環境設定の読み込み
if [ -f "$ENV_FILE" ]; then
    echo "📋 Loading environment from $ENV_FILE"
    export $(cat $ENV_FILE | xargs)
fi

# 事前チェック
echo "🔍 Running pre-deployment checks..."

# Docker & Docker Compose の確認
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed"
    exit 1
fi

# 設定ファイルの確認
if [ ! -f "docker-compose.yml" ]; then
    echo "❌ docker-compose.yml not found"
    exit 1
fi

# SSL証明書の確認（本番環境）
if [ "$ENVIRONMENT" = "production" ] && [ ! -d "ssl" ]; then
    echo "⚠️  SSL certificates not found. HTTPS will not be available."
fi

# デプロイ実行
echo "🏗️  Building and deploying..."

# 既存コンテナの停止
echo "🛑 Stopping existing containers..."
docker-compose --env-file $ENV_FILE down || true

# イメージのビルド
echo "🔨 Building images..."
docker-compose --env-file $ENV_FILE build --no-cache

# サービスの起動
echo "▶️  Starting services..."
COMPOSE_PROFILES=$COMPOSE_PROFILES docker-compose --env-file $ENV_FILE up -d

# ヘルスチェック
echo "🏥 Waiting for services to be healthy..."
for i in {1..60}; do
    if docker-compose --env-file $ENV_FILE ps | grep -q "healthy\|Up"; then
        echo "✅ Services are healthy"
        break
    fi
    echo "⏳ Waiting for services... ($i/60)"
    sleep 5
done

# 最終確認
if docker-compose --env-file $ENV_FILE ps | grep -q "Exit\|Restarting"; then
    echo "❌ Some services failed to start"
    docker-compose --env-file $ENV_FILE logs
    exit 1
fi

# デプロイ後の確認
echo "🧪 Running post-deployment tests..."

# API ヘルスチェック
APP_PORT=${PORT:-8080}
for i in {1..30}; do
    if curl -f "http://localhost:$APP_PORT/healthz" > /dev/null 2>&1; then
        echo "✅ Application is responding"
        break
    fi
    echo "⏳ Waiting for application... ($i/30)"
    sleep 5
done

if ! curl -f "http://localhost:$APP_PORT/healthz" > /dev/null 2>&1; then
    echo "❌ Application health check failed"
    exit 1
fi

# 監視システムの確認
if [[ $COMPOSE_PROFILES == *"monitoring"* ]]; then
    echo "📊 Checking monitoring systems..."
    
    # Prometheus
    if curl -f "http://localhost:9090/-/healthy" > /dev/null 2>&1; then
        echo "✅ Prometheus is healthy"
    else
        echo "⚠️  Prometheus health check failed"
    fi
    
    # Grafana
    if curl -f "http://localhost:3000/api/health" > /dev/null 2>&1; then
        echo "✅ Grafana is healthy"
    else
        echo "⚠️  Grafana health check failed"
    fi
fi

echo "
🎉 Deployment completed successfully!

Environment: $ENVIRONMENT
Services: $(docker-compose --env-file $ENV_FILE ps --services | tr '\n' ' ')

Access points:
- Application: http://localhost:$APP_PORT
- Monitoring Dashboard: http://localhost:$APP_PORT/monitoring/dashboard
- System Status: http://localhost:$APP_PORT/system-status"

if [[ $COMPOSE_PROFILES == *"monitoring"* ]]; then
    echo "- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin/admin123)"
fi

echo "
Logs: docker-compose --env-file $ENV_FILE logs -f
Stop: docker-compose --env-file $ENV_FILE down
"