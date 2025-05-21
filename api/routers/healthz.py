# api/routers/healthz.py

from fastapi import APIRouter
import os
import psycopg2

router = APIRouter()

@router.get("/healthz")
def healthz():
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT", 5432),
            database=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
        )
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            result = cur.fetchone()
        conn.close()
        return {"status": "ok", "db": result}
    except Exception as e:
        return {"status": "ng", "error": str(e)}
