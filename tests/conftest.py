"""
テスト設定・フィクスチャ
pytest設定とテスト用データ準備

機能:
- テスト用データベース設定
- モックオブジェクト
- テストデータファクトリー
- セットアップ・ティアダウン

Requirements:
- pytest
- pytest-asyncio (任意: 無い場合は同期フィクスチャとしてフォールバック)
- sqlalchemy
- fastapi.testclient
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, date
from typing import AsyncGenerator, Generator, Dict, Any
import tempfile
import os
from unittest.mock import Mock, AsyncMock, patch

import pytest

# pytest-asyncio を任意依存として扱う（無い場合はシムで代替）
try:
    import pytest_asyncio  # type: ignore[reportMissingImports]
    _HAS_PYTEST_ASYNCIO = True
except Exception:
    _HAS_PYTEST_ASYNCIO = False

    class _PytestAsyncioShim:
        """
        pytest-asyncio が無い環境向けの簡易シム。
        非同期フィクスチャを同期フィクスチャとして登録するだけなので、
        本当に非同期実行が必要なテストは実行時にプラグイン導入を推奨。
        """
        fixture = pytest.fixture

    pytest_asyncio = _PytestAsyncioShim()  # type: ignore[assignment]

# プラグイン宣言も存在確認の上で設定
pytest_plugins = ("pytest_asyncio",) if _HAS_PYTEST_ASYNCIO else ()

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

# プロジェクトインポート
from main import app
from database import get_db_session, Base
from models import ConsentRecord, ConsentWithdrawal, AuditLog
from api.services.worm_service import EnhancedWORMManager, WORMConfig
from api.services.manifest_service import ManifestService
from api.services.lifecycle_service import ConsentLifecycleManager
from api.services.auto_deletion_service import AutoDeletionService
from config import settings

# ==================================================
# 非同期テスト用設定
# ==================================================

@pytest.fixture(scope="session")
def event_loop():
    """セッションスコープのイベントループ"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

# ==================================================
# データベーステストフィクスチャ
# ==================================================

@pytest_asyncio.fixture(scope="function")
async def test_db():
    """テスト用データベース（SQLiteメモリ）"""
    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # テーブル作成
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # セッションファクトリー
    TestSessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    yield TestSessionLocal

    # クリーンアップ
    await test_engine.dispose()

@pytest_asyncio.fixture
async def db_session(test_db):
    """データベースセッション"""
    async with test_db() as session:
        yield session

# ==================================================
# FastAPIテストクライアント
# ==================================================

@pytest.fixture
def client(test_db):
    """テストクライアント"""
    def override_get_db():
        async def _get_db():
            async with test_db() as session:
                yield session
        return _get_db()

    app.dependency_overrides[get_db_session] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()

# ==================================================
# モックサービス
# ==================================================

@pytest.fixture
def mock_worm_manager():
    """モックWORM管理者"""
    mock = AsyncMock(spec=EnhancedWORMManager)

    # デフォルトレスポンス設定
    mock.store_object.return_value = Mock(
        object_id="test_object_123",
        path="test/path",
        checksum="abc123",
    )

    mock.retrieve_object.return_value = (
        b"test content",
        Mock(object_id="test_object_123", checksum="abc123"),
    )

    mock.health_check.return_value = {"status": "healthy"}

    mock.verify_object_integrity.return_value = {
        "object_id": "test_object_123",
        "integrity_score": 1.0,
        "checksum_valid": True,
    }

    return mock

@pytest.fixture
def mock_manifest_service():
    """モックマニフェストサービス"""
    mock = AsyncMock(spec=ManifestService)

    mock.generate_daily_manifest.return_value = Mock(
        manifest_id="test_manifest_123",
        date=date.today().isoformat(),
        total_entries=100,
        compliance_verified=True,
    )

    return mock

@pytest.fixture
def mock_lifecycle_manager():
    """モックライフサイクル管理者"""
    mock = AsyncMock(spec=ConsentLifecycleManager)

    mock.process_daily_lifecycle.return_value = {
        "notifications_sent": 5,
        "consents_expired": 2,
        "renewals_processed": 1,
        "success": True,
    }

    return mock

