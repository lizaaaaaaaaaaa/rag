FROM python:3.11-slim

WORKDIR /app

# requirements.txt を先にコピーして依存関係を一括インストール
COPY requirements.txt .

# pip更新と依存パッケージの一括インストール
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# アプリケーションのファイル一式をコピー
COPY . .
COPY rag/vectorstore rag/vectorstore
COPY rag/prompt_template.txt rag/prompt_template.txt

# Cloud Run用の環境変数
ENV PORT=8080
ENV CLOUD_RUN=true
ENV PYTHONUNBUFFERED=1

# FastAPI (Uvicorn) 起動
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
