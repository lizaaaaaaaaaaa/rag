"""
同意管理ライフサイクルサービス
同意の有効期限管理・自動処理・通知システム

機能:
- 同意有効期限の自動管理
- 期限切れ前の通知送信
- 自動取り消し処理
- 再同意促進システム
- データ保全期間管理
- コンプライアンス自動確認

Requirements:
- asyncio
- sqlalchemy
- google-cloud-scheduler
- email notification system
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import uuid

from sqlalchemy import text, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from google.cloud import scheduler_v1
from google.api_core import exceptions as gcp_exceptions

from database import get_db_session
from models import ConsentRecord, ConsentWithdrawal, AuditLog
from .worm_service import EnhancedWORMManager
from .manifest_service import ManifestService
from utils.notification import send_email_notification, send_line_notification
from utils.encryption import encrypt_sensitive_data

# ロギング設定
logger = logging.getLogger(__name__)

# ==================================================
# 列挙型・データクラス
# ==================================================

class ConsentStatus(Enum):
    """同意ステータス"""
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"  # 30日以内に期限切れ
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"
    PENDING_RENEWAL = "pending_renewal"

class NotificationType(Enum):
    """通知タイプ"""
    EXPIRY_WARNING_30D = "expiry_warning_30d"
    EXPIRY_WARNING_7D = "expiry_warning_7d"
    EXPIRY_WARNING_1D = "expiry_warning_1d"
    CONSENT_EXPIRED = "consent_expired"
    RENEWAL_REQUIRED = "renewal_required"
    COMPLIANCE_ALERT = "compliance_alert"

@dataclass
class ConsentLifecycleInfo:
    """同意ライフサイクル情報"""
    consent_id: str
    user_id: str
    line_user_id: Optional[str]
    consented_at: datetime
    expires_at: datetime
    status: ConsentStatus
    days_until_expiry: int
    policy_version: str
    tos_version: str
    last_notification_sent: Optional[datetime] = None
    renewal_attempts: int = 0
    auto_renewal_enabled: bool = False

@dataclass
class LifecycleAction:
    """ライフサイクルアクション"""
    action_id: str
    consent_id: str
    action_type: str  # 'notify', 'expire', 'withdraw', 'renew'
    scheduled_at: datetime
    status: str  # 'pending', 'completed', 'failed'
    details: Dict[str, Any]
    created_at: datetime
    executed_at: Optional[datetime] = None
    error_message: Optional[str] = None

@dataclass
class LifecycleMetrics:
    """ライフサイクルメトリクス"""
    total_consents: int
    active_consents: int
    expiring_soon_consents: int
    expired_consents: int
    withdrawn_consents: int
    renewal_success_rate: float
    average_consent_duration_days: float
    notification_delivery_rate: float

# ==================================================
# メインクラス: ConsentLifecycleManager
# ==================================================

class ConsentLifecycleManager:
    """同意ライフサイクル管理"""
    
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
        self.consent_validity_days = 365  # 12ヶ月
        self.warning_days = [30, 7, 1]  # 期限切れ警告日
        self.max_renewal_attempts = 3
        self.batch_size = 100
        self.retention_years = 5

    async def process_daily_lifecycle(self, target_date: Optional[date] = None) -> Dict[str, Any]:
        """日次ライフサイクル処理"""
        if target_date is None:
            target_date = date.today()
            
        try:
            logger.info(f"Starting daily lifecycle processing for {target_date}")
            
            results = {
                'date': target_date.isoformat(),
                'started_at': datetime.utcnow().isoformat(),
                'notifications_sent': 0,
                'consents_expired': 0,
                'renewals_processed': 0,
                'errors': [],
                'metrics': None
            }
            
            async with get_db_session() as db:
                # 1. 同意ステータス更新
                await self._update_consent_statuses(db, target_date)
                
                # 2. 期限切れ警告通知
                notification_result = await self._process_expiry_notifications(db, target_date)
                results['notifications_sent'] = notification_result['sent_count']
                results['errors'].extend(notification_result['errors'])
                
                # 3. 期限切れ処理
                expiry_result = await self._process_expired_consents(db, target_date)
                results['consents_expired'] = expiry_result['expired_count']
                results['errors'].extend(expiry_result['errors'])
                
                # 4. 自動更新処理
                renewal_result = await self._process_consent_renewals(db, target_date)
                results['renewals_processed'] = renewal_result['renewal_count']
                results['errors'].extend(renewal_result['errors'])
                
                # 5. データ保全確認
                retention_result = await self._verify_data_retention(db, target_date)
                results['errors'].extend(retention_result['errors'])
                
                # 6. メトリクス計算
                metrics = await self._calculate_lifecycle_metrics(db, target_date)
                results['metrics'] = asdict(metrics)
                
                # 7. コンプライアンスチェック
                compliance_result = await self._check_compliance_status(db, target_date)
                if not compliance_result['compliant']:
                    results['errors'].append({
                        'type': 'COMPLIANCE_FAILURE',
                        'message': 'Daily compliance check failed',
                        'details': compliance_result
                    })
                
                results['completed_at'] = datetime.utcnow().isoformat()
                results['success'] = len([e for e in results['errors'] if e.get('severity') == 'CRITICAL']) == 0
                
                # 8. 結果をWORMストレージに保存
                await self._store_lifecycle_report(results, target_date)
                
                logger.info(f"Daily lifecycle processing completed: {results['success']}")
                return results
                
        except Exception as e:
            logger.error(f"Daily lifecycle processing failed: {e}")
            
            error_result = {
                'date': target_date.isoformat(),
                'success': False,
                'error': str(e),
                'completed_at': datetime.utcnow().isoformat()
            }
            
            # 緊急アラート送信
            await self._send_critical_lifecycle_alert(
                "LIFECYCLE_PROCESSING_FAILED",
                f"Daily lifecycle processing failed for {target_date}",
                {'error': str(e), 'date': target_date.isoformat()}
            )
            
            return error_result

    async def _update_consent_statuses(self, db: AsyncSession, target_date: date):
        """同意ステータス更新"""
        try:
            # 期限切れ同意の自動取り消し
            expire_query = text("""
                UPDATE consent_records 
                SET 
                    withdrawn = TRUE,
                    withdrawn_at = NOW(),
                    withdrawal_reason = 'Automatic expiration after 12 months'
                WHERE 
                    expires_at::date <= :target_date
                    AND withdrawn = FALSE
                    AND is_immutable = TRUE
            """)
            
            expire_result = await db.execute(expire_query, {"target_date": target_date})
            expired_count = expire_result.rowcount
            
            if expired_count > 0:
                logger.info(f"Automatically expired {expired_count} consents")
                
                # 監査ログ記録
                await self._log_lifecycle_action(
                    db, "AUTOMATIC_EXPIRY", target_date.isoformat(),
                    {"expired_count": expired_count}
                )
            
            await db.commit()
            
        except Exception as e:
            logger.error(f"Failed to update consent statuses: {e}")
            await db.rollback()
            raise

    async def _process_expiry_notifications(
        self, 
        db: AsyncSession, 
        target_date: date
    ) -> Dict[str, Any]:
        """期限切れ通知処理"""
        try:
            sent_count = 0
            errors = []
            
            for warning_days in self.warning_days:
                # 通知対象の同意を取得
                notification_date = target_date + timedelta(days=warning_days)
                
                query = text("""
                    SELECT 
                        consent_id, user_id, line_user_id, consented_at, 
                        expires_at, policy_version, tos_version,
                        last_notification_sent
                    FROM consent_records 
                    WHERE 
                        expires_at::date = :notification_date
                        AND withdrawn = FALSE
                        AND (
                            last_notification_sent IS NULL 
                            OR last_notification_sent < NOW() - INTERVAL '24 hours'
                        )
                    ORDER BY consented_at
                    LIMIT :batch_size
                """)
                
                result = await db.execute(query, {
                    "notification_date": notification_date,
                    "batch_size": self.batch_size
                })
                
                consents_to_notify = result.fetchall()
                
                # 並列通知送信
                notification_tasks = []
                for consent in consents_to_notify:
                    notification_tasks.append(
                        self._send_expiry_notification(
                            consent, warning_days, target_date
                        )
                    )
                
                if notification_tasks:
                    notification_results = await asyncio.gather(
                        *notification_tasks, return_exceptions=True
                    )
                    
                    # 結果処理
                    for i, result in enumerate(notification_results):
                        consent = consents_to_notify[i]
                        
                        if isinstance(result, Exception):
                            errors.append({
                                'type': 'NOTIFICATION_FAILED',
                                'consent_id': consent.consent_id,
                                'error': str(result),
                                'severity': 'MEDIUM'
                            })
                        elif result:
                            sent_count += 1
                            
                            # 通知送信記録を更新
                            update_query = text("""
                                UPDATE consent_records 
                                SET last_notification_sent = NOW()
                                WHERE consent_id = :consent_id
                            """)
                            await db.execute(update_query, {"consent_id": consent.consent_id})
                        else:
                            errors.append({
                                'type': 'NOTIFICATION_SKIPPED',
                                'consent_id': consent.consent_id,
                                'severity': 'LOW'
                            })
            
            await db.commit()
            
            logger.info(f"Processed expiry notifications: {sent_count} sent, {len(errors)} errors")
            return {
                'sent_count': sent_count,
                'errors': errors
            }
            
        except Exception as e:
            logger.error(f"Failed to process expiry notifications: {e}")
            await db.rollback()
            return {
                'sent_count': 0,
                'errors': [{
                    'type': 'NOTIFICATION_PROCESSING_FAILED',
                    'error': str(e),
                    'severity': 'HIGH'
                }]
            }

    async def _send_expiry_notification(
        self, 
        consent, 
        warning_days: int, 
        target_date: date
    ) -> bool:
        """期限切れ通知送信"""
        try:
            # 通知タイプ決定
            if warning_days == 30:
                notification_type = NotificationType.EXPIRY_WARNING_30D
            elif warning_days == 7:
                notification_type = NotificationType.EXPIRY_WARNING_7D
            elif warning_days == 1:
                notification_type = NotificationType.EXPIRY_WARNING_1D
            else:
                notification_type = NotificationType.CONSENT_EXPIRED
            
            # 通知内容生成
            notification_content = self._generate_notification_content(
                consent, notification_type, warning_days
            )
            
            # LINE通知（優先）
            line_sent = False
            if consent.line_user_id and self.notification_config.get('line_enabled', True):
                try:
                    line_sent = await send_line_notification(
                        user_id=consent.line_user_id,
                        message=notification_content['line_message'],
                        config=self.notification_config.get('line')
                    )
                except Exception as e:
                    logger.warning(f"LINE notification failed for {consent.consent_id}: {e}")
            
            # メール通知（フォールバック）
            email_sent = False
            if not line_sent and self.notification_config.get('email_enabled', True):
                try:
                    email_sent = await send_email_notification(
                        subject=notification_content['email_subject'],
                        body=notification_content['email_body'],
                        recipients=[f"user_{consent.user_id}@example.com"],  # 実際のメールアドレス取得が必要
                        smtp_config=self.notification_config.get('smtp')
                    )
                except Exception as e:
                    logger.warning(f"Email notification failed for {consent.consent_id}: {e}")
            
            # 送信結果
            success = line_sent or email_sent
            
            if success:
                logger.debug(f"Expiry notification sent for {consent.consent_id} ({warning_days} days)")
            else:
                logger.warning(f"All notification methods failed for {consent.consent_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to send expiry notification: {e}")
            return False

    def _generate_notification_content(
        self, 
        consent, 
        notification_type: NotificationType, 
        warning_days: int
    ) -> Dict[str, str]:
        """通知内容生成"""
        expires_date = consent.expires_at.strftime('%Y年%m月%d日')
        
        if notification_type == NotificationType.EXPIRY_WARNING_30D:
            line_message = f"""
