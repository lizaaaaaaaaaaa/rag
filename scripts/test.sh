# scripts/test.sh - テスト実行スクリプト

#!/bin/bash

# テスト実行スクリプト
set -e

echo "🧪 Running Unified Chat System Tests..."

# 環境変数の設定
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
export APP_ENV=testing

# テストサーバーの起動チェック
echo "🔍 Checking if test server is needed..."
if ! curl -f http://localhost:8080/healthz > /dev/null 2>&1; then
    echo "🚀 Starting test server..."
    python main.py &
    SERVER_PID=$!
    
    # サーバー起動待機
    for i in {1..30}; do
        if curl -f http://localhost:8080/healthz > /dev/null 2>&1; then
            echo "✅ Test server is ready"
            break
        fi
        echo "⏳ Waiting for server to start... ($i/30)"
        sleep 2
    done
    
    # サーバーが起動しない場合
    if ! curl -f http://localhost:8080/healthz > /dev/null 2>&1; then
        echo "❌ Failed to start test server"
        kill $SERVER_PID 2>/dev/null || true
        exit 1
    fi
else
    echo "✅ Test server is already running"
    SERVER_PID=""
fi

# テストの実行
echo "🏃 Running tests..."

# Unit tests with pytest
echo "📋 Running unit tests..."
pytest tests/test_unified_chat.py -v || TEST_FAILED=1

# Integration tests with custom script
echo "🔄 Running integration tests..."
python tests/test_unified_chat.py || TEST_FAILED=1

# API endpoint tests
echo "🌐 Running API tests..."
python -c "
import requests
import sys

try:
    # Basic endpoints
    response = requests.get('http://localhost:8080/healthz')
    assert response.status_code == 200
    print('✅ Health check: OK')
    
    response = requests.get('http://localhost:8080/system-status')
    assert response.status_code == 200
    print('✅ System status: OK')
    
    # Chat endpoint
    response = requests.post('http://localhost:8080/chat', json={
        'question': '坪単価について教えて',
        'platform': 'web'
    })
    assert response.status_code == 200
    assert 'answer' in response.json()
    print('✅ Chat endpoint: OK')
    
    # Monitoring dashboard
    response = requests.get('http://localhost:8080/monitoring/dashboard')
    assert response.status_code == 200
    print('✅ Monitoring dashboard: OK')
    
    print('🎉 All API tests passed!')
    
except Exception as e:
    print(f'❌ API test failed: {e}')
    sys.exit(1)
" || TEST_FAILED=1

# Performance tests
echo "⚡ Running performance tests..."
python -c "
import requests
import time
import statistics

# Response time test
response_times = []
for i in range(10):
    start = time.time()
    response = requests.post('http://localhost:8080/chat', json={
        'question': f'テストクエリ {i}',
        'platform': 'web'
    })
    end = time.time()
    
    if response.status_code == 200:
        response_times.append(end - start)

if response_times:
    avg_time = statistics.mean(response_times)
    max_time = max(response_times)
    
    print(f'📊 Average response time: {avg_time:.3f}s')
    print(f'📊 Maximum response time: {max_time:.3f}s')
    
    if avg_time < 3.0:
        print('✅ Performance test: PASSED')
    else:
        print('❌ Performance test: FAILED (too slow)')
else:
    print('❌ Performance test: No successful requests')
"

# テストサーバーの停止
if [ ! -z "$SERVER_PID" ]; then
    echo "🛑 Stopping test server..."
    kill $SERVER_PID 2>/dev/null || true
    sleep 2
fi

# 結果の表示
if [ "$TEST_FAILED" = "1" ]; then
    echo "❌ Some tests failed"
    exit 1
else
    echo "🎉 All tests passed successfully!"
    exit 0
fi

---

# scripts/setup.sh - 初回セットアップスクリプト

#!/bin/bash

# 統合チャットシステム初回セットアップスクリプト
set -e

echo "🔧 Setting up Unified Chat System..."

# Python バージョンチェック
python_version=$(python3 --version 2>&1 | grep -o '[0-9]\+\.[0-9]\+')
required_version="3.11"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
    echo "❌ Python $required_version or higher is required (found: $python_version)"
    exit 1
fi

echo "✅ Python version check passed ($python_version)"

# 仮想環境の作成
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# 仮想環境の活性化
echo "🔌 Activating virtual environment..."
source venv/bin/activate

# パッケージの更新
echo "⬆️  Updating pip..."
pip install --upgrade pip

# 依存関係のインストール
echo "📚 Installing dependencies..."
pip install -r requirements.txt

# ディレクトリ構造の作成
echo "📁 Creating directory structure..."
mkdir -p data/{vectorstore,cache,uploads}
mkdir -p logs
mkdir -p templates/chat
mkdir -p config
mkdir -p tests

# 設定ファイルのコピー
if [ ! -f ".env" ]; then
    echo "⚙️  Creating .env file from template..."
    cp .env.example .env
    echo "✏️  Please edit .env file with your actual configuration"
fi

# テンプレート設定ファイルの配置
if [ ! -f "templates/chat/template_config.yaml" ]; then
    echo "📝 Creating template configuration..."
    # テンプレート設定ファイルの内容をここに書く、または別ファイルからコピー
fi

# 実行権限の付与
echo "🔓 Setting execute permissions..."
chmod +x scripts/*.sh

# Git hooks の設定（オプション）
if [ -d ".git" ]; then
    echo "🔗 Setting up git hooks..."
    cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
echo "Running pre-commit checks..."
python -m pytest tests/ --tb=short -q || exit 1
echo "Pre-commit checks passed ✅"
EOF
    chmod +x .git/hooks/pre-commit
fi

# 初期データの準備（オプション）
echo "🗂️  Preparing initial data..."
if [ ! -f "data/sample_documents.txt" ]; then
    cat > data/sample_documents.txt << 'EOF'
これは統合チャットシステムのサンプル文書です。
住宅の坪単価について説明します。
標準仕様には耐震等級3の構造が含まれています。
断熱性能はUA値0.6以下を実現しています。
EOF
fi

# ヘルスチェック
echo "🏥 Running health check..."
python -c "
try:
    from main import app
    print('✅ Main application import: OK')
    
    from utils.chat_cache import get_global_cache
    print('✅ Cache system: OK')
    
    from utils.chat_templates import get_template_manager
    print('✅ Template system: OK')
    
    from services.rag_processing_service import get_rag_service
    print('✅ RAG service: OK')
    
    from services.response_enhancement import get_response_enhancement_service
    print('✅ Enhancement service: OK')
    
    print('🎉 All components loaded successfully!')
    
except Exception as e:
    print(f'❌ Setup validation failed: {e}')
    exit(1)
"

echo "
🎉 Setup completed successfully!

Next steps:
1. Edit .env file with your configuration
2. Start the system: ./scripts/start.sh
3. Run tests: ./scripts/test.sh
4. Access monitoring: http://localhost:8080/monitoring/dashboard

For development:
  ./scripts/start.sh development

For production:
  ./scripts/start.sh production

For Docker deployment:
  docker-compose up -d
"