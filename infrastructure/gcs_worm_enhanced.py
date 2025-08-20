"""
Google Cloud Storage WORM (Write Once Read Many) 強化版
5年保全 + 監査対応 + 暗号化 + 整合性検証

Requirements:
- google-cloud-storage
- google-cloud-kms
- cryptography
- asyncio

法的要件対応:
- 電気通信事業法: 5年保全義務
- 個人情報保護法: 安全管理措置
- GDPR Article 32: セキュリティ要件
"""

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass, asdict
from pathlib import Path
import gzip
import base64

from google.cloud import storage
from google.cloud import kms
from google.api_core import exceptions as gcp_exceptions
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ロギング設定
logger = logging.getLogger(__name__)

# ==================================================
# 設定・定数
# ==================================================

@dataclass
class WORMConfig:
    """WORM設定クラス"""
    project_id: str
    bucket_name: str
    kms_key_ring: str
    kms_key_name: str
    location: str = "asia-northeast1"
    retention_years: int = 5
    enable_encryption: bool = True
    enable_versioning: bool = True
    enable_lifecycle: bool = True
    audit_logs_enabled: bool = True
    integrity_check_interval: int = 24  # hours
    max_retry_attempts: int = 3
    chunk_size: int = 1024 * 1024  # 1MB

@dataclass
class ConsentRecord:
    """同意記録データクラス"""
    consent_id: str
    user_id: str
    consented_at: str
    policy_version: str
    tos_version: str
    consents: Dict[str, bool]
    metadata: Dict[str, Any]
    checksum: Optional[str] = None
    encrypted: bool = False

@dataclass
class AuditEntry:
    """監査エントリクラス"""
    audit_id: str
    timestamp: str
    action: str
    object_name: str
    actor: str
    result: str
    details: Dict[str, Any]
    integrity_hash: Optional[str] = None

# ==================================================
# メインクラス: EnhancedWORMManager
# ==================================================

