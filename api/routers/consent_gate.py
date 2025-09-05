# api/routers/consent_gate.py
# PDF準拠・完全修正版：LIFF同意ゲート（必須4チェック + GCS疑似WORM + 全バグ修正済み）

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
    import redis.asyncio as redis
except Exception:
    redis = None

if TYPE_CHECKING:
    from redis.asyncio import Redis as RedisClient
else:
    from typing import Any as RedisClient

# ---- GCS with Versioning (疑似WORM) ----------------------------------------
try:
    from google.cloud import storage
except Exception:
    storage = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/consent", tags=["consent"])

# =============================================================================
# 設定（PDF準拠）
# =============================================================================
POLICY_VERSION_DEFAULT = os.getenv("POLICY_VERSION", "1.0.0")
CONSENT_VALIDITY_MONTHS = int(os.getenv("CONSENT_VALIDITY_MONTHS", "12"))
WORM_RETENTION_YEARS = int(os.getenv("WORM_RETENTION_YEARS", "5"))
GCS_CONSENT_BUCKET = os.getenv("GCS_CONSENT_BUCKET", "consent-logs-rag-cloud-project-asia-northeast1")
REDIS_URL = os.getenv("REDIS_URL", "")
CONSENT_CACHE_TTL_SEC = int(os.getenv("CONSENT_CACHE_TTL_SEC", "2592000"))  # 30日

# PDF準拠：必須4チェック + アカウント情報
REQUIRED_FLAGS = ["pp", "xfer", "ai_limits", "cookie"]
LINE_ACCOUNT = os.getenv("LINE_BASIC_ID", "487urklv")  # @なしで保存
PRIVACY_POLICY_URL = os.getenv("PRIVACY_POLICY_URL", "https://rag-api-190389115361.asia-northeast1.run.app/privacy")

DEFAULT_DB_PATH = os.getenv("CONSENT_SQLITE_PATH", "/tmp/consent_management.db")

# =============================================================================
# ユーティリティ
# =============================================================================

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

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
    tok = request.headers.get("X-User-Token") or request.headers.get("user_token")
    if tok:
        return tok
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth.split(" ", 1)[1]
    return None

def _user_id_from_token(token: str) -> Optional[str]:
    if isinstance(token, str) and token.startswith("U"):
        return token
    try:
        payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256", "RS256", "ES256"])
        return payload.get("sub") or payload.get("user_id") or payload.get("email")
    except Exception:
        return None

# =============================================================================
# Redis キャッシュ
# =============================================================================

class _ConsentCache:
    def __init__(self):
        self._redis: Optional["RedisClient"] = None
        self._mem: Dict[str, tuple[int, bool]] = {}

    async def _ensure(self):
        if self._redis is None and redis and REDIS_URL:
            try:
                self._redis = redis.from_url(REDIS_URL, decode_responses=True)
                await self._redis.ping()
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
            v = await self._redis.get(k)
            return None if v is None else bool(int(v))
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
                await self._redis.set(k, "1" if ok else "0", ex=ttl)
                return
            except Exception as e:
                logger.warning("Redis set failed: %s", e)
        expire_ts = int(datetime.now(timezone.utc).timestamp()) + ttl
        self._mem[k] = (expire_ts, ok)

_consent_cache = _ConsentCache()

# =============================================================================
# DB（SQLite）- PDF準拠スキーマ
# =============================================================================

def _open_db():
    os.makedirs(os.path.dirname(DEFAULT_DB_PATH), exist_ok=True)
    return aiosqlite.connect(DEFAULT_DB_PATH)

