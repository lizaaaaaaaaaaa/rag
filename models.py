# ====================
# models.py
# ====================

import uuid
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, Date, JSON, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from database import Base

class ConsentRecord(Base):
    """同意記録モデル"""
    __tablename__ = "consent_records"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), nullable=False, index=True)
    consent_type = Column(String(100), nullable=False)
    purpose = Column(Text, nullable=False)
    data_categories = Column(JSON, nullable=False)
    processing_basis = Column(String(100), nullable=False)
    retention_period = Column(Integer, nullable=False)  # days
    third_party_sharing = Column(Boolean, default=False)
    consent_text = Column(Text, nullable=False)
    consent_version = Column(String(50), nullable=False)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)
    withdrawal_date = Column(DateTime(timezone=True), nullable=True)
    
    __table_args__ = (
        Index('idx_consent_user_type', 'user_id', 'consent_type'),
        Index('idx_consent_timestamp', 'timestamp'),
    )

class ConsentWithdrawal(Base):
    """同意撤回記録モデル"""
    __tablename__ = "consent_withdrawals"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    consent_record_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    withdrawal_reason = Column(Text)
    withdrawal_method = Column(String(50), nullable=False)  # API, Web UI, Email
    ip_address = Column(String(45))
    user_agent = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    processing_status = Column(String(50), default='pending')  # pending, completed, failed
    deletion_completed_at = Column(DateTime(timezone=True), nullable=True)

class AuditLog(Base):
    """監査ログモデル"""
    __tablename__ = "audit_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_name = Column(String(100), nullable=False, index=True)
    record_id = Column(String(255), nullable=False, index=True)
    action_type = Column(String(50), nullable=False)  # CREATE, READ, UPDATE, DELETE
    user_id = Column(String(255), nullable=True, index=True)
    user_role = Column(String(50), nullable=True)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    old_values = Column(JSON)
    new_values = Column(JSON)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    compliance_hash = Column(String(64), nullable=False)  # SHA-256
    
    __table_args__ = (
        Index('idx_audit_table_action', 'table_name', 'action_type'),
        Index('idx_audit_timestamp', 'timestamp'),
    )

class DailyConsentStats(Base):
    """日次同意統計モデル"""
    __tablename__ = "daily_consent_stats"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date, nullable=False, unique=True, index=True)
    total_consents = Column(Integer, default=0)
    new_consents = Column(Integer, default=0)
    withdrawals = Column(Integer, default=0)
    active_consents = Column(Integer, default=0)
    consent_rate = Column(String(10))  # percentage as string
    stats_data = Column(JSON)  # 詳細統計データ
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class DocumentChunk(Base):
    """RAG用ドキュメントチャンクモデル"""
    __tablename__ = "document_chunks"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(String(255), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)  # SHA-256
    metadata = Column(JSON)
    embedding_vector = Column(JSON)  # Vector embeddings
    source_file = Column(String(500))
    gcs_path = Column(String(1000))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    __table_args__ = (
        Index('idx_doc_chunk_doc_id', 'document_id'),
        Index('idx_doc_chunk_hash', 'content_hash'),
    )

class QueryLog(Base):
    """クエリログモデル"""
    __tablename__ = "query_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), nullable=False, index=True)
    query_text = Column(Text, nullable=False)
    query_hash = Column(String(64), nullable=False)
    response_text = Column(Text)
    context_chunks = Column(JSON)  # 使用されたチャンク情報
    processing_time_ms = Column(Integer)
    tokens_used = Column(Integer)
    model_used = Column(String(100))
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    feedback_score = Column(Integer, nullable=True)  # 1-5 rating
    
    __table_args__ = (
        Index('idx_query_user_time', 'user_id', 'timestamp'),
        Index('idx_query_hash', 'query_hash'),