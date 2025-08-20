"""
自動削除システム API ルーター
法的要件に基づくデータの自動削除・保全期間管理

エンドポイント:
- POST /api/deletion/scan-candidates - 削除対象スキャン
- POST /api/deletion/process-scheduled - スケジュール済み削除処理
- GET /api/deletion/status/{deletion_id} - 削除ステータス確認
- POST /api/deletion/approve - 削除承認
- POST /api/deletion/emergency-stop - 緊急停止
"""

import logging
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Path
from pydantic import BaseModel, Field

from api.services.auto_deletion_service import AutoDeletionService, DeletionStatus, DeletionType
from database import get_db_session

# ロギング設定
logger = logging.getLogger(__name__)

# ルーター作成
router = APIRouter(prefix="/api/deletion", tags=["deletion"])

# ==================================================
# データモデル
# ==================================================

class DeletionScanRequest(BaseModel):
    """削除対象スキャンリクエスト"""
    target_date: Optional[date] = Field(None, description="スキャン対象日（デフォルト：今日）")
    scan_types: List[str] = Field(
        default=["legal_retention_expiry", "user_request", "system_cleanup"],
        description="スキャン対象タイプ"
    )

class DeletionProcessRequest(BaseModel):
    """削除処理リクエスト"""
    target_date: Optional[date] = Field(None, description="処理対象日（デフォルト：今日）")
    max_concurrent: Optional[int] = Field(5, description="最大並列処理数")

class DeletionApprovalRequest(BaseModel):
    """削除承認リクエスト"""
    deletion_id: str = Field(..., description="削除ID")
    approver_id: str = Field(..., description="承認者ID")
    approval_comment: Optional[str] = Field(None, description="承認コメント")

class EmergencyStopRequest(BaseModel):
    """緊急停止リクエスト"""
    reason: str = Field(..., description="緊急停止理由")
    stop_all_operations: bool = Field(True, description="全削除操作を停止")

class DeletionStatusResponse(BaseModel):
    """削除ステータスレスポンス"""
    deletion_id: str
    target_type: str
    target_count: int
    deletion_type: str
    status: str
    scheduled_at: Optional[datetime]
    executed_at: Optional[datetime]
    approval_level: str
    legal_basis: str
    error_details: Optional[Dict[str, Any]] = None

class DeletionCandidatesResponse(BaseModel):
    """削除対象レスポンス"""
    scan_id: str
    target_date: date
    total_candidates: int
    legal_retention_expiry: int
    user_requests: int
    system_cleanup: int
    gdpr_deletions: int
    candidates: List[Dict[str, Any]]
    scanned_at: datetime

class DeletionProcessResponse(BaseModel):
    """削除処理レスポンス"""
    process_id: str
    target_date: date
    processed_count: int
    completed_count: int
    failed_count: int
    errors: List[Dict[str, Any]]
    processing_duration: Optional[float]
    completed_at: Optional[datetime]

# ==================================================
# エンドポイント
# ==================================================

