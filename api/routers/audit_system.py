"""
監査システムAPI
同意管理の監査ログ、統計レポート、コンプライアンス確認機能を提供

Requirements:
- FastAPI
- SQLAlchemy
- PostgreSQL
- Google Cloud Storage (WORM)
- 法的要件対応（5年保全、監査証跡）
"""

from __future__ import annotations

import asyncio
import json
import logging
import hashlib
from datetime import datetime, timedelta, date
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import text, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# --- 相対/絶対インポートのフォールバック（Pylance対策） ---
try:
    from ..database import get_db_session  # type: ignore
except Exception:  # pragma: no cover
    from api.database import get_db_session  # type: ignore

try:
    from ..models import ConsentRecord, ConsentWithdrawal, AuditLog, DailyConsentStats  # type: ignore
except Exception:  # pragma: no cover
    from api.models import ConsentRecord, ConsentWithdrawal, AuditLog, DailyConsentStats  # type: ignore

try:
    from ..auth import verify_token, get_current_user, require_admin  # type: ignore
except Exception:  # pragma: no cover
    from api.auth import verify_token, get_current_user, require_admin  # type: ignore

try:
    from ..utils.gcs_client import upload_audit_manifest, verify_worm_storage  # type: ignore
except Exception:  # pragma: no cover
    from api.utils.gcs_client import upload_audit_manifest, verify_worm_storage  # type: ignore

try:
    from ..utils.encryption import encrypt_sensitive_data, decrypt_sensitive_data  # type: ignore
except Exception:  # pragma: no cover
    from api.utils.encryption import encrypt_sensitive_data, decrypt_sensitive_data  # type: ignore

# ロギング設定
logger = logging.getLogger(__name__)

# FastAPIルーター
router = APIRouter(prefix="/api/audit", tags=["audit"])
security = HTTPBearer()

# ==================================================
# Pydanticモデル定義
# ==================================================

class AuditLogCreate(BaseModel):
    """監査ログ作成モデル"""
    table_name: str = Field(..., description="操作対象テーブル名")
    record_id: str = Field(..., description="操作対象レコードID")
    action_type: str = Field(..., description="アクション種別")
    action_description: Optional[str] = None
    user_id: Optional[str] = None
    actor_type: str = Field(default="user", description="実行者種別")
    actor_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: Optional[str] = None
    api_endpoint: Optional[str] = None
    old_values: Optional[Dict[str, Any]] = None
    new_values: Optional[Dict[str, Any]] = None
    success: bool = True
    error_message: Optional[str] = None

class AuditLogResponse(BaseModel):
    """監査ログレスポンス"""
    from uuid import UUID
    log_id: UUID
    table_name: str
    record_id: str
    action_type: str
    action_description: Optional[str]
    user_id: Optional[str]
    actor_type: str
    actor_id: Optional[str]
    ip_address: Optional[str]
    success: bool
    error_message: Optional[str]
    created_at: datetime

class ConsentStatsResponse(BaseModel):
    """同意統計レスポンス"""
    stat_date: date
    total_consents: int
    new_consents: int
    withdrawn_consents: int
    expired_consents: int
    policy_version_stats: Dict[str, int]
    generated_at: datetime

class ComplianceReportResponse(BaseModel):
    """コンプライアンスレポート"""
    report_id: str
    generated_at: datetime
    period_start: date
    period_end: date
    total_consents: int
    active_consents: int
    expired_consents: int
    withdrawn_consents: int
    policy_versions: Dict[str, int]
    worm_verification: bool
    audit_trail_complete: bool
    legal_compliance_status: str
    recommendations: List[str]

class ManifestResponse(BaseModel):
    """日次マニフェストレスポンス"""
    manifest_id: str
    date: date
    consent_count: int
    audit_log_count: int
    worm_hash: str
    storage_verified: bool
    uploaded_at: datetime

# ==================================================
# 依存性注入・認証
# ==================================================

async def get_audit_context(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db_session)
) -> Dict[str, Any]:
    """監査コンテキストの取得"""
    try:
        user_info = await verify_token(credentials.credentials)
        return {
            "user_id": user_info.get("user_id"),
            "actor_type": "user",
            "actor_id": user_info.get("user_id"),
            "session_id": user_info.get("session_id"),
            "permissions": user_info.get("permissions", [])
        }
    except Exception as e:
        logger.warning(f"Authentication failed: {e}")
        return {
            "user_id": None,
            "actor_type": "anonymous",
            "actor_id": None,
            "session_id": None,
            "permissions": []
        }

