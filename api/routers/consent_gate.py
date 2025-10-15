# api/routers/consent_gate.py
# PDF準拠・完全修正版：LIFF同意ゲート（必須4チェック + GCS疑似WORM + 高速チェック + LINE push 追加）
# 追記: ルーター内CORS（プリフライト対応 & 応答ヘッダ付与）を実装

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
from fastapi.responses import JSONResponse, Response  # ← 追加

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

# ---- LINE push（追加） ------------------------------------------------------
try:
    from linebot import LineBotApi
    from linebot.models import TextSendMessage
except Exception:
    LineBotApi = None
    TextSendMessage = None

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/consent", tags=["consent"])

# =============================================================================
# 設定
# =============================================================================
POLICY_VERSION_DEFAULT = os.getenv("POLICY_VERSION", "1.0.0")
CONSENT_VALIDITY_MONTHS = int(os.getenv("CONSENT_VALIDITY_MONTHS", "12"))
WORM_RETENTION_YEARS = int(os.getenv("WORM_RETENTION_YEARS", "5"))
GCS_CONSENT_BUCKET = os.getenv("GCS_CONSENT_BUCKET", "consent-logs-rag-cloud-project-asia-northeast1")
REDIS_URL = os.getenv("REDIS_URL", "")
CONSENT_CACHE_TTL_SEC = int(os.getenv("CONSENT_CACHE_TTL_SEC", "2592000"))  # 30日

# 必須4チェック
REQUIRED_FLAGS = ["pp", "xfer", "ai_limits", "cookie"]

# LINE関連
LINE_ACCOUNT = os.getenv("LINE_BASIC_ID", "").lstrip("@")  # 例: "kinoe-ai"
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
_line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN) if (LineBotApi and LINE_CHANNEL_ACCESS_TOKEN) else None

# ポリシーURL
PRIVACY_POLICY_URL = os.getenv("PRIVACY_POLICY_URL", "https://example.com/privacy")

# AI相談の定型文（環境変数が無ければ既定文）
AI_CONSULTATION_MESSAGE = os.getenv(
    "AI_CONSULTATION_MESSAGE",
    "こんにちは！家づくりのことなら何でも聞いてください！"
)

DEFAULT_DB_PATH = os.getenv("CONSENT_SQLITE_PATH", "/tmp/consent_management.db")

# ---- ここから CORS（このファイル内で自己完結） -----------------------------
def _parse_allowed_origins() -> list[str]:
    """
    ALLOWED_ORIGINS は Cloud Run に
      --set-env-vars=^|^ALLOWED_ORIGINS=url1|url2|...
    の形式で入ってくる想定。万一カンマ区切りでも許容。
    """
    raw = os.getenv("ALLOWED_ORIGINS", "")
    if not raw:
        # デフォルト（LIFF と想定フロント）: 必要に応じて環境に合わせてOK
        return [
            "https://liff.line.me",
            "https://rag-frontend-jy2dt7mlwq-an.a.run.app",
            "https://ai.kinoedesign.co.jp",
            "https://leafy-kitsune-eb4566.netlify.app",
        ]
    if "|" in raw:
        parts = [p.strip() for p in raw.split("|") if p.strip()]
    else:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts

_ALLOWED_ORIGINS = set(_parse_allowed_origins())
_CORS_ALLOW_METHODS = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
_CORS_ALLOW_HEADERS = "Authorization,Content-Type,X-User-Token,X-LIFF-ID"
_CORS_MAX_AGE = "86400"

def _match_origin(origin: Optional[str]) -> Optional[str]:
    """要求 Origin が許可リストに存在するならそのまま返す（ワイルドカードは使わない）"""
    if not origin:
        return None
    return origin if origin in _ALLOWED_ORIGINS else None

def _cors_json(data: Dict[str, Any] | list | bool, origin: Optional[str]) -> JSONResponse:
    resp = JSONResponse(content=data)
    allow = _match_origin(origin)
    if allow:
        resp.headers["Access-Control-Allow-Origin"] = allow
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Expose-Headers"] = "*"
    return resp

@router.options("/{full_path:path}")
async def _options_preflight(full_path: str, request: Request):
    """
    ルーター配下のすべてのプリフライトに応答。
    """
    origin = request.headers.get("origin")
    allow = _match_origin(origin)
    if not allow:
        # 許可外 Origin には最小限の応答（CORS不成立）
        return Response(status_code=204)

    resp = Response(status_code=204)
    resp.headers["Access-Control-Allow-Origin"] = allow
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    resp.headers["Access-Control-Allow-Methods"] = _CORS_ALLOW_METHODS
    resp.headers["Access-Control-Allow-Headers"] = _CORS_ALLOW_HEADERS
    resp.headers["Access-Control-Max-Age"] = _CORS_MAX_AGE
    return resp
