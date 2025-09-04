# api/routers/consent_gate.py
# AI同意ゲート（高速版：必須3チェック / scope=ai / version / Redisキャッシュ / WORMは非同期）

import os
import json
import logging
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, TYPE_CHECKING
from uuid import uuid4

import jwt
import aiosqlite
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks, Query, Body
from pydantic import BaseModel, Field

# ---- Optional Redis ---------------------------------------------------------
try:
    import redis.asyncio as redis  # redis>=4
except Exception:  # ランタイムにより未導入でも動くように
    redis = None

# ★ 型専用エイリアス（Pylance対策）
if TYPE_CHECKING:
    from redis.asyncio import Redis as RedisClient  # 静的型チェック時のみ参照
else:
    from typing import Any as RedisClient           # 実行時は Any として扱う

# ---- Optional GCS -----------------------------------------------------------
try:
    from google.cloud import storage
except Exception:
    storage = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/consent", tags=["consent"])

# =============================================================================
# 設定
# =============================================================================
POLICY_VERSION_DEFAULT = os.getenv("POLICY_VERSION", "1.0.0")
CONSENT_VALIDITY_MONTHS = int(os.getenv("CONSENT_VALIDITY_MONTHS", "12"))
WORM_RETENTION_YEARS = int(os.getenv("WORM_RETENTION_YEARS", "5"))
GCS_CONSENT_BUCKET = os.getenv("GCS_CONSENT_BUCKET", "consent-logs-rag-cloud-project")
REDIS_URL = os.getenv("REDIS_URL", "")
CONSENT_CACHE_TTL_SEC = int(os.getenv("CONSENT_CACHE_TTL_SEC", "2592000"))  # 30日

# ★ 必須3チェック（Cookieは任意）
REQUIRED_FLAGS = ["pp", "xfer", "ai_limits"]

# Cloud Run の書き込み可領域は /tmp
DEFAULT_DB_PATH = os.getenv("CONSENT_SQLITE_PATH", "/tmp/consent_management.db")

# =============================================================================
# ユーティリティ
# =============================================================================
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _threshold_iso() -> str:
    days = 30 * CONSENT_VALIDITY_MONTHS
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

