# ====================
# utils/exception_handlers.py
# ====================

import traceback
import uuid
from typing import Dict, Any, Optional
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging
from datetime import datetime
from utils.notification import send_compliance_alert
from utils.monitoring import metrics_collector

logger = logging.getLogger(__name__)

class CustomException(Exception):
    """カスタム例外基底クラス"""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

class ValidationException(CustomException):
    """バリデーション例外"""
    
    def __init__(self, message: str, field_errors: Dict[str, str] = None):
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            status_code=422,
            details={"field_errors": field_errors or {}}
        )

class AuthenticationException(CustomException):
    """認証例外"""
    
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(
            message=message,
            error_code="AUTHENTICATION_ERROR",
            status_code=401
        )

class AuthorizationException(CustomException):
    """認可例外"""
    
    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(
            message=message,
            error_code="AUTHORIZATION_ERROR",
            status_code=403
        )

class ResourceNotFoundException(CustomException):
    """リソース未発見例外"""
    
    def __init__(self, resource_type: str, resource_id: str):
        super().__init__(
            message=f"{resource_type} with ID {resource_id} not found",
            error_code="RESOURCE_NOT_FOUND",
            status_code=404,
            details={"resource_type": resource_type, "resource_id": resource_id}
        )

class BusinessLogicException(CustomException):
    """ビジネスロジック例外"""
    
    def __init__(self, message: str, error_code: str = "BUSINESS_LOGIC_ERROR"):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=400
        )

class ExternalServiceException(CustomException):
    """外部サービス例外"""
    
    def __init__(self, service_name: str, message: str):
        super().__init__(
            message=f"External service error ({service_name}): {message}",
            error_code="EXTERNAL_SERVICE_ERROR",
            status_code=502,
            details={"service_name": service_name}
        )

class ComplianceViolationException(CustomException):
    """コンプライアンス違反例外"""
    
    def __init__(self, violation_type: str, details: Dict[str, Any]):
        super().__init__(
            message=f"Compliance violation: {violation_type}",
            error_code="COMPLIANCE_VIOLATION",
            status_code=403,
            details=details
        )

async def custom_exception_handler(request: Request, exc: CustomException) -> JSONResponse:
    """カスタム例外ハンドラー"""
    
    # エラーカウントの更新
    metrics_collector.increment_error_count()
    
    # エラーIDの生成
    error_id = str(uuid.uuid4())
    
    # ログの出力
    logger.error(
        f"Custom exception occurred: {exc.error_code} - {exc.message} "
        f"(Error ID: {error_id})",
        extra={
            "error_id": error_id,
            "error_code": exc.error_code,
            "status_code": exc.status_code,
            "details": exc.details,
            "request_path": request.url.path,
            "request_method": request.method,
            "client_ip": request.client.host
        }
    )
    
    # コンプライアンス違反の場合は通知を送信
    if isinstance(exc, ComplianceViolationException):
        await send_compliance_alert(
            alert_type="compliance_violation",
            details={
                "error_id": error_id,
                "violation_type": exc.details.get("violation_type"),
                "request_path": request.url.path,
                "client_ip": request.client.host,
                "timestamp": datetime.utcnow().isoformat()
            },
            severity="high"
        )
    
    # レスポンスの生成
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
                "error_id": error_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )

async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """HTTP例外ハンドラー"""
    
    metrics_collector.increment_error_count()
    error_id = str(uuid.uuid4())
    
    logger.warning(
        f"HTTP exception: {exc.status_code} - {exc.detail} (Error ID: {error_id})",
        extra={
            "error_id": error_id,
            "status_code": exc.status_code,
            "request_path": request.url.path,
            "request_method": request.method,
            "client_ip": request.client.host
        }
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "message": exc.detail,
                "error_id": error_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """バリデーション例外ハンドラー"""
    
    metrics_collector.increment_error_count()
    error_id = str(uuid.uuid4())
    
    # バリデーションエラーの詳細を整理
    field_errors = {}
    for error in exc.errors():
        field_name = ".".join(str(loc) for loc in error["loc"])
        field_errors[field_name] = error["msg"]
    
    logger.warning(
        f"Validation error: {field_errors} (Error ID: {error_id})",
        extra={
            "error_id": error_id,
            "field_errors": field_errors,
            "request_path": request.url.path,
            "request_method": request.method,
            "client_ip": request.client.host
        }
    )
    
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Input validation failed",
                "details": {"field_errors": field_errors},
                "error_id": error_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )

async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """一般例外ハンドラー"""
    
    metrics_collector.increment_error_count()
    error_id = str(uuid.uuid4())
    
    # スタックトレースの取得
    tb = traceback.format_exc()
    
    logger.error(
        f"Unhandled exception: {str(exc)} (Error ID: {error_id})",
        extra={
            "error_id": error_id,
            "exception_type": type(exc).__name__,
            "traceback": tb,
            "request_path": request.url.path,
            "request_method": request.method,
            "client_ip": request.client.host
        }
    )
    
    # 重大なエラーの場合は通知を送信
    await send_compliance_alert(
        alert_type="system_error",
        details={
            "error_id": error_id,
            "exception_type": type(exc).__name__,
            "request_path": request.url.path,
            "client_ip": request.client.host,
            "timestamp": datetime.utcnow().isoformat()
        },
        severity="high"
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred",
                "error_id": error_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )

# 例外ハンドラーのマッピング
exception_handlers = {
    CustomException: custom_exception_handler,
    HTTPException: http_exception_handler,
    StarletteHTTPException: http_exception_handler,
    RequestValidationError: validation_exception_handler,
    Exception: general_exception_handler
}