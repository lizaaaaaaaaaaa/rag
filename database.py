# ====================
# database.py
# ====================

import asyncio
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from contextlib import asynccontextmanager

# 設定を読み込むためのダミー関数（実際のconfig.pyがない場合）
def get_settings():
    class Settings:
        database_url = "sqlite+aiosqlite:///./consent_management.db"
        debug = True
        database_pool_size = 5
        database_max_overflow = 10
        database_pool_timeout = 30
    return Settings()

settings = get_settings()

# データベースエンジンの作成
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout,
    poolclass=NullPool if "sqlite" in settings.database_url else None
)

# セッションファクトリーの作成
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# ベースモデルクラス
Base = declarative_base()

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """データベースセッションの依存性注入"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

@asynccontextmanager
async def get_db_context():
    """コンテキストマネージャー形式でのDB操作"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

async def init_database():
    """データベース初期化"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def close_database():
    """データベース接続を閉じる"""
    await engine.dispose()

async def create_tables():
    """テーブル作成"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def drop_tables():
    """テーブル削除（開発・テスト用）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

async def check_db_connection():
    """データベース接続チェック"""
    try:
        async with get_db_context() as session:
            await session.execute("SELECT 1")
        return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False