async def _init_tables():
    async with _open_db() as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS consent_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            consent_id TEXT UNIQUE NOT NULL,
            user_id_hash TEXT NOT NULL,         -- PDF準拠：user_id_hash
            account TEXT NOT NULL,              -- PDF準拠：@kinoe-ai
            liff_id TEXT,
            ts TEXT NOT NULL,                   -- PDF準拠：consented_at → ts
            ip TEXT,
            ua TEXT,
            liff_os TEXT,                       -- PDF準拠：LIFF環境
            version TEXT NOT NULL,              -- PDF準拠：policy_version → version
            scope TEXT NOT NULL,                -- PDF準拠：scope (JSON array)
            policy_url TEXT,                    -- PDF準拠
            flags TEXT NOT NULL,                -- JSON（pp/cookie/xfer/ai_limits）
            locale TEXT,                        -- PDF準拠
            withdrawn INTEGER DEFAULT 0,        -- PDF準拠：boolean
            withdrawn_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            gcs_object_name TEXT,               -- WORM保存先
            gcs_generation INTEGER              -- GCS世代番号（疑似immutable）
        )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_consent_user_hash ON consent_logs(user_id_hash)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_consent_valid ON consent_logs(user_id_hash, version, withdrawn)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_consent_created ON consent_logs(created_at)")
        await db.commit()
        logger.info("✅ PDF準拠 consent_logs table ready (SQLite) at %s", DEFAULT_DB_PATH)

# =============================================================================
# モデル（PDF準拠）
# =============================================================================

class ConsentSaveBody(BaseModel):
    """PDF準拠：必須4チェック"""
    agree_privacy: bool = Field(..., description="プライバシーポリシーに同意")
    understand_external_send: bool = Field(..., description="外部送信（OpenAI/GA4等）の理解")
    understand_ai_may_be_wrong: bool = Field(..., description="AIの限界理解")
    agree_cookie: bool = Field(..., description="Cookie同意（計測含む）")
    liff_os: Optional[str] = Field(None, description="LIFF環境（iOS/Android）")
    locale: Optional[str] = Field("ja-JP", description="ロケール")
    meta: Optional[Dict[str, Any]] = None

class ConsentCheckRequest(BaseModel):
    user_id: Optional[str] = None
    version: Optional[str] = None
    scope: Optional[str] = None

class ConsentWithdrawRequest(BaseModel):
    user_id: str
    consent_id: Optional[str] = None

# =============================================================================
# GCS疑似WORM保存（PDF要件・バグ修正済み）
# =============================================================================

async def _save_to_gcs_pseudo_worm(consent_json: Dict[str, Any]) -> tuple[str, int]:
    """
    GCSにWORM風保存（バージョニング+Lifecycle Policy前提）
    ★ 注意：真のWORMにはAWS S3 Object Lockが必要
    """
    if not storage:
        logger.warning("GCS storage client not available")
        return "", 0
    
    try:
        client = storage.Client()
        bucket = client.bucket(GCS_CONSENT_BUCKET)
        
        # PDF準拠パス: consents/YYYY/MM/DD/account/user_hash/uuid.json
        # ★ バグ修正：正しいキー名 "ts" を使用
        dt = datetime.fromisoformat(consent_json["ts"].replace("Z", "+00:00"))
        user_hash = consent_json["user_id_hash"]
        account = consent_json.get("account", LINE_ACCOUNT)
        
        object_name = f"consents/{dt.year}/{dt.month:02d}/{dt.day:02d}/{account}/{user_hash}/{consent_json['consent_id']}.json"
        
        # 疑似WORM設定
        blob = bucket.blob(object_name)
        
        # PDF準拠スキーマで保存
        worm_payload = {
            **consent_json,
            "worm_metadata": {
                "saved_at": _now_iso(),
                "retention_until": (datetime.now(timezone.utc) + timedelta(days=365 * WORM_RETENTION_YEARS)).isoformat(),
                "pseudo_worm": True,
                "gcs_versioning": True,
                "note": "GCS versioning enabled - true WORM requires AWS S3 Object Lock"
            }
        }
        
        # Content-Type + メタデータ設定
        blob.content_type = "application/json"
        blob.metadata = {
            "consent_id": consent_json["consent_id"],
            "version": consent_json["version"],
            "scope": ",".join(consent_json.get("scope", ["ai"])),
            "retention_years": str(WORM_RETENTION_YEARS),
            "immutable": "pseudo",
            "account": account
        }
        
        blob.upload_from_string(
            json.dumps(worm_payload, ensure_ascii=False, indent=2),
            content_type="application/json"
        )
        
        # 世代番号取得（GCSバージョニング）
        generation = blob.generation or 0
        
        logger.info(f"✅ Consent saved to GCS pseudo-WORM: {object_name} (gen: {generation})")
        return object_name, generation
        
    except Exception as e:
        logger.error(f"❌ GCS pseudo-WORM save failed: {e}")
        return "", 0

