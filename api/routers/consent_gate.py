# api/routers/consent_gate.py
# AI同意ゲート（SQLite/aiosqlite版・Cloud SQL不要）
# - 5点同意: pp / tos / cookie / xfer / ai_limits
# - POLICY_VERSION / TOS_VERSION は ENV で一元管理
# - Web/LINE 両対応のユーザー識別 (X-User-Id / Bearer JWT / user_token)
# - GCS へのWORM風保存は任意（権限が無ければ自動スキップ）
# - ★ aiosqlite 接続は「await しないで async with」に渡す（本修正版）

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from uuid import uuid4

import jwt            # PyJWT（署名検証は上流で実施想定。ここではID抽出のみ）
import aiosqlite
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

# GCS（任意）
try:
    from google.cloud import storage
except Exception:
    storage = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/consent", tags=["consent"])

# =========================================================
# 設定
# =========================================================
CONSENT_CONFIG = {
    "POLICY_VERSION": os.getenv("POLICY_VERSION", "2025-09-01"),
    "TOS_VERSION": os.getenv("TOS_VERSION", "2025-09-01"),
    "CONSENT_VALIDITY_MONTHS": int(os.getenv("CONSENT_VALIDITY_MONTHS", "12")),
    "WORM_RETENTION_YEARS": int(os.getenv("WORM_RETENTION_YEARS", "5")),
    "GCS_CONSENT_BUCKET": os.getenv("GCS_CONSENT_BUCKET", "consent-logs-rag-cloud-project"),
    "REQUIRED_FLAGS": ["pp", "tos", "cookie", "xfer", "ai_limits"],
}

# Cloud Run の書き込み可領域は /tmp
DEFAULT_DB_PATH = os.getenv("CONSENT_SQLITE_PATH", "/tmp/consent_management.db")

# =========================================================
# モデル
# =========================================================
class ConsentRequest(BaseModel):
    consent_id: str
    user_id: str
    liff_id: Optional[str] = None
    consented_at: str
    ip: Optional[str] = None
    ua: Optional[str] = None
    policy_version: str
    tos_version: str
    flags: Dict[str, bool]
    locale: Optional[str] = None
    source: Optional[str] = None
    withdrawn: bool = False

class ConsentCheckRequest(BaseModel):
    user_id: Optional[str] = None
    policy_version: Optional[str] = None
    tos_version: Optional[str] = None

class ConsentWithdrawRequest(BaseModel):
    user_id: str
    consent_id: Optional[str] = None

# =========================================================
# DBユーティリティ（SQLite / aiosqlite）
# =========================================================
def _open_db():
    """
    aiosqlite.connect(...) は await せず、そのまま async with に渡す。
    （await してしまうと二重起動エラーの原因になる）
    """
    os.makedirs(os.path.dirname(DEFAULT_DB_PATH), exist_ok=True)
    return aiosqlite.connect(DEFAULT_DB_PATH)

