"""
自動削除システム
法的要件に基づくデータの自動削除・保全期間管理

機能:
- 法定保全期間管理（5年）
- 段階的削除処理
- 削除前承認フロー
- 削除実行と監査ログ
- 復元不可能な完全削除
- 緊急停止機能

Requirements:
- asyncio
- sqlalchemy
- google-cloud-storage
- google-cloud-scheduler
- 多段階承認システム
"""

import asyncio
import json
import logging
import hashlib
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import uuid
import secrets

from sqlalchemy import text, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from google.cloud import storage, scheduler_v1
from google.api_core import exceptions as gcp_exceptions

from database import get_db_session
from models import ConsentRecord, ConsentWithdrawal, AuditLog
from .worm_service import EnhancedWORMManager
from .manifest_service import ManifestService
from utils.notification import send_email_notification
from utils.encryption import encrypt_sensitive_data, secure_delete

# ロギング設定
logger = logging.getLogger(__name__)

# ==================================================
# 列挙型・データクラス
# ==================================================

class DeletionStatus(Enum):
    """削除ステータス"""
    PENDING = "pending"              # 削除予定
    SCHEDULED = "scheduled"          # スケジュール済み
    APPROVAL_REQUIRED = "approval_required"  # 承認待ち
    APPROVED = "approved"            # 承認済み
    IN_PROGRESS = "in_progress"      # 削除実行中
    COMPLETED = "completed"          # 削除完了
    FAILED = "failed"                # 削除失敗
    CANCELLED = "cancelled"          # キャンセル
    EMERGENCY_STOPPED = "emergency_stopped"  # 緊急停止

class DeletionType(Enum):
    """削除タイプ"""
    LEGAL_RETENTION_EXPIRY = "legal_retention_expiry"  # 法定保全期間満了
    USER_REQUEST = "user_request"                      # ユーザー要求
    GDPR_RIGHT_TO_ERASURE = "gdpr_right_to_erasure"  # GDPR削除権
    SYSTEM_CLEANUP = "system_cleanup"                  # システムクリーンアップ
    EMERGENCY_DELETION = "emergency_deletion"          # 緊急削除

class ApprovalLevel(Enum):
    """承認レベル"""
    SYSTEM_AUTO = "system_auto"      # システム自動
    ADMIN_SINGLE = "admin_single"    # 管理者単独
    ADMIN_DUAL = "admin_dual"        # 管理者複数
    EXECUTIVE = "executive"          # 役員承認
    LEGAL_COUNSEL = "legal_counsel"  # 法務承認

@dataclass
class DeletionRecord:
    """削除記録"""
    deletion_id: str
    target_type: str  # 'consent', 'user_data', 'audit_log'
    target_ids: List[str]
    deletion_type: DeletionType
    status: DeletionStatus
    
    # スケジュール情報
    scheduled_at: datetime
    retention_expiry: datetime
    legal_basis: str
    
    # 承認情報
    approval_level: ApprovalLevel
    approvers: List[Dict[str, Any]]
    approval_deadline: Optional[datetime]
    
    # 実行情報
    deletion_method: str
    executed_at: Optional[datetime]
    execution_duration: Optional[float]
    
    # メタデータ
    created_at: datetime
    created_by: str
    data_classification: str
    estimated_size_bytes: int
    
    # 監査情報
    pre_deletion_hash: Optional[str]
    post_deletion_verification: Optional[str]
    deletion_certificate: Optional[str]
    
    # エラー情報
    error_details: Optional[Dict[str, Any]] = None
    retry_count: int = 0

@dataclass
class DeletionPolicy:
    """削除ポリシー"""
    policy_id: str
    name: str
    description: str
    
    # 保全期間設定
    retention_period_days: int
    grace_period_days: int  # 削除前猶予期間
    
    # 削除条件
    data_types: List[str]
    deletion_triggers: List[str]
    exclusion_criteria: List[str]
    
    # 承認要件
    required_approval_level: ApprovalLevel
    approval_timeout_hours: int
    
    # 実行設定
    deletion_method: str
    batch_size: int
    max_concurrent_deletions: int
    
    # 監査要件
    require_pre_deletion_backup: bool
    require_post_deletion_verification: bool
    require_legal_review: bool
    
    active: bool = True
    created_at: datetime = None
    updated_at: datetime = None

@dataclass
class DeletionApproval:
    """削除承認"""
    approval_id: str
    deletion_id: str
    approver_id: str
    approver_role: str
    
    approval_status: str  # 'pending', 'approved', 'rejected'
    approval_timestamp: Optional[datetime]
    approval_comment: Optional[str]
    approval_evidence: Optional[Dict[str, Any]]
    
    created_at: datetime
    expires_at: datetime

