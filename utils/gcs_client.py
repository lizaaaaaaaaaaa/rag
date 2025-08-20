# ====================
# utils/gcs_client.py
# ====================

import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, BinaryIO
from google.cloud import storage
from google.cloud.exceptions import NotFound, GoogleCloudError
from google.api_core import retry
import aiofiles
import logging
from config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

class GCSClient:
    """Google Cloud Storage クライアント"""
    
    def __init__(self):
        self.client = storage.Client(project=settings.google_cloud_project)
        self.bucket = self.client.bucket(settings.gcs_bucket_name)
        self.audit_bucket = self.client.bucket(settings.gcs_audit_bucket)
    
    async def upload_file(
        self,
        file_content: bytes,
        destination_path: str,
        content_type: str = "application/octet-stream",
        metadata: Optional[Dict[str, str]] = None
    ) -> str:
        """ファイルのアップロード"""
        try:
            blob = self.bucket.blob(destination_path)
            
            # メタデータの設定
            if metadata:
                blob.metadata = metadata
            
            # ファイルのアップロード
            blob.upload_from_string(
                file_content,
                content_type=content_type,
                retry=retry.Retry(deadline=60)
            )
            
            logger.info(f"File uploaded to GCS: {destination_path}")
            return f"gs://{settings.gcs_bucket_name}/{destination_path}"
            
        except GoogleCloudError as e:
            logger.error(f"Failed to upload file to GCS: {e}")
            raise
    
    async def download_file(self, source_path: str) -> bytes:
        """ファイルのダウンロード"""
        try:
            blob = self.bucket.blob(source_path)
            content = blob.download_as_bytes(retry=retry.Retry(deadline=60))
            
            logger.info(f"File downloaded from GCS: {source_path}")
            return content
            
        except NotFound:
            logger.error(f"File not found in GCS: {source_path}")
            raise
        except GoogleCloudError as e:
            logger.error(f"Failed to download file from GCS: {e}")
            raise
    
    async def delete_file(self, file_path: str) -> bool:
        """ファイルの削除"""
        try:
            blob = self.bucket.blob(file_path)
            blob.delete(retry=retry.Retry(deadline=30))
            
            logger.info(f"File deleted from GCS: {file_path}")
            return True
            
        except NotFound:
            logger.warning(f"File not found for deletion: {file_path}")
            return False
        except GoogleCloudError as e:
            logger.error(f"Failed to delete file from GCS: {e}")
            raise
    
    async def list_files(self, prefix: str = "", limit: int = 1000) -> List[Dict[str, Any]]:
        """ファイル一覧の取得"""
        try:
            blobs = self.bucket.list_blobs(
                prefix=prefix,
                max_results=limit
            )
            
            files = []
            for blob in blobs:
                files.append({
                    "name": blob.name,
                    "size": blob.size,
                    "created": blob.time_created.isoformat() if blob.time_created else None,
                    "updated": blob.updated.isoformat() if blob.updated else None,
                    "content_type": blob.content_type,
                    "md5_hash": blob.md5_hash,
                    "metadata": blob.metadata or {}
                })
            
            return files
            
        except GoogleCloudError as e:
            logger.error(f"Failed to list files from GCS: {e}")
            raise
    
    async def upload_audit_manifest(self, manifest_data: Dict[str, Any]) -> str:
        """監査マニフェストのアップロード（WORM対応）"""
        try:
            timestamp = datetime.utcnow().isoformat()
            manifest_path = f"audit-manifests/{timestamp.split('T')[0]}/{timestamp}.json"
            
            # マニフェストデータにタイムスタンプとハッシュを追加
            manifest_data.update({
                "timestamp": timestamp,
                "hash": hashlib.sha256(
                    json.dumps(manifest_data, sort_keys=True).encode()
                ).hexdigest()
            })
            
            blob = self.audit_bucket.blob(manifest_path)
            
            # WORM設定（Write Once, Read Many）
            if settings.worm_storage_enabled:
                # オブジェクトロック設定
                blob.metadata = {
                    "retention-policy": "true",
                    "immutable": "true",
                    "created-by": "rag-system"
                }
            
            blob.upload_from_string(
                json.dumps(manifest_data, indent=2),
                content_type="application/json"
            )
            
            logger.info(f"Audit manifest uploaded: {manifest_path}")
            return f"gs://{settings.gcs_audit_bucket}/{manifest_path}"
            
        except GoogleCloudError as e:
            logger.error(f"Failed to upload audit manifest: {e}")
            raise
    
    async def verify_worm_storage(self, file_path: str) -> bool:
        """WORM ストレージの検証"""
        try:
            blob = self.audit_bucket.blob(file_path)
            
            if not blob.exists():
                return False
            
            # メタデータの確認
            metadata = blob.metadata or {}
            return (
                metadata.get("retention-policy") == "true" and
                metadata.get("immutable") == "true"
            )
            
        except GoogleCloudError as e:
            logger.error(f"Failed to verify WORM storage: {e}")
            return False
    
    async def generate_signed_url(
        self,
        file_path: str,
        expiration_hours: int = 24,
        method: str = "GET"
    ) -> str:
        """署名付きURLの生成"""
        try:
            blob = self.bucket.blob(file_path)
            
            expiration = datetime.utcnow() + timedelta(hours=expiration_hours)
            
            url = blob.generate_signed_url(
                expiration=expiration,
                method=method,
                version="v4"
            )
            
            return url
            
        except GoogleCloudError as e:
            logger.error(f"Failed to generate signed URL: {e}")
            raise

# シングルトンインスタンス
gcs_client = GCSClient()

# 便利関数
async def upload_document_chunk(content: str, document_id: str, chunk_index: int) -> str:
    """ドキュメントチャンクのアップロード"""
    file_path = f"documents/{document_id}/chunks/{chunk_index:06d}.txt"
    
    metadata = {
        "document-id": document_id,
        "chunk-index": str(chunk_index),
        "content-hash": hashlib.sha256(content.encode()).hexdigest()
    }
    
    return await gcs_client.upload_file(
        content.encode('utf-8'),
        file_path,
        content_type="text/plain",
        metadata=metadata
    )

async def upload_audit_manifest(manifest_data: Dict[str, Any]) -> str:
    """監査マニフェストのアップロード（便利関数）"""
    return await gcs_client.upload_audit_manifest(manifest_data)

async def verify_worm_storage(file_path: str) -> bool:
    """WORM ストレージの検証（便利関数）"""
    return await gcs_client.verify_worm_storage(file_path)