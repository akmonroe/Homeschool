import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine, _session_factory
    if not DATABASE_URL:
        return None
    if _engine is None:
        _engine = create_async_engine(
            DATABASE_URL,
            pool_pre_ping=True,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


def core_db_enabled() -> bool:
    return bool(DATABASE_URL)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    if _session_factory is None:
        get_engine()
    if _session_factory is None:
        raise RuntimeError("DATABASE_URL is not configured.")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