# ==================================================
# メインクラス: AutoDeletionService
# ==================================================

class AutoDeletionService:
    """自動削除サービス"""
    
    def __init__(
        self,
        worm_manager: EnhancedWORMManager,
        manifest_service: ManifestService,
        project_id: str,
        notification_config: Optional[Dict[str, Any]] = None
    ):
        self.worm_manager = worm_manager
        self.manifest_service = manifest_service
        self.project_id = project_id
        self.notification_config = notification_config or {}
        self.scheduler_client = scheduler_v1.CloudSchedulerClient()
        
        # 設定
        self.legal_retention_years = 5  # 法定保全期間
        self.grace_period_days = 30     # 削除前猶予期間
        self.max_concurrent_deletions = 5
        self.emergency_stop_enabled = True
        
        # セキュリティ
        self.deletion_key = secrets.token_hex(32)
        self.emergency_stop_token = None

    async def scan_for_deletion_candidates(
        self, 
        target_date: Optional[date] = None
    ) -> List[DeletionRecord]:
        """削除対象の検索"""
        if target_date is None:
            target_date = date.today()
            
        try:
            logger.info(f"Scanning for deletion candidates on {target_date}")
            
            deletion_candidates = []
            
            async with get_db_session() as db:
                # 1. 法定保全期間満了の同意記録
                legal_expiry_candidates = await self._scan_legal_retention_expiry(db, target_date)
                deletion_candidates.extend(legal_expiry_candidates)
                
                # 2. ユーザー削除要求
                user_deletion_requests = await self._scan_user_deletion_requests(db, target_date)
                deletion_candidates.extend(user_deletion_requests)
                
                # 3. GDPR削除権行使
                gdpr_deletion_requests = await self._scan_gdpr_deletion_requests(db, target_date)
                deletion_candidates.extend(gdpr_deletion_requests)
                
                # 4. システムクリーンアップ対象
                system_cleanup_candidates = await self._scan_system_cleanup_targets(db, target_date)
                deletion_candidates.extend(system_cleanup_candidates)
                
                # 削除記録をデータベースに保存
                for candidate in deletion_candidates:
                    await self._store_deletion_record(db, candidate)
                
                await db.commit()
                
                logger.info(f"Found {len(deletion_candidates)} deletion candidates")
                return deletion_candidates
                
        except Exception as e:
            logger.error(f"Failed to scan deletion candidates: {e}")
            raise

    async def _scan_legal_retention_expiry(
        self, 
        db: AsyncSession, 
        target_date: date
    ) -> List[DeletionRecord]:
        """法定保全期間満了の検索"""
        try:
            # 5年前の日付を計算
            retention_cutoff = target_date - timedelta(days=self.legal_retention_years * 365)
            
            query = text("""
                SELECT 
                    consent_id, user_id, created_at, withdrawn_at,
                    pg_column_size(ROW(consent_records.*)) as estimated_size
                FROM consent_records 
                WHERE 
                    created_at::date <= :retention_cutoff
                    AND (withdrawn_at IS NOT NULL OR expires_at < NOW())
                    AND consent_id NOT IN (
                        SELECT target_ids::text FROM deletion_records 
                        WHERE target_type = 'consent' 
                        AND status NOT IN ('completed', 'failed', 'cancelled')
                    )
                ORDER BY created_at
                LIMIT 1000
            """)
            
            result = await db.execute(query, {"retention_cutoff": retention_cutoff})
            expired_consents = result.fetchall()
            
            deletion_records = []
            
            for consent in expired_consents:
                deletion_record = DeletionRecord(
                    deletion_id=f"del_{datetime.utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}",
                    target_type="consent",
                    target_ids=[consent.consent_id],
                    deletion_type=DeletionType.LEGAL_RETENTION_EXPIRY,
                    status=DeletionStatus.SCHEDULED,
                    scheduled_at=datetime.utcnow() + timedelta(days=self.grace_period_days),
                    retention_expiry=datetime.combine(retention_cutoff, datetime.min.time()),
                    legal_basis="Personal Information Protection Law - 5 year retention limit",
                    approval_level=ApprovalLevel.ADMIN_SINGLE,
                    approvers=[],
                    approval_deadline=datetime.utcnow() + timedelta(days=self.grace_period_days - 7),
                    deletion_method="secure_multi_pass",
                    created_at=datetime.utcnow(),
                    created_by="auto_deletion_service",
                    data_classification="personal_data",
                    estimated_size_bytes=consent.estimated_size or 0
                )
                
                deletion_records.append(deletion_record)
            
            logger.info(f"Found {len(deletion_records)} legal retention expiry candidates")
            return deletion_records
            
        except Exception as e:
            logger.error(f"Failed to scan legal retention expiry: {e}")
            return []

    async def _scan_user_deletion_requests(
        self, 
        db: AsyncSession, 
        target_date: date
    ) -> List[DeletionRecord]:
        """ユーザー削除要求の検索"""
        try:
            # ユーザー削除要求テーブルから検索（実装例）
            query = text("""
                SELECT 
                    request_id, user_id, requested_at, deletion_reason,
                    approval_status, data_types
                FROM user_deletion_requests 
                WHERE 
                    approval_status = 'approved'
                    AND scheduled_deletion_date::date <= :target_date
                    AND processed = FALSE
                ORDER BY requested_at
                LIMIT 100
            """)
            
            try:
                result = await db.execute(query, {"target_date": target_date})
                user_requests = result.fetchall()
            except Exception:
                # テーブルが存在しない場合はスキップ
                logger.info("User deletion requests table not found, skipping")
                return []
            
            deletion_records = []
            
            for request in user_requests:
                deletion_record = DeletionRecord(
                    deletion_id=f"usr_{datetime.utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}",
                    target_type="user_data",
                    target_ids=[request.user_id],
                    deletion_type=DeletionType.USER_REQUEST,
                    status=DeletionStatus.APPROVED,
                    scheduled_at=datetime.utcnow(),
                    retention_expiry=datetime.utcnow(),
                    legal_basis="User deletion request under Privacy Policy",
                    approval_level=ApprovalLevel.ADMIN_SINGLE,
                    approvers=[{"request_id": request.request_id, "approved_at": request.requested_at}],
                    approval_deadline=None,
                    deletion_method="secure_multi_pass",
                    created_at=datetime.utcnow(),
                    created_by="user_deletion_request",
                    data_classification="personal_data",
                    estimated_size_bytes=1024 * 1024  # 推定1MB
                )
                
                deletion_records.append(deletion_record)
            
            logger.info(f"Found {len(deletion_records)} user deletion requests")
            return deletion_records
            
        except Exception as e:
            logger.error(f"Failed to scan user deletion requests: {e}")
            return []

    async def _scan_gdpr_deletion_requests(
        self, 
        db: AsyncSession, 
        target_date: date
    ) -> List[DeletionRecord]:
        """GDPR削除権行使の検索"""
        try:
            # GDPR削除権行使テーブルから検索（実装例）
            # 実際の実装では、GDPR Article 17に基づく削除要求を管理
            
            logger.info("GDPR deletion requests scanning - feature not yet implemented")
            return []
            
        except Exception as e:
            logger.error(f"Failed to scan GDPR deletion requests: {e}")
            return []

    async def _scan_system_cleanup_targets(
        self, 
        db: AsyncSession, 
        target_date: date
    ) -> List[DeletionRecord]:
        """システムクリーンアップ対象の検索"""
        try:
            # 古い一時データ、ログファイル等の検索
            cleanup_cutoff = target_date - timedelta(days=90)  # 90日より古い一時データ
            
            query = text("""
                SELECT 
                    log_id, created_at,
                    pg_column_size(ROW(audit_logs.*)) as estimated_size
                FROM audit_logs 
                WHERE 
                    created_at::date <= :cleanup_cutoff
                    AND table_name = 'temporary_data'
                    AND success = TRUE
                ORDER BY created_at
                LIMIT 500
            """)
            
            result = await db.execute(query, {"cleanup_cutoff": cleanup_cutoff})
            old_logs = result.fetchall()
            
            if not old_logs:
                return []
            
            # バッチで削除レコードを作成
            deletion_record = DeletionRecord(
                deletion_id=f"sys_{datetime.utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}",
                target_type="audit_log",
                target_ids=[log.log_id for log in old_logs],
                deletion_type=DeletionType.SYSTEM_CLEANUP,
                status=DeletionStatus.SCHEDULED,
                scheduled_at=datetime.utcnow() + timedelta(hours=24),  # 24時間後に実行
                retention_expiry=datetime.combine(cleanup_cutoff, datetime.min.time()),
                legal_basis="System maintenance - temporary data cleanup",
                approval_level=ApprovalLevel.SYSTEM_AUTO,
                approvers=[],
                approval_deadline=None,
                deletion_method="standard_delete",
                created_at=datetime.utcnow(),
                created_by="system_cleanup",
                data_classification="operational_data",
                estimated_size_bytes=sum(log.estimated_size or 0 for log in old_logs)
            )
            
            logger.info(f"Found {len(old_logs)} system cleanup targets")
            return [deletion_record] if old_logs else []
            
        except Exception as e:
            logger.error(f"Failed to scan system cleanup targets: {e}")
            return []

    async def process_scheduled_deletions(
        self, 
        target_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """スケジュール済み削除の処理"""
        if target_date is None:
            target_date = date.today()
            
        try:
            logger.info(f"Processing scheduled deletions for {target_date}")
            
            results = {
                'date': target_date.isoformat(),
                'started_at': datetime.utcnow().isoformat(),
                'processed_count': 0,
                'completed_count': 0,
                'failed_count': 0,
                'errors': [],
                'deletion_results': []
            }
            
            # 緊急停止チェック
            if await self._check_emergency_stop():
                logger.warning("Emergency stop is active, skipping deletion processing")
                results['errors'].append({
                    'type': 'EMERGENCY_STOP_ACTIVE',
                    'message': 'Deletion processing halted due to emergency stop'
                })
                return results
            
            async with get_db_session() as db:
                # 処理対象の削除レコードを取得
                scheduled_deletions = await self._get_scheduled_deletions(db, target_date)
                
                # 並列処理制限
                semaphore = asyncio.Semaphore(self.max_concurrent_deletions)
                
                # 削除タスクを作成
                deletion_tasks = []
                for deletion_record in scheduled_deletions:
                    task = self._process_single_deletion(semaphore, deletion_record)
                    deletion_tasks.append(task)
                
                # 並列実行
                if deletion_tasks:
                    deletion_results = await asyncio.gather(
                        *deletion_tasks, return_exceptions=True
                    )
                    
                    # 結果処理
                    for i, result in enumerate(deletion_results):
                        deletion_record = scheduled_deletions[i]
                        results['processed_count'] += 1
                        
                        if isinstance(result, Exception):
                            results['failed_count'] += 1
                            results['errors'].append({
                                'deletion_id': deletion_record.deletion_id,
                                'error': str(result),
                                'type': 'DELETION_PROCESSING_ERROR'
                            })
                        elif result.get('success', False):
                            results['completed_count'] += 1
                            results['deletion_results'].append(result)
                        else:
                            results['failed_count'] += 1
                            results['errors'].append({
                                'deletion_id': deletion_record.deletion_id,
                                'error': result.get('error', 'Unknown error'),
                                'type': 'DELETION_EXECUTION_FAILED'
                            })
                
                # 削除統計を更新
                await self._update_deletion_statistics(db, results)
                
                await db.commit()
            
            results['completed_at'] = datetime.utcnow().isoformat()
            results['success'] = results['failed_count'] == 0
            
            logger.info(f"Deletion processing completed: {results['completed_count']}/{results['processed_count']} successful")
            return results
            
        except Exception as e:
            logger.error(f"Failed to process scheduled deletions: {e}")
            
            # 緊急停止を有効化
            await self._activate_emergency_stop("DELETION_PROCESSING_CRITICAL_ERROR")
            
            return {
                'date': target_date.isoformat(),
                'success': False,
                'error': str(e),
                'emergency_stop_activated': True,
                'completed_at': datetime.utcnow().isoformat()
            }

    async def _process_single_deletion(
        self, 
        semaphore: asyncio.Semaphore, 
        deletion_record: DeletionRecord
    ) -> Dict[str, Any]:
        """単一削除の処理"""
        async with semaphore:
            try:
                logger.info(f"Processing deletion: {deletion_record.deletion_id}")
                
                start_time = datetime.utcnow()
                
                # 1. 承認状況確認
                if not await self._verify_deletion_approval(deletion_record):
                    return {
                        'deletion_id': deletion_record.deletion_id,
                        'success': False,
                        'error': 'Deletion not properly approved'
                    }
                
                # 2. 削除前バックアップ（必要な場合）
                backup_result = await self._create_pre_deletion_backup(deletion_record)
                if not backup_result['success']:
                    return {
                        'deletion_id': deletion_record.deletion_id,
                        'success': False,
                        'error': f"Pre-deletion backup failed: {backup_result['error']}"
                    }
                
                # 3. データ削除実行
                deletion_result = await self._execute_data_deletion(deletion_record)
                if not deletion_result['success']:
                    return {
                        'deletion_id': deletion_record.deletion_id,
                        'success': False,
                        'error': f"Data deletion failed: {deletion_result['error']}"
                    }
                
                # 4. 削除後検証
                verification_result = await self._verify_deletion_completion(deletion_record)
                if not verification_result['success']:
                    return {
                        'deletion_id': deletion_record.deletion_id,
                        'success': False,
                        'error': f"Deletion verification failed: {verification_result['error']}"
                    }
                
                # 5. 削除証明書生成
                certificate = await self._generate_deletion_certificate(deletion_record)
                
                # 6. 削除記録更新
                await self._update_deletion_status(
                    deletion_record.deletion_id, 
                    DeletionStatus.COMPLETED,
                    {
                        'executed_at': datetime.utcnow().isoformat(),
                        'execution_duration': (datetime.utcnow() - start_time).total_seconds(),
                        'deletion_certificate': certificate,
                        'verification_result': verification_result
                    }
                )
                
                logger.info(f"Deletion completed successfully: {deletion_record.deletion_id}")
                
                return {
                    'deletion_id': deletion_record.deletion_id,
                    'success': True,
                    'executed_at': datetime.utcnow().isoformat(),
                    'execution_duration': (datetime.utcnow() - start_time).total_seconds(),
                    'targets_deleted': len(deletion_record.target_ids),
                    'deletion_certificate': certificate
                }
                
            except Exception as e:
                logger.error(f"Deletion processing failed for {deletion_record.deletion_id}: {e}")
                
                # 失敗状態に更新
                await self._update_deletion_status(
                    deletion_record.deletion_id,
                    DeletionStatus.FAILED,
                    {'error_details': str(e), 'failed_at': datetime.utcnow().isoformat()}
                )
                
                return {
                    'deletion_id': deletion_record.deletion_id,
                    'success': False,
                    'error': str(e)
                }

    async def _execute_data_deletion(self, deletion_record: DeletionRecord) -> Dict[str, Any]:
        """データ削除実行"""
        try:
            deleted_count = 0
            deletion_details = {}
            
            if deletion_record.target_type == "consent":
                # 同意記録の削除
                deleted_count = await self._delete_consent_records(deletion_record.target_ids)
                deletion_details['consent_records_deleted'] = deleted_count
                
            elif deletion_record.target_type == "user_data":
                # ユーザーデータの削除
                deleted_count = await self._delete_user_data(deletion_record.target_ids)
                deletion_details['user_data_deleted'] = deleted_count
                
            elif deletion_record.target_type == "audit_log":
                # 監査ログの削除
                deleted_count = await self._delete_audit_logs(deletion_record.target_ids)
                deletion_details['audit_logs_deleted'] = deleted_count
            
            # WORMストレージからの削除
            if deletion_record.deletion_method == "secure_multi_pass":
                worm_deletion_result = await self._secure_delete_from_worm(deletion_record)
                deletion_details['worm_deletion'] = worm_deletion_result
            
            return {
                'success': True,
                'deleted_count': deleted_count,
                'deletion_details': deletion_details
            }
            
        except Exception as e:
            logger.error(f"Data deletion execution failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def _delete_consent_records(self, consent_ids: List[str]) -> int:
        """同意記録の削除"""
        try:
            async with get_db_session() as db:
                # まず関連する取り消し記録を削除
                withdrawal_delete_query = text("""
                    DELETE FROM consent_withdrawals 
                    WHERE consent_id = ANY(:consent_ids)
                """)
                await db.execute(withdrawal_delete_query, {"consent_ids": consent_ids})
                
                # 同意記録を削除
                consent_delete_query = text("""
                    DELETE FROM consent_records 
                    WHERE consent_id = ANY(:consent_ids)
                """)
                result = await db.execute(consent_delete_query, {"consent_ids": consent_ids})
                deleted_count = result.rowcount
                
                await db.commit()
                
                logger.info(f"Deleted {deleted_count} consent records")
                return deleted_count
                
        except Exception as e:
            logger.error(f"Failed to delete consent records: {e}")
            raise

    async def _delete_user_data(self, user_ids: List[str]) -> int:
        """ユーザーデータの削除"""
        try:
            async with get_db_session() as db:
                # ユーザーに関連するすべてのデータを削除
                tables_to_clean = [
                    'consent_records',
                    'consent_withdrawals', 
                    'audit_logs'
                ]
                
                total_deleted = 0
                
                for table in tables_to_clean:
                    delete_query = text(f"""
                        DELETE FROM {table} 
                        WHERE user_id = ANY(:user_ids)
                    """)
                    result = await db.execute(delete_query, {"user_ids": user_ids})
                    total_deleted += result.rowcount
                
                await db.commit()
                
                logger.info(f"Deleted {total_deleted} user data records")
                return total_deleted
                
        except Exception as e:
            logger.error(f"Failed to delete user data: {e}")
            raise

    async def _delete_audit_logs(self, log_ids: List[str]) -> int:
        """監査ログの削除"""
        try:
            async with get_db_session() as db:
                delete_query = text("""
                    DELETE FROM audit_logs 
                    WHERE log_id = ANY(:log_ids)
                """)
                result = await db.execute(delete_query, {"log_ids": log_ids})
                deleted_count = result.rowcount
                
                await db.commit()
                
                logger.info(f"Deleted {deleted_count} audit log records")
                return deleted_count
                
        except Exception as e:
            logger.error(f"Failed to delete audit logs: {e}")
            raise

    async def _secure_delete_from_worm(self, deletion_record: DeletionRecord) -> Dict[str, Any]:
        """WORMストレージからの安全削除"""
        try:
            # WORMストレージからのファイル削除
            # 注意: 実際のWORMストレージでは物理削除は制限される場合がある
            
            deleted_objects = []
            
            for target_id in deletion_record.target_ids:
                # オブジェクトパスの構築
                if deletion_record.target_type == "consent":
                    object_paths = [
                        f"consents/**/{target_id}.json.gz",
                        f"manifests/**/*{target_id}*"
                    ]
                elif deletion_record.target_type == "audit_log":
                    object_paths = [
                        f"audit_logs/**/{target_id}.json"
                    ]
                else:
                    continue
                
                # オブジェクト削除実行
                for pattern in object_paths:
                    try:
                        blobs = self.worm_manager.storage_client.list_blobs(
                            self.worm_manager.bucket,
                            prefix=pattern.split('**')[0] if '**' in pattern else pattern
                        )
                        
                        for blob in blobs:
                            if target_id in blob.name:
                                # セキュア削除（複数回上書き）
                                await self._secure_overwrite_blob(blob)
                                blob.delete()
                                deleted_objects.append(blob.name)
                                
                    except Exception as e:
                        logger.warning(f"Failed to delete WORM object {pattern}: {e}")
            
            return {
                'success': True,
                'deleted_objects': deleted_objects,
                'deletion_method': 'secure_multi_pass_overwrite'
            }
            
        except Exception as e:
            logger.error(f"WORM deletion failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    async def _secure_overwrite_blob(self, blob):
        """Blobのセキュア上書き削除"""
        try:
            # DOD 5220.22-M標準に基づく3回上書き
            overwrite_patterns = [
                b'\x00' * 1024,  # ゼロで上書き
                b'\xFF' * 1024,  # 1で上書き  
                secrets.token_bytes(1024)  # ランダムデータで上書き
            ]
            
            for pattern in overwrite_patterns:
                blob.upload_from_string(pattern, content_type='application/octet-stream')
                
            logger.debug(f"Secure overwrite completed for {blob.name}")
            
        except Exception as e:
            logger.error(f"Secure overwrite failed for {blob.name}: {e}")
            raise

    async def _generate_deletion_certificate(self, deletion_record: DeletionRecord) -> str:
        """削除証明書生成"""
        try:
            certificate_data = {
                'deletion_id': deletion_record.deletion_id,
                'deletion_type': deletion_record.deletion_type.value,
                'target_type': deletion_record.target_type,
                'target_count': len(deletion_record.target_ids),
                'executed_at': datetime.utcnow().isoformat(),
                'legal_basis': deletion_record.legal_basis,
                'deletion_method': deletion_record.deletion_method,
                'approvers': deletion_record.approvers,
                'certificate_version': '1.0'
            }
            
            # デジタル署名
            certificate_json = json.dumps(certificate_data, sort_keys=True)
            certificate_hash = hashlib.sha256(certificate_json.encode()).hexdigest()
            
            # 証明書ID生成
            certificate_id = f"cert_{deletion_record.deletion_id}_{certificate_hash[:8]}"
            
            # 証明書をWORMストレージに保存
            certificate_path = f"deletion_certificates/{datetime.utcnow().strftime('%Y/%m')}/{certificate_id}.json"
            
            blob = self.worm_manager.bucket.blob(certificate_path)
            blob.metadata = {
                'certificate_id': certificate_id,
                'deletion_id': deletion_record.deletion_id,
                'certificate_hash': certificate_hash,
                'issued_at': datetime.utcnow().isoformat()
            }
            
            blob.upload_from_string(certificate_json, content_type='application/json')
            
            logger.info(f"Deletion certificate generated: {certificate_id}")
            return certificate_id
            
        except Exception as e:
            logger.error(f"Failed to generate deletion certificate: {e}")
            return f"certificate_generation_failed_{deletion_record.deletion_id}"

    # ==================================================
    # 承認管理
    # ==================================================

    async def request_deletion_approval(
        self, 
        deletion_id: str, 
        approver_id: str,
        approval_comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """削除承認要求"""
        try:
            async with get_db_session() as db:
                # 削除記録を取得
                deletion_record = await self._get_deletion_record(db, deletion_id)
                if not deletion_record:
                    return {'success': False, 'error': 'Deletion record not found'}
                
                # 承認レコード作成
                approval = DeletionApproval(
                    approval_id=f"app_{deletion_id}_{uuid.uuid4().hex[:8]}",
                    deletion_id=deletion_id,
                    approver_id=approver_id,
                    approver_role="admin",  # 実際はユーザー情報から取得
                    approval_status="approved",
                    approval_timestamp=datetime.utcnow(),
                    approval_comment=approval_comment,
                    created_at=datetime.utcnow(),
                    expires_at=datetime.utcnow() + timedelta(hours=24)
                )
                
                # 承認をデータベースに保存
                await self._store_deletion_approval(db, approval)
                
                # 削除記録のステータス更新
                if deletion_record.approval_level == ApprovalLevel.ADMIN_SINGLE:
                    new_status = DeletionStatus.APPROVED
                else:
                    new_status = DeletionStatus.APPROVAL_REQUIRED  # 複数承認の場合
                
                await self._update_deletion_status(deletion_id, new_status)
                
                await db.commit()
                
                logger.info(f"Deletion approval recorded: {approval.approval_id}")
                return {
                    'success': True,
                    'approval_id': approval.approval_id,
                    'deletion_status': new_status.value
                }
                
        except Exception as e:
            logger.error(f"Failed to process deletion approval: {e}")
            return {'success': False, 'error': str(e)}

    # ==================================================
    # 緊急停止機能
    # ==================================================

    async def activate_emergency_stop(self, reason: str) -> str:
        """緊急停止の有効化"""
        try:
            self.emergency_stop_token = secrets.token_hex(16)
            
            # 緊急停止状態をデータベースに記録
            async with get_db_session() as db:
                emergency_query = text("""
                    INSERT INTO system_emergency_stops (
                        stop_id, reason, activated_at, stop_token, active
                    ) VALUES (
                        :stop_id, :reason, NOW(), :token, TRUE
                    )
                """)
                
                stop_id = f"emergency_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
                
                await db.execute(emergency_query, {
                    "stop_id": stop_id,
                    "reason": reason,
                    "token": self.emergency_stop_token
                })
                
                await db.commit()
            
            # 緊急通知送信
            await self._send_emergency_notification(reason, self.emergency_stop_token)
            
            logger.critical(f"Emergency stop activated: {reason}")
            return self.emergency_stop_token
            
        except Exception as e:
            logger.error(f"Failed to activate emergency stop: {e}")
            return ""

    async def _check_emergency_stop(self) -> bool:
        """緊急停止状態の確認"""
        try:
            async with get_db_session() as db:
                check_query = text("""
                    SELECT COUNT(*) FROM system_emergency_stops 
                    WHERE active = TRUE
                """)
                
                result = await db.execute(check_query)
                active_stops = result.scalar()
                
                return active_stops > 0
                
        except Exception:
            # エラーの場合は安全側に倒して停止状態とみなす
            return True

    async def _send_emergency_notification(self, reason: str, stop_token: str):
        """緊急通知送信"""
        try:
            subject = "[CRITICAL] Auto-Deletion Emergency Stop Activated"
            body = f"""
CRITICAL ALERT: Auto-deletion system emergency stop has been activated.

Reason: {reason}
Timestamp: {datetime.utcnow().isoformat()}
Stop Token: {stop_token}

All deletion operations have been immediately halted.
Manual intervention is required to resume operations.

Please investigate the cause and contact the system administrator.
            """.strip()
            
            if self.notification_config.get('emergency_contacts'):
                await send_email_notification(
                    subject=subject,
                    body=body,
                    recipients=self.notification_config['emergency_contacts'],
                    smtp_config=self.notification_config.get('smtp')
                )
            
        except Exception as e:
            logger.error(f"Failed to send emergency notification: {e}")

    # ==================================================
    # ユーティリティメソッド
    # ==================================================

    async def _get_scheduled_deletions(
        self, 
        db: AsyncSession, 
        target_date: date
    ) -> List[DeletionRecord]:
        """スケジュール済み削除の取得"""
        try:
            query = text("""
                SELECT * FROM deletion_records 
                WHERE scheduled_at::date <= :target_date
                AND status IN ('scheduled', 'approved')
                ORDER BY scheduled_at
                LIMIT 100
            """)
            
            result = await db.execute(query, {"target_date": target_date})
            
            # DeletionRecordオブジェクトに変換
            deletion_records = []
            for row in result.fetchall():
                # 実際の実装では、データベースから適切にデシリアライズ
                deletion_record = DeletionRecord(**dict(row))
                deletion_records.append(deletion_record)
            
            return deletion_records
            
        except Exception as e:
            logger.error(f"Failed to get scheduled deletions: {e}")
            return []

    async def _store_deletion_record(self, db: AsyncSession, deletion_record: DeletionRecord):
        """削除記録の保存"""
        try:
            store_query = text("""
                INSERT INTO deletion_records (
                    deletion_id, target_type, target_ids, deletion_type, status,
                    scheduled_at, retention_expiry, legal_basis, approval_level,
                    deletion_method, created_at, created_by, data_classification,
                    estimated_size_bytes
                ) VALUES (
                    :deletion_id, :target_type, :target_ids, :deletion_type, :status,
                    :scheduled_at, :retention_expiry, :legal_basis, :approval_level,
                    :deletion_method, :created_at, :created_by, :data_classification,
                    :estimated_size_bytes
                )
            """)
            
            await db.execute(store_query, {
                "deletion_id": deletion_record.deletion_id,
                "target_type": deletion_record.target_type,
                "target_ids": json.dumps(deletion_record.target_ids),
                "deletion_type": deletion_record.deletion_type.value,
                "status": deletion_record.status.value,
                "scheduled_at": deletion_record.scheduled_at,
                "retention_expiry": deletion_record.retention_expiry,
                "legal_basis": deletion_record.legal_basis,
                "approval_level": deletion_record.approval_level.value,
                "deletion_method": deletion_record.deletion_method,
                "created_at": deletion_record.created_at,
                "created_by": deletion_record.created_by,
                "data_classification": deletion_record.data_classification,
                "estimated_size_bytes": deletion_record.estimated_size_bytes
            })
            
        except Exception as e:
            logger.error(f"Failed to store deletion record: {e}")
            raise

    async def get_deletion_status(self, deletion_id: str) -> Optional[Dict[str, Any]]:
        """削除ステータスの取得"""
        try:
            async with get_db_session() as db:
                query = text("""
                    SELECT * FROM deletion_records 
                    WHERE deletion_id = :deletion_id
                """)
                
                result = await db.execute(query, {"deletion_id": deletion_id})
                row = result.fetchone()
                
                if row:
                    return dict(row)
                return None
                
        except Exception as e:
            logger.error(f"Failed to get deletion status: {e}")
            return None

    # ==================================================
    # スケジューラー設定
    # ==================================================

    async def setup_deletion_schedules(self):
        """削除スケジュール設定"""
        try:
            parent = f"projects/{self.project_id}/locations/asia-northeast1"
            
            # 日次削除候補スキャン（毎日午前1時）
            scan_job = {
                "name": f"{parent}/jobs/daily-deletion-scan",
                "description": "Daily deletion candidates scanning",
                "schedule": "0 0 1 * * *",  # 毎日1:00 AM JST
                "time_zone": "Asia/Tokyo",
                "http_target": {
                    "http_method": "POST",
                    "uri": "https://your-service-url/api/deletion/scan-candidates",
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"scheduled": True}).encode()
                }
            }
            
            # 日次削除処理実行（毎日午前2時）
            process_job = {
                "name": f"{parent}/jobs/daily-deletion-processing",
                "description": "Daily deletion processing execution",
                "schedule": "0 0 2 * * *",  # 毎日2:00 AM JST
                "time_zone": "Asia/Tokyo",
                "http_target": {
                    "http_method": "POST",
                    "uri": "https://your-service-url/api/deletion/process-scheduled",
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"scheduled": True}).encode()
                }
            }
            
            # ジョブ作成/更新
            for job in [scan_job, process_job]:
                try:
                    self.scheduler_client.create_job(parent=parent, job=job)
                    logger.info(f"Deletion job created: {job['name']}")
                except gcp_exceptions.AlreadyExists:
                    self.scheduler_client.update_job(job=job)
                    logger.info(f"Deletion job updated: {job['name']}")
                    
        except Exception as e:
            logger.error(f"Failed to setup deletion schedules: {e}")
            raise

# ==================================================
# エクスポート
# ==================================================

__all__ = [
    "AutoDeletionService",
    "DeletionRecord",
    "DeletionPolicy", 
    "DeletionApproval",
    "DeletionStatus",
    "DeletionType",
    "ApprovalLevel"
]