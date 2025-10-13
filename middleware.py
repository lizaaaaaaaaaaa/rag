# ====================
# middleware.py（CORS/RateLimit/Headers/ConsentGate） - fixed
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
            rate_limit_per_minute = 600
            allowed_origins = []
        return Settings()

settings = get_settings()
logger = logging.getLogger(__name__)


# ---------- helpers
def _starts_with_any(path: str, prefixes: Iterable[str]) -> bool:
    return any(path.startswith(p) for p in prefixes)


def _normalize(o: str | None) -> str | None:
    if not o:
        return None
    return o.strip().rstrip("/")


def _build_allowed_origins() -> list[str]:
    """
    許可 Origin を環境変数と既定値から生成
    - ALLOWED_ORIGINS（カンマ区切り）
    - PUBLIC_FRONT_BASE / PUBLIC_API_BASE / PUBLIC_BASE_URL
    - settings.allowed_origins
    - 既定で Netlify 本番 / 自社ドメイン / LIFF を含める
    """
    origins: set[str] = set()

    # 明示指定（例: "https://a.com,https://b.com"）
    env_allow = _normalize(os.getenv("ALLOWED_ORIGINS") or "")
    if env_allow:
        for o in env_allow.split(","):
            o = _normalize(o)
            if o:
                origins.add(o)

    # プロジェクトの公開 URL 群
    for key in ("PUBLIC_FRONT_BASE", "PUBLIC_API_BASE", "PUBLIC_BASE_URL"):
        v = _normalize(os.getenv(key))
        if v:
            origins.add(v)

    # 設定ファイルに書いてあるもの
    for o in getattr(settings, "allowed_origins", []) or []:
        o = _normalize(o)
        if o:
            origins.add(o)

    # ★ 既定の許可オリジン（要件に合わせて追加）
    defaults = [
        "https://leafy-kitsune-eb4566.netlify.app",
        "https://ai.kinoedesign.co.jp",
    ]
    origins.update([_normalize(x) for x in defaults])

    # LIFF は常に許可
    origins.add("https://liff.line.me")

    # 何もなければ "自己自身" をフォールバックで許可
    if not origins:
        self_url = _normalize(os.getenv("PUBLIC_API_BASE") or os.getenv("PUBLIC_BASE_URL") or "")
        if self_url:
            origins.add(self_url)

    # None を除去して整形
    return sorted([o for o in origins if o])


