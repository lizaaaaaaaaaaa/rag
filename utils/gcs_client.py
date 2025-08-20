# utils/gcs_client.py - 完全修正版
"""
GCS クライアントユーティリティ
- 監査マニフェストのアップロード
- WORM ストレージ設定の検証
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, List

from google.cloud import storage
from google.api_core import exceptions as gcp_exceptions

# ✅ 設定読込の明示（get_settings の未定義エラー対策）
try:
    # プロジェクト直下に config.py があり、get_settings() を公開している想定
    from config import get_settings  # <-- ここがポイント
except Exception as e:  # pragma: no cover
    # もし import に失敗した場合のフォールバック（最低限動くダミー設定）
    get_settings = None  # type: ignore[misc]
    _import_error = e

logger = logging.getLogger(__name__)


class GCSClient:
    """Google Cloud Storage の薄いラッパー"""

    def __init__(
        self,
        project_id: Optional[str] = None,
        bucket_name: Optional[str] = None,
        credentials: Any = None,
    ) -> None:
        # 設定の取得
        settings = None
        if get_settings is not None:
            try:
                settings = get_settings()
            except Exception as e:  # pragma: no cover
                logger.warning(f"get_settings() failed, fallback to env only: {e}")

        self.project_id: Optional[str] = project_id or getattr(settings, "gcp_project_id", None)
        self.bucket_name: Optional[str] = bucket_name or getattr(settings, "worm_bucket_name", None)

        # GCS クライアント初期化
        try:
            self.client: storage.Client = storage.Client(project=self.project_id, credentials=credentials)
        except Exception as e:
            logger.error(f"Failed to initialize GCS client: {e}")
            raise

        # バケット参照（存在チェックは必要時に行う）
        self._bucket: Optional[storage.Bucket] = None
        if self.bucket_name:
            self._bucket = self.client.bucket(self.bucket_name)

    @property
    def bucket(self) -> storage.Bucket:
        if not self._bucket:
            raise RuntimeError("GCS bucket is not configured. Set 'worm_bucket_name' in settings.")
        return self._bucket

    # ------------------------------
    # アップロード
    # ------------------------------

    def upload_json(
        self,
        object_path: str,
        payload: Dict[str, Any],
        content_type: str = "application/json",
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """JSON をアップロードして GCS パスを返す"""
        try:
            blob = self.bucket.blob(object_path)
            if metadata:
                blob.metadata = metadata
            blob.upload_from_string(json.dumps(payload, ensure_ascii=False), content_type=content_type)
            logger.info(f"Uploaded JSON to gs://{self.bucket.name}/{object_path}")
            return f"gs://{self.bucket.name}/{object_path}"
        except Exception as e:
            logger.error(f"Failed to upload JSON to {object_path}: {e}")
            raise

    def upload_bytes(
        self,
        object_path: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """バイナリをアップロードして GCS パスを返す"""
        try:
            blob = self.bucket.blob(object_path)
            if metadata:
                blob.metadata = metadata
            blob.upload_from_string(data, content_type=content_type)
            logger.info(f"Uploaded bytes to gs://{self.bucket.name}/{object_path}")
            return f"gs://{self.bucket.name}/{object_path}"
        except Exception as e:
            logger.error(f"Failed to upload bytes to {object_path}: {e}")
            raise

    # ------------------------------
    # WORM / バケット設定検証
    # ------------------------------

    def verify_bucket_settings(self) -> Dict[str, Any]:
        """バケットの WORM/セキュリティ関連設定を検証して返す"""
        try:
            bucket = self.bucket
            bucket.reload()

            # lifecycle_rules は generator の場合があるため安全に扱う
            lifecycle_rules_raw = getattr(bucket, "lifecycle_rules", None)
            lifecycle_rules_count = 0
            if lifecycle_rules_raw is not None:
                if hasattr(lifecycle_rules_raw, "__len__"):
                    lifecycle_rules_count = len(lifecycle_rules_raw)  # type: ignore[arg-type]
                elif hasattr(lifecycle_rules_raw, "__iter__"):
                    lifecycle_rules_count = len(list(lifecycle_rules_raw))  # 生成器 → list へ

            status = {
                "bucket": bucket.name,
                "project": self.project_id,
                "uniform_bucket_level_access": getattr(
                    bucket.iam_configuration, "uniform_bucket_level_access_enabled", False
                ),
                "versioning_enabled": bool(getattr(bucket, "versioning_enabled", False)),
                "retention_period": getattr(bucket, "retention_period", None),
                "retention_policy_locked": bool(getattr(bucket, "retention_policy_locked", False)),
                "storage_class": getattr(bucket, "storage_class", None),
                "lifecycle_rules_count": lifecycle_rules_count,
            }
            return status
        except Exception as e:
            logger.error(f"Failed to verify bucket settings: {e}")
            raise

    # ------------------------------
    # マニフェスト関連
    # ------------------------------

    def upload_audit_manifest(
        self,
        manifest_id: str,
        entries: List[Dict[str, Any]],
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """監査マニフェストを標準パスへ保存"""
        now = datetime.now(timezone.utc)
        object_path = f"manifests/{now:%Y/%m/%d}/{manifest_id}.json"

        payload = {
            "manifest_id": manifest_id,
            "generated_at": now.isoformat(),
            "entries": entries,
            "extra": extra or {},
            "version": "1.0",
        }

        metadata = {
            "manifest_id": manifest_id,
            "generated_at": now.isoformat(),
        }

        return self.upload_json(object_path, payload, metadata=metadata)

    # ------------------------------
    # 便利関数
    # ------------------------------

    def object_exists(self, object_path: str) -> bool:
        try:
            return self.bucket.blob(object_path).exists()
        except gcp_exceptions.NotFound:
            return False
        except Exception as e:
            logger.error(f"object_exists check failed for {object_path}: {e}")
            return False

    def download_text(self, object_path: str, encoding: str = "utf-8") -> str:
        try:
            blob = self.bucket.blob(object_path)
            return blob.download_as_text(encoding=encoding)
        except Exception as e:
            logger.error(f"Failed to download text from {object_path}: {e}")
            raise
