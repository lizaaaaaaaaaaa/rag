# api/routers/consent_gate.py - API同意ゲート＆同意管理システム（完全版）

import os
import logging
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from uuid import uuid4

import psycopg2
from psycopg2.extras import RealDictCursor

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# GCS（任意・本番向け）
from google.cloud import storage
from google.cloud.storage.bucket import Bucket  # 型注釈用
from google.cloud.storage.client import Client  # 型注釈用

# Web/OAuth の Bearer JWT でも user_id を抽出できるように
import jwt  # PyJWT（署名検証は上流で実施想定）

import asyncio

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/consent", tags=["consent"])

# ========== 設定 ==========
# ★ 5点同意 & バージョンは ENV で一元管理
CONSENT_CONFIG = {
    "POLICY_VERSION": os.environ.get("POLICY_VERSION", "2025-09-01"),
    "TOS_VERSION": os.environ.get("TOS_VERSION", "2025-09-01"),
    "CONSENT_VALIDITY_MONTHS": int(os.getenv("CONSENT_VALIDITY_MONTHS", "12")),
    "WORM_RETENTION_YEARS": int(os.getenv("WORM_RETENTION_YEARS", "5")),
    "GCS_CONSENT_BUCKET": os.environ.get("GCS_CONSENT_BUCKET", "consent-logs-rag-cloud-project"),
    # ★ 必須フラグ（5点）
    "REQUIRED_FLAGS": ["pp", "tos", "cookie", "xfer", "ai_limits"],
}

# ========== データモデル ==========
class ConsentRequest(BaseModel):
    consent_id: str
    user_id: str
    liff_id: Optional[str] = None
    consented_at: str
    ip: Optional[str] = None
    ua: Optional[str] = None
    policy_version: str
    tos_version: str
    flags: Dict[str, bool]
    locale: Optional[str] = None
    source: Optional[str] = None
    withdrawn: bool = False

class ConsentCheckRequest(BaseModel):
    # ★ user_id / versions は省略可（ヘッダやENVから補う）
    user_id: Optional[str] = None
    policy_version: Optional[str] = None
    tos_version: Optional[str] = None

class ConsentWithdrawRequest(BaseModel):
    user_id: str
    consent_id: Optional[str] = None

