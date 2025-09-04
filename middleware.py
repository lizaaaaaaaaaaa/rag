# ====================
# middleware.py（RateLimitをCloud Run向けに安全化）
# ====================

import os
import time
import uuid
import logging
from typing import Callable, Iterable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

try:
    from config import get_settings  # optional
except ImportError:  # pragma: no cover
    def get_settings():
        class Settings:
            rate_limit_per_minute = 100
            allowed_origins = ["*"]
        return Settings()

settings = get_settings()
logger = logging.getLogger(__name__)

def _starts_with_any(path: str, prefixes: Iterable[str]) -> bool:
    return any(path.startswith(p) for p in prefixes)

class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.time()
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        elapsed = time.time() - start
        response.headers["X-Process-Time"] = f"{elapsed:.6f}"
        response.headers["X-Request-ID"] = request.state.request_id
        if elapsed > 1.0:
            logger.warning("Slow request %s %s took %.2fs (RID=%s)",
                           request.method, request.url.path, elapsed, request.state.request_id)
        return response

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Cloud Run での誤爆を避けるためのレート制限:
      - /line/webhook と /liff/*、/health*、/system-status は除外
      - X-Forwarded-For 優先でクライアントIPを取得
      - パス別バケツで集計（/chat と /upload のカウントを分離）
      - 上限は RATE_LIMIT_PER_MINUTE 環境変数で変更可（未設定時は設定値 or 600）
    """
    def __init__(self, app, requests_per_minute: int = None):
        super().__init__(app)
        # Cloud Run で落ちない安全値。環境変数があればそれを採用。
        self.limit = int(os.getenv("RATE_LIMIT_PER_MINUTE",
                                   str(getattr(settings, "rate_limit_per_minute", 600))))
        self.client_requests: dict[str, list[float]] = {}
        # レート制限を掛けない経路（LINE/ヘルス/同意導線は常に通す）
        self.allow_prefixes = ("/liff/", "/health", "/healthz")
        self.allow_paths = {"/line/webhook", "/system-status", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path in self.allow_paths or _starts_with_any(path, self.allow_prefixes):
            return await call_next(request)

        # Cloud Run は request.client.host が 169.254.169.126 になることが多い → X-Forwarded-For を優先
        xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
        ip_hdr = xff.split(",")[0].strip() if xff else None
        ip = ip_hdr or request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")

        now = time.time()
        # 経路ごとのバケツにして誤爆を減らす（同一IPでも /line/webhook と /chat を分離）
        key = f"{ip}:{path}"
        bucket = self.client_requests.setdefault(key, [])
        # 直近60秒に限定
        self.client_requests[key] = [t for t in bucket if now - t < 60.0]
        if len(self.client_requests[key]) >= self.limit:
            return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                content={"detail": "Rate limit exceeded"})
        self.client_requests[key].append(now)

        return await call_next(request)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'")
        return response

class CORSMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_origins=None):
        super().__init__(app)
        self.allowed = allowed_origins or getattr(settings, "allowed_origins", ["*"])

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
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

class AuditLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        rid = getattr(request.state, "request_id", "-")
        logger.info("Request %s %s (RID=%s) from %s",
                    request.method, request.url.path, rid, request.client.host if request.client else "-")
        response = await call_next(request)
        logger.info("Response %s %s -> %s (RID=%s)",
                    request.method, request.url.path, response.status_code, rid)
        return response

class ConsentGateMiddleware(BaseHTTPMiddleware):
    """
    同意ゲート:
      - /upload /ingest /api /line などは同意必須
      - Web /chat は除外（今回の要件）
    """
    def __init__(self, app, excluded_paths: list = None, required_version_env: str = "POLICY_VERSION"):
        super().__init__(app)
        self.excluded_prefixes = tuple((excluded_paths or []) + [
            "/health", "/healthz", "/legal", "/privacy", "/terms", "/cookie",
            "/liff", "/consent", "/consent/", "/auth", "/debug", "/system-status", "/ops",
            "/static", "/favicon.ico",
            "/line/webhook",
            "/chat", "/chat/",  # ★ Webチャットは同意不要
        ])
        self.required_version = os.getenv(required_version_env, "").strip() or "2025-09-01"
        self.required_flags = {"pp", "tos", "cookie", "xfer", "ai_limits"}
        self.enforce = (os.getenv("CONSENT_ENFORCE", "true").lower() == "true")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        if request.method == "OPTIONS" or _starts_with_any(path, self.excluded_prefixes):
            return await call_next(request)

        if path == "/" and request.method == "GET":
            return await call_next(request)

        # /chat は上で除外済み。ここでは /upload /ingest /api /line のみ保護
        protected = path.startswith(("/upload", "/ingest", "/api", "/line"))
        if not protected:
            return await call_next(request)

        # ここから先は（LINE等の）同意ゲート判定…（元の実装を維持）
        user_id = request.headers.get("X-User-Id")
        if not user_id:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth.split(" ", 1)[1]
                try:
                    import jwt
                    payload = jwt.decode(token, options={"verify_signature": False},
                                         algorithms=["HS256", "RS256", "ES256"])
                    user_id = payload.get("sub") or payload.get("user_id") or payload.get("email")
                except Exception:
                    user_id = None

        if not user_id:
            if not self.enforce:
                return await call_next(request)
            return JSONResponse(status_code=403, content={"detail": "consent_required: unidentified_user"})

        try:
            from database import get_db_context
            from sqlalchemy import select
            from models import ConsentRecord
        except Exception:
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
                return await call_next(request)
            return JSONResponse(status_code=403, content={"detail": "consent_required: not_found"})

        try:
            txt = (res.consent_text or "").lower()
            dc = res.data_categories or {}
            flag_map = (dc.get("flags") or {}) if isinstance(dc, dict) else {}
            flags = {k for k, v in flag_map.items() if v} | {f for f in ("pp","tos","cookie","xfer","ai_limits") if f in txt}
        except Exception:
            flags = set()

        required_flags = {"pp", "tos", "cookie", "xfer", "ai_limits"}
        if not required_flags.issubset(flags):
            if not self.enforce:
                return await call_next(request)
            return JSONResponse(status_code=403, content={"detail": "consent_required: flags_insufficient"})

        return await call_next(request)
