# Dockerfile - 統合チャットシステム用 (fixed to use Cloud Run's $PORT)

FROM python:3.11-slim

# 作業ディレクトリの設定
WORKDIR /app

# システム依存関係のインストール
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Pythonの依存関係をコピーしてインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# ディレクトリ作成
RUN mkdir -p data logs templates/chat

# 非rootユーザーの作成
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# ポートの公開（Cloud Run のデフォルト8080を利用）
EXPOSE 8080

# ヘルスチェック設定：$PORT 環境変数を利用してヘルスチェック
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/healthz || exit 1

# 環境変数の設定
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV LOG_LEVEL=INFO

# 起動コマンド：bashを介して$PORTを展開
CMD ["bash", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]