# ---------- middlewares
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
      - /line/webhook と /liff/*、/consent*、/health*、/system-status は除外
      - X-Forwarded-For 優先でクライアントIPを取得
      - パス別バケツで集計（同一IPでも経路ごとに分離）
      - 上限は RATE_LIMIT_PER_MINUTE 環境変数（未設定は 600）
    """
    def __init__(self, app, requests_per_minute: int | None = None):
        super().__init__(app)
        self.limit = int(os.getenv("RATE_LIMIT_PER_MINUTE",
                                   str(getattr(settings, "rate_limit_per_minute", 600))))
        self.client_requests: dict[str, list[float]] = {}
        self.allow_prefixes = ("/liff/", "/consent", "/health", "/healthz")
        self.allow_paths = {"/line/webhook", "/system-status", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method in ("OPTIONS", "HEAD"):
            # Preflight や HEAD は素通し
            return await call_next(request)

        path = request.url.path
        if path in self.allow_paths or _starts_with_any(path, self.allow_prefixes):
            return await call_next(request)

        # Cloud Run 環境の実IP判定
        xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
        ip_hdr = xff.split(",")[0].strip() if xff else None
        ip = ip_hdr or request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")

        now = time.time()
        key = f"{ip}:{path}"
        bucket = self.client_requests.setdefault(key, [])
        self.client_requests[key] = [t for t in bucket if now - t < 60.0]
        if len(self.client_requests[key]) >= self.limit:
            return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                content={"detail": "Rate limit exceeded"})
        self.client_requests[key].append(now)

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    LIFF からの利用を妨げないセキュリティヘッダ（LIFF SDK許可対応）
    """
    def __init__(self, app):
        super().__init__(app)
        # 許可する frame 祖先
        self.frame_ancestors = " ".join(["'self'", "https://liff.line.me", "https://*.line.me"])

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        res = await call_next(request)
        # クリックジャッキング対策（LIFF を許可）
        res.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        # XSS/CTO/HSTS
        res.headers.setdefault("X-Content-Type-Options", "nosniff")
        res.headers.setdefault("X-XSS-Protection", "1; mode=block")
        res.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        # Referrer/Permissions
        res.headers.setdefault("Referrer-Policy", "no-referrer-when-downgrade")
        res.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=()")

        # ★ LIFF / GTM / CDN を許可する最小限CSP（速度劣化なし）
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://static.line-scdn.net https://liff.line.me https://www.googletagmanager.com https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src * data: blob:; "
            "media-src * data: blob:; "
            "connect-src *; "
            "frame-ancestors " + self.frame_ancestors + "; "
            "frame-src https://liff.line.me https://*.line.me"
        )
        res.headers.setdefault("Content-Security-Policy", csp)
        return res


class CORSMiddleware(BaseHTTPMiddleware):
    """
    自前 CORS（Origin ホワイトリスト方式）
    """
    def __init__(self, app, allowed_origins: list[str] | None = None):
        super().__init__(app)
        self.allowed = [o for o in (allowed_origins or _build_allowed_origins()) if o]
        logger.info(f"CORS allowed origins: {self.allowed}")

        # CORS統一ヘッダ（preflight/本番応答で共用）
        self.allow_methods = "GET, POST, PUT, DELETE, OPTIONS"
        self.allow_headers = (
            "Authorization, Content-Type, X-User-Id, X-User-Token, "
            "X-Requested-With, user_token, Accept, Accept-Language, Origin, Referer"
        )
        self.max_age = "86400"

    def _origin_is_allowed(self, origin: str | None) -> bool:
        if not origin:
            return False
        origin = origin.rstrip("/")
        if origin in self.allowed:
            return True
        # line.me のサブドメインは広めに許可
        if origin.endswith(".line.me"):
            return True
        return False

    def _apply_cors(self, resp: Response, origin: str):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = self.allow_methods
        resp.headers["Access-Control-Allow-Headers"] = self.allow_headers
        resp.headers["Access-Control-Max-Age"] = self.max_age

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        origin = request.headers.get("origin") or request.headers.get("Origin")
        allowed = self._origin_is_allowed(origin)

        if request.method == "OPTIONS":
            # Preflight は即時応答（許可時のみCORSヘッダを付与）
            resp = Response(status_code=204)
            if allowed:
                self._apply_cors(resp, origin.rstrip("/"))
            else:
                logger.warning(f"CORS rejected origin (preflight): {origin}")
            return resp

        # 通常リクエスト
        resp = await call_next(request)
        if allowed:
            self._apply_cors(resp, origin.rstrip("/"))
        else:
            logger.warning(f"CORS rejected origin: {origin}")
        return resp


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
      - /ingest /api /line などは同意必須
      - Web /chat は除外
      - LINEログイン関連も除外
      - /upload* は UI 用に除外
    """
    def __init__(self, app, excluded_paths: list | None = None, required_version_env: str = "POLICY_VERSION"):
        super().__init__(app)
        self.excluded_prefixes = tuple((excluded_paths or []) + [
            "/health", "/healthz", "/legal", "/privacy", "/terms", "/cookie",
            "/liff", "/consent", "/consent/", "/auth", "/debug", "/system-status", "/ops",
            "/static", "/favicon.ico",
            "/line/webhook",
            "/line/after-consent",  # 同意直後のPushは通す
            "/line-login",          # LINEログイン関連
            "/chat", "/chat/",
            "/upload", "/upload/",  # アップロードUI
        ])
        self.required_version = os.getenv(required_version_env, "").strip() or "2025-09-01"
        self.required_flags = {"pp", "tos", "cookie", "xfer", "ai_limits"}
        self.enforce = (os.getenv("CONSENT_ENFORCE", "true").lower() == "true")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        if request.method in ("OPTIONS", "HEAD") or _starts_with_any(path, self.excluded_prefixes):
            return await call_next(request)

        if path == "/" and request.method == "GET":
            return await call_next(request)

        # ここでは /ingest /api /line を保護（/upload は除外済み）
        protected = path.startswith(("/ingest", "/api", "/line"))
        if not protected:
            return await call_next(request)

        # ユーザー識別（できなければ enforcement オフ時は通す）
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

        # DB 確認（実装がない場合は enforcement オフで通す）
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