async def require_audit_permission(context: Dict = Depends(get_audit_context)):
    """監査権限の確認"""
    if "audit_read" not in context.get("permissions", []):
        raise HTTPException(
            status_code=403,
            detail="Audit access permission required"
        )

# ==================================================
# 監査ログ関連エンドポイント
# ==================================================

@router.post("/logs", response_model=Dict[str, str])
async def create_audit_log(
    log_data: AuditLogCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
    context: Dict = Depends(get_audit_context)
):
    """
    監査ログの作成
    """
    try:
        from uuid import uuid4

        # 監査ログエントリの作成
        audit_log = AuditLog(
            log_id=uuid4(),
            table_name=log_data.table_name,
            record_id=log_data.record_id,
            action_type=log_data.action_type,
            action_description=log_data.action_description,
            user_id=log_data.user_id or context.get("user_id"),
            actor_type=log_data.actor_type,
            actor_id=log_data.actor_id or context.get("actor_id"),
            ip_address=log_data.ip_address,
            user_agent=log_data.user_agent,
            session_id=log_data.session_id or context.get("session_id"),
            api_endpoint=log_data.api_endpoint,
            old_values=log_data.old_values,
            new_values=log_data.new_values,
            success=log_data.success,
            error_message=log_data.error_message,
            created_at=datetime.utcnow()
        )

        db.add(audit_log)
        await db.commit()

        # バックグラウンドでWORMストレージにアップロード
        background_tasks.add_task(
            upload_audit_to_worm,
            str(audit_log.log_id),
            audit_log.__dict__ if hasattr(audit_log, "__dict__") else {}
        )

        logger.info(f"Audit log created: {audit_log.log_id}")
        return {"log_id": str(audit_log.log_id), "status": "created"}

    except Exception as e:
        logger.error(f"Failed to create audit log: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create audit log")

@router.get("/logs", response_model=List[AuditLogResponse])
async def get_audit_logs(
    table_name: Optional[str] = Query(None, description="テーブル名でフィルタ"),
    record_id: Optional[str] = Query(None, description="レコードIDでフィルタ"),
    action_type: Optional[str] = Query(None, description="アクション種別でフィルタ"),
    user_id: Optional[str] = Query(None, description="ユーザーIDでフィルタ"),
    start_date: Optional[datetime] = Query(None, description="開始日時"),
    end_date: Optional[datetime] = Query(None, description="終了日時"),
    limit: int = Query(100, le=1000, description="取得件数制限"),
    offset: int = Query(0, description="オフセット"),
    db: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_audit_permission)
):
    """
    監査ログの取得・検索
    """
    try:
        # クエリ条件の構築
        conditions = []
        if table_name:
            conditions.append(AuditLog.table_name == table_name)
        if record_id:
            conditions.append(AuditLog.record_id == record_id)
        if action_type:
            conditions.append(AuditLog.action_type == action_type)
        if user_id:
            conditions.append(AuditLog.user_id == user_id)
        if start_date:
            conditions.append(AuditLog.created_at >= start_date)
        if end_date:
            conditions.append(AuditLog.created_at <= end_date)

        # 注意: text() + AND 条件の埋め込みは実運用では ORM/SQLBuilder 推奨
        query = text("""
            SELECT 
                log_id, table_name, record_id, action_type, action_description,
                user_id, actor_type, actor_id, ip_address, success, error_message, created_at
            FROM audit_logs 
            ORDER BY created_at DESC 
            LIMIT :limit OFFSET :offset
        """)

        result = await db.execute(query, {"limit": limit, "offset": offset})

        logs: List[AuditLogResponse] = []
        for row in result.fetchall():
            logs.append(AuditLogResponse(
                log_id=row.log_id,
                table_name=row.table_name,
                record_id=row.record_id,
                action_type=row.action_type,
                action_description=row.action_description,
                user_id=row.user_id,
                actor_type=row.actor_type,
                actor_id=row.actor_id,
                ip_address=row.ip_address,
                success=row.success,
                error_message=row.error_message,
                created_at=row.created_at
            ))

        return logs

    except Exception as e:
        logger.error(f"Failed to retrieve audit logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve audit logs")

