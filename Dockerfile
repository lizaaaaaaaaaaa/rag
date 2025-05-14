# ベースイメージ
FROM python:3.11-slim

# 作業ディレクトリ
WORKDIR /app

# ───── 1. 依存インストール ─────
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ───── 2. アプリケーションコピー ─────
COPY . .

# ───── 3. 環境変数 ─────
ENV PORT=8080
ENV CLOUD_RUN=true
ENV PYTHONUNBUFFERED=1

# ───── 4. 起動コマンド ─────
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

