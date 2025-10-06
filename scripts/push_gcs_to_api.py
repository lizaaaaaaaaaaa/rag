# scripts/push_gcs_to_api.py
import os, io, time, requests
from google.cloud import storage

API_BASE = os.environ["API_BASE"]            # 例: https://<your-service>.a.run.app
BUCKET   = os.environ["GCS_BUCKET_NAME"]     # run-sources-rag-cloud-project-asia-northeast1
PREFIXES = [p.strip().rstrip('/')+'/' for p in
            os.getenv("GCS_UPLOADS_PREFIXES", "uploads/,uploads/admin/").split(",") if p.strip()]

# 現行の同意/認証運用に合わせて必要なものだけセット
HEADERS = {
    "X-Platform": "web",
    # "X-User-Id": "admin@example.com",
    # "X-Consent-Token": "true",
    # "Authorization": "Bearer <token>",
}

TIMEOUT = (10, 600)  # connect, read
SESSION = requests.Session()

def post_pdf(blob):
    bio = io.BytesIO()
    blob.download_to_file(bio)
    bio.seek(0)
    files = {"file": (os.path.basename(blob.name), bio, "application/pdf")}
    r = SESSION.post(f"{API_BASE}/upload/ingest", files=files, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def main():
    client = storage.Client()
    n_ok, n_ng = 0, 0
    t0 = time.time()

    for prefix in PREFIXES:
        print(f"[scan] gs://{BUCKET}/{prefix}")
        for blob in client.list_blobs(BUCKET, prefix=prefix):
            if not blob.name.lower().endswith(".pdf"):
                continue
            try:
                res = post_pdf(blob)
                n_ok += 1
                if n_ok % 10 == 0:
                    print(f"[progress] {n_ok} files ingested… last: {blob.name} / reloaded={res.get('rag_reloaded')}")
            except Exception as e:
                n_ng += 1
                print(f"[warn] ingest failed: {blob.name} -> {e}")

    dt = time.time() - t0
    print(f"[done] ok={n_ok}, ng={n_ng}, elapsed={dt:.1f}s")

    # 取り込みが大量で REFRESH_AFTER_INGEST=false にしていた場合は、最後に1回だけ手動リロード
    if os.getenv("FINAL_FORCE_RELOAD", "false").lower() in ("1","true","yes","on"):
        admin_secret = os.environ["OPS_ADMIN_SECRET"]
        r = SESSION.post(f"{API_BASE}/ops/rag/reload", headers={"X-Admin-Secret": admin_secret}, timeout=60)
        print("[reload]", r.status_code, r.text)

if __name__ == "__main__":
    import os.path
    os.path.basename = lambda p: p.split("/")[-1]  # GCS blob.name からファイル名だけ抜く簡易版
    main()
