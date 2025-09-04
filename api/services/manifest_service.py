"""
日次マニフェスト生成システム（高速・堅牢化）
- 同意記録の整合性確認・証跡管理・法的要件対応
- consent WORM ファイルパスの差異に両対応:
  * consent_logs/YYYY/MM/DD/<id>.json
  * consents/YYYY-MM-DD/<id>.json(.gz も許容)
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import uuid
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from google.api_core import exceptions as gcp_exceptions

from database import get_db_session
from api.services.worm_service import EnhancedWORMManager

logger = logging.getLogger(__name__)

# ========= 設定 =========
WORM_PREFIX_PRIMARY = os.getenv("WORM_PREFIX_PRIMARY", "consent_logs")  # 推奨: consent_logs/YYYY/MM/DD
WORM_PREFIX_COMPAT  = os.getenv("WORM_PREFIX_COMPAT",  "consents")      # 互換: consents/YYYY-MM-DD
MANIFEST_VERSION    = os.getenv("MANIFEST_VERSION",    "1.0.1")
ANOMALY_OK_RATIO    = float(os.getenv("MANIFEST_OK_RATIO", "0.95"))  # 95% 以上成功で compliant

# ========= データクラス =========
@dataclass
class ManifestEntry:
    record_id: str
    record_type: str  # 'consent' | 'withdrawal' | 'audit'
    timestamp: str
    checksum: str
    file_path: str
    size_bytes: int
    metadata: Dict[str, Any]

@dataclass
class DailyManifest:
    manifest_id: str
    date: str
    generated_at: str
    total_entries: int
    consent_records: int
    withdrawal_records: int
    audit_logs: int
    entries: List[ManifestEntry]
    merkle_root: str
    chain_hash: str
    previous_manifest_hash: Optional[str]
    generator_version: str
    compliance_verified: bool
    worm_verified: bool
    anomalies: List[Dict[str, Any]]
    digital_signature: Optional[str] = None
    timestamp_proof: Optional[str] = None

# ========= 本体 =========
class ManifestService:
    """日次マニフェスト生成サービス（差分最小・互換重視）"""

    def __init__(self, worm_manager: EnhancedWORMManager, project_id: str, notification_config: Optional[Dict[str, Any]] = None):
        self.worm_manager = worm_manager
        self.project_id = project_id
        self.notification_config = notification_config or {}
        self.manifest_version = MANIFEST_VERSION
        self._chain_cache: Dict[str, str] = {}

    async def generate_daily_manifest(self, target_date: date, force_regenerate: bool = False) -> DailyManifest:
        mid = f"manifest_{target_date.strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
        logger.info(f"[manifest] start {target_date} id={mid}")

        # 既存マニフェストがあれば再利用
        if not force_regenerate:
            existing = await self._check_existing_manifest(target_date)
            if existing:
                return existing

        async with get_db_session() as db:
            # 1) エントリ収集
            entries = await self._collect_daily_entries(db, target_date)

            # 2) Merkle / Chain
            merkle_root = self._calc_merkle(entries)
            prev_hash = await self._get_previous_manifest_hash(target_date)
            chain_hash = self._calc_chain(target_date, merkle_root, prev_hash)

            # 3) WORM 健全性&整合性
            worm_verified = await self._verify_worm()
            ok_ratio = await self._verify_entries_integrity(entries)
            compliant = ok_ratio >= ANOMALY_OK_RATIO

            # 4) マニフェスト構築
            manifest = DailyManifest(
                manifest_id=mid,
                date=target_date.isoformat(),
                generated_at=datetime.utcnow().isoformat(),
                total_entries=len(entries),
                consent_records=len([e for e in entries if e.record_type == "consent"]),
                withdrawal_records=len([e for e in entries if e.record_type == "withdrawal"]),
                audit_logs=len([e for e in entries if e.record_type == "audit"]),
                entries=entries,
                merkle_root=merkle_root,
                chain_hash=chain_hash,
                previous_manifest_hash=prev_hash,
                generator_version=self.manifest_version,
                compliance_verified=compliant,
                worm_verified=worm_verified,
                anomalies=[] if compliant else [{"type": "LOW_OK_RATIO", "ok_ratio": ok_ratio}],
            )

            # 5) 署名＆タイムスタンプ（簡易）
            manifest.digital_signature = hashlib.sha256(
                json.dumps({"id": mid, "root": merkle_root, "chain": chain_hash}, sort_keys=True).encode()
            ).hexdigest()
            manifest.timestamp_proof = hashlib.sha256(f"ts:{mid}:{manifest.generated_at}".encode()).hexdigest()

            # 6) 保存
            await self._store_manifest(manifest)

            logger.info(f"[manifest] done {target_date} id={mid}")
            return manifest

    # -------- 収集（DB→WORMパス付与） --------
    async def _collect_daily_entries(self, db: AsyncSession, target_date: date) -> List[ManifestEntry]:
        entries: List[ManifestEntry] = []

        # 同意記録
        consent_q = text("""
            SELECT consent_id, created_at, user_id, policy_version
            FROM consent_records
            WHERE DATE(created_at) = :d
            ORDER BY created_at
        """)
        for row in (await db.execute(consent_q, {"d": target_date})).fetchall():
            # WORM ファイルのパス候補（primary / compat）
            y, m, d = target_date.year, target_date.month, target_date.day
            primary = f"{WORM_PREFIX_PRIMARY}/{y:04d}/{m:02d}/{d:02d}/{row.consent_id}.json"
            compat1 = f"{WORM_PREFIX_COMPAT}/{target_date.isoformat()}/{row.consent_id}.json"
            compat2 = f"{WORM_PREFIX_COMPAT}/{target_date.isoformat()}/{row.consent_id}.json.gz"
            entries.append(ManifestEntry(
                record_id=row.consent_id,
                record_type="consent",
                timestamp=row.created_at.isoformat(),
                checksum=self._record_checksum(row.consent_id, "consent_records"),
                file_path=primary,  # 検証では alt_paths も試す
                size_bytes=0,
                metadata={"user_id": row.user_id, "policy_version": row.policy_version, "alt_paths": [compat1, compat2]}
            ))

        # 取り消し
        wd_q = text("""
            SELECT withdrawal_id, withdrawn_at, consent_id, user_id
            FROM consent_withdrawals
            WHERE DATE(withdrawn_at) = :d
            ORDER BY withdrawn_at
        """)
        for row in (await db.execute(wd_q, {"d": target_date})).fetchall():
            y, m, d = target_date.year, target_date.month, target_date.day
            primary = f"{WORM_PREFIX_PRIMARY}_withdrawals/{y:04d}/{m:02d}/{d:02d}/{row.withdrawal_id}.json"
            compat = f"withdrawals/{target_date.isoformat()}/{row.withdrawal_id}.json.gz"
            entries.append(ManifestEntry(
                record_id=row.withdrawal_id,
                record_type="withdrawal",
                timestamp=row.withdrawn_at.isoformat(),
                checksum=self._record_checksum(row.withdrawal_id, "consent_withdrawals"),
                file_path=primary,
                size_bytes=0,
                metadata={"consent_id": row.consent_id, "user_id": row.user_id, "alt_paths": [compat]}
            ))

        # 監査ログ（DB由来）
        audit_q = text("""
            SELECT log_id, created_at, table_name, action_type
            FROM audit_logs
            WHERE DATE(created_at) = :d
            ORDER BY created_at
        """)
        for row in (await db.execute(audit_q, {"d": target_date})).fetchall():
            path = f"audit_logs/{target_date.isoformat()}/{row.log_id}.json"
            entries.append(ManifestEntry(
                record_id=row.log_id,
                record_type="audit",
                timestamp=row.created_at.isoformat(),
                checksum=self._record_checksum(row.log_id, "audit_logs"),
                file_path=path,
                size_bytes=0,
                metadata={"table_name": row.table_name, "action_type": row.action_type}
            ))

        logger.info(f"[manifest] collected {len(entries)} entries for {target_date}")
        return entries

    # -------- 検証 --------
    async def _verify_worm(self) -> bool:
        try:
            health = await self.worm_manager.health_check()
            return health.get("status") == "healthy"
        except Exception as e:
            logger.warning(f"[manifest] worm health fail: {e}")
            return False

    async def _verify_entries_integrity(self, entries: List[ManifestEntry]) -> float:
        ok = 0
        total = max(1, len([e for e in entries if e.record_type in ("consent", "withdrawal")]))
        for e in entries:
            if e.record_type not in ("consent", "withdrawal"):
                continue
            if await self._check_blob_exists(e.file_path):
                ok += 1
                continue
            # alt_paths も試す
            for alt in e.metadata.get("alt_paths", []):
                if await self._check_blob_exists(alt):
                    ok += 1
                    e.file_path = alt  # 実在したものに差し替え
                    break
        ratio = ok / total
        logger.info(f"[manifest] integrity ok_ratio={ratio:.3f} ({ok}/{total})")
        return ratio

    async def _check_blob_exists(self, path: str) -> bool:
        try:
            blob = self.worm_manager.bucket.blob(path)
            return blob.exists()
        except Exception:
            return False

    # -------- 暗号学的関数 --------
    def _record_checksum(self, rid: str, table: str) -> str:
        return hashlib.sha256(f"{table}:{rid}".encode()).hexdigest()

    def _calc_merkle(self, entries: List[ManifestEntry]) -> str:
        hs = [hashlib.sha256(f"{e.record_id}:{e.checksum}".encode()).hexdigest() for e in sorted(entries, key=lambda x: x.record_id)]
        if not hs:
            return hashlib.sha256(b"").hexdigest()
        while len(hs) > 1:
            nxt = []
            for i in range(0, len(hs), 2):
                a = hs[i]
                b = hs[i + 1] if i + 1 < len(hs) else a
                nxt.append(hashlib.sha256((a + b).encode()).hexdigest())
            hs = nxt
        return hs[0]

    def _calc_chain(self, d: date, merkle_root: str, prev_hash: Optional[str]) -> str:
        return hashlib.sha256(f"{d.isoformat()}:{merkle_root}:{prev_hash or 'genesis'}".encode()).hexdigest()

    # -------- 保存＆既存確認 --------
    async def _store_manifest(self, m: DailyManifest):
        p = f"manifests/{m.date}/manifest_{m.manifest_id}.json"
        data = json.dumps(asdict(m), ensure_ascii=False, indent=2)
        blob = self.worm_manager.bucket.blob(p)
        blob.metadata = {
            "manifest_id": m.manifest_id,
            "date": m.date,
            "generated_at": m.generated_at,
            "total_entries": str(m.total_entries),
            "compliance_verified": str(m.compliance_verified),
            "merkle_root": m.merkle_root,
            "chain_hash": m.chain_hash,
        }
        blob.upload_from_string(data, content_type="application/json")
        logger.info(f"[manifest] stored {p}")

    async def _check_existing_manifest(self, d: date) -> Optional[DailyManifest]:
        prefix = f"manifests/{d.isoformat()}/"
        for blob in self.worm_manager.storage_client.list_blobs(self.worm_manager.bucket, prefix=prefix):
            if blob.name.endswith(".json"):
                try:
                    return DailyManifest(**json.loads(blob.download_as_text()))
                except Exception:
                    pass
        return None

    async def _get_previous_manifest_hash(self, d: date) -> Optional[str]:
        y = d - timedelta(days=1)
        m = await self._check_existing_manifest(y)
        return m.chain_hash if m else None