# ==================================================
# 統計・レポート関連エンドポイント
# ==================================================

@router.get("/stats/daily", response_model=List[ConsentStatsResponse])
async def get_daily_stats(
    start_date: Optional[date] = Query(None, description="開始日"),
    end_date: Optional[date] = Query(None, description="終了日"),
    db: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_audit_permission)
):
    """
    日次同意統計の取得
    """
    try:
        # デフォルトは過去30日
        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()

        query = text("""
            SELECT 
                stat_date, total_consents, new_consents, 
                withdrawn_consents, expired_consents, 
                policy_version_stats, generated_at
            FROM daily_consent_stats 
            WHERE stat_date BETWEEN :start_date AND :end_date
            ORDER BY stat_date DESC
        """)

        result = await db.execute(query, {
            "start_date": start_date,
            "end_date": end_date
        })

        stats: List[ConsentStatsResponse] = []
        for row in result.fetchall():
            stats.append(ConsentStatsResponse(
                stat_date=row.stat_date,
                total_consents=row.total_consents,
                new_consents=row.new_consents,
                withdrawn_consents=row.withdrawn_consents,
                expired_consents=row.expired_consents,
                policy_version_stats=row.policy_version_stats or {},
                generated_at=row.generated_at
            ))

        return stats

    except Exception as e:
        logger.error(f"Failed to retrieve daily stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve daily stats")

@router.post("/stats/generate")
async def generate_daily_stats(
    background_tasks: BackgroundTasks,  # ← 非デフォルトを先頭へ（順序修正）
    target_date: Optional[date] = Query(default_factory=date.today),
    db: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_admin)
):
    """
    日次統計の手動生成
    """
    try:
        # バックグラウンドタスクで統計生成
        background_tasks.add_task(
            generate_stats_task,
            target_date
        )
        return {"message": f"Daily stats generation started for {target_date}"}

    except Exception as e:
        logger.error(f"Failed to start stats generation: {e}")
        raise HTTPException(status_code=500, detail="Failed to start stats generation")

@router.get("/compliance/report", response_model=ComplianceReportResponse)
async def generate_compliance_report(
    background_tasks: BackgroundTasks,  # ← 非デフォルトを先頭へ（順序修正）
    start_date: date = Query(..., description="レポート開始日"),
    end_date: date = Query(..., description="レポート終了日"),
    db: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_audit_permission)
):
    """
    コンプライアンスレポートの生成
    """
    try:
        from uuid import uuid4

        report_id = f"compliance_{start_date}_{end_date}_{uuid4().hex[:8]}"

        # 期間内の統計データ収集（簡略化）
        stats_query = text("""
            SELECT 
                COUNT(*) as total_consents,
                COUNT(*) FILTER (WHERE withdrawn = false AND expires_at > NOW()) as active_consents,
                COUNT(*) FILTER (WHERE expires_at <= NOW()) as expired_consents,
                COUNT(*) FILTER (WHERE withdrawn = true) as withdrawn_consents,
                jsonb_object_agg(policy_version, version_count) as policy_versions
            FROM (
                SELECT 
                    policy_version,
                    COUNT(*) as version_count,
                    withdrawn,
                    expires_at
                FROM consent_records 
                WHERE created_at BETWEEN :start_date AND :end_date
                GROUP BY policy_version, withdrawn, expires_at
            ) subquery
        """)

        result = await db.execute(stats_query, {
            "start_date": start_date,
            "end_date": end_date
        })
        stats = result.fetchone()

        # WORM検証
        worm_verified = await verify_worm_storage_integrity(start_date, end_date)

        # 監査証跡の完全性確認
        audit_complete = await verify_audit_trail_completeness(start_date, end_date, db)

        # コンプライアンス評価
        compliance_status = evaluate_compliance_status(
            stats, worm_verified, audit_complete
        )

        # 推奨事項の生成
        recommendations = generate_compliance_recommendations(
            stats, worm_verified, audit_complete
        )

        # レポート作成
        report = ComplianceReportResponse(
            report_id=report_id,
            generated_at=datetime.utcnow(),
            period_start=start_date,
            period_end=end_date,
            total_consents=stats.total_consents or 0,
            active_consents=stats.active_consents or 0,
            expired_consents=stats.expired_consents or 0,
            withdrawn_consents=stats.withdrawn_consents or 0,
            policy_versions=stats.policy_versions or {},
            worm_verification=worm_verified,
            audit_trail_complete=audit_complete,
            legal_compliance_status=compliance_status,
            recommendations=recommendations
        )

        # バックグラウンドでレポート保存
        background_tasks.add_task(
            save_compliance_report,
            report_id,
            report.dict()
        )

        return report

    except Exception as e:
        logger.error(f"Failed to generate compliance report: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate compliance report")