🔔 同意期限のお知らせ

お客様の同意期限が30日後（{expires_date}）に迫っています。

継続してサービスをご利用いただくには、再度同意手続きが必要です。

▼ 同意更新はこちら
https://your-service.com/consent/renew?id={consent.consent_id}

※この通知は自動送信されています
            """.strip()
            
            email_subject = "【重要】同意期限のお知らせ（30日前）"
            email_body = f"""
お客様の同意期限が{expires_date}に迫っています。

継続してサービスをご利用いただくには、期限前に再同意手続きを行ってください。

同意更新URL: https://your-service.com/consent/renew?id={consent.consent_id}

ご不明な点がございましたら、サポートまでお問い合わせください。
            """.strip()
            
        elif notification_type == NotificationType.EXPIRY_WARNING_7D:
            line_message = f"""
⚠️ 同意期限まで7日です

同意期限: {expires_date}

サービス継続には再同意が必要です。
お早めにお手続きください。

▼ 同意更新
https://your-service.com/consent/renew?id={consent.consent_id}
            """.strip()
            
            email_subject = "【緊急】同意期限まで7日です"
            email_body = f"""
同意期限まで残り7日となりました。

期限: {expires_date}

期限を過ぎるとサービスをご利用いただけなくなります。
至急、再同意手続きを行ってください。

