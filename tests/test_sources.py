import re, json, requests

# FastAPI が localhost:8000 で動いている前提
def test_source_format():
    resp = requests.post(
        "http://localhost:8000/chat",
        json={"query": "PDFは何枚？"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    # sources は list / どれか 1 つでも file.pdf:ページ の形式があれば OK
    joined = json.dumps(data["sources"])
    assert re.search(r"\.pdf\":?\s*\"?\d+", joined)