# ==================================================
# 日次マニフェスト関連
# ==================================================

@router.post("/manifest/generate", response_model=ManifestResponse)
async def generate_daily_manifest(
    background_tasks: BackgroundTasks,  # ← 非デフォルトを先頭へ（順序修正）
    target_date: Optional[date] = Query(default_factory=date.today),
    db: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_admin)
):
    """
    日次マニフェストの生成
    """
    try:
        manifest_id = f"manifest_{target_date}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        # 対象日のデータ収集
        consent_query = text("""
            SELECT COUNT(*) FROM consent_records 
            WHERE DATE(created_at) = :target_date
        """)
        consent_result = await db.execute(consent_query, {"target_date": target_date})
        consent_count = consent_result.scalar() or 0

        audit_query = text("""
            SELECT COUNT(*) FROM audit_logs 
            WHERE DATE(created_at) = :target_date
        """)
        audit_result = await db.execute(audit_query, {"target_date": target_date})
        audit_count = audit_result.scalar() or 0

        # データ整合性ハッシュの生成
        hash_data = f"{target_date}_{consent_count}_{audit_count}_{datetime.utcnow().isoformat()}"
        worm_hash = hashlib.sha256(hash_data.encode()).hexdigest()

        # マニフェスト作成（保存用 dict）
        manifest = {
            "manifest_id": manifest_id,
            "date": str(target_date),
            "consent_count": consent_count,
            "audit_log_count": audit_count,
            "worm_hash": worm_hash,
            "generated_at": datetime.utcnow().isoformat()
        }

        # バックグラウンドでWORMストレージにアップロード
        background_tasks.add_task(
            upload_audit_manifest,
            manifest_id,
            manifest
        )

        # ストレージ検証
        storage_verified = await verify_worm_storage(manifest_id)

        return ManifestResponse(
            manifest_id=manifest_id,
            date=target_date,
            consent_count=consent_count,
            audit_log_count=audit_count,
            worm_hash=worm_hash,
            storage_verified=storage_verified,
            uploaded_at=datetime.utcnow()
        )

    except Exception as e:
        logger.error(f"Failed to generate daily manifest: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate daily manifest")

@router.get("/manifest/verify/{manifest_id}")
async def verify_manifest_integrity(
    manifest_id: str,
    _: None = Depends(require_audit_permission)
):
    """
    マニフェストの整合性検証
    """
    try:
        # WORMストレージからマニフェストを取得・検証
        verification_result = await verify_worm_storage(manifest_id)
        return {
            "manifest_id": manifest_id,
            "verified": verification_result,
            "verified_at": datetime.utcnow(),
            "status": "valid" if verification_result else "invalid"
        }

    except Exception as e:
        logger.error(f"Failed to verify manifest: {e}")
        raise HTTPException(status_code=500, detail="Failed to verify manifest")

# ==================================================
# バックグラウンドタスク
# ==================================================

async def upload_audit_to_worm(log_id: str, log_data: Dict[str, Any]):
    """監査ログをWORMストレージにアップロード"""
    try:
        # 暗号化
        encrypted_data = encrypt_sensitive_data(log_data)
        # WORMストレージにアップロード
        await upload_audit_manifest(f"audit_log_{log_id}", encrypted_data)
        logger.info(f"Audit log uploaded to WORM storage: {log_id}")
    except Exception as e:
        logger.error(f"Failed to upload audit log to WORM: {e}")