# ---- CORS ここまで ----------------------------------------------------------

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
    """
    LIFF から渡る user_token が LINEの userId(U...) ならそのまま、
    JWT 等なら sub / user_id / email を拾う。検証は行わない（速度優先）。
    """
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
# DB（SQLite）
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
            user_id_hash TEXT NOT NULL,
            account TEXT NOT NULL,
            liff_id TEXT,
            ts TEXT NOT NULL,
            ip TEXT,
            ua TEXT,
            liff_os TEXT,
            version TEXT NOT NULL,
            scope TEXT NOT NULL,
            policy_url TEXT,
            flags TEXT NOT NULL,
            locale TEXT,
            withdrawn INTEGER DEFAULT 0,
            withdrawn_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            gcs_object_name TEXT,
            gcs_generation INTEGER
        )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_consent_user_hash ON consent_logs(user_id_hash)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_consent_valid ON consent_logs(user_id_hash, version, withdrawn)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_consent_created ON consent_logs(created_at)")
        await db.commit()
        logger.info("✅ consent_logs ready at %s", DEFAULT_DB_PATH)

# =============================================================================
# モデル
# =============================================================================

class ConsentSaveBody(BaseModel):
    agree_privacy: bool = Field(..., description="プライバシーポリシーに同意")
    understand_external_send: bool = Field(..., description="外部送信への理解")
    understand_ai_may_be_wrong: bool = Field(..., description="AIの限界理解")
    agree_cookie: bool = Field(..., description="Cookie同意（計測含む）")
    liff_os: Optional[str] = Field(None, description="iOS/Android/Web")
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
# GCS疑似WORM保存
# =============================================================================

async def _save_to_gcs_pseudo_worm(consent_json: Dict[str, Any]) -> tuple[str, int]:
    if not storage:
        logger.warning("GCS storage client not available")
        return "", 0
    try:
        client = storage.Client()
        bucket = client.bucket(GCS_CONSENT_BUCKET)
        dt = datetime.fromisoformat(consent_json["ts"].replace("Z", "+00:00"))
        user_hash = consent_json["user_id_hash"]
        account = consent_json.get("account", f"@{LINE_ACCOUNT}" if LINE_ACCOUNT else "@account")
        object_name = f"consents/{dt.year}/{dt.month:02d}/{dt.day:02d}/{account}/{user_hash}/{consent_json['consent_id']}.json"
        blob = bucket.blob(object_name)

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
        blob.content_type = "application/json"
        blob.metadata = {
            "consent_id": consent_json["consent_id"],
            "version": consent_json["version"],
            "scope": ",".join(consent_json.get("scope", ["ai"])),
            "retention_years": str(WORM_RETENTION_YEARS),
            "immutable": "pseudo",
            "account": account
        }
        blob.upload_from_string(json.dumps(worm_payload, ensure_ascii=False, indent=2), content_type="application/json")
        generation = blob.generation or 0
        logger.info(f"✅ Consent saved to GCS pseudo-WORM: {object_name} (gen: {generation})")
        return object_name, generation
    except Exception as e:
        logger.error(f"❌ GCS pseudo-WORM save failed: {e}")
        return "", 0

async def _bg_gcs_save_and_mark(consent_json: Dict[str, Any], consent_id: str):
    obj_name, generation = await _save_to_gcs_pseudo_worm(consent_json)
    if obj_name:
        async with _open_db() as db:
            await db.execute(
                "UPDATE consent_logs SET gcs_object_name=?, gcs_generation=? WHERE consent_id=?",
                (obj_name, generation, consent_id)
            )
            await db.commit()

# =============================================================================
# LINE push（追加）
# =============================================================================

async def _bg_push_ai_welcome(user_token: str):
    """user_token から U始まりの userId を推定できた時だけ push"""
    if not _line_bot_api or not TextSendMessage:
        return
    user_id = _user_id_from_token(user_token)
    if not (isinstance(user_id, str) and user_id.startswith("U")):
        return
    try:
        _line_bot_api.push_message(user_id, TextSendMessage(text=AI_CONSULTATION_MESSAGE))
        logger.info(f"✅ AI consultation message pushed to {user_id}")
    except Exception as e:
        logger.warning(f"LINE push failed: {e}")