async def _bg_gcs_save_and_mark(consent_json: Dict[str, Any], consent_id: str):
    """バックグラウンドでGCS保存"""
    obj_name, generation = await _save_to_gcs_pseudo_worm(consent_json)
    if obj_name:
        async with _open_db() as db:
            await db.execute(
                "UPDATE consent_logs SET gcs_object_name=?, gcs_generation=? WHERE consent_id=?", 
                (obj_name, generation, consent_id)
            )
            await db.commit()
            logger.info(f"✅ GCS object reference saved to DB: {obj_name}")

# =============================================================================
# 高速チェック（PDF準拠・バグ修正済み）
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
            SELECT ts, flags
            FROM consent_logs
            WHERE user_id_hash=? AND version=? AND withdrawn=0 AND ts >= ?
            ORDER BY ts DESC LIMIT 1
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
# エンドポイント（PDF準拠・完全修正版）
# =============================================================================

@router.on_event("startup")
async def _startup():
    await _init_tables()

@router.post("/save")
async def save_consent(
    request: Request,
    body: ConsentSaveBody = Body(...),
    bg: BackgroundTasks = None,
    user_token: str = Query(..., description="LIFFからのuser_token"),
    scope: str = Query("ai", description="同意の適用範囲"),
    version: str = Query(None, description="ポリシー版"),
):
    """PDF準拠：LIFF同意ゲート保存API（完全修正版）"""
    version = version or POLICY_VERSION_DEFAULT
    user_id_raw = _user_id_from_token(user_token) or user_token
    user_id_hash = _sha256_hex(user_id_raw)  # PDF準拠：SHA-256ハッシュ

    # PDF準拠：必須4チェック
    flags = {
        "pp": bool(body.agree_privacy),
        "cookie": bool(body.agree_cookie),
        "xfer": bool(body.understand_external_send),
        "ai_limits": bool(body.understand_ai_may_be_wrong),
    }
    
    if not _all_required_true(flags):
        missing = [k for k in REQUIRED_FLAGS if not flags.get(k)]
        raise HTTPException(
            status_code=400, 
            detail=f"Required consent flags missing: {missing}"
        )

    consent_id = str(uuid4())
    ts = _now_iso()  # PDF準拠：consented_at → ts
    
    # PDF準拠スキーマ
    record = {
        "consent_id": consent_id,
        "user_id_hash": user_id_hash,                    # PDF準拠
        "account": f"@{LINE_ACCOUNT}",                   # PDF準拠
        "liff_id": request.headers.get("X-LIFF-ID"),
        "ts": ts,                                        # PDF準拠
        "ip": request.client.host if request.client else "",
        "ua": request.headers.get("user-agent", ""),
        "liff_os": body.liff_os or "",                   # PDF準拠
        "version": version,                              # PDF準拠
        "scope": json.dumps([scope]),                    # PDF準拠：配列
        "policy_url": PRIVACY_POLICY_URL,                # PDF準拠
        "flags": json.dumps(flags, ensure_ascii=False),
        "locale": body.locale or "ja-JP",               # PDF準拠
        "withdrawn": 0,
    }

    # DB保存
    async with _open_db() as db:
        # 既存同意を無効化
        await db.execute(
            "UPDATE consent_logs SET withdrawn=1, withdrawn_at=datetime('now') WHERE user_id_hash=? AND withdrawn=0",
            (user_id_hash,)
        )
        
        # 新規同意保存
        await db.execute(
            """
            INSERT INTO consent_logs (
              consent_id, user_id_hash, account, liff_id, ts, ip, ua, liff_os,
              version, scope, policy_url, flags, locale, withdrawn
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                record["consent_id"], record["user_id_hash"], record["account"], record["liff_id"],
                record["ts"], record["ip"], record["ua"], record["liff_os"],
                record["version"], record["scope"], record["policy_url"], 
                record["flags"], record["locale"]
            )
        )
        await db.commit()

    # キャッシュ更新
    await _consent_cache.set(user_id_hash, scope, version, True)

    # PDF準拠：バックグラウンドでGCS WORM保存（バグ修正済み）
    if bg is not None:
        consent_json = {
            "consent_id": consent_id,
            "user_id_hash": user_id_hash,              # PDF準拠
            "account": f"@{LINE_ACCOUNT}",             # PDF準拠  
            "scope": [scope],                          # PDF準拠：配列
            "version": version,                        # PDF準拠
            "policy_url": PRIVACY_POLICY_URL,          # PDF準拠
            "ts": ts,                                  # PDF準拠：正しいキー名
            "ip": record["ip"],
            "ua": record["ua"],
            "liff_os": body.liff_os or "",             # PDF準拠
            "locale": body.locale or "ja-JP",
            "withdrawn": False,                        # PDF準拠
            "flags": flags,
            "meta": body.meta or {},
        }
        bg.add_task(_bg_gcs_save_and_mark, consent_json, consent_id)

    return {
        "ok": True,
        "consent_id": consent_id,
        "message": "同意が正常に保存されました",
        "worm_scheduled": True,
        "version": version
    }

@router.post("/check")
async def check_consent(
    request: Request,
    payload: 'ConsentCheckRequest' = Body(None),
    scope: str = Query("ai"),
    version: str = Query(None),
):
    """PDF準拠：同意状況確認API（完全修正版）"""
    user_token = _extract_user_token_from_request(request)
    user_id = payload.user_id if payload and payload.user_id else None
    version = payload.version or version or POLICY_VERSION_DEFAULT
    scope = payload.scope or scope

    if not (user_token or user_id):
        return {
            "valid": False, 
            "error": "CONSENT_REQUIRED", 
            "version": version,
            "required_flags": REQUIRED_FLAGS
        }

    user_id_raw = user_id or _user_id_from_token(user_token) or user_token
    user_id_hash = _sha256_hex(user_id_raw)

    ok = await fast_check_consent(user_id_hash, scope, version)
    if not ok:
        return {
            "valid": False, 
            "error": "CONSENT_REQUIRED", 
            "version": version,
            "required_flags": REQUIRED_FLAGS
        }

    # 詳細情報取得
    threshold = _threshold_iso()
    async with _open_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT ts, flags, account, scope, policy_url
            FROM consent_logs
            WHERE user_id_hash=? AND version=? AND withdrawn=0 AND ts >= ?
            ORDER BY ts DESC LIMIT 1
            """,
            (user_id_hash, version, threshold)
        )
        row = await cur.fetchone()
        await cur.close()

    if not row:
        return {"valid": True}

    ts = (
        datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        if "Z" in row["ts"] else
        datetime.fromisoformat(row["ts"])
    )
    expires_at = ts + timedelta(days=30 * CONSENT_VALIDITY_MONTHS)

    return {
        "valid": True,
        "version": version,
        "account": row["account"],
        "scope": json.loads(row["scope"] or "[]"),
        "policy_url": row["policy_url"],
        "consented_at": ts.isoformat(),
        "expires_at": expires_at.isoformat(),
        "flags": _parse_flags(row["flags"])
    }