async def generate_stats_task(target_date: date):
    """統計生成バックグラウンドタスク"""
    try:
        # データベース接続
        async with get_db_session() as db:
            query = text("SELECT generate_daily_stats(:target_date)")
            await db.execute(query, {"target_date": target_date})
            await db.commit()
        logger.info(f"Daily stats generated for {target_date}")
    except Exception as e:
        logger.error(f"Failed to generate daily stats: {e}")

async def save_compliance_report(report_id: str, report_data: Dict[str, Any]):
    """コンプライアンスレポートの保存"""
    try:
        # 暗号化
        encrypted_report = encrypt_sensitive_data(report_data)
        # WORMストレージに保存
        await upload_audit_manifest(f"compliance_report_{report_id}", encrypted_report)
        logger.info(f"Compliance report saved: {report_id}")
    except Exception as e:
        logger.error(f"Failed to save compliance report: {e}")

# ==================================================
# ヘルパー関数
# ==================================================

async def verify_worm_storage_integrity(start_date: date, end_date: date) -> bool:
    """WORM ストレージの整合性検証"""
    try:
        # 期間タグなどでまとめて検証する想定（実装は GCS クライアントに依存）
        return await verify_worm_storage(f"period_{start_date}_{end_date}")
    except Exception as e:
        logger.error(f"WORM verification failed: {e}")
        return False

async def verify_audit_trail_completeness(
    start_date: date,
    end_date: date,
    db: AsyncSession
) -> bool:
    """監査証跡の完全性確認"""
    try:
        query = text("""
            SELECT 
                (SELECT COUNT(*) FROM consent_records 
                 WHERE DATE(created_at) BETWEEN :start_date AND :end_date) as consent_actions,
                (SELECT COUNT(*) FROM audit_logs 
                 WHERE table_name = 'consent_records' 
                 AND DATE(created_at) BETWEEN :start_date AND :end_date) as audit_logs
        """)
        result = await db.execute(query, {"start_date": start_date, "end_date": end_date})
        data = result.fetchone()
        return data.consent_actions <= data.audit_logs
    except Exception as e:
        logger.error(f"Audit trail verification failed: {e}")
        return False

def evaluate_compliance_status(stats, worm_verified: bool, audit_complete: bool) -> str:
    """コンプライアンス状況の評価"""
    if worm_verified and audit_complete and stats.total_consents > 0:
        return "COMPLIANT"
    elif worm_verified or audit_complete:
        return "PARTIALLY_COMPLIANT"
    else:
        return "NON_COMPLIANT"

def generate_compliance_recommendations(
    stats,
    worm_verified: bool,
    audit_complete: bool
) -> List[str]:
    """推奨事項の生成"""
    recommendations: List[str] = []
    if not worm_verified:
        recommendations.append("WORM ストレージの設定を確認し、データ整合性を回復してください")
    if not audit_complete:
        recommendations.append("監査証跡に欠損があります。ログ生成プロセスを確認してください")
    if getattr(stats, "expired_consents", 0) > getattr(stats, "total_consents", 0) * 0.1:
        recommendations.append("期限切れ同意が多すぎます。再同意プロセスの改善を検討してください")
    if not recommendations:
        recommendations.append("現在のコンプライアンス状況は良好です")
    return recommendations

# ==================================================
# ヘルスチェック
# ==================================================

@router.get("/health")
async def audit_system_health(
    db: AsyncSession = Depends(get_db_session)
):
    """監査システムのヘルスチェック"""
    try:
        await db.execute(text("SELECT 1"))
        latest_log = await db.execute(
            text("SELECT created_at FROM audit_logs ORDER BY created_at DESC LIMIT 1")
        )
        latest_log_time = latest_log.scalar()
        worm_status = await verify_worm_storage("health_check")
        return {
            "status": "healthy",
            "database": "connected",
            "latest_audit_log": latest_log_time,
            "worm_storage": "available" if worm_status else "unavailable",
            "timestamp": datetime.utcnow()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")

# ==================================================
# エクスポート設定
# ==================================================

__all__ = [
    "router",
    "AuditLogCreate",
    "AuditLogResponse",
    "ConsentStatsResponse",
    "ComplianceReportResponse",
    "ManifestResponse",
]
