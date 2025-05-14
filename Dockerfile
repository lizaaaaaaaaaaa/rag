FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .  
RUN pip install --upgrade pip  
RUN pip install --no-cache-dir -r requirements.txt

COPY . .  
COPY rag/vectorstore rag/vectorstore  
COPY rag/prompt_template.txt rag/prompt_template.txt

ENV PORT=8080
ENV CLOUD_RUN=true
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]


