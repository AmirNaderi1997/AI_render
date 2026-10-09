"""Async SQLAlchemy connection, disabled when DATABASE_URL is empty."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text

from app.config import settings
from app.models import Base


if settings.DATABASE_URL:
    engine = create_async_engine(settings.DATABASE_URL, pool_size=10, max_overflow=20)
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    DB_AVAILABLE = True
else:
    engine = None
    AsyncSessionLocal = None
    DB_AVAILABLE = False


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    if AsyncSessionLocal is None:
        raise RuntimeError("DATABASE_URL is not configured")
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
