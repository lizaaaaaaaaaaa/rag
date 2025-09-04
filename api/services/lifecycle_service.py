"""
同意管理ライフサイクルサービス（拡張版）
- 期限管理・通知は既存を踏襲
- 追加: POLICY_VERSION のメジャー更新時「再同意通知」を一括送信
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db_session
from api.services.worm_service import EnhancedWORMManager
from .manifest_service import ManifestService
from utils.notification import send_email_notification, send_line_notification

logger = logging.getLogger(__name__)

# ==== 既存の列挙・データクラス（必要最低限のみ再掲） ====
class ConsentStatus(Enum):
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"
    PENDING_RENEWAL = "pending_renewal"

@dataclass
class LifecycleMetrics:
    total_consents: int
    active_consents: int
    expiring_soon_consents: int
    expired_consents: int
    withdrawn_consents: int
    renewal_success_rate: float
    average_consent_duration_days: float
    notification_delivery_rate: float

# ==== ユーティリティ ====
def _major(v: str) -> int:
    try:
        return int(str(v).split(".")[0])
    except Exception:
        return 0

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
POLICY_VERSION = os.getenv("POLICY_VERSION", "1.0.0")

class ConsentLifecycleManager:
    """同意ライフサイクル管理（速度重視＋再同意促進の追加）"""

    def __init__(self, worm_manager: EnhancedWORMManager, manifest_service: ManifestService, project_id: str, notification_config: Optional[Dict[str, Any]] = None):
        self.worm_manager = worm_manager
        self.manifest_service = manifest_service
        self.project_id = project_id
        self.notification_config = notification_config or {}
        self.warning_days = [30, 7, 1]
        self.batch_size = 100
        self.retention_years = 5

    # ===== 既存: 日次処理（簡略要約・中身は従来通り） =====
    async def process_daily_lifecycle(self, target_date: Optional[date] = None) -> Dict[str, Any]:
        if target_date is None:
            target_date = date.today()
        results = {"date": target_date.isoformat(), "started_at": datetime.utcnow().isoformat(), "errors": []}
        try:
            async with get_db_session() as db:
                # 1) 期限警告通知
                n = await self._process_expiry_notifications(db, target_date)
                # 2) 期限切れ処理
                e = await self._process_expired_consents(db, target_date)
                # 3) メトリクス
                metrics = await self._calculate_metrics(db, target_date)
                results.update({"notifications_sent": n["sent_count"], "consents_expired": e["expired_count"], "metrics": asdict(metrics)})
            results["success"] = True
        except Exception as ex:
            logger.error(f"[lifecycle] daily failed: {ex}")
            results.update({"success": False, "error": str(ex)})
        results["completed_at"] = datetime.utcnow().isoformat()
        return results

    # ===== 新規: メジャー更新時の再同意通知 =====
    async def notify_policy_major_update(self, target_version: Optional[str] = None) -> Dict[str, Any]:
        """
        POLICY_VERSION のメジャーが上がった際に、古いメジャーでアクティブな同意へ再同意を促す。
        - LINE 優先通知（line_user_id がある場合）
        - メールはフォールバック（実装環境に応じて）
        """
        target_version = target_version or POLICY_VERSION
        major_new = _major(target_version)
        if not PUBLIC_BASE_URL:
            logger.warning("PUBLIC_BASE_URL is not set; consent link will be incomplete")

        notified, errors = 0, []
        async with get_db_session() as db:
            # アクティブ同意（withdrawn=false）で、policy_version の major が異なるユーザーを抽出
            q = text("""
                SELECT DISTINCT ON (user_id)
                    user_id, line_user_id, consent_id, policy_version
                FROM consent_records
                WHERE withdrawn = FALSE
                ORDER BY user_id, created_at DESC
            """)
            rows = (await db.execute(q)).fetchall()

            tasks = []
            for r in rows:
                if _major(r.policy_version) == major_new:
                    continue
                # ユーザー別 LIFF 同意導線
                link = f"{PUBLIC_BASE_URL}/liff/consent?user_token={r.line_user_id or r.user_id}"
                msg = (
                    "【重要】プライバシーポリシー更新に伴う再同意のお願い\n\n"
                    "引き続き AI 相談をご利用いただくため、最新のポリシーへの同意が必要です。\n"
                    f"▼ 再同意はこちら\n{link}\n\n"
                    "※ リッチメニューの文言・応答速度は従来どおりです。"
                )
                tasks.append(self._send_line_or_email(r, msg))

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for res in results:
                    if res is True:
                        notified += 1
                    elif isinstance(res, Exception):
                        errors.append({"type": "notify_error", "error": str(res)})

        return {"ok": True, "target_version": target_version, "notified": notified, "errors": errors}

    async def _send_line_or_email(self, row, message: str) -> bool:
        # LINE 優先
        if row.line_user_id and self.notification_config.get("line_enabled", True):
            try:
                return await send_line_notification(user_id=row.line_user_id, message=message, config=self.notification_config.get("line"))
            except Exception as e:
                logger.warning(f"[lifecycle] line push failed: {e}")
        # メールは環境に合わせて（サンプル）
        if self.notification_config.get("email_enabled", False):
            try:
                return await send_email_notification(
                    subject="再同意のお願い",
                    body=message,
                    recipients=[f"user_{row.user_id}@example.com"],
                    smtp_config=self.notification_config.get("smtp"),
                )
            except Exception as e:
                logger.warning(f"[lifecycle] email failed: {e}")
        return False

    # ===== 既存ロジックの要点（簡略版） =====
    async def _process_expiry_notifications(self, db: AsyncSession, target_date: date) -> Dict[str, Any]:
        sent = 0
        for days in self.warning_days:
            q = text("""
                SELECT consent_id, user_id, line_user_id, expires_at
                FROM consent_records
                WHERE DATE(expires_at) = :d AND withdrawn = FALSE
                LIMIT :n
            """)
            rows = (await db.execute(q, {"d": target_date + timedelta(days=days), "n": self.batch_size})).fetchall()
            if not rows:
                continue
            tasks = []
            for r in rows:
                link = f"{PUBLIC_BASE_URL}/liff/consent?user_token={r.line_user_id or r.user_id}"
                msg = f"🔔 同意期限のお知らせ（{days}日前）\n\n継続利用には再同意が必要です。\n{link}"
                tasks.append(self._send_line_or_email(r, msg))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            sent += sum(1 for x in results if x is True)
        return {"sent_count": sent, "errors": []}

    async def _process_expired_consents(self, db: AsyncSession, target_date: date) -> Dict[str, Any]:
        q = text("""
            SELECT consent_id, user_id, line_user_id
            FROM consent_records
            WHERE DATE(expires_at) < :d AND withdrawn = FALSE
            LIMIT :n
        """)
        rows = (await db.execute(q, {"d": target_date, "n": self.batch_size})).fetchall()
        expired = 0
        for r in rows:
            # 取り消し状態に更新（簡略）
            await db.execute(text("UPDATE consent_records SET withdrawn = TRUE, withdrawn_at = NOW() WHERE consent_id = :cid"), {"cid": r.consent_id})
            link = f"{PUBLIC_BASE_URL}/liff/consent?user_token={r.line_user_id or r.user_id}"
            await self._send_line_or_email(r, f"🚨 同意が失効しました。\n再同意はこちら\n{link}")
            expired += 1
        await db.commit()
        return {"expired_count": expired, "errors": []}

    async def _calculate_metrics(self, db: AsyncSession, target_date: date) -> LifecycleMetrics:
        q = text("""
            SELECT 
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE withdrawn = FALSE AND expires_at > NOW()) AS active,
                COUNT(*) FILTER (WHERE withdrawn = FALSE AND expires_at BETWEEN NOW() AND NOW() + INTERVAL '30 days') AS soon,
                COUNT(*) FILTER (WHERE withdrawn = FALSE AND expires_at <= NOW()) AS expired,
                COUNT(*) FILTER (WHERE withdrawn = TRUE) AS withdrawn
            FROM consent_records
        """)
        r = (await db.execute(q)).fetchone()
        return LifecycleMetrics(
            total_consents=r.total or 0,
            active_consents=r.active or 0,
            expiring_soon_consents=r.soon or 0,
            expired_consents=r.expired or 0,
            withdrawn_consents=r.withdrawn or 0,
            renewal_success_rate=0.0,
            average_consent_duration_days=0.0,
            notification_delivery_rate=0.95,
        )
