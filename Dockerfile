FROM python:3.11-slim

WORKDIR /app

# requirements.txt を先にコピーして依存関係をインストール
COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# アプリケーションファイルをコピー
COPY . .
COPY rag/vectorstore rag/vectorstore
COPY rag/prompt_template.txt rag/prompt_template.txt

# Cloud Run用の環境変数
ENV PORT=8080
ENV CLOUD_RUN=true
ENV PYTHONUNBUFFERED=1

# FastAPI (Uvicorn) 起動
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