# =============================================================================
# 高速チェック
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
    user_token: str = Query(..., description="LIFFからのuser_token"),
    scope: str = Query("ai", description="同意の適用範囲"),
    version: str = Query(None, description="ポリシー版"),
):
    """
    LIFF 同意保存API：
    - 必須4チェック（pp/xfer/ai_limits/cookie）すべて True でなければ 400
    - SQLite に保存（直前の有効同意は withdrawn=1）
    - バックグラウンドで GCS（疑似WORM）保存
    - 可能なら LINE に AI相談開始の定型文を push（非同期）
    """
    version = version or POLICY_VERSION_DEFAULT

    # 必須4チェック
    flags = {
        "pp": bool(body.agree_privacy),
        "cookie": bool(body.agree_cookie),
        "xfer": bool(body.understand_external_send),
        "ai_limits": bool(body.understand_ai_may_be_wrong),
    }
    if not _all_required_true(flags):
        missing = [k for k in REQUIRED_FLAGS if not flags.get(k)]
        raise HTTPException(status_code=400, detail=f"Required consent flags missing: {missing}")

    # ユーザー特定
    if not user_token:
        raise HTTPException(status_code=400, detail="user_token is required")
    user_id_raw = _user_id_from_token(user_token) or user_token
    user_id_hash = _sha256_hex(user_id_raw)

    consent_id = str(uuid4())
    ts = _now_iso()

    # 保存レコード
    record = {
        "consent_id": consent_id,
        "user_id_hash": user_id_hash,
        "account": f"@{LINE_ACCOUNT}" if LINE_ACCOUNT else "@account",
        "liff_id": request.headers.get("X-LIFF-ID"),
        "ts": ts,
        "ip": request.client.host if request.client else "",
        "ua": request.headers.get("user-agent", ""),
        "liff_os": body.liff_os or "",
        "version": version,
        "scope": json.dumps([scope]),
        "policy_url": PRIVACY_POLICY_URL,
        "flags": json.dumps(flags, ensure_ascii=False),
        "locale": body.locale or "ja-JP",
        "withdrawn": 0,
    }

    # DB保存：直前の有効同意を撤回 → 新規同意を追加
    async with _open_db() as db:
        await db.execute(
            "UPDATE consent_logs SET withdrawn=1, withdrawn_at=datetime('now') WHERE user_id_hash=? AND withdrawn=0",
            (user_id_hash,)
        )
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

    # キャッシュ更新（即時OKに）
    await _consent_cache.set(user_id_hash, scope, version, True)

    # GCS保存（バックグラウンド）
    if bg is not None:
        consent_json = {
            "consent_id": consent_id,
            "user_id_hash": user_id_hash,
            "account": record["account"],
            "scope": [scope],
            "version": version,
            "policy_url": PRIVACY_POLICY_URL,
            "ts": ts,
            "ip": record["ip"],
            "ua": record["ua"],
            "liff_os": record["liff_os"],
            "locale": record["locale"],
            "withdrawn": False,
            "flags": flags,
            "meta": body.meta or {},
        }
        bg.add_task(_bg_gcs_save_and_mark, consent_json, consent_id)

        # 追加：AI相談開始メッセージ push（可能なら）
        bg.add_task(_bg_push_ai_welcome, user_token)

    # ← CORS 付与して返す
    origin = request.headers.get("origin")
    return _cors_json(
        {
            "ok": True,
            "consent_id": consent_id,
            "message": "同意が正常に保存されました",
            "worm_scheduled": True,
            "version": version
        },
        origin,
    )

