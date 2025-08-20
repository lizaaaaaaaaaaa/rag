# infrastructure/gcs_worm_setup.py - 完全修正版
# GCS WORM（Write Once Read Many）設定・監査ユーティリティ

from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, List

from google.cloud import storage
from google.cloud.storage.bucket import Bucket
from google.cloud.storage.client import Client
from google.api_core.exceptions import NotFound

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


# =========================================
# ユーティリティ
# =========================================
def _to_sized_list(maybe_iter: Any) -> List[Any]:
    """
    Generator / Iterable / list / tuple を安全に list に変換して返す。
    Pylance の reportArgumentType を回避するため、len() 前に必ず list 化する。
    """
    if maybe_iter is None:
        return []
    # すでに list/tuple の場合や __len__ を持つ場合
    if hasattr(maybe_iter, "__len__"):
        try:
            return list(maybe_iter)  # type: ignore[arg-type]
        except Exception:
            return []
    # Iterable だが __len__ がない（generator 等）
    if hasattr(maybe_iter, "__iter__"):
        try:
            return list(maybe_iter)
        except Exception:
            return []
    return []


# =========================================
# 日次監査システム
# =========================================
class DailyAuditSystem:
    """日次監査システム（WORM保護含む GCS 設定の健全性チェック）"""

    def __init__(self, project_id: Optional[str] = None, storage_client: Optional[Client] = None):
        self.project_id: str = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        if not self.project_id:
            logger.warning("GOOGLE_CLOUD_PROJECT が設定されていません。")
        self.storage_client: Client = storage_client or storage.Client(project=self.project_id)

    async def run_all(self) -> Dict[str, Any]:
        """必要な監査すべてを実行（拡張用）"""
        results: Dict[str, Any] = {}
        results["worm_protection"] = await self._audit_worm_protection()
        return results

    # ====== ★ 修正箇所を含むメソッド ======
    async def _audit_worm_protection(self) -> Dict[str, Any]:
        """WORM保護状況の監査"""
        try:
            bucket_name = f"consent-logs-{self.project_id}"
            bucket: Bucket = self.storage_client.bucket(bucket_name)

            # バケット存在確認
            try:
                bucket.reload()
            except NotFound:
                logger.error(f"Bucket not found: {bucket_name}")
                return {"status": "failed", "error": "bucket_not_found", "bucket": bucket_name}
            except Exception as e:
                logger.error(f"Failed to reload bucket {bucket_name}: {e}")
                return {"status": "failed", "error": str(e), "bucket": bucket_name}

            # lifecycle_rules の安全な長さ取得（★ここが Pylance 対応の肝）
            lifecycle_rules_raw: Any = getattr(bucket, "lifecycle_rules", None)
            lifecycle_rules_list: List[Any] = _to_sized_list(lifecycle_rules_raw)
            lifecycle_rules_count: int = len(lifecycle_rules_list)

            # GCS 設定値を安全に取得（SDK 差分に備え getattr を多用）
            iam_conf = getattr(bucket, "iam_configuration", None)
            ublea_enabled = False
            if iam_conf is not None:
                ublea_enabled = bool(
                    getattr(iam_conf, "uniform_bucket_level_access_enabled", False)
                    or getattr(iam_conf, "uniform_bucket_level_access", False)
                )

            versioning_enabled = bool(getattr(bucket, "versioning_enabled", False))
            retention_period = getattr(bucket, "retention_period", None)
            retention_policy_locked = bool(getattr(bucket, "retention_policy_locked", False))
            storage_class = getattr(bucket, "storage_class", None)

            worm_status: Dict[str, Any] = {
                "bucket_exists": True,
                "uniform_bucket_level_access": ublea_enabled,
                "versioning_enabled": versioning_enabled,
                "retention_period": retention_period,
                "retention_policy_locked": retention_policy_locked,
                "storage_class": storage_class,
                "lifecycle_rules_count": lifecycle_rules_count,
            }

            # 最近のオブジェクト確認（最大10件）
            blobs = list(bucket.list_blobs(max_results=10))
            sample_objects: List[Dict[str, Any]] = []

            for blob in blobs:
                try:
                    blob.reload()
                except Exception:
                    # reload が未サポートでも続行
                    pass

                sample_objects.append(
                    {
                        "name": getattr(blob, "name", None),
                        "created": getattr(blob, "time_created", None).isoformat()
                        if getattr(blob, "time_created", None)
                        else None,
                        "storage_class": getattr(blob, "storage_class", None),
                        "retention_expiration": getattr(blob, "retention_expiration_time", None).isoformat()
                        if getattr(blob, "retention_expiration_time", None)
                        else None,
                    }
                )

            return {
                "status": "completed",
                "bucket": bucket_name,
                "worm_configuration": worm_status,
                "sample_objects": sample_objects,
                "compliance_score": self._calculate_worm_compliance_score(worm_status),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

        except Exception as e:
            logger.error(f"❌ WORM protection audit failed: {e}")
            return {"status": "failed", "error": str(e)}

    # 監査スコア算出（簡易）
    def _calculate_worm_compliance_score(self, status: Dict[str, Any]) -> float:
        """
        簡易スコアリング:
        - UBLA 有効: +0.25
        - Versioning 有効: +0.25
        - Retention 設定あり: +0.25
        - ライフサイクルルール 1件以上: +0.25
        """
        score = 0.0
        if status.get("uniform_bucket_level_access"):
            score += 0.25
        if status.get("versioning_enabled"):
            score += 0.25
        if status.get("retention_period"):
            score += 0.25
        if (status.get("lifecycle_rules_count") or 0) > 0:
            score += 0.25
        return round(score, 2)


# =========================================
# スクリプト実行時の簡易ランナー
# =========================================
async def _main():
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT") or ""
    audit = DailyAuditSystem(project_id=project)
    result = await audit.run_all()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
