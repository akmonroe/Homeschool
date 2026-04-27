"""Shared FastAPI dependencies for Postgres-backed features."""

from collections.abc import AsyncIterator

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import core_db_enabled, session_scope


async def get_core_pg_session() -> AsyncIterator[AsyncSession]:
    if not core_db_enabled():
        raise HTTPException(
            status_code=503,
            detail="Core database is not configured. Set DATABASE_URL (postgresql+asyncpg://...).",
        )
    async with session_scope() as session:
        yield session