@router.post("/withdraw")
async def withdraw_consent(withdraw_request: 'ConsentWithdrawRequest'):
    """同意撤回API（PDF準拠）"""
    user_hash = withdraw_request.user_id
    async with _open_db() as db:
        if withdraw_request.consent_id:
            await db.execute(
                "UPDATE consent_logs SET withdrawn=1, withdrawn_at=datetime('now') WHERE user_id_hash=? AND consent_id=?",
                (user_hash, withdraw_request.consent_id)
            )
        else:
            await db.execute(
                "UPDATE consent_logs SET withdrawn=1, withdrawn_at=datetime('now') WHERE user_id_hash=? AND withdrawn=0",
                (user_hash,)
            )
        await db.commit()
    return {"success": True, "message": "同意が撤回されました"}

@router.get("/user/{user_id}/history")
async def get_consent_history(user_id: str):
    """ユーザー同意履歴取得（PDF準拠）"""
    async with _open_db() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT consent_id, ts, version, withdrawn, withdrawn_at, flags, scope, account
            FROM consent_logs
            WHERE user_id_hash=?
            ORDER BY ts DESC
            """,
            (user_id,)
        )
        rows = await cur.fetchall()
        await cur.close()

    history = []
    for r in rows:
        history.append({
            "consent_id": r["consent_id"],
            "consented_at": r["ts"],                   # PDF準拠：ts
            "version": r["version"],                   # PDF準拠
            "account": r["account"],                   # PDF準拠
            "scope": json.loads(r["scope"] or "[]"),   # PDF準拠：配列
            "withdrawn": bool(r["withdrawn"]),
            "withdrawn_at": r["withdrawn_at"],
            "flags": _parse_flags(r["flags"]),
        })
    return {"user_id": user_id, "history": history, "total_records": len(history)}

@router.get("/admin/stats")
async def get_consent_stats():
    """管理用：同意統計（完全修正版）"""
    async with _open_db() as db:
        db.row_factory = aiosqlite.Row
        
        # 基本統計
        cur = await db.execute("SELECT COUNT(*) as total FROM consent_logs")
        total = (await cur.fetchone())["total"]
        await cur.close()

        cur = await db.execute("SELECT COUNT(*) as active FROM consent_logs WHERE withdrawn=0")
        active = (await cur.fetchone())["active"]
        await cur.close()

        cur = await db.execute("SELECT COUNT(DISTINCT user_id_hash) as unique_users FROM consent_logs")
        users = (await cur.fetchone())["unique_users"]
        await cur.close()

        # WORM保存統計
        cur = await db.execute("SELECT COUNT(*) as worm_saved FROM consent_logs WHERE gcs_object_name IS NOT NULL")
        worm_saved = (await cur.fetchone())["worm_saved"]
        await cur.close()

        # 日別統計（過去30日）
        cur = await db.execute(
            """
            SELECT substr(ts, 1, 10) as date, COUNT(*) as count
            FROM consent_logs
            WHERE datetime(ts) > datetime('now', '-30 days')
            GROUP BY substr(ts, 1, 10)
            ORDER BY date DESC
            """
        )
        daily_stats = [{"date": r[0], "count": r[1]} for r in await cur.fetchall()]
        await cur.close()

        # バージョン別統計
        cur = await db.execute(
            """
            SELECT version, COUNT(*) as count
            FROM consent_logs
            WHERE withdrawn=0
            GROUP BY version
            ORDER BY count DESC
            """
        )
        version_stats = [{"version": r[0], "count": r[1]} for r in await cur.fetchall()]
        await cur.close()

    return {
        "overview": {
            "total_consents": total,
            "active_consents": active,
            "withdrawn_consents": total - active,
            "unique_users": users,
            "worm_saved_count": worm_saved,
            "worm_save_rate": f"{(worm_saved/total*100):.1f}%" if total > 0 else "0%"
        },
        "daily_stats": daily_stats,
        "version_stats": version_stats,
        "config": {
            "required_flags": REQUIRED_FLAGS,
            "retention_years": WORM_RETENTION_YEARS,
            "validity_months": CONSENT_VALIDITY_MONTHS,
            "gcs_bucket": GCS_CONSENT_BUCKET,
            "policy_version": POLICY_VERSION_DEFAULT,
            "line_account": f"@{LINE_ACCOUNT}"
        },
        "generated_at": _now_iso(),
    }

# =============================================================================
# 高速チェック用ミドルウェア関数（完全修正版）
# =============================================================================

def require_valid_consent(scope: str = "ai", version: str = None):
    """デコレータ：同意必須APIの保護（完全修正版）"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            request: Optional[Request] = kwargs.get("request") or (args[0] if args else None)
            if request:
                user_token = _extract_user_token_from_request(request)
                if not user_token:
                    raise HTTPException(
                        status_code=403, 
                        detail="consent_required: unidentified_user"
                    )
                user_id_raw = _user_id_from_token(user_token) or user_token
                user_id_hash = _sha256_hex(user_id_raw)
                
                check_version = version or POLICY_VERSION_DEFAULT
                ok = await fast_check_consent(user_id_hash, scope, check_version)
                if not ok:
                    raise HTTPException(
                        status_code=403, 
                        detail={
                            "error": "CONSENT_REQUIRED",
                            "version": check_version,
                            "required_flags": REQUIRED_FLAGS,
                            "scope": scope
                        }
                    )
            return await func(*args, **kwargs)
        return wrapper
    return decorator