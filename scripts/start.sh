# scripts/start.sh - 起動スクリプト

#!/bin/bash

# 統合チャットシステム起動スクリプト
set -e

echo "🚀 Starting Unified Chat System..."

# 環境変数の読み込み
if [ -f .env ]; then
    echo "📋 Loading environment variables from .env"
    export $(cat .env | xargs)
else
    echo "⚠️  .env file not found, using default settings"
fi

# ディレクトリの作成
echo "📁 Creating directories..."
mkdir -p data logs templates/chat config

# Pythonパスの設定
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# 依存関係のチェック
echo "🔍 Checking dependencies..."
python -c "import fastapi, langchain, redis" || {
    echo "❌ Missing dependencies. Please run: pip install -r requirements.txt"
    exit 1
}

# RAGコンポーネントの初期化チェック
echo "🤖 Checking RAG components..."
if [ ! -d "data/vectorstore" ]; then
    echo "⚠️  Vector store not found. RAG features may be limited."
fi

# ポート使用状況チェック
PORT=${PORT:-8080}
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null; then
    echo "❌ Port $PORT is already in use"
    exit 1
fi

# 設定の表示
echo "⚙️  Configuration:"
echo "   - App Environment: ${APP_ENV:-development}"
echo "   - Port: $PORT"
echo "   - Unified Chat Mode: ${UNIFIED_CHAT_MODE:-enabled}"
echo "   - LINE Bot Mode: ${LINE_BOT_MODE:-ultra_fast_financial}"
echo "   - Debug Mode: ${DEBUG_MODE:-false}"
echo "   - Cache Max Size: ${CACHE_MAX_SIZE:-1000}"

# メイン起動処理
case "${1:-standard}" in
    "development"|"dev")
        echo "🔧 Starting in development mode with auto-reload..."
        uvicorn main:app \
            --host ${HOST:-0.0.0.0} \
            --port $PORT \
            --reload \
            --log-level ${LOG_LEVEL:-info}
        ;;
    "production"|"prod")
        echo "🏭 Starting in production mode..."
        uvicorn main:app \
            --host ${HOST:-0.0.0.0} \
            --port $PORT \
            --workers ${WORKERS:-4} \
            --log-level ${LOG_LEVEL:-info} \
            --access-log \
            --loop uvloop
        ;;
    "docker")
        echo "🐳 Starting in Docker mode..."
        exec uvicorn main:app \
            --host 0.0.0.0 \
            --port $PORT \
            --workers ${WORKERS:-1} \
            --log-level ${LOG_LEVEL:-info}
        ;;
    "test")
        echo "🧪 Starting test server..."
        uvicorn main:app \
            --host 127.0.0.1 \
            --port $PORT \
            --reload \
            --log-level debug
        ;;
    *)
        echo "🟢 Starting in standard mode..."
        uvicorn main:app \
            --host ${HOST:-0.0.0.0} \
            --port $PORT \
            --log-level ${LOG_LEVEL:-info}
        ;;
esac