@router.post("/scan-candidates", response_model=DeletionCandidatesResponse)
async def scan_deletion_candidates(
    request: DeletionScanRequest,
    deletion_service: AutoDeletionService = Depends()
):
    """削除対象スキャン"""
    try:
        target_date = request.target_date or date.today()
        
        # 削除対象をスキャン
        candidates = await deletion_service.scan_for_deletion_candidates(target_date)
        
        # タイプ別集計
        type_counts = {
            "legal_retention_expiry": 0,
            "user_requests": 0,
            "system_cleanup": 0,
            "gdpr_deletions": 0
        }
        
        candidate_details = []
        for candidate in candidates:
            deletion_type = candidate.deletion_type.value
            if deletion_type == DeletionType.LEGAL_RETENTION_EXPIRY.value:
                type_counts["legal_retention_expiry"] += 1
            elif deletion_type == DeletionType.USER_REQUEST.value:
                type_counts["user_requests"] += 1
            elif deletion_type == DeletionType.SYSTEM_CLEANUP.value:
                type_counts["system_cleanup"] += 1
            elif deletion_type == DeletionType.GDPR_RIGHT_TO_ERASURE.value:
                type_counts["gdpr_deletions"] += 1
            
            candidate_details.append({
                "deletion_id": candidate.deletion_id,
                "target_type": candidate.target_type,
                "target_count": len(candidate.target_ids),
                "deletion_type": deletion_type,
                "scheduled_at": candidate.scheduled_at.isoformat(),
                "legal_basis": candidate.legal_basis,
                "approval_level": candidate.approval_level.value,
                "estimated_size_bytes": candidate.estimated_size_bytes
            })
        
        scan_id = f"scan_{target_date.strftime('%Y%m%d')}_{datetime.utcnow().strftime('%H%M%S')}"
        
        return DeletionCandidatesResponse(
            scan_id=scan_id,
            target_date=target_date,
            total_candidates=len(candidates),
            legal_retention_expiry=type_counts["legal_retention_expiry"],
            user_requests=type_counts["user_requests"],
            system_cleanup=type_counts["system_cleanup"],
            gdpr_deletions=type_counts["gdpr_deletions"],
            candidates=candidate_details,
            scanned_at=datetime.utcnow()
        )
        
    except Exception as e:
        logger.error(f"Failed to scan deletion candidates: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/process-scheduled", response_model=DeletionProcessResponse)
async def process_scheduled_deletions(
    request: DeletionProcessRequest,
    background_tasks: BackgroundTasks,
    deletion_service: AutoDeletionService = Depends()
):
    """スケジュール済み削除処理"""
    try:
        target_date = request.target_date or date.today()
        
        # 削除処理を実行
        process_result = await deletion_service.process_scheduled_deletions(target_date)
        
        process_id = f"process_{target_date.strftime('%Y%m%d')}_{datetime.utcnow().strftime('%H%M%S')}"
        
        return DeletionProcessResponse(
            process_id=process_id,
            target_date=target_date,
            processed_count=process_result.get('processed_count', 0),
            completed_count=process_result.get('completed_count', 0),
            failed_count=process_result.get('failed_count', 0),
            errors=process_result.get('errors', []),
            processing_duration=None,  # 計算する場合は実装
            completed_at=datetime.fromisoformat(process_result['completed_at']) if process_result.get('completed_at') else None
        )
        
    except Exception as e:
        logger.error(f"Failed to process scheduled deletions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status/{deletion_id}", response_model=DeletionStatusResponse)