async def _init_tables():
    async with _open_db() as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS consent_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            consent_id TEXT UNIQUE NOT NULL,
            user_id TEXT NOT NULL,
            liff_id TEXT,
            consented_at TEXT NOT NULL,     -- ISO8601文字列
            ip TEXT,
            ua TEXT,
            policy_version TEXT NOT NULL,
            tos_version TEXT NOT NULL,
            flags TEXT NOT NULL,            -- JSON文字列
            locale TEXT,
            source TEXT,
            withdrawn INTEGER DEFAULT 0,    -- 0=false, 1=true
            withdrawn_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            gcs_object_name TEXT
        )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_consent_user_id ON consent_logs(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_consent_valid ON consent_logs(user_id, policy_version, tos_version, withdrawn)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_consent_created ON consent_logs(created_at)")
        await db.commit()
        logger.info("✅ consent_logs table ready (SQLite) at %s", DEFAULT_DB_PATH)

# =========================================================
# ヘルパ
# =========================================================
def _parse_flags(raw: str | Dict[str, Any]) -> Dict[str, bool]:
    if isinstance(raw, dict):
        return {k: bool(v) for k, v in raw.items()}
    try:
        data = json.loads(raw or "{}")
        return {k: bool(v) for k, v in data.items()}
    except Exception:
        return {}

def _all_required_flags_true(flags: Dict[str, bool]) -> bool:
    return all(flags.get(k) is True for k in CONSENT_CONFIG["REQUIRED_FLAGS"])

def _extract_user_id_from_token(token: str) -> Optional[str]:
    if isinstance(token, str) and token.startswith("U"):  # LINE UID
        return token
    try:
        payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256","RS256","ES256"])
        return payload.get("sub") or payload.get("user_id") or payload.get("email")
    except Exception:
        return None

def _extract_user_id_from_request(request: Request) -> Optional[str]:
    uid = request.headers.get("X-User-Id")
    if uid:
        return uid
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return _extract_user_id_from_token(auth.split(" ", 1)[1])
    tok = request.headers.get("user_token")
    if tok:
        return _extract_user_id_from_token(tok)
    return None

def _threshold_iso() -> str:
    days = 30 * CONSENT_CONFIG["CONSENT_VALIDITY_MONTHS"]
    return (datetime.utcnow() - timedelta(days=days)).isoformat()

async def _save_to_worm_if_available(consent_json: Dict[str, Any]) -> str:
    if not storage:
        return ""
    try:
        client = storage.Client()
        bucket = client.bucket(CONSENT_CONFIG["GCS_CONSENT_BUCKET"])
        dt = datetime.fromisoformat(consent_json["consented_at"].replace("Z","+00:00"))
        object_name = f"consent_logs/{dt.year}/{dt.month:02d}/{dt.day:02d}/{consent_json['consent_id']}.json"
        blob = bucket.blob(object_name)
        consent_json = {
            **consent_json,
            "saved_to_worm_at": datetime.utcnow().isoformat(),
            "retention_until": (datetime.utcnow() + timedelta(days=365*CONSENT_CONFIG["WORM_RETENTION_YEARS"])).isoformat(),
            "worm_protected": True,
        }
        blob.upload_from_string(json.dumps(consent_json, ensure_ascii=False, indent=2), content_type="application/json")
        return object_name
    except Exception as e:
        logger.warning("WORM save skipped: %s", e)
        return ""

# =========================================================
# エンドポイント
# =========================================================
@router.on_event("startup")
async def _startup():
    await _init_tables()

@router.post("/save")
async def save_consent(consent_data: ConsentRequest):
    flags = _parse_flags(consent_data.flags)
    if not _all_required_flags_true(flags):
        raise HTTPException(status_code=400, detail="Required flags are not all true")

    async with _open_db() as db:
        await db.execute(
            "UPDATE consent_logs SET withdrawn=1, withdrawn_at=datetime('now') WHERE user_id=? AND withdrawn=0",
            (consent_data.user_id,)
        )
        await db.execute(
            """
            INSERT INTO consent_logs (
                consent_id, user_id, liff_id, consented_at, ip, ua,
                policy_version, tos_version, flags, locale, source, withdrawn
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                consent_data.consent_id,
                consent_data.user_id,
                consent_data.liff_id,
                consent_data.consented_at,
                consent_data.ip,
                consent_data.ua,
                consent_data.policy_version,
                consent_data.tos_version,
                json.dumps(flags, ensure_ascii=False),
                consent_data.locale,
                consent_data.source,
            )
        )
        await db.commit()

    worm_object = await _save_to_worm_if_available({**consent_data.dict(), "flags": flags})
    if worm_object:
        async with _open_db() as db:
            await db.execute("UPDATE consent_logs SET gcs_object_name=? WHERE consent_id=?", (worm_object, consent_data.consent_id))
            await db.commit()

    return {"success": True, "consent_id": consent_data.consent_id, "worm_saved": bool(worm_object), "worm_object": worm_object}

@router.post("/check")
async def check_consent(check_request: ConsentCheckRequest, request: Request):
    user_id = check_request.user_id or _extract_user_id_from_request(request)
    if not user_id:
        return {
            "valid": False,
            "error": "CONSENT_REQUIRED",
            "policy_version": CONSENT_CONFIG["POLICY_VERSION"],
            "tos_version": CONSENT_CONFIG["TOS_VERSION"],
        }

    policy_version = check_request.policy_version or CONSENT_CONFIG["POLICY_VERSION"]
    tos_version = check_request.tos_version or CONSENT_CONFIG["TOS_VERSION"]
    threshold = _threshold_iso()

    async with _open_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT consent_id, consented_at, flags
            FROM consent_logs
            WHERE user_id=? AND policy_version=? AND tos_version=? AND withdrawn=0 AND consented_at >= ?
            ORDER BY consented_at DESC LIMIT 1
            """,
            (user_id, policy_version, tos_version, threshold)
        )
        row = await cur.fetchone()
        await cur.close()

    if not row:
        return {
            "valid": False,
            "error": "CONSENT_REQUIRED",
            "policy_version": policy_version,
            "tos_version": tos_version,
        }

    flags = _parse_flags(row["flags"])
    if not _all_required_flags_true(flags):
        return {
            "valid": False,
            "error": "CONSENT_REQUIRED",
            "policy_version": policy_version,
            "tos_version": tos_version,
        }

    consented_at = (
        datetime.fromisoformat(row["consented_at"].replace("Z","+00:00"))
        if "Z" in row["consented_at"] else
        datetime.fromisoformat(row["consented_at"])
    )
    expires_at = consented_at + timedelta(days=30 * CONSENT_CONFIG["CONSENT_VALIDITY_MONTHS"])

    return {
        "valid": True,
        "consent_id": row["consent_id"],
        "consented_at": consented_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "flags": flags,
    }

@router.post("/withdraw")
async def withdraw_consent(withdraw_request: ConsentWithdrawRequest):
    async with _open_db() as db:
        if withdraw_request.consent_id:
            await db.execute(
                "UPDATE consent_logs SET withdrawn=1, withdrawn_at=datetime('now') WHERE user_id=? AND consent_id=?",
                (withdraw_request.user_id, withdraw_request.consent_id)
            )
        else:
            await db.execute(
                "UPDATE consent_logs SET withdrawn=1, withdrawn_at=datetime('now') WHERE user_id=? AND withdrawn=0",
                (withdraw_request.user_id,)
            )
        await db.commit()
    return {"success": True}

@router.get("/user/{user_id}/history")
async def get_consent_history(user_id: str):
    async with _open_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT consent_id, consented_at, policy_version, tos_version, withdrawn, withdrawn_at, flags, source
            FROM consent_logs
            WHERE user_id=?
            ORDER BY consented_at DESC
            """,
            (user_id,)
        )
        rows = await cur.fetchall()
        await cur.close()

    history = []
    for r in rows:
        history.append({
            "consent_id": r["consent_id"],
            "consented_at": r["consented_at"],
            "policy_version": r["policy_version"],
            "tos_version": r["tos_version"],
            "withdrawn": bool(r["withdrawn"]),
            "withdrawn_at": r["withdrawn_at"],
            "flags": _parse_flags(r["flags"]),
            "source": r["source"],
        })
    return {"user_id": user_id, "history": history, "total_records": len(history)}

@router.get("/admin/stats")
async def get_consent_stats():
    async with _open_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT COUNT(*) as total_consents FROM consent_logs")
        total = (await cur.fetchone())["total_consents"]
        await cur.close()

        cur = await db.execute("SELECT COUNT(*) as active_consents FROM consent_logs WHERE withdrawn=0")
        active = (await cur.fetchone())["active_consents"]
        await cur.close()

        cur = await db.execute("SELECT COUNT(DISTINCT user_id) as unique_users FROM consent_logs")
        users = (await cur.fetchone())["unique_users"]
        await cur.close()

        cur = await db.execute(
            """
            SELECT substr(consented_at, 1, 10) as consent_date, COUNT(*) as daily_consents
            FROM consent_logs
            WHERE datetime(consented_at) > datetime('now','-30 days')
            GROUP BY substr(consented_at, 1, 10)
            ORDER BY consent_date DESC
            """
        )
        daily_stats = [{"consent_date": r[0], "daily_consents": r[1]} for r in await cur.fetchall()]
        await cur.close()

    return {
        "overview": {
            "total_consents": total,
            "active_consents": active,
            "withdrawn_consents": total - active,
            "unique_users": users,
        },
        "daily_stats": daily_stats,
        "generated_at": datetime.utcnow().isoformat(),
    }

# =========================================================
# チャットAPI保護用（任意）
# =========================================================
def require_valid_consent(func):
    async def wrapper(*args, **kwargs):
        request = kwargs.get("request") or (args[0] if args else None)
        if request:
            user_id = _extract_user_id_from_request(request)
            if not user_id:
                raise HTTPException(status_code=403, detail="consent_required: unidentified_user")
        return await func(*args, **kwargs)
    return wrapper
