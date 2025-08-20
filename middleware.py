# ====================
# middleware.py の修正版
# ====================

import time
import uuid
from typing import Callable
from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
import logging

# 設定のインポート（修正）
try:
    from config import get_settings
except ImportError:
    # config.pyが存在しない場合のフォールバック
    def get_settings():
        class Settings:
            rate_limit_per_minute = 100
        return Settings()

settings = get_settings()
logger = logging.getLogger(__name__)

class TimingMiddleware(BaseHTTPMiddleware):
    """レスポンス時間計測ミドルウェア"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        
        # リクエストIDの生成
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        response = await call_next(request)
        
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        response.headers["X-Request-ID"] = request_id
        
        # 遅いリクエストのログ出力
        if process_time > 1.0:  # 1秒以上
            logger.warning(
                f"Slow request: {request.method} {request.url.path} "
                f"took {process_time:.2f}s (Request ID: {request_id})"
            )
        
        return response

class RateLimitMiddleware(BaseHTTPMiddleware):
    """レート制限ミドルウェア"""
    
    def __init__(self, app, requests_per_minute: int = 100):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.client_requests = {}  # クライアントIP別のリクエスト履歴
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host
        current_time = time.time()
        
        # 古いエントリの削除
        if client_ip in self.client_requests:
            self.client_requests[client_ip] = [
                req_time for req_time in self.client_requests[client_ip]
                if current_time - req_time < 60  # 1分以内のリクエストのみ保持
            ]
        else:
            self.client_requests[client_ip] = []
        
        # レート制限チェック
        if len(self.client_requests[client_ip]) >= self.requests_per_minute:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded"}
            )
        
        # リクエスト記録
        self.client_requests[client_ip].append(current_time)
        
        response = await call_next(request)
        return response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """セキュリティヘッダーミドルウェア"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        # セキュリティヘッダーの追加
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        
        return response

class CORSMiddleware(BaseHTTPMiddleware):
    """CORS設定ミドルウェア"""
    
    def __init__(self, app, allowed_origins: list = None):
        super().__init__(app)
        self.allowed_origins = allowed_origins or ["*"]
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method == "OPTIONS":
            response = Response()
        else:
            response = await call_next(request)
        
        # CORS ヘッダーの設定
        origin = request.headers.get("origin")
        if origin in self.allowed_origins or "*" in self.allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin or "*"
        
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Max-Age"] = "86400"
        
        return response

class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """監査ログミドルウェア"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        
        # リクエスト情報の記録
        logger.info(
            f"Request: {request.method} {request.url.path} "
            f"from {request.client.host} "
            f"(Request ID: {getattr(request.state, 'request_id', 'unknown')})"
        )
        
        response = await call_next(request)
        
        # レスポンス情報の記録
        process_time = time.time() - start_time
        logger.info(
            f"Response: {response.status_code} "
            f"in {process_time:.3f}s "
            f"(Request ID: {getattr(request.state, 'request_id', 'unknown')})"
        )
        
        return response

class ConsentGateMiddleware(BaseHTTPMiddleware):
    """同意ゲートミドルウェア"""
    
    def __init__(self, app, excluded_paths: list = None):
        super().__init__(app)
        self.excluded_paths = excluded_paths or []
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 除外パスのチェック
        if any(request.url.path.startswith(path) for path in self.excluded_paths):
            return await call_next(request)
        
        # 同意チェックロジックをここに実装
        # 現在はパススルー
        return await call_next(request)