@router.post("/check")
async def check_consent(
    request: Request,
    payload: 'ConsentCheckRequest' = Body(None),
    scope: str = Query("ai"),
    version: str = Query(None),
):
    user_token = _extract_user_token_from_request(request)
    user_id = payload.user_id if payload and payload.user_id else None
    version = payload.version or version or POLICY_VERSION_DEFAULT
    scope = payload.scope or scope

    if not (user_token or user_id):
        return _cors_json(
            {"valid": False, "error": "CONSENT_REQUIRED", "version": version, "required_flags": REQUIRED_FLAGS},
            request.headers.get("origin"),
        )

    user_id_raw = user_id or _user_id_from_token(user_token) or user_token
    user_id_hash = _sha256_hex(user_id_raw)
    ok = await fast_check_consent(user_id_hash, scope, version)
    if not ok:
        return _cors_json(
            {"valid": False, "error": "CONSENT_REQUIRED", "version": version, "required_flags": REQUIRED_FLAGS},
            request.headers.get("origin"),
        )

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
        return _cors_json({"valid": True}, request.headers.get("origin"))

    ts = (
        datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        if "Z" in row["ts"] else
        datetime.fromisoformat(row["ts"])
    )
    expires_at = ts + timedelta(days=30 * CONSENT_VALIDITY_MONTHS)

    return _cors_json(
        {
            "valid": True,
            "version": version,
            "account": row["account"],
            "scope": json.loads(row["scope"] or "[]"),
            "policy_url": row["policy_url"],
            "consented_at": ts.isoformat(),
            "expires_at": expires_at.isoformat(),
            "flags": _parse_flags(row["flags"])
        },
        request.headers.get("origin"),
    )

@router.post("/withdraw")
async def withdraw_consent(withdraw_request: 'ConsentWithdrawRequest', request: Request):
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
    return _cors_json({"success": True, "message": "同意が撤回されました"}, request.headers.get("origin"))

@router.get("/user/{user_id}/history")
async def get_consent_history(user_id: str, request: Request):
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
            "consented_at": r["ts"],
            "version": r["version"],
            "account": r["account"],
            "scope": json.loads(r["scope"] or "[]"),
            "withdrawn": bool(r["withdrawn"]),
            "withdrawn_at": r["withdrawn_at"],
            "flags": _parse_flags(r["flags"]),
        })
    return _cors_json({"user_id": user_id, "history": history, "total_records": len(history)}, request.headers.get("origin"))

@router.get("/admin/stats")
async def get_consent_stats(request: Request):
    async with _open_db() as db:
        db.row_factory = aiosqlite.Row

        cur = await db.execute("SELECT COUNT(*) as total FROM consent_logs")
        total = (await cur.fetchone())["total"]; await cur.close()

        cur = await db.execute("SELECT COUNT(*) as active FROM consent_logs WHERE withdrawn=0")
        active = (await cur.fetchone())["active"]; await cur.close()

        cur = await db.execute("SELECT COUNT(DISTINCT user_id_hash) as unique_users FROM consent_logs")
        users = (await cur.fetchone())["unique_users"]; await cur.close()

        cur = await db.execute("SELECT COUNT(*) as worm_saved FROM consent_logs WHERE gcs_object_name IS NOT NULL")
        worm_saved = (await cur.fetchone())["worm_saved"]; await cur.close()

        cur = await db.execute(
            """
            SELECT substr(ts, 1, 10) as date, COUNT(*) as count
            FROM consent_logs
            WHERE datetime(ts) > datetime('now', '-30 days')
            GROUP BY substr(ts, 1, 10)
            ORDER BY date DESC
            """
        )
        daily_stats = [{"date": r[0], "count": r[1]} for r in await cur.fetchall()]; await cur.close()

        cur = await db.execute(
            """
            SELECT version, COUNT(*) as count
            FROM consent_logs
            WHERE withdrawn=0
            GROUP BY version
            ORDER BY count DESC
            """
        )
        version_stats = [{"version": r[0], "count": r[1]} for r in await cur.fetchall()]; await cur.close()

    return _cors_json(
        {
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
                "line_account": f"@{LINE_ACCOUNT}" if LINE_ACCOUNT else ""
            },
            "generated_at": _now_iso(),
        },
        request.headers.get("origin"),
    )

# =============================================================================
# デコレータ（必要なAPIの保護に使用可能）
# =============================================================================

def require_valid_consent(scope: str = "ai", version: str = None):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            request: Optional[Request] = kwargs.get("request") or (args[0] if args else None)
            if request:
                user_token = _extract_user_token_from_request(request)
                if not user_token:
                    raise HTTPException(status_code=403, detail="consent_required: unidentified_user")
                user_id_raw = _user_id_from_token(user_token) or user_token
                user_id_hash = _sha256_hex(user_id_raw)
                check_version = version or POLICY_VERSION_DEFAULT
                ok = await fast_check_consent(user_id_hash, scope, check_version)
                if not ok:
                    raise HTTPException(
                        status_code=403,
                        detail={"error": "CONSENT_REQUIRED", "version": check_version, "required_flags": REQUIRED_FLAGS, "scope": scope}
                    )
            return await func(*args, **kwargs)
        return wrapper
    return decorator