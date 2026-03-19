"""
Async SQLAlchemy engine and session factory.

Design notes:
- asyncpg driver for high-throughput async I/O.
- expire_on_commit=False so ORM objects remain readable after commit
  without re-querying inside async context.
- pool_size / max_overflow tuned for a single-service deployment;
  increase for Kubernetes multi-replica.
"""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    echo=(settings.app_env == "development"),  # SQL logging in dev only
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # discard stale connections silently
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a transactional DB session.
    Commits on success, rolls back on exception, always closes.
    """
    session: AsyncSession = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_raw_session() -> AsyncSession:
    """
    Returns a session for use outside FastAPI's dependency injection
    (e.g., ingestion pipeline, CLI).  Caller is responsible for
    committing/rolling back/closing.
    """
    return AsyncSessionLocal()
