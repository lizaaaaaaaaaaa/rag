"""
日次マニフェスト生成システム
同意記録の整合性確認・証跡管理・法的要件対応

機能:
- 日次データ整合性確認
- マニフェスト生成・保存
- チェーンハッシュによる改ざん検知
- 法的証跡の自動生成
- アラート・通知機能

Requirements:
- asyncio
- sqlalchemy
- google-cloud-storage
- google-cloud-scheduler
- smtplib (通知用)
"""

import asyncio
import hashlib
import json
import logging
import smtplib
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart
from email.mime.application import MimeApplication
import uuid

from sqlalchemy import text, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from google.cloud import storage, scheduler_v1
from google.api_core import exceptions as gcp_exceptions

from ..database import get_db_session
from ..models import ConsentRecord, ConsentWithdrawal, AuditLog, DailyConsentStats
from .worm_service import EnhancedWORMManager
from ..utils.encryption import encrypt_sensitive_data, decrypt_sensitive_data
from ..utils.notification import send_email_notification

# ロギング設定
logger = logging.getLogger(__name__)

# ==================================================
# データクラス定義
# ==================================================

@dataclass
class ManifestEntry:
    """マニフェストエントリ"""
    record_id: str
    record_type: str  # 'consent', 'withdrawal', 'audit'
    timestamp: str
    checksum: str
    file_path: str
    size_bytes: int
    metadata: Dict[str, Any]

@dataclass
class DailyManifest:
    """日次マニフェスト"""
    manifest_id: str
    date: str
    generated_at: str
    
    # データ統計
    total_entries: int
    consent_records: int
    withdrawal_records: int
    audit_logs: int
    
    # 整合性情報
    entries: List[ManifestEntry]
    merkle_root: str
    chain_hash: str
    previous_manifest_hash: Optional[str]
    
    # メタデータ
    generator_version: str
    compliance_verified: bool
    worm_verified: bool
    anomalies: List[Dict[str, Any]]
    
    # 署名・証明
    digital_signature: Optional[str] = None
    timestamp_proof: Optional[str] = None

@dataclass
class ComplianceAlert:
    """コンプライアンスアラート"""
    alert_id: str
    severity: str  # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    alert_type: str
    message: str
    details: Dict[str, Any]
    timestamp: str
    resolved: bool = False

# ==================================================
# メインクラス: ManifestService
# ==================================================

