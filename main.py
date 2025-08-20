"""
同意管理システム メインAPI
全コンポーネントの統合・エントリーポイント

統合コンポーネント:
- 同意ゲート管理
- WORM ストレージ
- 監査システム
- ライフサイクル管理
- 自動削除システム
- 日次マニフェスト
- 監査ダッシュボード

Requirements:
- FastAPI
- uvicorn
- google-cloud-*
- sqlalchemy[asyncio]
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, Any

from fastapi import FastAPI, Request, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import uvicorn

# =========================
# 内部モジュール
# =========================
from api.config import settings
from .database import init_database, close_database
from .middleware import (
    ConsentGateMiddleware,
    AuditLoggingMiddleware,
    SecurityHeadersMiddleware,
    RateLimitMiddleware,
)

# APIルーター
from .api.routers.consent_gate import router as consent_gate_router
from .api.routers.audit_system import router as audit_router
from .api.routers.lifecycle import router as lifecycle_router
from .api.routers.deletion import router as deletion_router
from .api.routers.manifest import router as manifest_router
from .api.routers.dashboard import router as dashboard_router

# サービス
from .api.services.worm_service import create_worm_manager
from .api.services.manifest_service import ManifestService
from .api.services.lifecycle_service import ConsentLifecycleManager
from .api.services.auto_deletion_service import AutoDeletionService

# ユーティリティ
from .utils.health_check import HealthChecker
from .utils.monitoring import setup_monitoring
from .utils.exception_handlers import setup_exception_handlers

# =========================
# ロギング設定
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/app/logs/consent_management.log")
        if settings.environment != "development"
        else logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# グローバルサービスインスタンス
app_services: Dict[str, Any] = {}

# ==================================================
# アプリケーションライフサイクル管理
# ==================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリケーションライフサイクル管理"""
    logger.info("Starting Consent Management System...")

    try:
        # 1. DB初期化
        await init_database()
        logger.info("Database initialized")

        # 2. WORMストレージ初期化
        worm_manager = await create_worm_manager(
            project_id=settings.gcp_project_id,
            bucket_name=settings.worm_bucket_name,
            kms_key_ring=settings.kms_key_ring,
            kms_key_name=settings.kms_key_name,
            location=settings.gcp_region,
        )
        app_services["worm_manager"] = worm_manager
        logger.info("WORM storage initialized")

        # 3. マニフェストサービス
        manifest_service = ManifestService(
            worm_manager=worm_manager,
            project_id=settings.gcp_project_id,
            notification_config=settings.notification_config,
        )
        app_services["manifest_service"] = manifest_service
        logger.info("Manifest service initialized")

        # 4. ライフサイクル管理
        lifecycle_manager = ConsentLifecycleManager(
            worm_manager=worm_manager,
            manifest_service=manifest_service,
            project_id=settings.gcp_project_id,
            notification_config=settings.notification_config,
        )
        app_services["lifecycle_manager"] = lifecycle_manager
        logger.info("Lifecycle manager initialized")

        # 5. 自動削除
        deletion_service = AutoDeletionService(
            worm_manager=worm_manager,
            manifest_service=manifest_service,
            project_id=settings.gcp_project_id,
            notification_config=settings.notification_config,
        )
        app_services["deletion_service"] = deletion_service
        logger.info("Auto-deletion service initialized")

        # 6. ヘルスチェッカー
        health_checker = HealthChecker(app_services)
        app_services["health_checker"] = health_checker
        logger.info("Health checker initialized")

        # 7. 監視
        if settings.enable_monitoring:
            await setup_monitoring(settings)
            logger.info("Monitoring system setup completed")

        # 8. 本番スケジューラー
        if settings.environment == "production":
            await setup_production_schedules()
            logger.info("Production schedules setup completed")

        logger.info("Consent Management System startup completed successfully")
        yield

    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        raise

    finally:
        logger.info("Shutting down Consent Management System...")
        try:
            await close_database()
            logger.info("Database connections closed")
            app_services.clear()
            logger.info("Services cleanup completed")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        logger.info("Consent Management System shutdown completed")

