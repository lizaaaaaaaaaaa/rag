FROM python:3.11-slim

WORKDIR /app

# 依存ファイルのコピー＆インストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリ全体をコピー（.env は含めない前提！）
COPY . .

# Cloud Run 用ポート環境変数（ポートは8080に固定）
ENV PORT=8080
EXPOSE 8080

# Streamlitでアプリを起動！
CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0"]


