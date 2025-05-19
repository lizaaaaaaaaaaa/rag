# tests/test_sources.py
import re
from fastapi.testclient import TestClient
from main import app   # ← FastAPI インスタンスを import

client = TestClient(app)

def test_source_format():
    resp = client.post("/chat", json={"query": "PDFは何枚？"})
    assert resp.status_code == 200
    data = resp.json()

    # sources が list で、少なくとも 1 件は file.pdf:page の形式
    joined = str(data.get("sources", ""))
    assert re.search(r"\.pdf[\"']?:[\"']?\d+", joined)