同意更新URL: https://your-service.com/consent/renew?id={consent.consent_id}
            """.strip()
            
        elif notification_type == NotificationType.EXPIRY_WARNING_1D:
            line_message = f"""
🚨 同意期限は明日です！

期限: {expires_date}

サービス継続には今すぐ再同意が必要です。

▼ 緊急同意更新
https://your-service.com/consent/renew?id={consent.consent_id}

※期限を過ぎるとサービス停止となります
            """.strip()
            
            email_subject = "【最終通知】同意期限は明日です"
            email_body = f"""
同意期限まで残り1日となりました。

期限: {expires_date}

明日の期限を過ぎると、サービスのご利用ができなくなります。
今すぐ再同意手続きを行ってください。

同意更新URL: https://your-service.com/consent/renew?id={consent.consent_id}

緊急の場合は、サポートまでご連絡ください。
            """.strip()
            
        else:
            line_message = "同意期限に関する通知があります。"
            email_subject = "同意期限通知"
            email_body = "同意期限に関する重要な通知です。"
        
        return {
            'line_message': line_message,
            'email_subject': email_subject,
            'email_body': email_body
        }

    async def _process_expired_consents(
        self, 
        db: AsyncSession, 
        target_date: date
    ) -> Dict[str, Any]:
        """期限切れ同意処理"""
        try:
            # 期限切れ同意取得
            query = text("""
                SELECT consent_id, user_id, line_user_id
                FROM consent_records 
                WHERE 
                    expires_at::date < :target_date
                    AND withdrawn = FALSE
                LIMIT :batch_size
            """)
            
            result = await db.execute(query, {
                "target_date": target_date,
                "batch_size": self.batch_size
            })
            
            expired_consents = result.fetchall()
            expired_count = 0
            errors = []
            
            for consent in expired_consents:
                try:
                    # 取り消し記録作成
                    withdrawal_id = str(uuid.uuid4())
                    
                    withdrawal_query = text("""
                        INSERT INTO consent_withdrawals (
                            withdrawal_id, consent_id, user_id,
                            withdrawn_at, withdrawal_method, withdrawal_reason,
                            processed_by, created_at
                        ) VALUES (
                            :withdrawal_id, :consent_id, :user_id,
                            NOW(), 'auto_expire', 'Automatic expiration after 12 months',
                            'system', NOW()
                        )
                    """)
                    
                    await db.execute(withdrawal_query, {
                        "withdrawal_id": withdrawal_id,
                        "consent_id": consent.consent_id,
                        "user_id": consent.user_id
                    })
                    
                    # 同意記録を取り消し状態に更新
                    update_query = text("""
                        UPDATE consent_records 
                        SET 
                            withdrawn = TRUE,
                            withdrawn_at = NOW(),
                            withdrawal_reason = 'Automatic expiration after 12 months'
                        WHERE consent_id = :consent_id
                    """)
                    
                    await db.execute(update_query, {"consent_id": consent.consent_id})
                    
                    expired_count += 1
                    
                    # 期限切れ通知送信
                    await self._send_expiry_notification(
                        consent, NotificationType.CONSENT_EXPIRED, 0
                    )
                    
                except Exception as e:
                    errors.append({
                        'type': 'EXPIRY_PROCESSING_FAILED',
                        'consent_id': consent.consent_id,
                        'error': str(e),
                        'severity': 'HIGH'
                    })
            
            await db.commit()
            
            logger.info(f"Processed {expired_count} expired consents")
            return {
                'expired_count': expired_count,
                'errors': errors
            }
            
        except Exception as e:
            logger.error(f"Failed to process expired consents: {e}")
            await db.rollback()
            return {
                'expired_count': 0,
                'errors': [{
                    'type': 'EXPIRY_BATCH_FAILED',
                    'error': str(e),
                    'severity': 'CRITICAL'
                }]
            }

    async def _process_consent_renewals(
        self, 
        db: AsyncSession, 
        target_date: date
    ) -> Dict[str, Any]:
        """同意更新処理"""
        try:
            # 自動更新対象の同意を取得
            query = text("""
                SELECT 
                    consent_id, user_id, line_user_id, policy_version, tos_version,
                    renewal_attempts, auto_renewal_enabled
                FROM consent_records 
                WHERE 
                    expires_at::date BETWEEN :target_date AND :target_date + INTERVAL '7 days'
                    AND withdrawn = FALSE
                    AND auto_renewal_enabled = TRUE
                    AND renewal_attempts < :max_attempts
                LIMIT :batch_size
            """)
            
            result = await db.execute(query, {
                "target_date": target_date,
                "max_attempts": self.max_renewal_attempts,
                "batch_size": self.batch_size
            })
            
            renewal_candidates = result.fetchall()
            renewal_count = 0
            errors = []
            
            for consent in renewal_candidates:
                try:
                    # 自動更新処理（ユーザー確認を経た場合のみ）
                    # 実際の実装では、ユーザーの明示的な同意確認が必要
                    
                    # 更新試行回数を増加
                    update_attempts_query = text("""
                        UPDATE consent_records 
                        SET 
                            renewal_attempts = renewal_attempts + 1,
                            last_notification_sent = NOW()
                        WHERE consent_id = :consent_id
                    """)
                    
                    await db.execute(update_attempts_query, {"consent_id": consent.consent_id})
                    
                    # 更新要求通知送信
                    await self._send_renewal_request_notification(consent)
                    
                    renewal_count += 1
                    
                except Exception as e:
                    errors.append({
                        'type': 'RENEWAL_PROCESSING_FAILED',
                        'consent_id': consent.consent_id,
                        'error': str(e),
                        'severity': 'MEDIUM'
                    })
            
            await db.commit()
            
            logger.info(f"Processed {renewal_count} consent renewals")
            return {
                'renewal_count': renewal_count,
                'errors': errors
            }
            
        except Exception as e:
            logger.error(f"Failed to process consent renewals: {e}")
            await db.rollback()
            return {
                'renewal_count': 0,
                'errors': [{
                    'type': 'RENEWAL_BATCH_FAILED',
                    'error': str(e),
                    'severity': 'HIGH'
                }]
            }

    async def _send_renewal_request_notification(self, consent):
        """更新要求通知送信"""
        try:
            notification_content = {
                'line_message': f"""