async def get_deletion_status(
    deletion_id: str = Path(..., description="削除ID"),
    deletion_service: AutoDeletionService = Depends()
):
    """削除ステータス確認"""
    try:
        # 削除ステータスを取得
        status = await deletion_service.get_deletion_status(deletion_id)
        
        if not status:
            raise HTTPException(status_code=404, detail="Deletion record not found")
        
        return DeletionStatusResponse(
            deletion_id=status.get('deletion_id', ''),
            target_type=status.get('target_type', ''),
            target_count=len(status.get('target_ids', [])),
            deletion_type=status.get('deletion_type', ''),
            status=status.get('status', ''),
            scheduled_at=datetime.fromisoformat(status['scheduled_at']) if status.get('scheduled_at') else None,
            executed_at=datetime.fromisoformat(status['executed_at']) if status.get('executed_at') else None,
            approval_level=status.get('approval_level', ''),
            legal_basis=status.get('legal_basis', ''),
            error_details=status.get('error_details')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get deletion status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/approve")
async def approve_deletion(
    request: DeletionApprovalRequest,
    deletion_service: AutoDeletionService = Depends()
):
    """削除承認"""
    try:
        # 削除承認を処理
        approval_result = await deletion_service.request_deletion_approval(
            deletion_id=request.deletion_id,
            approver_id=request.approver_id,
            approval_comment=request.approval_comment
        )
        
        if not approval_result.get('success'):
            raise HTTPException(
                status_code=400, 
                detail=approval_result.get('error', 'Approval failed')
            )
        
        return {
            "message": "Deletion approved successfully",
            "deletion_id": request.deletion_id,
            "approval_id": approval_result.get('approval_id'),
            "deletion_status": approval_result.get('deletion_status'),
            "approved_at": datetime.utcnow().isoformat(),
            "approver_id": request.approver_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to approve deletion: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/emergency-stop")
async def activate_emergency_stop(
    request: EmergencyStopRequest,
    deletion_service: AutoDeletionService = Depends()
):
    """緊急停止"""
    try:
        # 緊急停止を有効化
        stop_token = await deletion_service.activate_emergency_stop(request.reason)
        
        if not stop_token:
            raise HTTPException(status_code=500, detail="Failed to activate emergency stop")
        
        return {
            "message": "Emergency stop activated successfully",
            "reason": request.reason,
            "stop_token": stop_token,
            "activated_at": datetime.utcnow().isoformat(),
            "stop_all_operations": request.stop_all_operations
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to activate emergency stop: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/statistics")
async def get_deletion_statistics(
    start_date: date = Query(..., description="統計期間開始日"),
    end_date: date = Query(..., description="統計期間終了日")
):
    """削除統計取得"""
    try:
        async with get_db_session() as db:
            from sqlalchemy import text
            
            # 削除統計を取得
            stats_query = text("""
                SELECT 
                    COUNT(*) as total_deletions,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed_deletions,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed_deletions,
                    COUNT(*) FILTER (WHERE status = 'pending') as pending_deletions,
                    COUNT(*) FILTER (WHERE deletion_type = 'legal_retention_expiry') as legal_expiry_deletions,
                    COUNT(*) FILTER (WHERE deletion_type = 'user_request') as user_request_deletions,
                    COUNT(*) FILTER (WHERE deletion_type = 'system_cleanup') as system_cleanup_deletions,
                    SUM(estimated_size_bytes) as total_size_deleted
                FROM deletion_records 
                WHERE DATE(created_at) BETWEEN :start_date AND :end_date
            """)
            
            try:
                stats_result = await db.execute(stats_query, {
                    "start_date": start_date,
                    "end_date": end_date
                })
                stats = stats_result.fetchone()
                
                # 日別統計
                daily_query = text("""
                    SELECT 
                        DATE(created_at) as date,
                        COUNT(*) as total_deletions,
                        COUNT(*) FILTER (WHERE status = 'completed') as completed,
                        COUNT(*) FILTER (WHERE status = 'failed') as failed
                    FROM deletion_records 
                    WHERE DATE(created_at) BETWEEN :start_date AND :end_date
                    GROUP BY DATE(created_at)
                    ORDER BY date
                """)
                
                daily_result = await db.execute(daily_query, {
                    "start_date": start_date,
                    "end_date": end_date
                })
                daily_stats = daily_result.fetchall()
                
                return {
                    "period_start": start_date.isoformat(),
                    "period_end": end_date.isoformat(),
                    "summary": {
                        "total_deletions": stats.total_deletions or 0,
                        "completed_deletions": stats.completed_deletions or 0,
                        "failed_deletions": stats.failed_deletions or 0,
                        "pending_deletions": stats.pending_deletions or 0,
                        "success_rate": (stats.completed_deletions / stats.total_deletions * 100) if stats.total_deletions > 0 else 0,
                        "total_size_deleted_bytes": stats.total_size_deleted or 0
                    },
                    "by_type": {
                        "legal_expiry": stats.legal_expiry_deletions or 0,
                        "user_request": stats.user_request_deletions or 0,
                        "system_cleanup": stats.system_cleanup_deletions or 0
                    },
                    "daily_stats": [
                        {
                            "date": stat.date.isoformat(),
                            "total_deletions": stat.total_deletions,
                            "completed": stat.completed,
                            "failed": stat.failed,
                            "success_rate": (stat.completed / stat.total_deletions * 100) if stat.total_deletions > 0 else 0
                        }
                        for stat in daily_stats
                    ]
                }
                
            except Exception:
                # deletion_recordsテーブルが存在しない場合
                return {
                    "period_start": start_date.isoformat(),
                    "period_end": end_date.isoformat(),
                    "summary": {
                        "total_deletions": 0,
                        "completed_deletions": 0,
                        "failed_deletions": 0,
                        "pending_deletions": 0,
                        "success_rate": 0,
                        "total_size_deleted_bytes": 0
                    },
                    "by_type": {
                        "legal_expiry": 0,
                        "user_request": 0,
                        "system_cleanup": 0
                    },
                    "daily_stats": []
                }
            
    except Exception as e:
        logger.error(f"Failed to get deletion statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/pending-approvals")
async def get_pending_approvals():
    """承認待ち削除一覧"""
    try:
        async with get_db_session() as db:
            from sqlalchemy import text
            
            # 承認待ち削除を取得
            pending_query = text("""
                SELECT 
                    deletion_id, target_type, deletion_type,
                    scheduled_at, approval_level, legal_basis,
                    created_at, created_by
                FROM deletion_records 
                WHERE status IN ('approval_required', 'pending')
                AND approval_deadline > NOW()
                ORDER BY scheduled_at
                LIMIT 100
            """)
            
            try:
                pending_result = await db.execute(pending_query)
                pending_deletions = pending_result.fetchall()
                
                return {
                    "total_pending": len(pending_deletions),
                    "pending_deletions": [
                        {
                            "deletion_id": deletion.deletion_id,
                            "target_type": deletion.target_type,
                            "deletion_type": deletion.deletion_type,
                            "scheduled_at": deletion.scheduled_at.isoformat() if deletion.scheduled_at else None,
                            "approval_level": deletion.approval_level,
                            "legal_basis": deletion.legal_basis,
                            "created_at": deletion.created_at.isoformat(),
                            "created_by": deletion.created_by,
                            "urgency": "high" if deletion.scheduled_at and deletion.scheduled_at < datetime.utcnow() + timedelta(days=1) else "normal"
                        }
                        for deletion in pending_deletions
                    ],
                    "retrieved_at": datetime.utcnow().isoformat()
                }
                
            except Exception:
                # テーブルが存在しない場合
                return {
                    "total_pending": 0,
                    "pending_deletions": [],
                    "retrieved_at": datetime.utcnow().isoformat()
                }
            
    except Exception as e:
        logger.error(f"Failed to get pending approvals: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def deletion_system_health():
    """削除システムヘルスチェック"""
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "checks": {}
        }
        
        async with get_db_session() as db:
            from sqlalchemy import text
            
            # 緊急停止状態確認
            try:
                emergency_query = text("""
                    SELECT COUNT(*) 
                    FROM system_emergency_stops 
                    WHERE active = TRUE
                """)
                emergency_result = await db.execute(emergency_query)
                emergency_stops = emergency_result.scalar() or 0
                
                health_status["checks"]["emergency_stop_active"] = emergency_stops > 0
            except Exception:
                health_status["checks"]["emergency_stop_active"] = False
            
            # 処理遅延確認
            try:
                delayed_query = text("""
                    SELECT COUNT(*) 
                    FROM deletion_records 
                    WHERE status = 'scheduled'
                    AND scheduled_at < NOW() - INTERVAL '24 hours'
                """)
                delayed_result = await db.execute(delayed_query)
                delayed_deletions = delayed_result.scalar() or 0
                
                health_status["checks"]["processing_delays"] = delayed_deletions < 5
                health_status["checks"]["delayed_deletion_count"] = delayed_deletions
            except Exception:
                health_status["checks"]["processing_delays"] = True
                health_status["checks"]["delayed_deletion_count"] = 0
            
            # 最近の処理確認
            try:
                recent_query = text("""
                    SELECT COUNT(*) 
                    FROM deletion_records 
                    WHERE created_at >= NOW() - INTERVAL '24 hours'
                """)
                recent_result = await db.execute(recent_query)
                recent_deletions = recent_result.scalar() or 0
                
                health_status["checks"]["recent_activity"] = recent_deletions >= 0  # 0でも正常
            except Exception:
                health_status["checks"]["recent_activity"] = True
            
            # 全体的な健康状態判定
            if (health_status["checks"]["emergency_stop_active"] or
                not health_status["checks"]["processing_delays"]):
                health_status["status"] = "degraded"
            
            if health_status["checks"]["delayed_deletion_count"] > 50:
                health_status["status"] = "unhealthy"
        
        return health_status
        
    except Exception as e:
        logger.error(f"Deletion system health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

# ==================================================
# エクスポート
# ==================================================

__all__ = ["router"]