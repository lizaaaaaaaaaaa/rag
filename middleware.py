# ====================
# middleware.py（完全版）
# ====================

import os
import time
import uuid
import logging
from typing import Callable, Iterable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# 設定のインポート（存在しない環境でも安全にフォールバック）
try:
    from config import get_settings  # 任意
except ImportError:
    def get_settings():
        class Settings:
            rate_limit_per_minute = 100
            allowed_origins = ["*"]
        return Settings()

settings = get_settings()
logger = logging.getLogger(__name__)


# -----------------------------
# 共通ユーティリティ
# -----------------------------
def _starts_with_any(path: str, prefixes: Iterable[str]) -> bool:
    return any(path.startswith(p) for p in prefixes)


# -----------------------------
# レスポンス時間計測
# -----------------------------
class TimingMiddleware(BaseHTTPMiddleware):
    """レスポンス時間計測 & リクエストID付与"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.time()
        request.state.request_id = str(uuid.uuid4())

        response = await call_next(request)

        elapsed = time.time() - start
        response.headers["X-Process-Time"] = f"{elapsed:.6f}"
        response.headers["X-Request-ID"] = request.state.request_id

        if elapsed > 1.0:
            logger.warning(
                "Slow request %s %s took %.2fs (Request-ID: %s)",
                request.method, request.url.path, elapsed, request.state.request_id
            )
        return response


# -----------------------------
# レート制限（簡易・メモリ）
# -----------------------------
class RateLimitMiddleware(BaseHTTPMiddleware):
    """単純なIPベースのレート制限（必要ならRedisへ置換）"""

    def __init__(self, app, requests_per_minute: int = None):
        super().__init__(app)
        self.limit = requests_per_minute or getattr(settings, "rate_limit_per_minute", 100)
        self.client_requests = {}  # {ip: [timestamps]}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # OPTIONS は事前フライトで弾かない
        if request.method == "OPTIONS":
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        now = time.time()

        bucket = self.client_requests.setdefault(ip, [])
        # 1分超を掃除
        self.client_requests[ip] = [t for t in bucket if now - t < 60.0]
        if len(self.client_requests[ip]) >= self.limit:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded"}
            )
        self.client_requests[ip].append(now)
        return await call_next(request)


# -----------------------------
# セキュリティヘッダー
# -----------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """基本的なセキュリティヘッダーの付与"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        # 必要に応じて CSP を詳細化
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'")
        return response


# -----------------------------
# CORS（簡易）
# -----------------------------
class CORSMiddleware(BaseHTTPMiddleware):
    """許可オリジンの制御（必要に応じてFastAPI公式CORSへ置換可）"""

    def __init__(self, app, allowed_origins=None):
        super().__init__(app)
        self.allowed = allowed_origins or getattr(settings, "allowed_origins", ["*"])

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 事前フライト
        if request.method == "OPTIONS":
            response = Response()
        else:
            response = await call_next(request)

        origin = request.headers.get("origin")
        if "*" in self.allowed or (origin and origin in self.allowed):
            response.headers["Access-Control-Allow-Origin"] = origin or "*"
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-User-Id"
        response.headers["Access-Control-Max-Age"] = "86400"
        return response