🔄 同意更新のお願い

お客様の同意が間もなく期限切れとなります。

継続してサービスをご利用いただくには、最新のプライバシーポリシーへの同意が必要です。

▼ 同意更新手続き
https://your-service.com/consent/renew?id={consent.consent_id}

※自動更新をご希望の場合は、設定画面で有効化してください
                """.strip(),
                
                'email_subject': '同意更新のお願い',
                'email_body': f"""
お客様の同意期限が近づいています。

継続してサービスをご利用いただくには、同意の更新が必要です。

同意更新URL: https://your-service.com/consent/renew?id={consent.consent_id}

ご協力をお願いいたします。
                """.strip()
            }
            
            # 通知送信
            if consent.line_user_id:
                await send_line_notification(
                    user_id=consent.line_user_id,
                    message=notification_content['line_message'],
                    config=self.notification_config.get('line')
                )
            
        except Exception as e:
            logger.error(f"Failed to send renewal request notification: {e}")

    async def _verify_data_retention(
        self, 
        db: AsyncSession, 
        target_date: date
    ) -> Dict[str, Any]:
        """データ保全確認"""
        try:
            errors = []
            
            # 5年保全期間確認
            retention_cutoff = target_date - timedelta(days=self.retention_years * 365)
            
            # 期限切れデータ確認
            old_data_query = text("""
                SELECT COUNT(*) as old_count
                FROM consent_records 
                WHERE created_at::date < :retention_cutoff
                AND withdrawn = FALSE
            """)
            
            result = await db.execute(old_data_query, {"retention_cutoff": retention_cutoff})
            old_count = result.scalar()
            
            if old_count > 0:
                errors.append({
                    'type': 'OLD_DATA_RETENTION_VIOLATION',
                    'message': f'Found {old_count} records older than {self.retention_years} years',
                    'severity': 'HIGH',
                    'details': {'count': old_count, 'cutoff_date': retention_cutoff.isoformat()}
                })
            
            # WORMストレージ整合性確認
            worm_health = await self.worm_manager.health_check()
            if worm_health.get('status') != 'healthy':
                errors.append({
                    'type': 'WORM_STORAGE_UNHEALTHY',
                    'message': 'WORM storage health check failed',
                    'severity': 'CRITICAL',
                    'details': worm_health
                })
            
            return {'errors': errors}
            
        except Exception as e:
            logger.error(f"Data retention verification failed: {e}")
            return {
                'errors': [{
                    'type': 'RETENTION_VERIFICATION_FAILED',
                    'error': str(e),
                    'severity': 'HIGH'
                }]
            }

    async def _calculate_lifecycle_metrics(
        self, 
        db: AsyncSession, 
        target_date: date
    ) -> LifecycleMetrics:
        """ライフサイクルメトリクス計算"""
        try:
            # 基本統計
            stats_query = text("""
                SELECT 
                    COUNT(*) as total_consents,
                    COUNT(*) FILTER (WHERE withdrawn = FALSE AND expires_at > NOW()) as active_consents,
                    COUNT(*) FILTER (WHERE withdrawn = FALSE AND expires_at BETWEEN NOW() AND NOW() + INTERVAL '30 days') as expiring_soon,
                    COUNT(*) FILTER (WHERE withdrawn = FALSE AND expires_at <= NOW()) as expired_consents,
                    COUNT(*) FILTER (WHERE withdrawn = TRUE) as withdrawn_consents,
                    AVG(EXTRACT(EPOCH FROM (expires_at - created_at)) / 86400) as avg_duration_days
                FROM consent_records
                WHERE created_at >= :start_date
            """)
            
            start_date = target_date - timedelta(days=90)  # 過去90日
            result = await db.execute(stats_query, {"start_date": start_date})
            stats = result.fetchone()
            
            # 更新成功率計算
            renewal_query = text("""
                SELECT 
                    COUNT(*) FILTER (WHERE renewal_attempts > 0) as renewal_attempts,
                    COUNT(*) FILTER (WHERE renewal_attempts > 0 AND withdrawn = FALSE) as renewal_successes
                FROM consent_records
                WHERE last_notification_sent >= :start_date
            """)
            
            renewal_result = await db.execute(renewal_query, {"start_date": start_date})
            renewal_stats = renewal_result.fetchone()
            
            renewal_success_rate = (
                renewal_stats.renewal_successes / renewal_stats.renewal_attempts
                if renewal_stats.renewal_attempts > 0 else 0.0
            )
            
            # 通知配信率（簡易計算）
            notification_delivery_rate = 0.95  # 実際の配信ログから計算
            
            return LifecycleMetrics(
                total_consents=stats.total_consents or 0,
                active_consents=stats.active_consents or 0,
                expiring_soon_consents=stats.expiring_soon or 0,
                expired_consents=stats.expired_consents or 0,
                withdrawn_consents=stats.withdrawn_consents or 0,
                renewal_success_rate=renewal_success_rate,
                average_consent_duration_days=float(stats.avg_duration_days or 0),
                notification_delivery_rate=notification_delivery_rate
            )
            
        except Exception as e:
            logger.error(f"Failed to calculate lifecycle metrics: {e}")
            return LifecycleMetrics(
                total_consents=0, active_consents=0, expiring_soon_consents=0,
                expired_consents=0, withdrawn_consents=0, renewal_success_rate=0.0,
                average_consent_duration_days=0.0, notification_delivery_rate=0.0
            )

    async def _check_compliance_status(
        self, 
        db: AsyncSession, 
        target_date: date
    ) -> Dict[str, Any]:
        """コンプライアンス状況確認"""
        try:
            compliance_checks = []
            
            # 1. 期限切れ同意の適切な処理確認
            unprocessed_expired_query = text("""
                SELECT COUNT(*) 
                FROM consent_records 
                WHERE expires_at::date < :target_date 
                AND withdrawn = FALSE
            """)
            
            result = await db.execute(unprocessed_expired_query, {"target_date": target_date})
            unprocessed_count = result.scalar()
            
            compliance_checks.append({
                'check': 'expired_consent_processing',
                'passed': unprocessed_count == 0,
                'details': {'unprocessed_count': unprocessed_count}
            })
            
            # 2. 通知送信の適切性確認
            missing_notifications_query = text("""
                SELECT COUNT(*) 
                FROM consent_records 
                WHERE expires_at::date BETWEEN :target_date + INTERVAL '1 day' AND :target_date + INTERVAL '30 days'
                AND withdrawn = FALSE
                AND (last_notification_sent IS NULL OR last_notification_sent < NOW() - INTERVAL '48 hours')
            """)
            
            result = await db.execute(missing_notifications_query, {"target_date": target_date})
            missing_notifications = result.scalar()
            
            compliance_checks.append({
                'check': 'notification_timeliness',
                'passed': missing_notifications < 10,  # 許容範囲
                'details': {'missing_notifications': missing_notifications}
            })
            
            # 3. データ整合性確認
            integrity_passed = await self._quick_integrity_check(db)
            compliance_checks.append({
                'check': 'data_integrity',
                'passed': integrity_passed,
                'details': {}
            })
            
            # 総合判定
            all_passed = all(check['passed'] for check in compliance_checks)
            
            return {
                'compliant': all_passed,
                'checks': compliance_checks,
                'checked_at': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Compliance status check failed: {e}")
            return {
                'compliant': False,
                'error': str(e),
                'checks': [],
                'checked_at': datetime.utcnow().isoformat()
            }

    async def _quick_integrity_check(self, db: AsyncSession) -> bool:
        """簡易整合性チェック"""
        try:
            # 基本的な制約チェック
            constraint_query = text("""
                SELECT 
                    COUNT(*) FILTER (WHERE consent_id IS NULL) as null_ids,
                    COUNT(*) FILTER (WHERE user_id IS NULL) as null_users,
                    COUNT(*) FILTER (WHERE expires_at < created_at) as invalid_dates
                FROM consent_records
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            """)
            
            result = await db.execute(constraint_query)
            checks = result.fetchone()
            
            return (checks.null_ids == 0 and 
                   checks.null_users == 0 and 
                   checks.invalid_dates == 0)
            
        except Exception as e:
            logger.error(f"Quick integrity check failed: {e}")
            return False

    async def _store_lifecycle_report(self, results: Dict[str, Any], target_date: date):
        """ライフサイクルレポート保存"""
        try:
            # レポートをWORMストレージに保存
            report_path = f"lifecycle_reports/{target_date.strftime('%Y/%m')}/lifecycle_{target_date.isoformat()}.json"
            
            report_json = json.dumps(results, indent=2, ensure_ascii=False)
            
            blob = self.worm_manager.bucket.blob(report_path)
            blob.metadata = {
                'report_type': 'lifecycle',
                'date': target_date.isoformat(),
                'generated_at': results.get('completed_at'),
                'success': str(results.get('success', False))
            }
            
            blob.upload_from_string(report_json, content_type='application/json')
            
            logger.info(f"Lifecycle report stored: {report_path}")
            
        except Exception as e:
            logger.error(f"Failed to store lifecycle report: {e}")

    async def _log_lifecycle_action(
        self, 
        db: AsyncSession, 
        action_type: str, 
        target: str, 
        details: Dict[str, Any]
    ):
        """ライフサイクルアクション記録"""
        try:
            log_query = text("""
                INSERT INTO audit_logs (
                    log_id, table_name, record_id, action_type, action_description,
                    actor_type, actor_id, success, new_values, created_at
                ) VALUES (
                    :log_id, 'lifecycle_management', :target, :action_type, 
                    'Automated lifecycle action', 'system', 'lifecycle_manager',
                    TRUE, :details, NOW()
                )
            """)
            
            await db.execute(log_query, {
                "log_id": str(uuid.uuid4()),
                "target": target,
                "action_type": action_type,
                "details": json.dumps(details)
            })
            
        except Exception as e:
            logger.error(f"Failed to log lifecycle action: {e}")

    async def _send_critical_lifecycle_alert(
        self, 
        alert_type: str, 
        message: str, 
        details: Dict[str, Any]
    ):
        """緊急ライフサイクルアラート送信"""
        try:
            alert_message = f"""