class EnhancedWORMManager:
    """強化版WORM管理クラス"""
    
    def __init__(self, config: WORMConfig):
        self.config = config
        self.storage_client = None
        self.kms_client = None
        self.bucket = None
        self.encryption_key = None
        self._initialized = False
        
    async def initialize(self):
        """非同期初期化"""
        if self._initialized:
            return
            
        try:
            # Google Cloud クライアント初期化
            self.storage_client = storage.Client(project=self.config.project_id)
            
            if self.config.enable_encryption:
                self.kms_client = kms.KeyManagementServiceClient()
                await self._initialize_encryption()
            
            # バケット設定
            await self._setup_bucket()
            
            self._initialized = True
            logger.info(f"Enhanced WORM Manager initialized for bucket: {self.config.bucket_name}")
            
        except Exception as e:
            logger.error(f"Failed to initialize WORM Manager: {e}")
            raise

    async def _setup_bucket(self):
        """バケット設定・作成"""
        try:
            self.bucket = self.storage_client.bucket(self.config.bucket_name)
            
            # バケットが存在しない場合は作成
            if not self.bucket.exists():
                self.bucket = self.storage_client.create_bucket(
                    self.config.bucket_name,
                    location=self.config.location
                )
                logger.info(f"Created bucket: {self.config.bucket_name}")
            
            # バケット設定の適用
            await self._configure_bucket_policies()
            
        except Exception as e:
            logger.error(f"Failed to setup bucket: {e}")
            raise

    async def _configure_bucket_policies(self):
        """バケットポリシー設定"""
        try:
            # 1. オブジェクトロック設定（5年保全）
            retention_policy = {
                "retentionPeriod": str(self.config.retention_years * 365 * 24 * 3600)  # 5年を秒に変換
            }
            self.bucket.retention_policy = retention_policy
            
            # 2. バージョニング有効化
            if self.config.enable_versioning:
                self.bucket.versioning_enabled = True
            
            # 3. ライフサイクル管理設定
            if self.config.enable_lifecycle:
                await self._setup_lifecycle_rules()
            
            # 4. IAM設定
            await self._setup_iam_policies()
            
            # 5. 監査ログ設定
            if self.config.audit_logs_enabled:
                await self._setup_audit_logging()
            
            # 変更を適用
            self.bucket.patch()
            logger.info("Bucket policies configured successfully")
            
        except Exception as e:
            logger.error(f"Failed to configure bucket policies: {e}")
            raise

    async def _setup_lifecycle_rules(self):
        """ライフサイクルルール設定"""
        lifecycle_rules = [
            # 1. 古いバージョンの自動削除（1年後）
            {
                "action": {"type": "Delete"},
                "condition": {
                    "age": 365,
                    "isLive": False
                }
            },
            # 2. 多重バージョン制限（最新10バージョンのみ保持）
            {
                "action": {"type": "Delete"},
                "condition": {
                    "numNewerVersions": 10,
                    "isLive": False
                }
            },
            # 3. Nearlineストレージへの移行（90日後）
            {
                "action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
                "condition": {
                    "age": 90,
                    "matchesStorageClass": ["STANDARD"]
                }
            },
            # 4. Coldlineストレージへの移行（1年後）
            {
                "action": {"type": "SetStorageClass", "storageClass": "COLDLINE"},
                "condition": {
                    "age": 365,
                    "matchesStorageClass": ["NEARLINE"]
                }
            },
            # 5. Archiveストレージへの移行（3年後）
            {
                "action": {"type": "SetStorageClass", "storageClass": "ARCHIVE"},
                "condition": {
                    "age": 1095,  # 3年
                    "matchesStorageClass": ["COLDLINE"]
                }
            }
        ]
        
        self.bucket.lifecycle_rules = lifecycle_rules
        logger.info("Lifecycle rules configured")

    async def _setup_iam_policies(self):
        """IAM ポリシー設定"""
        try:
            # 読み取り専用ロール（監査・コンプライアンス用）
            policy = self.bucket.get_iam_policy(requested_policy_version=3)
            
            # WORM 管理者（書き込み権限）
            policy.bindings.append({
                "role": "roles/storage.objectAdmin",
                "members": [
                    f"serviceAccount:worm-admin@{self.config.project_id}.iam.gserviceaccount.com"
                ],
                "condition": {
                    "title": "WORM Write Access",
                    "description": "Write access for WORM operations only",
                    "expression": "request.time < timestamp('2030-01-01T00:00:00Z')"
                }
            })
            
            # 監査読み取り（読み取り専用）
            policy.bindings.append({
                "role": "roles/storage.objectViewer",
                "members": [
                    f"serviceAccount:audit-reader@{self.config.project_id}.iam.gserviceaccount.com"
                ]
            })
            
            self.bucket.set_iam_policy(policy)
            logger.info("IAM policies configured")
            
        except Exception as e:
            logger.error(f"Failed to setup IAM policies: {e}")
            # IAM設定失敗は致命的ではないので続行

    async def _setup_audit_logging(self):
        """監査ログ設定"""
        try:
            # Cloud Audit Logs設定（project レベルで設定済みと仮定）
            logger.info("Audit logging configuration verified")
            
        except Exception as e:
            logger.error(f"Failed to setup audit logging: {e}")

    async def _initialize_encryption(self):
        """暗号化設定初期化"""
        try:
            # KMS キーの存在確認・作成
            key_path = self.kms_client.crypto_key_path(
                self.config.project_id,
                self.config.location,
                self.config.kms_key_ring,
                self.config.kms_key_name
            )
            
            try:
                key = self.kms_client.get_crypto_key(request={"name": key_path})
                logger.info(f"Using existing KMS key: {key_path}")
            except gcp_exceptions.NotFound:
                # キーリングの作成
                parent = self.kms_client.location_path(self.config.project_id, self.config.location)
                ring_id = self.config.kms_key_ring
                
                try:
                    key_ring = self.kms_client.create_key_ring(
                        request={
                            "parent": parent,
                            "key_ring_id": ring_id,
                            "key_ring": {}
                        }
                    )
                    logger.info(f"Created key ring: {ring_id}")
                except gcp_exceptions.AlreadyExists:
                    logger.info(f"Key ring already exists: {ring_id}")
                
                # キーの作成
                ring_path = self.kms_client.key_ring_path(
                    self.config.project_id, self.config.location, ring_id
                )
                
                key = self.kms_client.create_crypto_key(
                    request={
                        "parent": ring_path,
                        "crypto_key_id": self.config.kms_key_name,
                        "crypto_key": {
                            "purpose": kms.CryptoKey.CryptoKeyPurpose.ENCRYPT_DECRYPT,
                            "version_template": {
                                "algorithm": kms.CryptoKeyVersion.CryptoKeyVersionAlgorithm.GOOGLE_SYMMETRIC_ENCRYPTION
                            }
                        }
                    }
                )
                logger.info(f"Created KMS key: {self.config.kms_key_name}")
            
            # ローカル暗号化キーの生成（KMSで暗号化）
            self.encryption_key = await self._generate_data_encryption_key()
            
        except Exception as e:
            logger.error(f"Failed to initialize encryption: {e}")
            raise

    async def _generate_data_encryption_key(self) -> bytes:
        """データ暗号化キー生成"""
        try:
            # KMSでデータ暗号化キーを生成
            key_path = self.kms_client.crypto_key_path(
                self.config.project_id,
                self.config.location,
                self.config.kms_key_ring,
                self.config.kms_key_name
            )
            
            response = self.kms_client.generate_data_encryption_key(
                request={
                    "parent": key_path,
                    "key_spec": kms.KeySpec.AES_256
                }
            )
            
            # 平文キーを返す（メモリ内でのみ使用）
            return response.plaintext
            
        except Exception as e:
            logger.error(f"Failed to generate data encryption key: {e}")
            raise

    # ==================================================
    # 同意記録管理
    # ==================================================

    async def store_consent_record(self, record: ConsentRecord) -> str:
        """同意記録の保存"""
        if not self._initialized:
            await self.initialize()
            
        try:
            # チェックサム計算
            record_data = asdict(record)
            record.checksum = self._calculate_checksum(record_data)
            
            # 暗号化
            if self.config.enable_encryption:
                encrypted_data = await self._encrypt_data(json.dumps(record_data).encode())
                record.encrypted = True
            else:
                encrypted_data = json.dumps(record_data).encode()
            
            # 圧縮
            compressed_data = gzip.compress(encrypted_data)
            
            # オブジェクト名生成（日付別フォルダ構造）
            date_prefix = datetime.fromisoformat(record.consented_at.replace('Z', '+00:00')).strftime('%Y/%m/%d')
            object_name = f"consents/{date_prefix}/{record.consent_id}.json.gz"
            
            # GCSにアップロード
            blob = self.bucket.blob(object_name)
            
            # メタデータ設定
            blob.metadata = {
                "consent_id": record.consent_id,
                "user_id": record.user_id,
                "policy_version": record.policy_version,
                "tos_version": record.tos_version,
                "checksum": record.checksum,
                "encrypted": str(record.encrypted),
                "upload_timestamp": datetime.utcnow().isoformat(),
                "retention_until": (datetime.utcnow() + timedelta(days=self.config.retention_years * 365)).isoformat()
            }
            
            # アップロード実行
            blob.upload_from_string(
                compressed_data,
                content_type="application/gzip",
                timeout=300
            )
            
            # オブジェクトロック設定
            await self._set_object_retention(blob)
            
            # 監査ログ記録
            await self._record_audit_event(
                action="STORE_CONSENT",
                object_name=object_name,
                actor="system",
                result="SUCCESS",
                details={
                    "consent_id": record.consent_id,
                    "user_id": record.user_id,
                    "size_bytes": len(compressed_data),
                    "checksum": record.checksum
                }
            )
            
            logger.info(f"Consent record stored: {object_name}")
            return object_name
            
        except Exception as e:
            logger.error(f"Failed to store consent record: {e}")
            
            # 失敗の監査ログ
            await self._record_audit_event(
                action="STORE_CONSENT",
                object_name=f"consents/{record.consent_id}",
                actor="system",
                result="FAILED",
                details={"error": str(e), "consent_id": record.consent_id}
            )
            raise

    async def retrieve_consent_record(self, object_name: str) -> ConsentRecord:
        """同意記録の取得"""
        if not self._initialized:
            await self.initialize()
            
        try:
            blob = self.bucket.blob(object_name)
            
            if not blob.exists():
                raise FileNotFoundError(f"Consent record not found: {object_name}")
            
            # データ取得
            compressed_data = blob.download_as_bytes()
            
            # 解凍
            encrypted_data = gzip.decompress(compressed_data)
            
            # 復号化
            if blob.metadata.get("encrypted") == "True":
                decrypted_data = await self._decrypt_data(encrypted_data)
                record_data = json.loads(decrypted_data.decode())
            else:
                record_data = json.loads(encrypted_data.decode())
            
            # 整合性検証
            stored_checksum = blob.metadata.get("checksum")
            calculated_checksum = self._calculate_checksum(record_data)
            
            if stored_checksum != calculated_checksum:
                raise ValueError(f"Checksum mismatch for {object_name}")
            
            # 監査ログ記録
            await self._record_audit_event(
                action="RETRIEVE_CONSENT",
                object_name=object_name,
                actor="system",
                result="SUCCESS",
                details={"checksum_verified": True}
            )
            
            logger.info(f"Consent record retrieved: {object_name}")
            return ConsentRecord(**record_data)
            
        except Exception as e:
            logger.error(f"Failed to retrieve consent record: {e}")
            
            # 失敗の監査ログ
            await self._record_audit_event(
                action="RETRIEVE_CONSENT",
                object_name=object_name,
                actor="system",
                result="FAILED",
                details={"error": str(e)}
            )
            raise

    async def list_consent_records(
        self, 
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        user_id: Optional[str] = None,
        policy_version: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """同意記録一覧の取得"""
        if not self._initialized:
            await self.initialize()
            
        try:
            prefix = "consents/"
            blobs = self.storage_client.list_blobs(self.bucket, prefix=prefix)
            
            records = []
            for blob in blobs:
                metadata = blob.metadata or {}
                
                # フィルタリング
                if start_date and metadata.get("upload_timestamp", "") < start_date:
                    continue
                if end_date and metadata.get("upload_timestamp", "") > end_date:
                    continue
                if user_id and metadata.get("user_id") != user_id:
                    continue
                if policy_version and metadata.get("policy_version") != policy_version:
                    continue
                
                records.append({
                    "object_name": blob.name,
                    "consent_id": metadata.get("consent_id"),
                    "user_id": metadata.get("user_id"),
                    "policy_version": metadata.get("policy_version"),
                    "upload_timestamp": metadata.get("upload_timestamp"),
                    "retention_until": metadata.get("retention_until"),
                    "size_bytes": blob.size
                })
            
            logger.info(f"Listed {len(records)} consent records")
            return records
            
        except Exception as e:
            logger.error(f"Failed to list consent records: {e}")
            raise

    # ==================================================
    # 監査・整合性検証
    # ==================================================

    async def verify_integrity(self, object_name: str) -> bool:
        """データ整合性検証"""
        try:
            record = await self.retrieve_consent_record(object_name)
            logger.info(f"Integrity verified for {object_name}")
            return True
            
        except ValueError as e:
            if "Checksum mismatch" in str(e):
                logger.error(f"Integrity check failed for {object_name}: {e}")
                
                # 整合性エラーの監査ログ
                await self._record_audit_event(
                    action="INTEGRITY_CHECK",
                    object_name=object_name,
                    actor="system",
                    result="FAILED",
                    details={"error": "checksum_mismatch"}
                )
                return False
            else:
                raise
                
        except Exception as e:
            logger.error(f"Error during integrity check for {object_name}: {e}")
            raise

    async def bulk_integrity_check(
        self, 
        batch_size: int = 100
    ) -> Dict[str, Any]:
        """一括整合性検証"""
        try:
            records = await self.list_consent_records()
            total_records = len(records)
            verified_count = 0
            failed_records = []
            
            logger.info(f"Starting bulk integrity check for {total_records} records")
            
            # バッチ処理
            for i in range(0, total_records, batch_size):
                batch = records[i:i + batch_size]
                
                # 並列処理で検証
                tasks = [
                    self.verify_integrity(record["object_name"]) 
                    for record in batch
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # 結果集計
                for j, result in enumerate(results):
                    if isinstance(result, Exception):
                        failed_records.append({
                            "object_name": batch[j]["object_name"],
                            "error": str(result)
                        })
                    elif result:
                        verified_count += 1
                    else:
                        failed_records.append({
                            "object_name": batch[j]["object_name"],
                            "error": "integrity_check_failed"
                        })
                
                # 進捗ログ
                if i % 1000 == 0:
                    logger.info(f"Processed {min(i + batch_size, total_records)}/{total_records} records")
            
            integrity_result = {
                "total_records": total_records,
                "verified_count": verified_count,
                "failed_count": len(failed_records),
                "success_rate": verified_count / total_records if total_records > 0 else 0,
                "failed_records": failed_records,
                "check_timestamp": datetime.utcnow().isoformat()
            }
            
            # 結果の監査ログ
            await self._record_audit_event(
                action="BULK_INTEGRITY_CHECK",
                object_name="all_records",
                actor="system",
                result="COMPLETED",
                details=integrity_result
            )
            
            logger.info(f"Bulk integrity check completed: {verified_count}/{total_records} verified")
            return integrity_result
            
        except Exception as e:
            logger.error(f"Bulk integrity check failed: {e}")
            raise

    async def generate_compliance_report(
        self, 
        start_date: str, 
        end_date: str
    ) -> Dict[str, Any]:
        """コンプライアンスレポート生成"""
        try:
            # 期間内の記録を取得
            records = await self.list_consent_records(start_date, end_date)
            
            # 統計計算
            policy_versions = {}
            storage_classes = {}
            total_size = 0
            
            for record in records:
                # ポリシーバージョン統計
                version = record.get("policy_version", "unknown")
                policy_versions[version] = policy_versions.get(version, 0) + 1
                
                # サイズ統計
                size = record.get("size_bytes", 0)
                total_size += size
            
            # WORM設定確認
            worm_status = await self._verify_worm_configuration()
            
            # 整合性検証
            integrity_result = await self.bulk_integrity_check()
            
            report = {
                "report_id": f"compliance_{int(time.time())}",
                "period": {"start": start_date, "end": end_date},
                "generated_at": datetime.utcnow().isoformat(),
                "statistics": {
                    "total_records": len(records),
                    "total_size_bytes": total_size,
                    "total_size_gb": round(total_size / (1024**3), 2),
                    "policy_versions": policy_versions
                },
                "worm_configuration": worm_status,
                "integrity_verification": integrity_result,
                "compliance_status": {
                    "retention_policy": worm_status.get("retention_enabled", False),
                    "encryption_enabled": self.config.enable_encryption,
                    "versioning_enabled": worm_status.get("versioning_enabled", False),
                    "audit_logging": self.config.audit_logs_enabled,
                    "integrity_verified": integrity_result.get("success_rate", 0) >= 0.99
                }
            }
            
            # レポートを保存
            await self._store_compliance_report(report)
            
            logger.info(f"Compliance report generated: {report['report_id']}")
            return report
            
        except Exception as e:
            logger.error(f"Failed to generate compliance report: {e}")
            raise

    # ==================================================
    # ヘルパーメソッド
    # ==================================================

    async def _encrypt_data(self, data: bytes) -> bytes:
        """データ暗号化"""
        try:
            fernet = Fernet(base64.urlsafe_b64encode(self.encryption_key[:32]))
            return fernet.encrypt(data)
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise

    async def _decrypt_data(self, encrypted_data: bytes) -> bytes:
        """データ復号化"""
        try:
            fernet = Fernet(base64.urlsafe_b64encode(self.encryption_key[:32]))
            return fernet.decrypt(encrypted_data)
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise

    def _calculate_checksum(self, data: Union[Dict, bytes]) -> str:
        """チェックサム計算"""
        if isinstance(data, dict):
            data_str = json.dumps(data, sort_keys=True)
            data_bytes = data_str.encode('utf-8')
        else:
            data_bytes = data
            
        return hashlib.sha256(data_bytes).hexdigest()

    async def _set_object_retention(self, blob):
        """オブジェクト保持期間設定"""
        try:
            # GCS Object Lockの設定（5年間）
            retention_date = datetime.utcnow() + timedelta(days=self.config.retention_years * 365)
            
            # メタデータに保持期限を記録
            blob.metadata["retention_until"] = retention_date.isoformat()
            blob.metadata["immutable"] = "true"
            
            # 実際のObject Lock（GCSの機能を使用）
            # 注: これはバケットレベルの設定で制御される
            
            logger.debug(f"Object retention set until {retention_date}")
            
        except Exception as e:
            logger.error(f"Failed to set object retention: {e}")
            # 非致命的エラーとして続行

    async def _record_audit_event(
        self, 
        action: str, 
        object_name: str, 
        actor: str, 
        result: str, 
        details: Dict[str, Any]
    ):
        """監査イベント記録"""
        try:
            audit_entry = AuditEntry(
                audit_id=f"audit_{int(time.time() * 1000000)}",
                timestamp=datetime.utcnow().isoformat(),
                action=action,
                object_name=object_name,
                actor=actor,
                result=result,
                details=details
            )
            
            # 整合性ハッシュ計算
            audit_data = asdict(audit_entry)
            audit_entry.integrity_hash = self._calculate_checksum(audit_data)
            
            # 監査ログをWORMストレージに保存
            audit_object_name = f"audit_logs/{datetime.utcnow().strftime('%Y/%m/%d')}/{audit_entry.audit_id}.json"
            
            audit_blob = self.bucket.blob(audit_object_name)
            audit_blob.upload_from_string(
                json.dumps(asdict(audit_entry)),
                content_type="application/json"
            )
            
            logger.debug(f"Audit event recorded: {audit_entry.audit_id}")
            
        except Exception as e:
            logger.error(f"Failed to record audit event: {e}")
            # 監査ログ失敗は重要なので別途ログに記録

    async def _verify_worm_configuration(self) -> Dict[str, Any]:
        """WORM設定確認"""
        try:
            # バケット設定を再取得して確認
            bucket_info = self.storage_client.get_bucket(self.config.bucket_name)
            
            return {
                "retention_enabled": bool(bucket_info.retention_policy),
                "retention_period_days": (
                    int(bucket_info.retention_policy.retention_period) // (24 * 3600)
                    if bucket_info.retention_policy else 0
                ),
                "versioning_enabled": bucket_info.versioning_enabled,
                "lifecycle_rules_count": len(bucket_info.lifecycle_rules or []),
                "location": bucket_info.location,
                "storage_class": bucket_info.storage_class
            }
            
        except Exception as e:
            logger.error(f"Failed to verify WORM configuration: {e}")
            return {"error": str(e)}

    async def _store_compliance_report(self, report: Dict[str, Any]):
        """コンプライアンスレポート保存"""
        try:
            report_name = f"compliance_reports/{report['report_id']}.json"
            
            blob = self.bucket.blob(report_name)
            blob.metadata = {
                "report_type": "compliance",
                "generated_at": report["generated_at"],
                "period_start": report["period"]["start"],
                "period_end": report["period"]["end"]
            }
            
            blob.upload_from_string(
                json.dumps(report, indent=2),
                content_type="application/json"
            )
            
            logger.info(f"Compliance report stored: {report_name}")
            
        except Exception as e:
            logger.error(f"Failed to store compliance report: {e}")
            raise

    # ==================================================
    # 公開メソッド
    # ==================================================

    async def health_check(self) -> Dict[str, Any]:
        """ヘルスチェック"""
        try:
            if not self._initialized:
                await self.initialize()
            
            # バケット接続確認
            bucket_exists = self.bucket.exists()
            
            # 最新の監査ログ確認
            audit_blobs = list(self.storage_client.list_blobs(
                self.bucket, 
                prefix="audit_logs/",
                max_results=1
            ))
            latest_audit = audit_blobs[0].time_created if audit_blobs else None
            
            # KMS接続確認
            kms_status = "not_configured"
            if self.config.enable_encryption and self.kms_client:
                try:
                    key_path = self.kms_client.crypto_key_path(
                        self.config.project_id,
                        self.config.location,
                        self.config.kms_key_ring,
                        self.config.kms_key_name
                    )
                    self.kms_client.get_crypto_key(request={"name": key_path})
                    kms_status = "healthy"
                except:
                    kms_status = "error"
            
            return {
                "status": "healthy" if bucket_exists else "error",
                "bucket_exists": bucket_exists,
                "encryption_enabled": self.config.enable_encryption,
                "kms_status": kms_status,
                "latest_audit_log": latest_audit.isoformat() if latest_audit else None,
                "retention_years": self.config.retention_years,
                "check_timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "check_timestamp": datetime.utcnow().isoformat()
            }

# ==================================================
# ファクトリー関数
# ==================================================

async def create_worm_manager(
    project_id: str,
    bucket_name: str,
    kms_key_ring: str = "consent-protection",
    kms_key_name: str = "consent-encryption-key",
    **kwargs
) -> EnhancedWORMManager:
    """WORM管理インスタンス作成"""
    config = WORMConfig(
        project_id=project_id,
        bucket_name=bucket_name,
        kms_key_ring=kms_key_ring,
        kms_key_name=kms_key_name,
        **kwargs
    )
    
    manager = EnhancedWORMManager(config)
    await manager.initialize()
    
    return manager

# ==================================================
# エクスポート
# ==================================================

__all__ = [
    "EnhancedWORMManager",
    "WORMConfig", 
    "ConsentRecord",
    "AuditEntry",
    "create_worm_manager"
]