def _sha256_hex(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()

def _parse_flags(raw: Dict[str, Any] | str) -> Dict[str, bool]:
    if isinstance(raw, dict):
        return {k: bool(v) for k, v in raw.items()}
    try:
        data = json.loads(raw or "{}")
        return {k: bool(v) for k, v in data.items()}
    except Exception:
        return {}

def _all_required_true(flags: Dict[str, bool]) -> bool:
    return all(flags.get(k) is True for k in REQUIRED_FLAGS)

def _extract_user_token_from_request(request: Request) -> Optional[str]:
    # 優先順位: X-User-Token -> user_token -> Authorization(Bearer)
    tok = request.headers.get("X-User-Token") or request.headers.get("user_token")
    if tok:
        return tok
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth.split(" ", 1)[1]
    return None

def _user_id_from_token(token: str) -> Optional[str]:
    # LINE UID ならそのまま、JWTなら sub/user_id/email を拾う。最終的にはハッシュ化して保存/照合。
    if isinstance(token, str) and token.startswith("U"):
        return token
    try:
        payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256","RS256","ES256"])
        return payload.get("sub") or payload.get("user_id") or payload.get("email")
    except Exception:
        return None

# =============================================================================
# Redis キャッシュ（任意）
# =============================================================================
class _ConsentCache:
    def __init__(self):
        self._redis: Optional["RedisClient"] = None  # ← Pylance OK（型別名）
        self._mem: Dict[str, tuple[int, bool]] = {}  # 簡易フォールバック: {key: (expire_epoch, bool)}

    async def _ensure(self):
        if self._redis is None and redis and REDIS_URL:
            try:
                self._redis = redis.from_url(REDIS_URL, decode_responses=True)  # type: ignore[assignment]
                await self._redis.ping()  # type: ignore[union-attr]
                logger.info("✅ Redis connected for consent cache")
            except Exception as e:
                logger.warning("Redis connect failed: %s", e)
                self._redis = None

    @staticmethod
    def _key(user_hash: str, scope: str, version: str) -> str:
        raw = f"consent:{user_hash}:{scope}:{version}"
        return hashlib.md5(raw.encode()).hexdigest()

    async def get(self, user_hash: str, scope: str, version: str) -> Optional[bool]:
        await self._ensure()
        k = self._key(user_hash, scope, version)
        if self._redis:
            v = await self._redis.get(k)  # type: ignore[union-attr]
            return None if v is None else bool(int(v))
        # memory fallback
        ts_val = self._mem.get(k)
        if not ts_val:
            return None
        expire_ts, val = ts_val
        if expire_ts < int(datetime.now(timezone.utc).timestamp()):
            self._mem.pop(k, None)
            return None
        return val

    async def set(self, user_hash: str, scope: str, version: str, ok: bool, ttl: int = CONSENT_CACHE_TTL_SEC):
        await self._ensure()
        k = self._key(user_hash, scope, version)
        if self._redis:
            try:
                await self._redis.set(k, "1" if ok else "0", ex=ttl)  # type: ignore[union-attr]
                return
            except Exception as e:
                logger.warning("Redis set failed: %s", e)
        # memory fallback
        expire_ts = int(datetime.now(timezone.utc).timestamp()) + ttl
        self._mem[k] = (expire_ts, ok)

_consent_cache = _ConsentCache()

# =============================================================================
# DB（SQLite / aiosqlite）
# =============================================================================
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
            user_id TEXT NOT NULL,           -- ここには user_token 由来のIDをハッシュ化して保存
            liff_id TEXT,
            consented_at TEXT NOT NULL,      -- ISO8601
            ip TEXT,
            ua TEXT,
            policy_version TEXT NOT NULL,    -- 本実装では version を保存
            tos_version TEXT NOT NULL,       -- 互換のため残す（同一値を入れておく）
            flags TEXT NOT NULL,             -- JSON（pp/cookie/xfer/ai_limits など）
            locale TEXT,
            source TEXT,                     -- 例: "liff:ai"
            withdrawn INTEGER DEFAULT 0,
            withdrawn_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            gcs_object_name TEXT
        )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_consent_user_id ON consent_logs(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_consent_valid ON consent_logs(user_id, policy_version, withdrawn)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_consent_created ON consent_logs(created_at)")
        await db.commit()
        logger.info("✅ consent_logs table ready (SQLite) at %s", DEFAULT_DB_PATH)

# =============================================================================
# モデル
# =============================================================================
class ConsentSaveBody(BaseModel):
    agree_privacy: bool = Field(..., description="PPに同意")
    understand_external_send: bool = Field(..., description="外部送信の理解")
    understand_ai_may_be_wrong: bool = Field(..., description="AIの限界理解")
    agree_cookie: Optional[bool] = Field(False, description="Cookie同意（任意）")
    meta: Optional[Dict[str, Any]] = None

class ConsentCheckRequest(BaseModel):
    user_id: Optional[str] = None
    version: Optional[str] = None
    scope: Optional[str] = None

class ConsentWithdrawRequest(BaseModel):
    user_id: str
    consent_id: Optional[str] = None

# =============================================================================
# WORM 保存（非同期）
# =============================================================================
async def _save_to_worm(consent_json: Dict[str, Any]) -> str:
    if not storage:
        return ""
    try:
        client = storage.Client()
        bucket = client.bucket(GCS_CONSENT_BUCKET)
        dt = datetime.fromisoformat(consent_json["consented_at"].replace("Z","+00:00"))
        object_name = f"consent_logs/{dt.year}/{dt.month:02d}/{dt.day:02d}/{consent_json['consent_id']}.json"
        blob = bucket.blob(object_name)
        payload = {
            **consent_json,
            "saved_to_worm_at": _now_iso(),
            "retention_until": (datetime.now(timezone.utc) + timedelta(days=365 * WORM_RETENTION_YEARS)).isoformat(),
            "worm_protected": True,
        }
        blob.upload_from_string(json.dumps(payload, ensure_ascii=False, indent=2), content_type="application/json")
        return object_name
    except Exception as e:
        logger.warning("WORM save skipped: %s", e)
        return ""

async def _bg_worm_save_and_mark(consent_json: Dict[str, Any], consent_id: str):
    obj = await _save_to_worm(consent_json)
    if obj:
        async with _open_db() as db:
            await db.execute("UPDATE consent_logs SET gcs_object_name=? WHERE consent_id=?", (obj, consent_id))
            await db.commit()

# =============================================================================
# 高速チェック（Redis→DB）
# =============================================================================
async def fast_check_consent(user_hash: str, scope: str, version: str) -> bool:
    cached = await _consent_cache.get(user_hash, scope, version)
    if cached is not None:
        return cached

    threshold = _threshold_iso()
    async with _open_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT consented_at, flags
            FROM consent_logs
            WHERE user_id=? AND policy_version=? AND withdrawn=0 AND consented_at >= ?
            ORDER BY consented_at DESC LIMIT 1
            """,
            (user_hash, version, threshold)
        )
        row = await cur.fetchone()
        await cur.close()

    ok = False
    if row:
        flags = _parse_flags(row["flags"])
        ok = _all_required_true(flags)

    await _consent_cache.set(user_hash, scope, version, ok)
    return ok

# =============================================================================
# エンドポイント
# =============================================================================
@router.on_event("startup")
async def _startup():
    await _init_tables()

@router.post("/save")
async def save_consent(
    request: Request,
    body: ConsentSaveBody = Body(...),
    bg: BackgroundTasks = None,
    user_token: str = Query(..., description="LIFFからの user_token"),
    scope: str = Query("ai", description="同意の適用範囲（既定: ai）"),
    version: str = Query(None, description="ポリシー版（未指定は POLICY_VERSION）"),
    liff_os: Optional[str] = Query(None),
):
    version = version or POLICY_VERSION_DEFAULT
    user_id_raw = _user_id_from_token(user_token) or user_token
    user_hash = _sha256_hex(user_id_raw)

    flags = {
        "pp": bool(body.agree_privacy),
        "cookie": bool(body.agree_cookie),
        "xfer": bool(body.understand_external_send),
        "ai_limits": bool(body.understand_ai_may_be_wrong),
    }
    if not _all_required_true(flags):
        raise HTTPException(status_code=400, detail="Required flags are not all true")

    consent_id = str(uuid4())
    record = {
        "consent_id": consent_id,
        "user_id": user_hash,
        "liff_id": None,
        "consented_at": _now_iso(),
        "ip": request.client.host if request.client else "",
        "ua": request.headers.get("user-agent", ""),
        "policy_version": version,
        "tos_version": version,
        "flags": json.dumps(flags, ensure_ascii=False),
        "locale": (body.meta or {}).get("locale") if body.meta else None,
        "source": f"liff:{scope}",
        "withdrawn": 0,
    }

    async with _open_db() as db:
        await db.execute(
            "UPDATE consent_logs SET withdrawn=1, withdrawn_at=datetime('now') WHERE user_id=? AND withdrawn=0",
            (user_hash,)
        )
        await db.execute(
            """
            INSERT INTO consent_logs (
              consent_id, user_id, liff_id, consented_at, ip, ua,
              policy_version, tos_version, flags, locale, source, withdrawn
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
              record["consent_id"], record["user_id"], record["liff_id"], record["consented_at"],
              record["ip"], record["ua"], record["policy_version"], record["tos_version"],
              record["flags"], record["locale"], record["source"]
            )
        )
        await db.commit()

    await _consent_cache.set(user_hash, scope, version, True)

    if bg is not None:
        consent_json = {
            "consent_id": consent_id,
            "user_hash": user_hash,
            "scope": [scope],
            "version": version,
            "policy_url": os.getenv("PRIVACY_URL", "/legal/privacy"),
            "consented_at": record["consented_at"],
            "ip": record["ip"],
            "ua": record["ua"],
            "liff_os": liff_os or "",
            "withdrawn": False,
            "flags": flags,
            "meta": body.meta or {},
        }
        bg.add_task(_bg_worm_save_and_mark, consent_json, consent_id)

    return {"ok": True, "consent_id": consent_id}