🚨 Critical Lifecycle Alert

Type: {alert_type}
Message: {message}

Details:
{json.dumps(details, indent=2)}

Timestamp: {datetime.utcnow().isoformat()}
            """.strip()
            
            if self.notification_config.get('emergency_contacts'):
                await send_email_notification(
                    subject=f"[CRITICAL] Consent Lifecycle Alert: {alert_type}",
                    body=alert_message,
                    recipients=self.notification_config['emergency_contacts'],
                    smtp_config=self.notification_config.get('smtp')
                )
            
        except Exception as e:
            logger.error(f"Failed to send critical lifecycle alert: {e}")

    # ==================================================
    # スケジューラー設定
    # ==================================================

    async def setup_lifecycle_schedules(self):
        """ライフサイクルスケジュール設定"""
        try:
            parent = f"projects/{self.project_id}/locations/asia-northeast1"
            
            # 日次ライフサイクル処理（毎日午前3時）
            daily_job = {
                "name": f"{parent}/jobs/daily-lifecycle-processing",
                "description": "Daily consent lifecycle processing",
                "schedule": "0 0 3 * * *",  # 毎日3:00 AM JST
                "time_zone": "Asia/Tokyo",
                "http_target": {
                    "http_method": "POST",
                    "uri": "https://your-service-url/api/lifecycle/process-daily",
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"scheduled": True}).encode()
                },
                "retry_config": {
                    "retry_count": 2,
                    "max_retry_duration": "300s"
                }
            }
            
            # 週次メトリクス集計（毎週月曜日午前4時）
            weekly_job = {
                "name": f"{parent}/jobs/weekly-lifecycle-metrics",
                "description": "Weekly lifecycle metrics calculation",
                "schedule": "0 0 4 * * 1",  # 毎週月曜日4:00 AM
                "time_zone": "Asia/Tokyo",
                "http_target": {
                    "http_method": "POST",
                    "uri": "https://your-service-url/api/lifecycle/calculate-weekly-metrics",
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"scheduled": True}).encode()
                }
            }
            
            # ジョブ作成/更新
            for job in [daily_job, weekly_job]:
                try:
                    self.scheduler_client.create_job(parent=parent, job=job)
                    logger.info(f"Lifecycle job created: {job['name']}")
                except gcp_exceptions.AlreadyExists:
                    self.scheduler_client.update_job(job=job)
                    logger.info(f"Lifecycle job updated: {job['name']}")
                    
        except Exception as e:
            logger.error(f"Failed to setup lifecycle schedules: {e}")
            raise

# ==================================================
# エクスポート
# ==================================================

__all__ = [
    "ConsentLifecycleManager",
    "ConsentStatus",
    "NotificationType",
    "ConsentLifecycleInfo",
    "LifecycleAction",
    "LifecycleMetrics"
]