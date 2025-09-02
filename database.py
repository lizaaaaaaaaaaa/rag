# ====================
# database.py (Cloud Run / SQLite最適化版)
# ====================
#
# 変更点:
# - デフォルトDBを /tmp/consent_management.db に変更（Cloud Run の書き込み領域）
# - DATABASE_URL で上書き可能（未設定時は上記にフォールバック）
# - SQLite では NullPool を使用し、pool_size 等の引数は付けない
# - SQLite ファイルのディレクトリを自動作成
# - /health 用の接続チェックを text("SELECT 1") で実行

import os
import asyncio
from typing import AsyncGenerator, Dict, Any
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool


# 設定
def get_settings():
    class Settings:
        # Cloud Run では /tmp が書き込み可
        database_url = os.getenv(
            "DATABASE_URL",
            "sqlite+aiosqlite:////tmp/consent_management.db",
        )
        debug = os.getenv("DB_ECHO", "false").lower() == "true"
        database_pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
        database_max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "10"))
        database_pool_timeout = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    return Settings()


settings = get_settings()


def _is_sqlite(url: str) -> bool:
    # "sqlite", "sqlite+aiosqlite" を含むものをSQLiteと判定
    return url.startswith("sqlite")


def _ensure_sqlite_dir(url: str) -> None:
    """
    sqlite+aiosqlite:///relative.db   -> relative
    sqlite+aiosqlite:////abs/path.db  -> /abs/path.db
    sqlite+aiosqlite:///:memory:      -> 無視
    """
    if not _is_sqlite(url):
        return
    if ":memory:" in url:
        return

    # スキーマ部を除いてパスを抽出
    # 先頭の "sqlite+aiosqlite:///" を取り除く（絶対パスはスラッシュ4つ）
    parts = url.split(":///", 1)
    if len(parts) < 2:
        return
    path = parts[1]
    # Windows のような edge case は今回考慮不要（Cloud Run/Linux想定）
    dirpath = os.path.dirname(path)
    if dirpath and not os.path.exists(dirpath):
        os.makedirs(dirpath, exist_ok=True)


# SQLite の場合はファイル置き場を確保
_ensure_sqlite_dir(settings.database_url)

# エンジン作成（SQLiteはNullPool、他はpool設定を適用）
_engine_kwargs: Dict[str, Any] = {"echo": settings.debug}
if _is_sqlite(settings.database_url):
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs.update(
        {
            "pool_size": settings.database_pool_size,
            "max_overflow": settings.database_max_overflow,
            "pool_timeout": settings.database_pool_timeout,
        }
    )

engine = create_async_engine(settings.database_url, **_engine_kwargs)

# セッションファクトリー
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ベースモデル
Base = declarative_base()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """依存性注入用のDBセッション"""
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
    """テーブル作成（初期化）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_database():
    """DBクローズ"""
    await engine.dispose()


async def create_tables():
    """テーブル作成（明示呼び出し用）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables():
    """テーブル削除（開発・テスト用）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def check_db_connection() -> bool:
    """接続チェック（/health 用）"""
    try:
        async with get_db_context() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        # ログはここで吐かず、呼び出し側で扱うことを想定
        return False
