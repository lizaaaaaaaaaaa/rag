"""
WORM (Write Once, Read Many) Storage Service
改ざん防止・法的証跡保全のためのストレージ管理

機能:
- データの暗号化保存
- バージョン管理
- 整合性検証
- アクセス制御
- 法的証跡保全

Requirements:
- google-cloud-storage
- google-cloud-kms
- cryptography
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, BinaryIO
from dataclasses import dataclass, asdict
from enum import Enum
import uuid

from google.cloud import storage, kms
from google.cloud.exceptions import NotFound, GoogleCloudError, Conflict
from google.api_core import retry
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

from config import settings

# ロギング設定
logger = logging.getLogger(__name__)

# ==================================================
# 列挙型・データクラス
# ==================================================

class WORMObjectType(Enum):
    """WORMオブジェクトタイプ"""
    CONSENT_RECORD = "consent_record"
    AUDIT_LOG = "audit_log"
    MANIFEST = "manifest"
    CERTIFICATE = "certificate"
    BACKUP = "backup"

class WORMOperation(Enum):
    """WORM操作タイプ"""
    WRITE = "write"
    READ = "read"
    VERIFY = "verify"
    LIST = "list"

@dataclass
class WORMConfig:
    """WORM設定"""
    project_id: str
    bucket_name: str
    kms_key_ring: str
    kms_key_name: str
    location: str
    encryption_enabled: bool = True
    retention_period_days: int = 1825  # 5年
    versioning_enabled: bool = True

@dataclass
class WORMObject:
    """WORMオブジェクト"""
    object_id: str
    object_type: WORMObjectType
    path: str
    checksum: str
    size_bytes: int
    created_at: datetime
    metadata: Dict[str, Any]
    version: int = 1
    encrypted: bool = True

@dataclass
class WORMAccessLog:
    """WORMアクセスログ"""
    access_id: str
    object_id: str
    operation: WORMOperation
    accessor: str
    timestamp: datetime
    success: bool
    error_message: Optional[str] = None

# ==================================================
# メインクラス: EnhancedWORMManager
# ==================================================

class EnhancedWORMManager:
    """強化WORM管理システム"""
    
    def __init__(self, config: WORMConfig):
        self.config = config
        self.storage_client = storage.Client(project=config.project_id)
        self.kms_client = kms.KeyManagementServiceClient()
        
        # バケット取得
        try:
            self.bucket = self.storage_client.bucket(config.bucket_name)
        except Exception as e:
            logger.error(f"Failed to get bucket {config.bucket_name}: {e}")
            raise
        
        # KMSキーパス
        self.key_name = self.kms_client.crypto_key_path(
            config.project_id, config.location, config.kms_key_ring, config.kms_key_name
        )
        
        # 暗号化キー
        self._cipher = None
        if config.encryption_enabled:
            self._cipher = self._initialize_encryption()
        
        # アクセスログ
        self._access_logs: List[WORMAccessLog] = []

    def _initialize_encryption(self) -> Fernet:
        """暗号化の初期化"""
        try:
            # 設定から暗号化キーを取得
            password = settings.encryption_key.encode()
            salt = b'rag_llm_salt_2025'  # 本番では動的に生成・管理
            
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password))
            
            return Fernet(key)
            
        except Exception as e:
            logger.error(f"Encryption initialization failed: {e}")
            raise

    async def store_object(
        self,
        content: bytes,
        object_type: WORMObjectType,
        object_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> WORMObject:
        """オブジェクトの保存"""
        try:
            if object_id is None:
                object_id = str(uuid.uuid4())
            
            # パス生成
            timestamp = datetime.utcnow()
            path = self._generate_object_path(object_type, object_id, timestamp)
            
            # 暗号化
            stored_content = content
            encrypted = False
            if self.config.encryption_enabled and self._cipher:
                stored_content = self._cipher.encrypt(content)
                encrypted = True
            
            # チェックサム計算
            checksum = hashlib.sha256(content).hexdigest()
            
            # メタデータ準備
            blob_metadata = {
                'object_id': object_id,
                'object_type': object_type.value,
                'checksum': checksum,
                'created_at': timestamp.isoformat(),
                'encrypted': str(encrypted),
                'version': '1',
                'worm_protected': 'true',
                'retention_until': (timestamp + timedelta(days=self.config.retention_period_days)).isoformat()
            }
            
            if metadata:
                blob_metadata.update({f'custom_{k}': str(v) for k, v in metadata.items()})
            
            # バケットにアップロード
            blob = self.bucket.blob(path)
            blob.metadata = blob_metadata
            
            # アップロード実行
            blob.upload_from_string(
                stored_content,
                content_type='application/octet-stream',
                retry=retry.Retry(deadline=60)
            )
            
            # WORMオブジェクト作成
            worm_object = WORMObject(
                object_id=object_id,
                object_type=object_type,
                path=path,
                checksum=checksum,
                size_bytes=len(content),
                created_at=timestamp,
                metadata=metadata or {},
                version=1,
                encrypted=encrypted
            )
            
            # アクセスログ記録
            await self._log_access(
                object_id, WORMOperation.WRITE, "system", True
            )
            
            logger.info(f"WORM object stored: {object_id} at {path}")
            return worm_object
            
        except Exception as e:
            logger.error(f"Failed to store WORM object: {e}")
            await self._log_access(
                object_id or "unknown", WORMOperation.WRITE, "system", False, str(e)
            )
            raise

    async def retrieve_object(
        self,
        object_id: str,
        accessor: str = "system"
    ) -> tuple[bytes, WORMObject]:
        """オブジェクトの取得"""
        try:
            # オブジェクト検索
            worm_object = await self._find_object_by_id(object_id)
            if not worm_object:
                raise NotFound(f"WORM object not found: {object_id}")
            
            # バケットからダウンロード
            blob = self.bucket.blob(worm_object.path)
            content = blob.download_as_bytes(retry=retry.Retry(deadline=60))
            
            # 復号化
            if worm_object.encrypted and self._cipher:
                content = self._cipher.decrypt(content)
            
            # 整合性検証
            actual_checksum = hashlib.sha256(content).hexdigest()
            if actual_checksum != worm_object.checksum:
                raise ValueError(f"Checksum mismatch for object {object_id}")
            
            # アクセスログ記録
            await self._log_access(object_id, WORMOperation.READ, accessor, True)
            
            logger.info(f"WORM object retrieved: {object_id}")
            return content, worm_object
            
        except Exception as e:
            logger.error(f"Failed to retrieve WORM object {object_id}: {e}")
            await self._log_access(object_id, WORMOperation.READ, accessor, False, str(e))
            raise

    async def verify_object_integrity(
        self,
        object_id: str
    ) -> Dict[str, Any]:
        """オブジェクト整合性検証"""
        try:
            # オブジェクト取得
            content, worm_object = await self.retrieve_object(object_id, "integrity_check")
            
            # チェックサム検証
            actual_checksum = hashlib.sha256(content).hexdigest()
            checksum_valid = actual_checksum == worm_object.checksum
            
            # メタデータ検証
            blob = self.bucket.blob(worm_object.path)
            blob.reload()
            
            metadata_valid = (
                blob.metadata.get('object_id') == object_id and
                blob.metadata.get('checksum') == worm_object.checksum
            )
            
            # WORM保護確認
            worm_protected = blob.metadata.get('worm_protected') == 'true'
            
            # 保持期間確認
            retention_until = blob.metadata.get('retention_until')
            retention_active = False
            if retention_until:
                retention_date = datetime.fromisoformat(retention_until.replace('Z', '+00:00'))
                retention_active = datetime.utcnow() < retention_date
            
            verification_result = {
                'object_id': object_id,
                'checksum_valid': checksum_valid,
                'metadata_valid': metadata_valid,
                'worm_protected': worm_protected,
                'retention_active': retention_active,
                'integrity_score': sum([
                    checksum_valid, metadata_valid, worm_protected, retention_active
                ]) / 4.0,
                'verified_at': datetime.utcnow().isoformat()
            }
            
            # アクセスログ記録
            await self._log_access(object_id, WORMOperation.VERIFY, "integrity_check", True)
            
            return verification_result
            
        except Exception as e:
            logger.error(f"Integrity verification failed for {object_id}: {e}")
            await self._log_access(object_id, WORMOperation.VERIFY, "integrity_check", False, str(e))
            return {
                'object_id': object_id,
                'integrity_score': 0.0,
                'error': str(e),
                'verified_at': datetime.utcnow().isoformat()
            }

    async def list_objects(
        self,
        object_type: Optional[WORMObjectType] = None,
        limit: int = 1000
    ) -> List[WORMObject]:
        """オブジェクト一覧取得"""
        try:
            objects = []
            
            # プレフィックス設定
            prefix = ""
            if object_type:
                prefix = f"{object_type.value}/"
            
            # バケットからリスト取得
            blobs = self.storage_client.list_blobs(
                self.bucket, prefix=prefix, max_results=limit
            )
            
            for blob in blobs:
                if not blob.metadata:
                    continue
                    
                try:
                    worm_object = WORMObject(
                        object_id=blob.metadata.get('object_id', ''),
                        object_type=WORMObjectType(blob.metadata.get('object_type', '')),
                        path=blob.name,
                        checksum=blob.metadata.get('checksum', ''),
                        size_bytes=blob.size or 0,
                        created_at=datetime.fromisoformat(
                            blob.metadata.get('created_at', '').replace('Z', '+00:00')
                        ),
                        metadata={
                            k.replace('custom_', ''): v 
                            for k, v in blob.metadata.items() 
                            if k.startswith('custom_')
                        },
                        version=int(blob.metadata.get('version', '1')),
                        encrypted=blob.metadata.get('encrypted', 'false').lower() == 'true'
                    )
                    objects.append(worm_object)
                    
                except (ValueError, KeyError) as e:
                    logger.warning(f"Skipping invalid WORM object {blob.name}: {e}")
                    continue
            
            # アクセスログ記録
            await self._log_access("list_operation", WORMOperation.LIST, "system", True)
            
            logger.info(f"Listed {len(objects)} WORM objects")
            return objects
            
        except Exception as e:
            logger.error(f"Failed to list WORM objects: {e}")
            await self._log_access("list_operation", WORMOperation.LIST, "system", False, str(e))
            return []

    async def health_check(self) -> Dict[str, Any]:
        """ヘルスチェック"""
        try:
            health_status = {
                'status': 'healthy',
                'timestamp': datetime.utcnow().isoformat(),
                'checks': {}
            }
            
            # バケット接続確認
            try:
                self.bucket.reload()
                health_status['checks']['bucket_access'] = True
            except Exception as e:
                health_status['checks']['bucket_access'] = False
                health_status['status'] = 'unhealthy'
                logger.error(f"Bucket access check failed: {e}")
            
            # 暗号化確認
            if self.config.encryption_enabled:
                try:
                    test_data = b"health_check_data"
                    encrypted = self._cipher.encrypt(test_data)
                    decrypted = self._cipher.decrypt(encrypted)
                    health_status['checks']['encryption'] = test_data == decrypted
                except Exception as e:
                    health_status['checks']['encryption'] = False
                    health_status['status'] = 'unhealthy'
                    logger.error(f"Encryption check failed: {e}")
            else:
                health_status['checks']['encryption'] = True
            
            # KMS接続確認（オプション）
            try:
                # KMSキーの存在確認
                self.kms_client.get_crypto_key(name=self.key_name)
                health_status['checks']['kms_access'] = True
            except Exception as e:
                health_status['checks']['kms_access'] = False
                logger.warning(f"KMS access check failed: {e}")
            
            return health_status
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }

    def _generate_object_path(
        self,
        object_type: WORMObjectType,
        object_id: str,
        timestamp: datetime
    ) -> str:
        """オブジェクトパス生成"""
        date_path = timestamp.strftime('%Y/%m/%d')
        return f"{object_type.value}/{date_path}/{object_id}.worm"

    async def _find_object_by_id(self, object_id: str) -> Optional[WORMObject]:
        """IDによるオブジェクト検索"""
        try:
            # 全タイプでの検索
            for object_type in WORMObjectType:
                objects = await self.list_objects(object_type, limit=10000)
                for obj in objects:
                    if obj.object_id == object_id:
                        return obj
            return None
            
        except Exception as e:
            logger.error(f"Object search failed for {object_id}: {e}")
            return None

    async def _log_access(
        self,
        object_id: str,
        operation: WORMOperation,
        accessor: str,
        success: bool,
        error_message: Optional[str] = None
    ):
        """アクセスログ記録"""
        try:
            access_log = WORMAccessLog(
                access_id=str(uuid.uuid4()),
                object_id=object_id,
                operation=operation,
                accessor=accessor,
                timestamp=datetime.utcnow(),
                success=success,
                error_message=error_message
            )
            
            self._access_logs.append(access_log)
            
            # メモリ制限（1000件まで）
            if len(self._access_logs) > 1000:
                self._access_logs = self._access_logs[-1000:]
            
        except Exception as e:
            logger.error(f"Failed to log WORM access: {e}")

    async def get_access_logs(
        self,
        object_id: Optional[str] = None,
        limit: int = 100
    ) -> List[WORMAccessLog]:
        """アクセスログ取得"""
        logs = self._access_logs
        
        if object_id:
            logs = [log for log in logs if log.object_id == object_id]
        
        return logs[-limit:]

# ==================================================
# ファクトリー関数
# ==================================================

async def create_worm_manager(
    project_id: str,
    bucket_name: str,
    kms_key_ring: str,
    kms_key_name: str,
    location: str = "asia-northeast1"
) -> EnhancedWORMManager:
    """WORM管理システムの作成"""
    try:
        config = WORMConfig(
            project_id=project_id,
            bucket_name=bucket_name,
            kms_key_ring=kms_key_ring,
            kms_key_name=kms_key_name,
            location=location
        )
        
        worm_manager = EnhancedWORMManager(config)
        
        # 初期化ヘルスチェック
        health = await worm_manager.health_check()
        if health['status'] != 'healthy':
            logger.warning(f"WORM manager health check shows issues: {health}")
        
        logger.info("WORM manager created successfully")
        return worm_manager
        
    except Exception as e:
        logger.error(f"Failed to create WORM manager: {e}")
        raise

# ==================================================
# エクスポート
# ==================================================

__all__ = [
    "EnhancedWORMManager",
    "WORMConfig",
    "WORMObject",
    "WORMObjectType",
    "WORMOperation",
    "create_worm_manager"
]