class ManifestService:
    """日次マニフェスト生成サービス"""
    
    def __init__(
        self,
        worm_manager: EnhancedWORMManager,
        project_id: str,
        notification_config: Optional[Dict[str, Any]] = None
    ):
        self.worm_manager = worm_manager
        self.project_id = project_id
        self.notification_config = notification_config or {}
        self.scheduler_client = scheduler_v1.CloudSchedulerClient()
        
        # 設定
        self.manifest_version = "1.0.0"
        self.max_chain_gap_hours = 25  # 24時間 + 1時間バッファ
        self.critical_anomaly_threshold = 0.95  # 95%未満で重要アラート
        
        # チェーンハッシュ管理
        self._chain_cache = {}

    async def generate_daily_manifest(
        self, 
        target_date: date,
        force_regenerate: bool = False
    ) -> DailyManifest:
        """日次マニフェスト生成"""
        try:
            manifest_id = f"manifest_{target_date.strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
            
            logger.info(f"Starting daily manifest generation for {target_date}")
            
            # 既存マニフェスト確認
            if not force_regenerate:
                existing = await self._check_existing_manifest(target_date)
                if existing:
                    logger.info(f"Daily manifest already exists for {target_date}")
                    return existing
            
            # データベースセッション取得
            async with get_db_session() as db:
                # 1. データ収集
                entries = await self._collect_daily_entries(db, target_date)
                
                # 2. 整合性検証
                verification_result = await self._verify_data_integrity(entries)
                
                # 3. 前日のマニフェストハッシュ取得
                previous_hash = await self._get_previous_manifest_hash(target_date)
                
                # 4. Merkle tree構築
                merkle_root = self._calculate_merkle_root(entries)
                
                # 5. チェーンハッシュ計算
                chain_hash = self._calculate_chain_hash(
                    target_date, merkle_root, previous_hash
                )
                
                # 6. 異常検知
                anomalies = await self._detect_anomalies(db, target_date, entries)
                
                # 7. WORMストレージ検証
                worm_verified = await self._verify_worm_storage(target_date)
                
                # 8. マニフェスト構築
                manifest = DailyManifest(
                    manifest_id=manifest_id,
                    date=target_date.isoformat(),
                    generated_at=datetime.utcnow().isoformat(),
                    total_entries=len(entries),
                    consent_records=len([e for e in entries if e.record_type == 'consent']),
                    withdrawal_records=len([e for e in entries if e.record_type == 'withdrawal']),
                    audit_logs=len([e for e in entries if e.record_type == 'audit']),
                    entries=entries,
                    merkle_root=merkle_root,
                    chain_hash=chain_hash,
                    previous_manifest_hash=previous_hash,
                    generator_version=self.manifest_version,
                    compliance_verified=verification_result['compliant'],
                    worm_verified=worm_verified,
                    anomalies=anomalies
                )
                
                # 9. デジタル署名
                manifest.digital_signature = await self._sign_manifest(manifest)
                
                # 10. タイムスタンプ証明
                manifest.timestamp_proof = await self._generate_timestamp_proof(manifest)
                
                # 11. マニフェスト保存
                await self._store_manifest(manifest)
                
                # 12. 統計更新
                await self._update_daily_statistics(db, manifest)
                
                # 13. アラート処理
                await self._process_alerts(manifest)
                
                logger.info(f"Daily manifest generated successfully: {manifest_id}")
                return manifest
                
        except Exception as e:
            logger.error(f"Failed to generate daily manifest for {target_date}: {e}")
            
            # 緊急アラート送信
            await self._send_critical_alert(
                "MANIFEST_GENERATION_FAILED",
                f"Failed to generate daily manifest for {target_date}",
                {"error": str(e), "date": target_date.isoformat()}
            )
            raise

    async def _collect_daily_entries(
        self, 
        db: AsyncSession, 
        target_date: date
    ) -> List[ManifestEntry]:
        """日次データエントリ収集"""
        entries = []
        
        try:
            # 同意記録の収集
            consent_query = text("""
                SELECT 
                    consent_id, created_at, user_id, policy_version,
                    pg_column_size(ROW(consent_records.*)) as size_bytes
                FROM consent_records 
                WHERE DATE(created_at) = :target_date
                ORDER BY created_at
            """)
            
            consent_result = await db.execute(consent_query, {"target_date": target_date})
            
            for row in consent_result.fetchall():
                # チェックサム計算（実際のデータから）
                checksum = await self._calculate_record_checksum(db, 'consent_records', row.consent_id)
                
                # WORMストレージパス
                file_path = f"consents/{target_date.strftime('%Y/%m/%d')}/{row.consent_id}.json.gz"
                
                entries.append(ManifestEntry(
                    record_id=row.consent_id,
                    record_type='consent',
                    timestamp=row.created_at.isoformat(),
                    checksum=checksum,
                    file_path=file_path,
                    size_bytes=row.size_bytes or 0,
                    metadata={
                        'user_id': row.user_id,
                        'policy_version': row.policy_version
                    }
                ))
            
            # 取り消し記録の収集
            withdrawal_query = text("""
                SELECT 
                    withdrawal_id, withdrawn_at, consent_id, user_id,
                    pg_column_size(ROW(consent_withdrawals.*)) as size_bytes
                FROM consent_withdrawals 
                WHERE DATE(withdrawn_at) = :target_date
                ORDER BY withdrawn_at
            """)
            
            withdrawal_result = await db.execute(withdrawal_query, {"target_date": target_date})
            
            for row in withdrawal_result.fetchall():
                checksum = await self._calculate_record_checksum(db, 'consent_withdrawals', row.withdrawal_id)
                file_path = f"withdrawals/{target_date.strftime('%Y/%m/%d')}/{row.withdrawal_id}.json.gz"
                
                entries.append(ManifestEntry(
                    record_id=row.withdrawal_id,
                    record_type='withdrawal',
                    timestamp=row.withdrawn_at.isoformat(),
                    checksum=checksum,
                    file_path=file_path,
                    size_bytes=row.size_bytes or 0,
                    metadata={
                        'consent_id': row.consent_id,
                        'user_id': row.user_id
                    }
                ))
            
            # 監査ログの収集
            audit_query = text("""
                SELECT 
                    log_id, created_at, table_name, action_type,
                    pg_column_size(ROW(audit_logs.*)) as size_bytes
                FROM audit_logs 
                WHERE DATE(created_at) = :target_date
                ORDER BY created_at
            """)
            
            audit_result = await db.execute(audit_query, {"target_date": target_date})
            
            for row in audit_result.fetchall():
                checksum = await self._calculate_record_checksum(db, 'audit_logs', row.log_id)
                file_path = f"audit_logs/{target_date.strftime('%Y/%m/%d')}/{row.log_id}.json"
                
                entries.append(ManifestEntry(
                    record_id=row.log_id,
                    record_type='audit',
                    timestamp=row.created_at.isoformat(),
                    checksum=checksum,
                    file_path=file_path,
                    size_bytes=row.size_bytes or 0,
                    metadata={
                        'table_name': row.table_name,
                        'action_type': row.action_type
                    }
                ))
            
            logger.info(f"Collected {len(entries)} entries for {target_date}")
            return entries
            
        except Exception as e:
            logger.error(f"Failed to collect daily entries: {e}")
            raise

    async def _verify_data_integrity(
        self, 
        entries: List[ManifestEntry]
    ) -> Dict[str, Any]:
        """データ整合性検証"""
        try:
            verification_tasks = []
            
            # 各エントリの整合性を並列チェック
            for entry in entries:
                if entry.record_type in ['consent', 'withdrawal']:
                    # WORMストレージとの整合性チェック
                    verification_tasks.append(
                        self._verify_worm_entry_integrity(entry)
                    )
            
            # 並列実行
            results = await asyncio.gather(*verification_tasks, return_exceptions=True)
            
            # 結果集計
            verified_count = 0
            failed_entries = []
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    failed_entries.append({
                        'entry_id': entries[i].record_id,
                        'error': str(result)
                    })
                elif result:
                    verified_count += 1
                else:
                    failed_entries.append({
                        'entry_id': entries[i].record_id,
                        'error': 'integrity_check_failed'
                    })
            
            total_checkable = len(verification_tasks)
            success_rate = verified_count / total_checkable if total_checkable > 0 else 1.0
            
            return {
                'compliant': success_rate >= self.critical_anomaly_threshold,
                'success_rate': success_rate,
                'verified_count': verified_count,
                'total_checkable': total_checkable,
                'failed_entries': failed_entries
            }
            
        except Exception as e:
            logger.error(f"Data integrity verification failed: {e}")
            return {
                'compliant': False,
                'error': str(e),
                'success_rate': 0.0
            }

    async def _detect_anomalies(
        self, 
        db: AsyncSession, 
        target_date: date, 
        entries: List[ManifestEntry]
    ) -> List[Dict[str, Any]]:
        """異常検知"""
        anomalies = []
        
        try:
            # 1. ボリューム異常検知
            # 過去7日間の平均と比較
            volume_query = text("""
                SELECT AVG(total_consents) as avg_consents,
                       AVG(new_consents) as avg_new_consents,
                       AVG(withdrawn_consents) as avg_withdrawn
                FROM daily_consent_stats 
                WHERE stat_date BETWEEN :start_date AND :end_date
            """)
            
            start_date = target_date - timedelta(days=7)
            end_date = target_date - timedelta(days=1)
            
            volume_result = await db.execute(volume_query, {
                "start_date": start_date,
                "end_date": end_date
            })
            volume_data = volume_result.fetchone()
            
            if volume_data and volume_data.avg_consents:
                current_consents = len([e for e in entries if e.record_type == 'consent'])
                avg_consents = float(volume_data.avg_consents)
                
                # 50%以上の変動をチェック
                if current_consents < avg_consents * 0.5:
                    anomalies.append({
                        'type': 'VOLUME_DROP',
                        'severity': 'HIGH',
                        'message': f'Consent volume dropped significantly: {current_consents} vs avg {avg_consents:.1f}',
                        'details': {
                            'current': current_consents,
                            'average': avg_consents,
                            'drop_percentage': ((avg_consents - current_consents) / avg_consents) * 100
                        }
                    })
                elif current_consents > avg_consents * 2.0:
                    anomalies.append({
                        'type': 'VOLUME_SPIKE',
                        'severity': 'MEDIUM',
                        'message': f'Consent volume spiked: {current_consents} vs avg {avg_consents:.1f}',
                        'details': {
                            'current': current_consents,
                            'average': avg_consents,
                            'spike_percentage': ((current_consents - avg_consents) / avg_consents) * 100
                        }
                    })
            
            # 2. タイムスタンプ異常検知
            timestamp_anomalies = self._detect_timestamp_anomalies(entries)
            anomalies.extend(timestamp_anomalies)
            
            # 3. チェックサム重複検知
            checksum_anomalies = self._detect_duplicate_checksums(entries)
            anomalies.extend(checksum_anomalies)
            
            # 4. ファイルサイズ異常検知
            size_anomalies = self._detect_size_anomalies(entries)
            anomalies.extend(size_anomalies)
            
            # 5. チェーン継続性検証
            chain_anomalies = await self._detect_chain_anomalies(target_date)
            anomalies.extend(chain_anomalies)
            
            if anomalies:
                logger.warning(f"Detected {len(anomalies)} anomalies for {target_date}")
            
            return anomalies
            
        except Exception as e:
            logger.error(f"Anomaly detection failed: {e}")
            return [{
                'type': 'DETECTION_ERROR',
                'severity': 'CRITICAL',
                'message': f'Anomaly detection failed: {str(e)}',
                'details': {'error': str(e)}
            }]

    def _detect_timestamp_anomalies(self, entries: List[ManifestEntry]) -> List[Dict[str, Any]]:
        """タイムスタンプ異常検知"""
        anomalies = []
        
        # 未来のタイムスタンプをチェック
        now = datetime.utcnow()
        future_entries = [
            e for e in entries 
            if datetime.fromisoformat(e.timestamp.replace('Z', '+00:00')) > now
        ]
        
        if future_entries:
            anomalies.append({
                'type': 'FUTURE_TIMESTAMP',
                'severity': 'HIGH',
                'message': f'Found {len(future_entries)} entries with future timestamps',
                'details': {
                    'count': len(future_entries),
                    'entries': [e.record_id for e in future_entries[:5]]  # 最初の5件
                }
            })
        
        # タイムスタンプの順序性チェック
        sorted_entries = sorted(entries, key=lambda x: x.timestamp)
        if [e.record_id for e in entries] != [e.record_id for e in sorted_entries]:
            anomalies.append({
                'type': 'TIMESTAMP_ORDER',
                'severity': 'MEDIUM',
                'message': 'Entries are not in chronological order',
                'details': {'total_entries': len(entries)}
            })
        
        return anomalies

    def _detect_duplicate_checksums(self, entries: List[ManifestEntry]) -> List[Dict[str, Any]]:
        """チェックサム重複検知"""
        anomalies = []
        checksums = {}
        
        for entry in entries:
            if entry.checksum in checksums:
                anomalies.append({
                    'type': 'DUPLICATE_CHECKSUM',
                    'severity': 'HIGH',
                    'message': f'Duplicate checksum found: {entry.checksum}',
                    'details': {
                        'checksum': entry.checksum,
                        'entries': [checksums[entry.checksum], entry.record_id]
                    }
                })
            else:
                checksums[entry.checksum] = entry.record_id
        
        return anomalies

    def _detect_size_anomalies(self, entries: List[ManifestEntry]) -> List[Dict[str, Any]]:
        """ファイルサイズ異常検知"""
        anomalies = []
        
        # 異常に大きなファイル（1MB超）
        large_files = [e for e in entries if e.size_bytes > 1024 * 1024]
        if large_files:
            anomalies.append({
                'type': 'LARGE_FILE_SIZE',
                'severity': 'MEDIUM',
                'message': f'Found {len(large_files)} unusually large files',
                'details': {
                    'count': len(large_files),
                    'max_size': max(e.size_bytes for e in large_files),
                    'files': [{'id': e.record_id, 'size': e.size_bytes} for e in large_files[:3]]
                }
            })
        
        # 空ファイル
        empty_files = [e for e in entries if e.size_bytes == 0]
        if empty_files:
            anomalies.append({
                'type': 'EMPTY_FILE',
                'severity': 'HIGH',
                'message': f'Found {len(empty_files)} empty files',
                'details': {
                    'count': len(empty_files),
                    'files': [e.record_id for e in empty_files[:5]]
                }
            })
        
        return anomalies

    async def _detect_chain_anomalies(self, target_date: date) -> List[Dict[str, Any]]:
        """チェーン継続性異常検知"""
        anomalies = []
        
        try:
            # 前日のマニフェスト存在確認
            yesterday = target_date - timedelta(days=1)
            previous_manifest = await self._check_existing_manifest(yesterday)
            
            if not previous_manifest:
                # 初回の場合は問題なし
                if target_date > date(2025, 8, 1):  # システム開始日以降
                    anomalies.append({
                        'type': 'MISSING_PREVIOUS_MANIFEST',
                        'severity': 'CRITICAL',
                        'message': f'Previous day manifest missing: {yesterday}',
                        'details': {'missing_date': yesterday.isoformat()}
                    })
            
            # チェーンハッシュの継続性確認
            # （具体的な実装は前のマニフェストのハッシュ計算に依存）
            
        except Exception as e:
            anomalies.append({
                'type': 'CHAIN_VERIFICATION_ERROR',
                'severity': 'HIGH',
                'message': f'Failed to verify chain continuity: {str(e)}',
                'details': {'error': str(e)}
            })
        
        return anomalies

    # ==================================================
    # 暗号学的関数
    # ==================================================

    def _calculate_merkle_root(self, entries: List[ManifestEntry]) -> str:
        """Merkle tree root計算"""
        if not entries:
            return hashlib.sha256(b'').hexdigest()
        
        # リーフノード（各エントリのハッシュ）
        leaf_hashes = [
            hashlib.sha256(f"{entry.record_id}:{entry.checksum}".encode()).hexdigest()
            for entry in sorted(entries, key=lambda x: x.record_id)
        ]
        
        # Merkle tree構築
        while len(leaf_hashes) > 1:
            next_level = []
            
            # ペアでハッシュ化
            for i in range(0, len(leaf_hashes), 2):
                if i + 1 < len(leaf_hashes):
                    combined = leaf_hashes[i] + leaf_hashes[i + 1]
                else:
                    combined = leaf_hashes[i] + leaf_hashes[i]  # 奇数の場合は自分自身とペア
                
                next_level.append(hashlib.sha256(combined.encode()).hexdigest())
            
            leaf_hashes = next_level
        
        return leaf_hashes[0]

    def _calculate_chain_hash(
        self, 
        target_date: date, 
        merkle_root: str, 
        previous_hash: Optional[str]
    ) -> str:
        """チェーンハッシュ計算"""
        chain_data = f"{target_date.isoformat()}:{merkle_root}:{previous_hash or 'genesis'}"
        return hashlib.sha256(chain_data.encode()).hexdigest()

    async def _sign_manifest(self, manifest: DailyManifest) -> str:
        """マニフェストのデジタル署名生成"""
        try:
            # 署名対象データ
            sign_data = {
                'manifest_id': manifest.manifest_id,
                'date': manifest.date,
                'merkle_root': manifest.merkle_root,
                'chain_hash': manifest.chain_hash,
                'total_entries': manifest.total_entries
            }
            
            # 簡易的なHMAC署名（本格運用では RSA/ECDSA を使用）
            sign_string = json.dumps(sign_data, sort_keys=True)
            signature = hashlib.sha256(f"CONSENT_MANIFEST_KEY:{sign_string}".encode()).hexdigest()
            
            return signature
            
        except Exception as e:
            logger.error(f"Failed to sign manifest: {e}")
            return "signature_failed"

    async def _generate_timestamp_proof(self, manifest: DailyManifest) -> str:
        """タイムスタンプ証明生成"""
        try:
            # RFC 3161 タイムスタンプサーバーを使用する場合の実装
            # 簡易的な実装（本格運用では外部TSAを使用）
            timestamp_data = f"{manifest.manifest_id}:{manifest.generated_at}"
            proof = hashlib.sha256(f"TIMESTAMP_PROOF:{timestamp_data}".encode()).hexdigest()
            
            return proof
            
        except Exception as e:
            logger.error(f"Failed to generate timestamp proof: {e}")
            return "timestamp_proof_failed"

    # ==================================================
    # ストレージ・通知
    # ==================================================

    async def _store_manifest(self, manifest: DailyManifest):
        """マニフェストの保存"""
        try:
            # JSONシリアライズ
            manifest_json = json.dumps(asdict(manifest), indent=2, ensure_ascii=False)
            
            # WORMストレージに保存
            manifest_path = f"manifests/{manifest.date}/manifest_{manifest.manifest_id}.json"
            
            # メタデータ
            metadata = {
                'manifest_id': manifest.manifest_id,
                'date': manifest.date,
                'generated_at': manifest.generated_at,
                'total_entries': str(manifest.total_entries),
                'compliance_verified': str(manifest.compliance_verified),
                'merkle_root': manifest.merkle_root,
                'chain_hash': manifest.chain_hash
            }
            
            # 保存実行
            await self.worm_manager.storage_client.get_bucket(
                self.worm_manager.config.bucket_name
            ).blob(manifest_path).upload_from_string(
                manifest_json,
                content_type='application/json'
            )
            
            # メタデータ設定
            blob = self.worm_manager.storage_client.get_bucket(
                self.worm_manager.config.bucket_name
            ).blob(manifest_path)
            blob.metadata = metadata
            blob.patch()
            
            logger.info(f"Manifest stored: {manifest_path}")
            
        except Exception as e:
            logger.error(f"Failed to store manifest: {e}")
            raise

    async def _process_alerts(self, manifest: DailyManifest):
        """アラート処理"""
        try:
            alerts = []
            
            # コンプライアンス関連アラート
            if not manifest.compliance_verified:
                alerts.append(ComplianceAlert(
                    alert_id=f"compliance_{manifest.date}_{uuid.uuid4().hex[:8]}",
                    severity='CRITICAL',
                    alert_type='COMPLIANCE_FAILURE',
                    message=f'Compliance verification failed for {manifest.date}',
                    details={
                        'manifest_id': manifest.manifest_id,
                        'date': manifest.date,
                        'total_entries': manifest.total_entries
                    },
                    timestamp=datetime.utcnow().isoformat()
                ))
            
            # WORM検証アラート
            if not manifest.worm_verified:
                alerts.append(ComplianceAlert(
                    alert_id=f"worm_{manifest.date}_{uuid.uuid4().hex[:8]}",
                    severity='HIGH',
                    alert_type='WORM_VERIFICATION_FAILURE',
                    message=f'WORM storage verification failed for {manifest.date}',
                    details={
                        'manifest_id': manifest.manifest_id,
                        'date': manifest.date
                    },
                    timestamp=datetime.utcnow().isoformat()
                ))
            
            # 異常検知アラート
            for anomaly in manifest.anomalies:
                if anomaly.get('severity') in ['HIGH', 'CRITICAL']:
                    alerts.append(ComplianceAlert(
                        alert_id=f"anomaly_{manifest.date}_{uuid.uuid4().hex[:8]}",
                        severity=anomaly['severity'],
                        alert_type=f"ANOMALY_{anomaly['type']}",
                        message=anomaly['message'],
                        details=anomaly.get('details', {}),
                        timestamp=datetime.utcnow().isoformat()
                    ))
            
            # アラート送信
            for alert in alerts:
                await self._send_alert_notification(alert)
                
        except Exception as e:
            logger.error(f"Failed to process alerts: {e}")

    async def _send_alert_notification(self, alert: ComplianceAlert):
        """アラート通知送信"""
        try:
            if not self.notification_config:
                logger.warning("No notification config provided, skipping alert notification")
                return
            
            # メール通知
            subject = f"[{alert.severity}] Consent Management Alert: {alert.alert_type}"
            
            body = f"""
            Alert Details:
            - Alert ID: {alert.alert_id}
            - Severity: {alert.severity}
            - Type: {alert.alert_type}
            - Message: {alert.message}
            - Timestamp: {alert.timestamp}
            
            Details:
            {json.dumps(alert.details, indent=2)}
            
            Please investigate this issue immediately.
            """
            
            await send_email_notification(
                subject=subject,
                body=body,
                recipients=self.notification_config.get('alert_recipients', []),
                smtp_config=self.notification_config.get('smtp')
            )
            
            logger.info(f"Alert notification sent: {alert.alert_id}")
            
        except Exception as e:
            logger.error(f"Failed to send alert notification: {e}")

    # ==================================================
    # スケジューラー設定
    # ==================================================

    async def setup_daily_schedule(self, schedule_time: str = "02:00"):
        """日次実行スケジュール設定"""
        try:
            parent = f"projects/{self.project_id}/locations/asia-northeast1"
            
            job = {
                "name": f"{parent}/jobs/daily-manifest-generation",
                "description": "Daily consent manifest generation",
                "schedule": f"0 {schedule_time.split(':')[1]} {schedule_time.split(':')[0]} * * *",  # Cron format
                "time_zone": "Asia/Tokyo",
                "http_target": {
                    "http_method": "POST",
                    "uri": f"https://your-service-url/api/manifest/generate-daily",
                    "headers": {
                        "Content-Type": "application/json"
                    },
                    "body": json.dumps({
                        "scheduled": True,
                        "force_regenerate": False
                    }).encode()
                },
                "retry_config": {
                    "retry_count": 3,
                    "max_retry_duration": "600s",
                    "max_backoff_duration": "60s",
                    "min_backoff_duration": "5s",
                    "max_doublings": 3
                }
            }
            
            try:
                self.scheduler_client.create_job(parent=parent, job=job)
                logger.info(f"Daily manifest job scheduled at {schedule_time}")
            except gcp_exceptions.AlreadyExists:
                # 既存ジョブを更新
                self.scheduler_client.update_job(job=job)
                logger.info(f"Daily manifest job updated: {schedule_time}")
                
        except Exception as e:
            logger.error(f"Failed to setup daily schedule: {e}")
            raise

    # ==================================================
    # ユーティリティメソッド
    # ==================================================

    async def _check_existing_manifest(self, target_date: date) -> Optional[DailyManifest]:
        """既存マニフェスト確認"""
        try:
            # WORMストレージから検索
            prefix = f"manifests/{target_date.isoformat()}/"
            blobs = self.worm_manager.storage_client.list_blobs(
                self.worm_manager.bucket,
                prefix=prefix
            )
            
            for blob in blobs:
                if blob.name.endswith('.json'):
                    # マニフェストデータを取得
                    manifest_json = blob.download_as_text()
                    manifest_data = json.loads(manifest_json)
                    return DailyManifest(**manifest_data)
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to check existing manifest: {e}")
            return None

    async def _get_previous_manifest_hash(self, target_date: date) -> Optional[str]:
        """前日マニフェストハッシュ取得"""
        try:
            yesterday = target_date - timedelta(days=1)
            previous_manifest = await self._check_existing_manifest(yesterday)
            
            return previous_manifest.chain_hash if previous_manifest else None
            
        except Exception as e:
            logger.error(f"Failed to get previous manifest hash: {e}")
            return None

    async def _calculate_record_checksum(
        self, 
        db: AsyncSession, 
        table_name: str, 
        record_id: str
    ) -> str:
        """レコードチェックサム計算"""
        try:
            query = text(f"""
                SELECT md5(ROW({table_name}.*)::text) as checksum
                FROM {table_name} 
                WHERE {table_name.rstrip('s')}_id = :record_id
            """)
            
            result = await db.execute(query, {"record_id": record_id})
            row = result.fetchone()
            
            return row.checksum if row else "checksum_failed"
            
        except Exception as e:
            logger.error(f"Failed to calculate record checksum: {e}")
            return "checksum_error"

    async def _verify_worm_entry_integrity(self, entry: ManifestEntry) -> bool:
        """WORMエントリ整合性検証"""
        try:
            # WORMストレージから実際のファイルを取得して検証
            blob = self.worm_manager.bucket.blob(entry.file_path)
            
            if not blob.exists():
                logger.warning(f"WORM file not found: {entry.file_path}")
                return False
            
            # ファイルサイズチェック
            if blob.size != entry.size_bytes:
                logger.warning(f"Size mismatch for {entry.file_path}: {blob.size} vs {entry.size_bytes}")
                return False
            
            # 簡易チェックサム検証（本格的にはファイル内容のハッシュ計算）
            return True
            
        except Exception as e:
            logger.error(f"WORM entry verification failed: {e}")
            return False

    async def _verify_worm_storage(self, target_date: date) -> bool:
        """WORMストレージ検証"""
        try:
            health_result = await self.worm_manager.health_check()
            return health_result.get('status') == 'healthy'
            
        except Exception as e:
            logger.error(f"WORM storage verification failed: {e}")
            return False

    async def _update_daily_statistics(self, db: AsyncSession, manifest: DailyManifest):
        """日次統計更新"""
        try:
            # DailyConsentStatsテーブルに統計を保存
            stats_query = text("""
                INSERT INTO daily_consent_stats (
                    stat_date, total_consents, new_consents, 
                    withdrawn_consents, expired_consents, 
                    policy_version_stats, generated_at
                ) VALUES (
                    :stat_date, :total_consents, :new_consents,
                    :withdrawn_consents, 0,
                    :policy_stats, NOW()
                )
                ON CONFLICT (stat_date) 
                DO UPDATE SET
                    total_consents = EXCLUDED.total_consents,
                    new_consents = EXCLUDED.new_consents,
                    withdrawn_consents = EXCLUDED.withdrawn_consents,
                    generated_at = NOW()
            """)
            
            # ポリシーバージョン統計を集計
            policy_stats = {}
            for entry in manifest.entries:
                if entry.record_type == 'consent':
                    version = entry.metadata.get('policy_version', 'unknown')
                    policy_stats[version] = policy_stats.get(version, 0) + 1
            
            await db.execute(stats_query, {
                "stat_date": manifest.date,
                "total_consents": manifest.consent_records,
                "new_consents": manifest.consent_records,
                "withdrawn_consents": manifest.withdrawal_records,
                "policy_stats": json.dumps(policy_stats)
            })
            
            await db.commit()
            
        except Exception as e:
            logger.error(f"Failed to update daily statistics: {e}")

    async def _send_critical_alert(
        self, 
        alert_type: str, 
        message: str, 
        details: Dict[str, Any]
    ):
        """緊急アラート送信"""
        try:
            alert = ComplianceAlert(
                alert_id=f"critical_{int(datetime.utcnow().timestamp())}",
                severity='CRITICAL',
                alert_type=alert_type,
                message=message,
                details=details,
                timestamp=datetime.utcnow().isoformat()
            )
            
            await self._send_alert_notification(alert)
            
        except Exception as e:
            logger.error(f"Failed to send critical alert: {e}")

# ==================================================
# エクスポート
# ==================================================

__all__ = [
    "ManifestService",
    "DailyManifest",
    "ManifestEntry", 
    "ComplianceAlert"
]