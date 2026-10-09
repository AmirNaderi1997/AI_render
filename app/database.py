"""Async SQLAlchemy connection, disabled when DATABASE_URL is empty."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy import text

from app.config import settings
from app.models import Base


if settings.DATABASE_URL:
    # Requests, Celery workers, and legacy synchronous render callbacks can
    # legitimately use different event loops. NullPool prevents asyncpg
    # connections created in one loop from being reused in another.
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    DB_AVAILABLE = True
else:
    engine = None
    AsyncSessionLocal = None
    DB_AVAILABLE = False


async def get_db() -> AsyncGenerator[AsyncSession | None, None]:
    if AsyncSessionLocal is None:
        # Development/test fallback has no durable store; production startup
        # rejects this configuration before requests are served.
        yield None
        return
    async with AsyncSessionLocal() as session:
        yield session


async def init_db(*, create_schema: bool = True) -> None:
    if engine is None:
        return
    async with engine.begin() as conn:
        if create_schema:
            await conn.run_sync(Base.metadata.create_all)
        else:
            await conn.execute(text("SELECT 1"))


async def close_db() -> None:
    if engine is not None:
        await engine.dispose()
