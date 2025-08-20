# ====================
# config.py
# ====================

import os
from typing import Optional
from pydantic import BaseSettings, validator
from functools import lru_cache

class Settings(BaseSettings):
    """アプリケーション設定"""
    
    # アプリケーション基本設定
    app_name: str = "RAG-LLM-Project"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = "production"
    
    # データベース設定
    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout: int = 30
    
    # Google Cloud設定
    google_cloud_project: str
    gcs_bucket_name: str
    gcs_audit_bucket: str
    gcs_service_account_path: Optional[str] = None
    
    # Vector Store設定
    vector_store_type: str = "chroma"  # chroma, pinecone, weaviate
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    embedding_model: str = "text-embedding-ada-002"
    
    # OpenAI/LLM設定
    openai_api_key: str
    llm_model: str = "gpt-4-turbo-preview"
    max_tokens: int = 4000
    temperature: float = 0.1
    
    # 認証・セキュリティ設定
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # 暗号化設定
    encryption_key: str
    salt: str
    
    # 監査設定
    audit_retention_days: int = 2555  # 7年
    worm_storage_enabled: bool = True
    compliance_checks_enabled: bool = True
    
    # 通知設定
    notification_webhook_url: Optional[str] = None
    slack_webhook_url: Optional[str] = None
    email_smtp_server: Optional[str] = None
    email_username: Optional[str] = None
    email_password: Optional[str] = None
    
    # Redis設定（キャッシュ用）
    redis_url: str = "redis://localhost:6379"
    cache_ttl_seconds: int = 3600
    
    # APIレート制限
    rate_limit_per_minute: int = 100
    
    @validator('database_url', pre=True)
    def validate_database_url(cls, v):
        if not v:
            raise ValueError('DATABASE_URL is required')
        return v
    
    @validator('secret_key', pre=True)
    def validate_secret_key(cls, v):
        if not v or len(v) < 32:
            raise ValueError('SECRET_KEY must be at least 32 characters')
        return v
    
    class Config:
        env_file = ".env"
        case_sensitive = False

@lru_cache()
def get_settings() -> Settings:
    """設定のシングルトンインスタンスを取得"""
    return Settings()