# ========== データベース管理 ==========
class ConsentDB:
    def __init__(self):
        self.conn_params = {
            "host": os.getenv("DB_HOST"),
            "port": int(os.getenv("DB_PORT", 5432)),
            "database": os.getenv("DB_NAME"),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD"),
        }

    def get_connection(self):
        return psycopg2.connect(**self.conn_params)

    def create_consent_table(self):
        """同意テーブル作成"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS consent_logs (
                        id SERIAL PRIMARY KEY,
                        consent_id VARCHAR(255) UNIQUE NOT NULL,
                        user_id VARCHAR(255) NOT NULL,
                        liff_id VARCHAR(255),
                        consented_at TIMESTAMP WITH TIME ZONE NOT NULL,
                        ip INET,
                        ua TEXT,
                        policy_version VARCHAR(50) NOT NULL,
                        tos_version VARCHAR(50) NOT NULL,
                        flags JSONB NOT NULL,
                        locale VARCHAR(10),
                        source VARCHAR(50),
                        withdrawn BOOLEAN DEFAULT FALSE,
                        withdrawn_at TIMESTAMP WITH TIME ZONE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        gcs_object_name VARCHAR(500)
                    );
                """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_consent_user_id ON consent_logs (user_id);
                    CREATE INDEX IF NOT EXISTS idx_consent_valid ON consent_logs (user_id, policy_version, tos_version, withdrawn);
                    CREATE INDEX IF NOT EXISTS idx_consent_created ON consent_logs (created_at);
                """
                )
                conn.commit()
                logger.info("✅ Consent table created/verified")

    def save_consent(self, consent_data: ConsentRequest) -> Dict[str, Any]:
        """同意情報を保存"""
        # 入力の5点同意を軽く検証
        if not all(consent_data.flags.get(k) for k in CONSENT_CONFIG["REQUIRED_FLAGS"]):
            raise HTTPException(status_code=400, detail="Required flags are not all true")

        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # 既存の有効同意を無効化（再同意時）
                    cur.execute(
                        """
                        UPDATE consent_logs
                        SET withdrawn = TRUE, withdrawn_at = NOW()
                        WHERE user_id = %s AND withdrawn = FALSE
                        """,
                        (consent_data.user_id,),
                    )

                    # 新しい同意を保存
                    cur.execute(
                        """
                        INSERT INTO consent_logs (
                            consent_id, user_id, liff_id, consented_at, ip, ua,
                            policy_version, tos_version, flags, locale, source, withdrawn
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, consent_id, created_at
                        """,
                        (
                            consent_data.consent_id,
                            consent_data.user_id,
                            consent_data.liff_id,
                            consent_data.consented_at,
                            consent_data.ip,
                            consent_data.ua,
                            consent_data.policy_version,
                            consent_data.tos_version,
                            json.dumps(consent_data.flags),
                            consent_data.locale,
                            consent_data.source,
                            consent_data.withdrawn,
                        ),
                    )

                    result = cur.fetchone()
                    conn.commit()

                    logger.info(f"✅ Consent saved: {consent_data.consent_id} for user {consent_data.user_id}")
                    return {
                        "success": True,
                        "consent_id": result["consent_id"],
                        "database_id": result["id"],
                        "created_at": result["created_at"].isoformat(),
                    }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Failed to save consent: {e}")
            raise HTTPException(status_code=500, detail="Failed to save consent")

    def check_valid_consent(self, user_id: str, policy_version: str, tos_version: str) -> Optional[Dict]:
        """有効な同意をチェック（最新を1件返す）"""
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # months → interval へ確実に変換（文字列連結 cast）
                    cur.execute(
                        """
                        SELECT *
                        FROM consent_logs
                        WHERE user_id = %s
                          AND policy_version = %s
                          AND tos_version = %s
                          AND withdrawn = FALSE
                          AND consented_at > NOW() - ((%s) || ' months')::interval
                        ORDER BY consented_at DESC
                        LIMIT 1
                        """,
                        (user_id, policy_version, tos_version, str(CONSENT_CONFIG["CONSENT_VALIDITY_MONTHS"])),
                    )

                    result = cur.fetchone()
                    if result:
                        flags = result["flags"]  # JSONB→dict で来る想定
                        if all(flags.get(f, False) for f in CONSENT_CONFIG["REQUIRED_FLAGS"]):
                            return dict(result)
                    return None

        except Exception as e:
            logger.error(f"❌ Failed to check consent: {e}")
            return None

    def withdraw_consent(self, user_id: str, consent_id: Optional[str] = None) -> Dict[str, Any]:
        """同意を撤回"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    if consent_id:
                        cur.execute(
                            """
                            UPDATE consent_logs
                            SET withdrawn = TRUE, withdrawn_at = NOW()
                            WHERE user_id = %s AND consent_id = %s
                            """,
                            (user_id, consent_id),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE consent_logs
                            SET withdrawn = TRUE, withdrawn_at = NOW()
                            WHERE user_id = %s AND withdrawn = FALSE
                            """,
                            (user_id,),
                        )
                    affected_rows = cur.rowcount
                    conn.commit()
                    logger.info(f"✅ Consent withdrawn for user {user_id}: {affected_rows} records")
                    return {"success": True, "affected_records": affected_rows}
        except Exception as e:
            logger.error(f"❌ Failed to withdraw consent: {e}")
            raise HTTPException(status_code=500, detail="Failed to withdraw consent")

# ========== GCS WORM管理 ==========
class ConsentWORMStorage:
    def __init__(self):
        self.bucket_name: str = CONSENT_CONFIG["GCS_CONSENT_BUCKET"]
        try:
            self.client: Optional[Client] = storage.Client()
            self.bucket: Optional[Bucket] = self.client.bucket(self.bucket_name) if self.client else None
        except Exception as e:
            logger.error(f"❌ Failed to initialize GCS client: {e}")
            self.client = None
            self.bucket = None

    def save_to_worm(self, consent_data: ConsentRequest) -> str:
        """同意データをWORM保護されたGCSに保存"""
        if not self.client or not self.bucket:
            logger.warning("⚠️ GCS not available, skipping WORM storage")
            return ""

        try:
            dt = datetime.fromisoformat(consent_data.consented_at.replace("Z", "+00:00"))
            object_name = f"consent_logs/{dt.year}/{dt.month:02d}/{dt.day:02d}/{consent_data.consent_id}.json"

            blob = self.bucket.blob(object_name)
            retention_date = datetime.now() + timedelta(days=365 * CONSENT_CONFIG["WORM_RETENTION_YEARS"])

            consent_json = {
                **consent_data.dict(),
                "saved_to_worm_at": datetime.now().isoformat(),
                "retention_until": retention_date.isoformat(),
                "worm_protected": True,
            }

            blob.upload_from_string(json.dumps(consent_json, ensure_ascii=False, indent=2), content_type="application/json")

            try:
                update_storage_class = getattr(blob, "update_storage_class", None)
                if callable(update_storage_class):
                    update_storage_class("ARCHIVE")
            except Exception as e:
                logger.warning(f"⚠️ Failed to set archive storage class: {e}")

            logger.info(f"✅ Consent saved to WORM storage: {object_name}")
            return object_name

        except Exception as e:
            logger.error(f"❌ Failed to save to WORM storage: {e}")
            return ""

    def setup_bucket_lifecycle(self):
        """バケットライフサイクル設定"""
        if not self.client or not self.bucket:
            logger.warning("⚠️ GCS client/bucket not available for lifecycle setup")
            return

        try:
            lifecycle_rule = {
                "rule": [
                    {
                        "action": {"type": "Delete"},
                        "condition": {
                            "age": 365 * CONSENT_CONFIG["WORM_RETENTION_YEARS"],
                            "matchesStorageClass": ["ARCHIVE"],
                        },
                    }
                ]
            }
            if hasattr(self.bucket, "lifecycle_rules"):
                self.bucket.lifecycle_rules = lifecycle_rule["rule"]
                if hasattr(self.bucket, "patch"):
                    self.bucket.patch()
                    logger.info("✅ Bucket lifecycle configured for retention")
        except Exception as e:
            logger.error(f"❌ Failed to setup bucket lifecycle: {e}")

# ========== 依存性注入 ==========
consent_db = ConsentDB()
worm_storage = ConsentWORMStorage()

def get_consent_db():
    return consent_db

# ========== ユーザー識別（Web/LINE両対応） ==========
def extract_user_id_from_token(token: str) -> Optional[str]:
    """
    トークンから user_id を抽出。
    - LINE: 'U' で始まる UID をそのまま受容
    - Web/OAuth: Bearer JWT を署名検証なしで decode して sub/user_id/email を拾う
    """
    try:
        if isinstance(token, str) and token.startswith("U"):
            return token
        payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256", "RS256", "ES256"])
        return payload.get("sub") or payload.get("user_id") or payload.get("email")
    except Exception:
        return None

def extract_user_id_from_request(request: Request) -> Optional[str]:
    uid = request.headers.get("X-User-Id")
    if uid:
        return uid
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return extract_user_id_from_token(auth.split(" ", 1)[1])
    tok = request.headers.get("user_token")
    if tok:
        return extract_user_id_from_token(tok)
    return None

def verify_user_consent(request: Request, db: ConsentDB = Depends(get_consent_db)):
    """ユーザーの同意を検証"""
    user_id = extract_user_id_from_request(request)
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "CONSENT_REQUIRED",
                "policy_version": CONSENT_CONFIG["POLICY_VERSION"],
                "tos_version": CONSENT_CONFIG["TOS_VERSION"],
                "message": "User consent required",
            },
        )

    valid_consent = db.check_valid_consent(user_id, CONSENT_CONFIG["POLICY_VERSION"], CONSENT_CONFIG["TOS_VERSION"])
    if not valid_consent:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "CONSENT_REQUIRED",
                "policy_version": CONSENT_CONFIG["POLICY_VERSION"],
                "tos_version": CONSENT_CONFIG["TOS_VERSION"],
                "message": "Valid consent not found",
            },
        )
    return user_id

# ========== API エンドポイント ==========
@router.post("/save")
async def save_consent(consent_data: ConsentRequest, db: ConsentDB = Depends(get_consent_db)):
    """同意情報の保存"""
    try:
        # 1. DB 保存
        db_result = db.save_consent(consent_data)

        # 2. WORM保存（任意、失敗しても致命ではない）
        worm_object = ""
        try:
            worm_object = worm_storage.save_to_worm(consent_data)
        except Exception as e:
            logger.error(f"⚠️ WORM storage failed: {e}")

        # 3. WORMオブジェクト名をDBに反映
        if worm_object:
            try:
                with db.get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE consent_logs SET gcs_object_name = %s WHERE consent_id = %s",
                            (worm_object, consent_data.consent_id),
                        )
                        conn.commit()
            except Exception as e:
                logger.error(f"⚠️ Failed to update WORM object name: {e}")

        return {
            "success": True,
            "consent_id": consent_data.consent_id,
            "database_saved": True,
            "worm_saved": bool(worm_object),
            "worm_object": worm_object,
            "message": "同意情報が正常に保存されました",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Save consent error: {e}")
        raise HTTPException(status_code=500, detail="同意情報の保存に失敗しました")

@router.post("/check")
async def check_consent(check_request: ConsentCheckRequest, request: Request, db: ConsentDB = Depends(get_consent_db)):
    """同意状況の確認（ヘッダからの自動補完に対応）"""
    # body.user_id が無ければヘッダから拾う
    user_id = check_request.user_id or extract_user_id_from_request(request)
    if not user_id:
        return {
            "valid": False,
            "error": "CONSENT_REQUIRED",
            "policy_version": CONSENT_CONFIG["POLICY_VERSION"],
            "tos_version": CONSENT_CONFIG["TOS_VERSION"],
        }

    policy_version = check_request.policy_version or CONSENT_CONFIG["POLICY_VERSION"]
    tos_version = check_request.tos_version or CONSENT_CONFIG["TOS_VERSION"]

    vc = db.check_valid_consent(user_id, policy_version, tos_version)
    if vc:
        # 有効期限は「30日×月数」の簡易換算
        expires_at = vc["consented_at"] + timedelta(days=30 * CONSENT_CONFIG["CONSENT_VALIDITY_MONTHS"])
        return {
            "valid": True,
            "consent_id": vc["consent_id"],
            "consented_at": vc["consented_at"].isoformat(),
            "expires_at": expires_at.isoformat(),
            "flags": vc["flags"],
        }

    return {
        "valid": False,
        "error": "CONSENT_REQUIRED",
        "policy_version": policy_version,
        "tos_version": tos_version,
    }

@router.post("/withdraw")
async def withdraw_consent(withdraw_request: ConsentWithdrawRequest, db: ConsentDB = Depends(get_consent_db)):
    """同意の撤回"""
    result = db.withdraw_consent(withdraw_request.user_id, withdraw_request.consent_id)
    return {"success": True, "message": "同意が撤回されました", "affected_records": result["affected_records"]}

@router.get("/user/{user_id}/history")
async def get_consent_history(user_id: str, db: ConsentDB = Depends(get_consent_db)):
    """ユーザーの同意履歴取得"""
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT consent_id, consented_at, policy_version, tos_version,
                           withdrawn, withdrawn_at, flags, source
                    FROM consent_logs
                    WHERE user_id = %s
                    ORDER BY consented_at DESC
                    """,
                    (user_id,),
                )
                history = cur.fetchall()
                return {"user_id": user_id, "history": [dict(r) for r in history], "total_records": len(history)}
    except Exception as e:
        logger.error(f"❌ Failed to get consent history: {e}")
        raise HTTPException(status_code=500, detail="同意履歴の取得に失敗しました")

@router.get("/admin/stats")
async def get_consent_stats(db: ConsentDB = Depends(get_consent_db)):
    """管理者用同意統計"""
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total_consents,
                        COUNT(*) FILTER (WHERE withdrawn = FALSE) as active_consents,
                        COUNT(*) FILTER (WHERE withdrawn = TRUE) as withdrawn_consents,
                        COUNT(DISTINCT user_id) as unique_users,
                        MIN(consented_at) as first_consent,
                        MAX(consented_at) as latest_consent
                    FROM consent_logs
                    """
                )
                stats = cur.fetchone()

                cur.execute(
                    """
                    SELECT DATE(consented_at) as consent_date, COUNT(*) as daily_consents
                    FROM consent_logs
                    WHERE consented_at > NOW() - INTERVAL '30 days'
                    GROUP BY DATE(consented_at)
                    ORDER BY consent_date DESC
                    """
                )
                daily_stats = cur.fetchall()

                return {
                    "overview": dict(stats),
                    "daily_stats": [dict(r) for r in daily_stats],
                    "generated_at": datetime.now().isoformat(),
                }
    except Exception as e:
        logger.error(f"❌ Failed to get consent stats: {e}")
        raise HTTPException(status_code=500, detail="統計の取得に失敗しました")

# ========== 初期化 ==========
@router.on_event("startup")
async def initialize_consent_system():
    """同意システム初期化"""
    try:
        consent_db.create_consent_table()
        worm_storage.setup_bucket_lifecycle()
        logger.info("✅ Consent system initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize consent system: {e}")

# ========== チャットAPI保護用デコレータ ==========
def require_valid_consent(func):
    """チャットAPIなどを同意ゲートで保護するデコレータ"""
    async def wrapper(*args, **kwargs):
        request = kwargs.get("request") or (args[0] if args else None)
        if request:
            verify_user_consent(request)
        return await func(*args, **kwargs)
    return wrapper
