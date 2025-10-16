# utils/gcs_client.py - 完全修正版
"""
GCS クライアントユーティリティ
- 監査マニフェストのアップロード
- WORM ストレージ設定の検証
- （追加）GCS→ローカル補完: download_if_exists(...)
"""

from __future__ import annotations

import json
import os
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, List

from google.cloud import storage
from google.api_core import exceptions as gcp_exceptions

# ✅ 設定読込の明示（get_settings が未定義の環境でも安全にフォールバック）
try:
    from config import get_settings  # type: ignore
except Exception:  # pragma: no cover
    get_settings = None  # type: ignore

logger = logging.getLogger(__name__)


class GCSClient:
    """
    - settings.worm_bucket_name または 環境変数からバケットを解決
    - 監査/マニフェスト/各種の JSON/バイナリをアップロード
    - WORM/バケット設定の検証
    """

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

        # ★ バケット名のフォールバック強化
        #   1) 引数 bucket_name
        #   2) settings.worm_bucket_name
        #   3) 環境変数 GCS_BUCKET_NAME → GCS_CONSENT_BUCKET → GCS_BUCKET
        self.bucket_name: Optional[str] = (
            bucket_name
            or getattr(settings, "worm_bucket_name", None)
            or os.getenv("GCS_BUCKET_NAME")
            or os.getenv("GCS_CONSENT_BUCKET")
            or os.getenv("GCS_BUCKET")
        )

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
            raise RuntimeError(
                "GCS bucket is not configured. Set 'worm_bucket_name' in settings "
                "or GCS_BUCKET_NAME/GCS_CONSENT_BUCKET/GCS_BUCKET in env."
            )
        return self._bucket

    # ---------------------------------------------------------------------
    # 基本 I/O
    # ---------------------------------------------------------------------
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
        """バイト列をアップロードして GCS パスを返す"""
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

    # ---------------------------------------------------------------------
    # バケット設定の検証（WORM 近似）
    # ---------------------------------------------------------------------
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
                    lifecycle_rules_count = len(list(lifecycle_rules_raw))  # generator → list

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

    # ---------------------------------------------------------------------
    # 監査マニフェスト（標準パス）: manifests/YYYY/MM/DD/<manifest_id>.json
    # ---------------------------------------------------------------------
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

    # ---------------------------------------------------------------------
    # 補助
    # ---------------------------------------------------------------------
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


# ---------------------------------------------------------------------
# 追加: GCS にオブジェクトがあればローカルへ保存するユーティリティ
#  - rag/fast_rag_chain.py の「起動時補完」で利用（index.faiss / index.pkl 等）
#  - 失敗や未設定は False を返し、起動継続を阻害しない設計
# ---------------------------------------------------------------------
def download_if_exists(blob_name: str, local_path: str) -> bool:
    """
    GCS_BUCKET_NAME/<blob_name> が存在すれば local_path へ保存して True。
    無ければ False。親ディレクトリは自動作成。例外時も False を返す。

    例:
        download_if_exists("vectorstore/index.faiss", "/tmp/rag/vectorstore/index.faiss")
    """
    # バケット名は広めのフォールバックで解決
    bucket_name = (
        (os.getenv("GCS_BUCKET_NAME") or "").strip()
        or (os.getenv("GCS_CONSENT_BUCKET") or "").strip()
        or (os.getenv("GCS_BUCKET") or "").strip()
    )
    if not bucket_name or not blob_name or not local_path:
        logger.warning("download_if_exists skipped: missing bucket or path (bucket=%r, blob=%r)", bucket_name, blob_name)
        return False
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        if not blob.exists():
            return False
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(local_path)
        logger.info("download_if_exists success: gs://%s/%s -> %s", bucket_name, blob_name, local_path)
        return True
    except Exception as e:
        logger.error("download_if_exists error: %s", e)
        return False