# ==================================================
# FastAPIアプリケーション作成
# ==================================================
app = FastAPI(
    title="Consent Management System",
    description="""
    同意管理システム API

    機能:
    - 同意収集・管理
    - LIFF連携
    - WORM ストレージ
    - 監査証跡管理
    - ライフサイクル管理
    - 自動削除機能
    - コンプライアンス報告
    """,
    version="1.0.0",
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
    openapi_url="/openapi.json" if settings.environment != "production" else None,
    lifespan=lifespan,
)

# ==================================================
# ミドルウェア設定
# ==================================================
# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Trusted Hosts（本番）
if settings.environment == "production":
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

# セキュリティヘッダー / レート制限 / 監査ログ / 同意ゲート
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, requests_per_minute=settings.rate_limit_per_minute)
app.add_middleware(AuditLoggingMiddleware)
app.add_middleware(
    ConsentGateMiddleware,
    excluded_paths=[
        "/health",
        "/api/consent/submit",
        "/api/consent/check",
        "/docs",
        "/redoc",
        "/openapi.json",
    ],
)

# 例外ハンドラー
setup_exception_handlers(app)

# ==================================================
# 依存性注入
# ==================================================
def get_worm_manager():
    if "worm_manager" not in app_services:
        raise HTTPException(status_code=503, detail="WORM manager not available")
    return app_services["worm_manager"]

def get_manifest_service():
    if "manifest_service" not in app_services:
        raise HTTPException(status_code=503, detail="Manifest service not available")
    return app_services["manifest_service"]

def get_lifecycle_manager():
    if "lifecycle_manager" not in app_services:
        raise HTTPException(status_code=503, detail="Lifecycle manager not available")
    return app_services["lifecycle_manager"]

def get_deletion_service():
    if "deletion_service" not in app_services:
        raise HTTPException(status_code=503, detail="Deletion service not available")
    return app_services["deletion_service"]

def get_health_checker():
    if "health_checker" not in app_services:
        raise HTTPException(status_code=503, detail="Health checker not available")
    return app_services["health_checker"]

# ==================================================
# ルーター登録
# ==================================================
app.include_router(consent_gate_router, dependencies=[Depends(get_worm_manager)])
app.include_router(audit_router, dependencies=[Depends(get_worm_manager)])
app.include_router(lifecycle_router, dependencies=[Depends(get_lifecycle_manager)])
app.include_router(deletion_router, dependencies=[Depends(get_deletion_service)])
app.include_router(manifest_router, dependencies=[Depends(get_manifest_service)])
app.include_router(dashboard_router, dependencies=[Depends(get_worm_manager)])

# ==================================================
# 静的ファイル配信
# ==================================================
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/frontend", StaticFiles(directory="frontend", html=True), name="frontend")