# -----------------------------
# 監査ログ（INFO）
# -----------------------------
class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """簡易監査ログ（PIIは原則記録しない）"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        rid = getattr(request.state, "request_id", "-")
        logger.info("Request %s %s (RID=%s) from %s",
                    request.method, request.url.path, rid, request.client.host if request.client else "-")
        response = await call_next(request)
        logger.info("Response %s %s -> %s (RID=%s)",
                    request.method, request.url.path, response.status_code, rid)
        return response


# -----------------------------
# 同意ゲート（本実装）
# -----------------------------
class ConsentGateMiddleware(BaseHTTPMiddleware):
    """
    同意ゲート:
      - /chat /upload /ingest /api /line など“AI/個人情報に触れる入口”は同意が必須
      - 有効同意(5点: pp/tos/cookie/xfer/ai_limits) & policy_version 一致をDBで検証
      - 未同意/不足は 403 (fail-closed)
      - ユーザー識別: Authorization: Bearer <JWT> または X-User-Id
      - ENFORCE=false でドライラン可（ログのみ）
    """

    def __init__(self, app, excluded_paths: list = None, required_version_env: str = "POLICY_VERSION"):
        super().__init__(app)
        self.excluded_prefixes = tuple((excluded_paths or []) + [
            # 法務/同意/認証/診断/静的系は除外
            "/health", "/healthz", "/legal", "/privacy", "/terms", "/cookie",
            "/liff", "/consent", "/auth", "/debug", "/system-status", "/ops",
            "/static", "/favicon.ico"
        ])
        self.required_version = os.getenv(required_version_env, "").strip() or "2025-09-01"
        self.required_flags = {"pp", "tos", "cookie", "xfer", "ai_limits"}
        self.enforce = (os.getenv("CONSENT_ENFORCE", "true").lower() == "true")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # 事前フライト / 除外パス
        if request.method == "OPTIONS" or _starts_with_any(path, self.excluded_prefixes):
            return await call_next(request)

        # GET "/"（トップ）だけは素通し（必要に応じて外してOK）
        if path == "/" and request.method == "GET":
            return await call_next(request)

        # 保護対象
        protected = path.startswith(("/chat", "/upload", "/ingest", "/api", "/line"))
        if not protected:
            return await call_next(request)

        # ユーザー特定
        user_id = request.headers.get("X-User-Id")
        if not user_id:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth.split(" ", 1)[1]
                try:
                    import jwt  # PyJWT
                    # 署名検証は上流のAuthで実施想定。ここではID抽出のみ。
                    payload = jwt.decode(token, options={"verify_signature": False},
                                         algorithms=["HS256", "RS256", "ES256"])
                    user_id = payload.get("sub") or payload.get("user_id") or payload.get("email")
                except Exception:
                    user_id = None

        if not user_id:
            if not self.enforce:
                logger.warning("ConsentGate(drill): unidentified user -> allow (path=%s)", path)
                return await call_next(request)
            return JSONResponse(status_code=403, content={"detail": "consent_required: unidentified_user"})

        # DB検証
        try:
            from database import get_db_context
            from sqlalchemy import select
            from models import ConsentRecord
        except Exception:
            # 依存解決失敗時は安全側（本番 enforce=True で 403）
            logger.exception("ConsentGate: dependency import error")
            if not self.enforce:
                return await call_next(request)
            return JSONResponse(status_code=403, content={"detail": "consent_required: system_error"})

        async with get_db_context() as session:
            q = select(ConsentRecord).where(
                ConsentRecord.user_id == user_id,
                ConsentRecord.is_active == True,
                ConsentRecord.consent_version == self.required_version
            ).order_by(ConsentRecord.timestamp.desc())
            res = (await session.execute(q)).scalars().first()

        if not res:
            if not self.enforce:
                logger.warning("ConsentGate(drill): consent not found (uid=%s ver=%s) -> allow", user_id, self.required_version)
                return await call_next(request)
            return JSONResponse(status_code=403, content={"detail": "consent_required: not_found"})

        # 5点同意の担保: data_categories.flags または consent_text 内のキーワード
        try:
            txt = (res.consent_text or "").lower()
            dc = res.data_categories or {}
            flag_map = (dc.get("flags") or {}) if isinstance(dc, dict) else {}
            flags = {k for k, v in flag_map.items() if v} | \
                    {f for f in ("pp", "tos", "cookie", "xfer", "ai_limits") if f in txt}
        except Exception:
            flags = set()

        if not self.required_flags.issubset(flags):
            if not self.enforce:
                logger.warning("ConsentGate(drill): flags insufficient (%s) -> allow", flags)
                return await call_next(request)
            return JSONResponse(status_code=403, content={"detail": "consent_required: flags_insufficient"})

        # ここまで通ればOK
        return await call_next(request)
