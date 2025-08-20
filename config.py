# config.py - プロジェクトルートに配置
"""
設定管理モジュール
"""

import os
from typing import List, Optional, Dict, Any
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """アプリケーション設定"""
    
    # 基本設定
    app_name: str = "RAG-LLM Project"
    version: str = "1.0.0"
    debug: bool = Field(default=False, env="DEBUG")
    environment: str = Field(default="development", env="ENVIRONMENT")
    
    # データベース設定
    database_url: str = Field(
        default="sqlite+aiosqlite:///./rag_llm.db",
        env="DATABASE_URL"
    )
    database_pool_size: int = Field(default=5, env="DB_POOL_SIZE")
    database_max_overflow: int = Field(default=10, env="DB_MAX_OVERFLOW")
    database_pool_timeout: int = Field(default=30, env="DB_POOL_TIMEOUT")
    
    # Redis設定
    redis_url: str = Field(default="redis://localhost:6379/0", env="REDIS_URL")
    
    # セキュリティ設定
    secret_key: str = Field(
        default="your-secret-key-change-this-in-production",
        env="SECRET_KEY"
    )
    encryption_key: str = Field(
        default="default-encryption-key-change-this-in-production",
        env="ENCRYPTION_KEY"
    )
    salt: str = Field(default="default-salt-change-this", env="SALT")
    
    # JWT設定
    jwt_secret_key: str = Field(
        default="jwt-secret-key-change-this-in-production",
        env="JWT_SECRET_KEY"
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # Google Cloud設定
    gcp_project_id: str = Field(default="", env="GCP_PROJECT_ID")
    gcp_region: str = Field(default="asia-northeast1", env="GCP_REGION")
    gcs_bucket_name: str = Field(default="", env="GCS_BUCKET_NAME")
    gcs_audit_bucket: str = Field(default="", env="GCS_AUDIT_BUCKET")
    worm_bucket_name: str = Field(default="", env="WORM_BUCKET_NAME")
    kms_key_ring: str = Field(default="", env="KMS_KEY_RING")
    kms_key_name: str = Field(default="", env="KMS_KEY_NAME")
    
    # OpenAI設定
    openai_api_key: str = Field(default="", env="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4", env="OPENAI_MODEL")
    
    # セキュリティ設定
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
    
    # 機能フラグ
    enable_monitoring: bool = Field(default=False, env="ENABLE_MONITORING")
    worm_storage_enabled: bool = Field(default=True, env="WORM_STORAGE_ENABLED")
    
    # 通知設定
    notification_config: Dict[str, Any] = Field(
        default_factory=lambda: {
            "email_enabled": True,
            "line_enabled": False,
            "emergency_contacts": [],
            "smtp": {
                "host": "localhost",
                "port": 587,
                "use_tls": True,
                "username": "",
                "password": ""
            }
        }
    )
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def get_settings() -> Settings:
    """設定インスタンスを取得"""
    return Settings()