# ==================================================
# ルート／ヘルス／情報
# ==================================================
@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>同意管理システム</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; padding: 2rem; background: #f5f7fa; }
            .container { max-width: 800px; margin: 0 auto; background: white; padding: 2rem; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h1 { color: #2d3748; margin-bottom: 1rem; }
            .link-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-top: 2rem; }
            .link-card { padding: 1rem; border: 1px solid #e2e8f0; border-radius: 8px; text-decoration: none; color: #4a5568; transition: all 0.2s; }
            .link-card:hover { border-color: #4299e1; color: #2b6cb0; transform: translateY(-2px); }
            .status { padding: 0.5rem 1rem; border-radius: 6px; font-size: 0.9rem; font-weight: 600; }
            .status-ok { background: #d4edda; color: #155724; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔒 同意管理システム</h1>
            <div class="status status-ok">システム稼働中</div>

            <div class="link-grid">
                <a href="/frontend/audit_dashboard.html" class="link-card">
                    <h3>📊 監査ダッシュボード</h3>
                    <p>リアルタイム監査・統計</p>
                </a>
                <a href="/api/docs" class="link-card">
                    <h3>📖 API ドキュメント</h3>
                    <p>開発者向け API 仕様</p>
                </a>
                <a href="/health" class="link-card">
                    <h3>🏥 ヘルスチェック</h3>
                    <p>システム状態確認</p>
                </a>
                <a href="/api/audit/compliance/report?start_date=2025-08-01&end_date=2025-08-19" class="link-card">
                    <h3>📋 コンプライアンス</h3>
                    <p>法的要件準拠状況</p>
                </a>
            </div>

            <div style="margin-top: 2rem; padding-top: 2rem; border-top: 1px solid #e2e8f0; font-size: 0.9rem; color: #718096;">
                <p><strong>同意管理システム v1.0.0</strong></p>
                <p>法的要件対応: 電気通信事業法、個人情報保護法、GDPR</p>
                <p>データ保全: 5年WORM、暗号化、監査証跡</p>
            </div>
        </div>
    </body>
    </html>
    """

@app.get("/health")
async def health_check(health_checker: HealthChecker = Depends(get_health_checker)):
    """システムヘルスチェック"""
    try:
        health_status = await health_checker.comprehensive_health_check()
        status_code = 200 if health_status["overall_status"] in ("healthy", "degraded") else 503
        return JSONResponse(status_code=status_code, content=health_status)
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "overall_status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

@app.get("/api/system/info")
async def system_info():
    return {
        "system_name": "Consent Management System",
        "version": "1.0.0",
        "environment": settings.environment,
        "features": [
            "LIFF同意ゲート",
            "WORM ストレージ",
            "監査証跡管理",
            "ライフサイクル管理",
            "自動削除機能",
            "コンプライアンス報告",
        ],
        "compliance": ["電気通信事業法", "個人情報保護法", "GDPR Article 17", "ISO 27001"],
        "data_retention": "5年WORM保全",
        "timestamp": datetime.utcnow().isoformat(),
    }

# ==================================================
# 管理用エンドポイント
# ==================================================
@app.post("/api/admin/emergency-stop")
async def emergency_stop(
    reason: str,
    deletion_service: AutoDeletionService = Depends(get_deletion_service),
):
    """緊急停止"""
    try:
        stop_token = await deletion_service.activate_emergency_stop(reason)
        return {
            "message": "Emergency stop activated",
            "reason": reason,
            "stop_token": stop_token,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Emergency stop failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/force-manifest-generation")
async def force_manifest_generation(
    background_tasks: BackgroundTasks,
    manifest_service: ManifestService = Depends(get_manifest_service),
):
    """強制マニフェスト生成"""
    try:
        background_tasks.add_task(
            manifest_service.generate_daily_manifest,
            target_date=datetime.utcnow().date(),
            force_regenerate=True,
        )
        return {"message": "Manifest generation started", "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f"Force manifest generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/force-lifecycle-processing")
async def force_lifecycle_processing(
    background_tasks: BackgroundTasks,
    lifecycle_manager: ConsentLifecycleManager = Depends(get_lifecycle_manager),
):
    """強制ライフサイクル処理"""
    try:
        background_tasks.add_task(
            lifecycle_manager.process_daily_lifecycle,
            target_date=datetime.utcnow().date(),
        )
        return {"message": "Lifecycle processing started", "timestamp": datetime.utcnow().isoformat()}
    except Exception as e:
        logger.error(f"Force lifecycle processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================================================
# デバッグ（開発環境のみ）
# ==================================================
if settings.environment == "development":

    @app.get("/debug/services")
    async def debug_services():
        return {
            "available_services": list(app_services.keys()),
            "service_details": {name: str(type(svc)) for name, svc in app_services.items()},
        }

    @app.get("/debug/config")
    async def debug_config():
        return {
            "environment": settings.environment,
            "database_url": (settings.database_url[:50] + "...") if settings.database_url else None,
            "gcp_project": settings.gcp_project_id,
            "worm_bucket": settings.worm_bucket_name,
            "features": {
                "monitoring": settings.enable_monitoring,
                "rate_limiting": bool(settings.rate_limit_per_minute),
                "cors": bool(settings.allowed_origins),
            },
        }

# ==================================================
# 本番スケジュール
# ==================================================
async def setup_production_schedules():
    """本番環境スケジュール設定"""
    try:
        if "manifest_service" in app_services:
            await app_services["manifest_service"].setup_daily_schedule("02:00")
        if "lifecycle_manager" in app_services:
            await app_services["lifecycle_manager"].setup_lifecycle_schedules()
        if "deletion_service" in app_services:
            await app_services["deletion_service"].setup_deletion_schedules()
        logger.info("Production schedules setup completed")
    except Exception as e:
        logger.error(f"Failed to setup production schedules: {e}")
        # 非致命で続行

# ==================================================
# 実行
# ==================================================
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=True if settings.environment == "development" else False,
        log_level="info",
        access_log=True,
    )
