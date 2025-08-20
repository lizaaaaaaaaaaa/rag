"""
Google Cloud Storage 型安全ユーティリティ
Pylanceの型チェックエラーを避けるためのヘルパー関数
"""

import logging
from typing import Optional, List, Dict, Any, Union
from google.cloud import storage
from google.cloud.storage import Bucket, Blob

logger = logging.getLogger(__name__)

class SafeGCSClient:
    """型安全なGCSクライアントラッパー"""
    
    def __init__(self, project_id: Optional[str] = None):
        try:
            self._client = storage.Client(project=project_id)
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize GCS client: {e}")
            self._client = None
            self._initialized = False
    
    @property
    def client(self) -> Optional[storage.Client]:
        """GCSクライアントを取得"""
        return self._client if self._initialized else None
    
    def get_bucket(self, bucket_name: str) -> Optional[Bucket]:
        """バケットを安全に取得"""
        if not self._initialized or not self._client:
            logger.warning("GCS client not initialized")
            return None
        
        try:
            bucket = self._client.bucket(bucket_name)
            # バケットの存在確認
            if bucket.exists():
                return bucket
            else:
                logger.warning(f"Bucket {bucket_name} does not exist")
                return None
        except Exception as e:
            logger.error(f"Failed to get bucket {bucket_name}: {e}")
            return None
    
    def get_blob(self, bucket_name: str, blob_name: str) -> Optional[Blob]:
        """Blobを安全に取得"""
        bucket = self.get_bucket(bucket_name)
        if not bucket:
            return None
        
        try:
            blob = bucket.blob(blob_name)
            if blob.exists():
                return blob
            else:
                logger.warning(f"Blob {blob_name} does not exist in bucket {bucket_name}")
                return None
        except Exception as e:
            logger.error(f"Failed to get blob {blob_name}: {e}")
            return None
    
    def safe_lifecycle_rules_count(self, bucket: Bucket) -> int:
        """ライフサイクルルール数を安全に取得"""
        try:
            lifecycle_rules = bucket.lifecycle_rules
            if lifecycle_rules is None:
                return 0
            
            # Generator型の場合はlistに変換
            if hasattr(lifecycle_rules, '__iter__') and not hasattr(lifecycle_rules, '__len__'):
                return len(list(lifecycle_rules))
            elif hasattr(lifecycle_rules, '__len__'):
                return len(lifecycle_rules)
            else:
                return 0
        except Exception as e:
            logger.error(f"Failed to get lifecycle rules count: {e}")
            return 0
    
    def safe_bucket_patch(self, bucket: Bucket) -> bool:
        """バケット設定を安全に更新"""
        try:
            if hasattr(bucket, 'patch'):
                bucket.patch()
                return True
            else:
                logger.warning("Bucket patch method not available")
                return False
        except Exception as e:
            logger.error(f"Failed to patch bucket: {e}")
            return False
    
    def get_bucket_info(self, bucket_name: str) -> Dict[str, Any]:
        """バケット情報を安全に取得"""
        bucket = self.get_bucket(bucket_name)
        if not bucket:
            return {
                "exists": False,
                "error": "Bucket not found or not accessible"
            }
        
        try:
            # バケット情報を再読み込み
            bucket.reload()
            
            return {
                "exists": True,
                "name": bucket.name,
                "location": bucket.location,
                "storage_class": bucket.storage_class,
                "versioning_enabled": getattr(bucket, 'versioning_enabled', False),
                "retention_period": getattr(bucket, 'retention_period', None),
                "retention_policy_locked": getattr(bucket, 'retention_policy_locked', False),
                "lifecycle_rules_count": self.safe_lifecycle_rules_count(bucket),
                "uniform_bucket_level_access": (
                    bucket.iam_configuration.uniform_bucket_level_access_enabled
                    if hasattr(bucket, 'iam_configuration') else False
                )
            }
        except Exception as e:
            logger.error(f"Failed to get bucket info: {e}")
            return {
                "exists": True,
                "error": str(e)
            }

class SafeSchedulerClient:
    """型安全なCloud Schedulerクライアントラッパー"""
    
    def __init__(self):
        try:
            from google.cloud import scheduler_v1
            from google.cloud.scheduler_v1 import Job, PubsubTarget
            
            self._client = scheduler_v1.CloudSchedulerClient()
            self._Job = Job
            self._PubsubTarget = PubsubTarget
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize Scheduler client: {e}")
            self._client = None
            self._initialized = False
    
    def create_job_safe(
        self, 
        parent: str,
        job_id: str,
        schedule: str,
        time_zone: str,
        description: str,
        pubsub_config: Dict[str, Any]
    ) -> bool:
        """ジョブを安全に作成"""
        if not self._initialized or not self._client:
            logger.error("Scheduler client not initialized")
            return False
        
        try:
            # 正しいJob型オブジェクトを作成
            job = self._Job(
                name=f"{parent}/jobs/{job_id}",
                schedule=schedule,
                time_zone=time_zone,
                description=description,
                pubsub_target=self._PubsubTarget(
                    topic_name=pubsub_config.get("topic_name"),
                    data=pubsub_config.get("data", b"")
                )
            )
            
            # ジョブが既に存在するかチェック
            try:
                existing_job = self._client.get_job(name=job.name)
                # 既存の場合は更新
                self._client.update_job(job=job)
                logger.info(f"Updated scheduler job: {job_id}")
            except Exception:
                # 存在しない場合は作成
                self._client.create_job(parent=parent, job=job)
                logger.info(f"Created scheduler job: {job_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to create/update job {job_id}: {e}")
            return False

# グローバルインスタンス
_gcs_client: Optional[SafeGCSClient] = None
_scheduler_client: Optional[SafeSchedulerClient] = None

def get_safe_gcs_client(project_id: Optional[str] = None) -> SafeGCSClient:
    """グローバルなSafeGCSClientインスタンスを取得"""
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = SafeGCSClient(project_id)
    return _gcs_client

def get_safe_scheduler_client() -> SafeSchedulerClient:
    """グローバルなSafeSchedulerClientインスタンスを取得"""
    global _scheduler_client
    if _scheduler_client is None:
        _scheduler_client = SafeSchedulerClient()
    return _scheduler_client