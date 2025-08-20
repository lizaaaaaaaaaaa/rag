# ====================
# utils/health_check.py
# ====================

from __future__ import annotations

import asyncio
import time
import logging
from typing import Dict, Any, Optional
import aiohttp
from datetime import datetime

from database import check_db_connection
from utils.gcs_client import gcs_client
from config import settings

# aioredis の代替インポート（未導入でも動くようにする）
try:
    import aioredis  # type: ignore
    REDIS_AVAILABLE = True
except Exception:
    aioredis = None  # type: ignore
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class HealthChecker:
    """システムヘルスチェッククラス"""

    def __init__(self):
        # aioredis が無い環境でも型エラーにならないよう Any を使用
        self.redis_client: Optional[Any] = None

    async def check_database(self) -> Dict[str, Any]:
        """データベースヘルスチェック"""
        start_time = time.time()
        try:
            is_connected = await check_db_connection()
            response_time = (time.time() - start_time) * 1000  # ms
            return {
                "status": "healthy" if is_connected else "unhealthy",
                "response_time_ms": round(response_time, 2),
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "response_time_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": datetime.utcnow().isoformat(),
            }

    async def check_redis(self) -> Dict[str, Any]:
        """Redisヘルスチェック"""
        start_time = time.time()
        try:
            if not REDIS_AVAILABLE:
                return {
                    "status": "unavailable",
                    "error": "aioredis not installed",
                    "response_time_ms": round((time.time() - start_time) * 1000, 2),
                    "timestamp": datetime.utcnow().isoformat(),
                }

            redis_url = getattr(settings, "redis_url", None)
            if not redis_url:
                return {
                    "status": "unavailable",
                    "error": "REDIS URL not configured",
                    "response_time_ms": round((time.time() - start_time) * 1000, 2),
                    "timestamp": datetime.utcnow().isoformat(),
                }

            if not self.redis_client:
                self.redis_client = aioredis.from_url(redis_url)  # type: ignore[attr-defined]

            await self.redis_client.ping()
            response_time = (time.time() - start_time) * 1000  # ms
            return {
                "status": "healthy",
                "response_time_ms": round(response_time, 2),
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "response_time_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": datetime.utcnow().isoformat(),
            }

    async def check_gcs(self) -> Dict[str, Any]:
        """Google Cloud Storageヘルスチェック"""
        start_time = time.time()
        try:
            # テストファイルの作成と削除でGCSの動作を確認
            test_content = f"health_check_{datetime.utcnow().isoformat()}"
            test_path = f"health-checks/test_{int(time.time())}.txt"

            # アップロード／ダウンロード／削除
            await gcs_client.upload_file(
                test_content.encode(),
                test_path,
                content_type="text/plain",
            )
            downloaded_content = await gcs_client.download_file(test_path)
            await gcs_client.delete_file(test_path)

            response_time = (time.time() - start_time) * 1000  # ms
            if downloaded_content.decode() == test_content:
                return {
                    "status": "healthy",
                    "response_time_ms": round(response_time, 2),
                    "timestamp": datetime.utcnow().isoformat(),
                }
            else:
                return {
                    "status": "unhealthy",
                    "error": "Content mismatch",
                    "response_time_ms": round(response_time, 2),
                    "timestamp": datetime.utcnow().isoformat(),
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "response_time_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": datetime.utcnow().isoformat(),
            }

    async def check_external_apis(self) -> Dict[str, Any]:
        """外部APIヘルスチェック（OpenAI等）"""
        start_time = time.time()
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {getattr(settings, 'openai_api_key', '')}",
                    "Content-Type": "application/json",
                }
                async with session.get(
                    "https://api.openai.com/v1/models",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    response_time = (time.time() - start_time) * 1000  # ms
                    if response.status == 200:
                        return {
                            "status": "healthy",
                            "response_time_ms": round(response_time, 2),
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                    else:
                        return {
                            "status": "unhealthy",
                            "error": f"HTTP {response.status}",
                            "response_time_ms": round(response_time, 2),
                            "timestamp": datetime.utcnow().isoformat(),
                        }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "response_time_ms": round((time.time() - start_time) * 1000, 2),
                "timestamp": datetime.utcnow().isoformat(),
            }

    async def comprehensive_health_check(self) -> Dict[str, Any]:
        """包括的ヘルスチェック"""
        start_time = time.time()

        # 並行実行
        checks = await asyncio.gather(
            self.check_database(),
            self.check_redis(),
            self.check_gcs(),
            self.check_external_apis(),
            return_exceptions=True,
        )

        # 例外を辞書に変換
        normalized = []
        for chk in checks:
            if isinstance(chk, Exception):
                normalized.append(
                    {
                        "status": "unhealthy",
                        "error": str(chk),
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
            else:
                normalized.append(chk)

        database_health, redis_health, gcs_health, api_health = normalized
        total_time = (time.time() - start_time) * 1000

        all_healthy = all(
            c.get("status") == "healthy" for c in normalized if isinstance(c, dict)
        )

        return {
            "overall_status": "healthy" if all_healthy else "unhealthy",
            "total_response_time_ms": round(total_time, 2),
            "timestamp": datetime.utcnow().isoformat(),
            "components": {
                "database": database_health,
                "redis": redis_health,
                "gcs": gcs_health,
                "external_apis": api_health,
            },
        }


# シングルトンインスタンス
health_checker = HealthChecker()


# 便利関数
async def get_health_status() -> Dict[str, Any]:
    """ヘルスステータス取得（便利関数）"""
    return await health_checker.comprehensive_health_check()


async def is_system_healthy() -> bool:
    """システムが健全かどうかの簡易チェック"""
    health_status = await health_checker.comprehensive_health_check()
    return health_status.get("overall_status") == "healthy"