@router.post("/check")
async def check_consent(
    request: Request,
    payload: ConsentCheckRequest = Body(None),
    scope: str = Query("ai"),
    version: str = Query(None),
):
    user_token = _extract_user_token_from_request(request)
    user_id = payload.user_id if payload and payload.user_id else None
    version = payload.version or version or POLICY_VERSION_DEFAULT
    scope = payload.scope or scope

    if not (user_token or user_id):
        return {"valid": False, "error": "CONSENT_REQUIRED", "version": version}

    user_id_raw = user_id or _user_id_from_token(user_token) or user_token
    user_hash = _sha256_hex(user_id_raw)

    ok = await fast_check_consent(user_hash, scope, version)
    if not ok:
        return {"valid": False, "error": "CONSENT_REQUIRED", "version": version}

    threshold = _threshold_iso()
    async with _open_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT consented_at, flags
            FROM consent_logs
            WHERE user_id=? AND policy_version=? AND withdrawn=0 AND consented_at >= ?
            ORDER BY consented_at DESC LIMIT 1
            """,
            (user_hash, version, threshold)
        )
        row = await cur.fetchone()
        await cur.close()

    if not row:
        return {"valid": True}  # キャッシュOKならOK扱い（速度優先）

    consented_at = (
        datetime.fromisoformat(row["consented_at"].replace("Z","+00:00"))
        if "Z" in row["consented_at"] else
        datetime.fromisoformat(row["consented_at"])
    )
    expires_at = consented_at + timedelta(days=30 * CONSENT_VALIDITY_MONTHS)

    return {
        "valid": True,
        "version": version,
        "consented_at": consented_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "flags": _parse_flags(row["flags"])
    }

@router.post("/withdraw")
async def withdraw_consent(withdraw_request: ConsentWithdrawRequest):
    user_hash = withdraw_request.user_id
    async with _open_db() as db:
        if withdraw_request.consent_id:
            await db.execute(
                "UPDATE consent_logs SET withdrawn=1, withdrawn_at=datetime('now') WHERE user_id=? AND consent_id=?",
                (user_hash, withdraw_request.consent_id)
            )
        else:
            await db.execute(
                "UPDATE consent_logs SET withdrawn=1, withdrawn_at=datetime('now') WHERE user_id=? AND withdrawn=0",
                (user_hash,)
            )
        await db.commit()
    return {"success": True}

@router.get("/user/{user_id}/history")
async def get_consent_history(user_id: str):
    async with _open_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT consent_id, consented_at, policy_version, withdrawn, withdrawn_at, flags, source
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
            "version": r["policy_version"],
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
        "generated_at": _now_iso(),
    }

# =============================================================================
# チャットAPI保護用（任意ミドルウェアに組み込み可能）
# =============================================================================
def require_valid_consent(func):
    async def wrapper(*args, **kwargs):
        request: Optional[Request] = kwargs.get("request") or (args[0] if args else None)
        if request:
            user_token = _extract_user_token_from_request(request)
            if not user_token:
                raise HTTPException(status_code=403, detail="consent_required: unidentified_user")
            user_id_raw = _user_id_from_token(user_token) or user_token
            user_hash = _sha256_hex(user_id_raw)
            ok = await fast_check_consent(user_hash, "ai", POLICY_VERSION_DEFAULT)
            if not ok:
                raise HTTPException(status_code=403, detail="consent_required")
        return await func(*args, **kwargs)
    return wrapper
