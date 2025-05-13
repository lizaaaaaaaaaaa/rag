FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install langchain-openai==0.0.6
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .
COPY rag/vectorstore rag/vectorstore
COPY .env /app/.env

# Cloud Run 側で PORT が渡されるので指定
ENV PORT=8080
ENV CLOUD_RUN=true

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]