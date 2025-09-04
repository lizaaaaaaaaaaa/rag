"""
設定管理モジュール
環境変数とデフォルト値の管理（同意/WORM/LINE/法務URLを拡充）
"""

import os
from typing import List, Dict, Any, Optional
from functools import lru_cache
from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    """アプリケーション設定"""

    # 基本設定
    app_name: str = "RAG-LLM-Project"
    version: str = "1.0.0"
    environment: str = Field(default="development", env="ENVIRONMENT")
    debug: bool = Field(default=True, env="DEBUG")

    # データベース設定
    database_url: str = Field(
        default="sqlite+aiosqlite:///./rag_llm.db",
        env="DATABASE_URL"
    )

    # セキュリティ設定
    secret_key: str = Field(
        default="default-secret-key-change-this-in-production",
        env="SECRET_KEY"
    )
    encryption_key: str = Field(
        default="default-encryption-key-change-this-in-production",
        env="ENCRYPTION_KEY"
    )

    # API設定
    openai_api_key: str = Field(default="", env="OPENAI_API_KEY")

    # Google Cloud設定
    gcp_project_id: str = Field(default="", env="GCP_PROJECT_ID")
    gcp_region: str = Field(default="asia-northeast1", env="GCP_REGION")
    google_cloud_project: str = Field(default="", env="GOOGLE_CLOUD_PROJECT")

    # Cloud Storage設定
    gcs_bucket_name: str = Field(default="rag-llm-storage", env="GCS_BUCKET_NAME")
    gcs_audit_bucket: str = Field(default="rag-llm-audit", env="GCS_AUDIT_BUCKET")
    worm_bucket_name: str = Field(default="rag-llm-worm", env="WORM_BUCKET_NAME")
    worm_storage_enabled: bool = Field(default=True, env="WORM_STORAGE_ENABLED")
    # consent_gate.py 互換（GCS_CONSENT_BUCKET を見る実装のため）
    gcs_consent_bucket: str = Field(default="consent-logs-rag-cloud-project", env="GCS_CONSENT_BUCKET")

    # KMS設定
    kms_key_ring: str = Field(default="rag-llm-keyring", env="KMS_KEY_RING")
    kms_key_name: str = Field(default="rag-llm-key", env="KMS_KEY_NAME")
    # 互換: 直接キーを参照する実装向け
    kms_key: str = Field(default="", env="KMS_KEY")

    # Redis設定
    redis_url: str = Field(default="redis://localhost:6379", env="REDIS_URL")

    # LINE Bot設定
    line_channel_access_token: str = Field(default="", env="LINE_CHANNEL_ACCESS_TOKEN")
    line_channel_secret: str = Field(default="", env="LINE_CHANNEL_SECRET")
    # 追加: LINE Basic ID（LIFF同意戻りのOAメッセージ送信などで利用）
    line_basic_id: str = Field(default="", env="LINE_BASIC_ID")

    # CORS設定
    allowed_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        env="ALLOWED_ORIGINS"
    )
    allowed_hosts: List[str] = Field(
        default=["localhost", "127.0.0.1"],
        env="ALLOWED_HOSTS"
    )

    # レート制限
    rate_limit_per_minute: int = Field(default=100, env="RATE_LIMIT_PER_MINUTE")

    # 監視設定
    enable_monitoring: bool = Field(default=False, env="ENABLE_MONITORING")

    # 通知設定
    notification_config: Dict[str, Any] = Field(default_factory=dict)

    # ログ設定
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_file: Optional[str] = Field(default=None, env="LOG_FILE")

    # ===== 追加：同意/法務/WORM/公開URL =====
    # ポリシー版（同意キャッシュのバージョンキー）
    policy_version: str = Field(default="1.0.0", env="POLICY_VERSION")
    # 法務URL（LIFF同意モーダル・各通知で利用）
    privacy_url: str = Field(default="/legal/privacy", env="PRIVACY_URL")
    terms_url: str = Field(default="/legal/terms", env="TERMS_URL")
    cookie_url: str = Field(default="/legal/cookie", env="COOKIE_URL")
    # 公開ベースURL（Cloud Run などの外向けドメイン）
    public_base_url: str = Field(default="", env="PUBLIC_BASE_URL")
    # 同意の有効期間（月）・キャッシュTTL（秒）・WORM保持年数
    consent_validity_months: int = Field(default=12, env="CONSENT_VALIDITY_MONTHS")
    consent_cache_ttl_sec: int = Field(default=2_592_000, env="CONSENT_CACHE_TTL_SEC")  # 30日
    worm_retention_years: int = Field(default=5, env="WORM_RETENTION_YEARS")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """設定のシングルトンインスタンスを取得"""
    return Settings()


# デフォルトエクスポート
settings = get_settings()

# 通知設定の初期化（未指定時のみ）
if not settings.notification_config:
    settings.notification_config = {
        "email_enabled": True,
        "line_enabled": True,
        "smtp": {
            "host": os.getenv("SMTP_HOST", "localhost"),
            "port": int(os.getenv("SMTP_PORT", "587")),
            "username": os.getenv("SMTP_USERNAME", ""),
            "password": os.getenv("SMTP_PASSWORD", ""),
            "use_tls": os.getenv("SMTP_USE_TLS", "true").lower() == "true",
        },
        "line": {
            "channel_access_token": settings.line_channel_access_token,
            "channel_secret": settings.line_channel_secret,
        },
        "alert_recipients": [
            "admin@example.com"
        ],
        "emergency_contacts": [
            "emergency@example.com"
        ]
    }