@pytest.fixture
def mock_deletion_service():
    """モック削除サービス"""
    mock = AsyncMock(spec=AutoDeletionService)

    mock.scan_for_deletion_candidates.return_value = []
    mock.process_scheduled_deletions.return_value = {
        "processed_count": 0,
        "completed_count": 0,
        "failed_count": 0,
    }

    return mock

# ==================================================
# テストデータファクトリー
# ==================================================

class ConsentFactory:
    """同意データファクトリー"""

    @staticmethod
    def create_consent_data(**kwargs) -> Dict[str, Any]:
        """同意データ作成"""
        defaults = {
            "user_id": "test_user_123",
            "line_user_id": "line_user_456",
            "policy_version": "1.0",
            "tos_version": "1.0",
            "data_collection_consent": True,
            "data_usage_consent": True,
            "marketing_consent": False,
            "third_party_sharing_consent": False,
            "consent_method": "web_form",
            "user_agent": "Mozilla/5.0 Test",
            "ip_address": "192.168.1.100",
        }
        defaults.update(kwargs)
        return defaults

    @staticmethod
    async def create_consent_record(session: AsyncSession, **kwargs) -> ConsentRecord:
        """同意レコード作成"""
        from uuid import uuid4

        defaults = {
            "consent_id": str(uuid4()),
            "consented_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(days=365),
            "withdrawn": False,
            "is_immutable": True,
            "created_at": datetime.utcnow(),
        }
        defaults.update(ConsentFactory.create_consent_data())
        defaults.update(kwargs)

        consent = ConsentRecord(**defaults)
        session.add(consent)
        await session.commit()
        await session.refresh(consent)

        return consent

class WithdrawalFactory:
    """取り消しデータファクトリー"""

    @staticmethod
    async def create_withdrawal_record(
        session: AsyncSession,
        consent_id: str,
        **kwargs,
    ) -> ConsentWithdrawal:
        """取り消しレコード作成"""
        from uuid import uuid4

        defaults = {
            "withdrawal_id": str(uuid4()),
            "consent_id": consent_id,
            "user_id": "test_user_123",
            "withdrawn_at": datetime.utcnow(),
            "withdrawal_method": "user_request",
            "withdrawal_reason": "User requested withdrawal",
            "processed_by": "test",
            "created_at": datetime.utcnow(),
        }
        defaults.update(kwargs)

        withdrawal = ConsentWithdrawal(**defaults)
        session.add(withdrawal)
        await session.commit()
        await session.refresh(withdrawal)

        return withdrawal

class AuditLogFactory:
    """監査ログファクトリー"""

    @staticmethod
    async def create_audit_log(session: AsyncSession, **kwargs) -> AuditLog:
        """監査ログ作成"""
        from uuid import uuid4

        defaults = {
            "log_id": str(uuid4()),
            "table_name": "consent_records",
            "record_id": "test_record_123",
            "action_type": "CREATE",
            "action_description": "Test audit log",
            "actor_type": "user",
            "actor_id": "test_user_123",
            "success": True,
            "old_values": None,
            "new_values": {"test": "data"},
            "created_at": datetime.utcnow(),
        }
        defaults.update(kwargs)

        audit_log = AuditLog(**defaults)
        session.add(audit_log)
        await session.commit()
        await session.refresh(audit_log)

        return audit_log

# ==================================================
# テストデータセット
# ==================================================

@pytest_asyncio.fixture
async def sample_consent(db_session):
    """サンプル同意レコード"""
    return await ConsentFactory.create_consent_record(db_session)

@pytest_asyncio.fixture
async def expired_consent(db_session):
    """期限切れ同意レコード"""
    return await ConsentFactory.create_consent_record(
        db_session, expires_at=datetime.utcnow() - timedelta(days=1)
    )

@pytest_asyncio.fixture
async def withdrawn_consent(db_session):
    """取り消し済み同意レコード"""
    return await ConsentFactory.create_consent_record(
        db_session, withdrawn=True, withdrawn_at=datetime.utcnow() - timedelta(hours=1)
    )

@pytest_asyncio.fixture
async def sample_withdrawal(db_session, sample_consent):
    """サンプル取り消しレコード"""
    return await WithdrawalFactory.create_withdrawal_record(
        db_session, consent_id=sample_consent.consent_id
    )

@pytest_asyncio.fixture
async def sample_audit_logs(db_session):
    """サンプル監査ログ群"""
    logs = []
    for i in range(5):
        log = await AuditLogFactory.create_audit_log(
            db_session,
            action_type="CREATE" if i % 2 == 0 else "UPDATE",
            success=True if i < 4 else False,
        )
        logs.append(log)
    return logs

# ==================================================
# 設定モック
# ==================================================

@pytest.fixture
def mock_settings():
    """モック設定"""
    with patch("config.settings") as mock:
        mock.environment = "test"
        mock.database_url = "sqlite+aiosqlite:///:memory:"
        mock.encryption_key = "test-encryption-key"
        mock.secret_key = "test-secret-key"
        mock.notification_config = {"email_enabled": False, "line_enabled": False}
        yield mock

# ==================================================
# 外部サービスモック
# ==================================================

@pytest.fixture
def mock_email_service():
    """メールサービスモック"""
    with patch("utils.notification.send_email_notification") as mock:
        mock.return_value = True
        yield mock

@pytest.fixture
def mock_line_service():
    """LINEサービスモック"""
    with patch("utils.notification.send_line_notification") as mock:
        mock.return_value = True
        yield mock

@pytest.fixture
def mock_gcs_client():
    """GCSクライアントモック"""
    with patch("utils.gcs_client.gcs_client") as mock:
        mock.upload_file.return_value = "gs://test-bucket/test-file"
        mock.download_file.return_value = b"test content"
        yield mock

# ==================================================
# 統合テスト用フィクスチャ
# ==================================================

@pytest_asyncio.fixture
async def full_test_environment(
    test_db,
    mock_worm_manager,
    mock_settings,
    mock_email_service,
    mock_line_service,
):
    """完全テスト環境"""
    async with test_db() as session:
        consent = await ConsentFactory.create_consent_record(session)
        audit_log = await AuditLogFactory.create_audit_log(session)

        yield {
            "db_session": session,
            "consent": consent,
            "audit_log": audit_log,
            "worm_manager": mock_worm_manager,
        }

# ==================================================
# パフォーマンステスト用
# ==================================================

@pytest.fixture
def performance_test_data():
    """パフォーマンステスト用データ"""
    return {
        "bulk_consent_count": 100,
        "concurrent_requests": 10,
        "max_response_time_ms": 1000,
    }

# ==================================================
# セキュリティテスト用
# ==================================================

@pytest.fixture
def security_test_payloads():
    """セキュリティテスト用ペイロード"""
    return {
        "sql_injection": ["'; DROP TABLE consent_records; --", "1' OR '1'='1"],
        "xss_payloads": ["<script>alert('xss')</script>", "javascript:alert('xss')"],
        "oversized_data": "A" * 10000,
        "invalid_emails": ["not-an-email", "@domain.com", "user@"],
        "invalid_user_ids": ["", None, "   ", "user@domain", "../../../etc/passwd"],
    }

# ==================================================
# ヘルパー関数
# ==================================================

async def cleanup_test_data(session: AsyncSession):
    """テストデータクリーンアップ"""
    try:
        await session.execute(text("DELETE FROM audit_logs"))
        await session.execute(text("DELETE FROM consent_withdrawals"))
        await session.execute(text("DELETE FROM consent_records"))
        await session.commit()
    except Exception as e:
        await session.rollback()
        raise e

def assert_response_format(response_json: Dict[str, Any], expected_fields: list):
    """レスポンス形式アサーション"""
    for field in expected_fields:
        assert field in response_json, f"Expected field '{field}' not found in response"

def assert_error_response(response_json: Dict[str, Any], expected_error_code: str):
    """エラーレスポンスアサーション"""
    assert "error" in response_json
    assert "code" in response_json["error"]
    assert response_json["error"]["code"] == expected_error_code

# ==================================================
# カスタムマーカー
# ==================================================

# pytest.iniで定義するマーカー
pytestmark = [pytest.mark.asyncio]

# ==================================================
# テスト用定数
# ==================================================

TEST_USER_ID = "test_user_123"
TEST_LINE_USER_ID = "line_user_456"
TEST_CONSENT_ID = "consent_123"
TEST_EMAIL = "test@example.com"
TEST_POLICY_VERSION = "1.0"
TEST_TOS_VERSION = "1.0"
