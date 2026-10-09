"""Refuse to apply the initial migration over unstamped application tables."""
import asyncio

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings


async def main() -> None:
    if not settings.DATABASE_URL:
        raise SystemExit("DATABASE_URL is required for migration preflight")
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as connection:
            tables = set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))
            stamped = bool((await connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))).first()) if "alembic_version" in tables else False
    finally:
        await engine.dispose()
    if not stamped and tables.intersection(
        {"users", "jobs", "style_profiles", "content_requests"}
    ):
        raise SystemExit(
            "Existing application tables have no Alembic version. Back up and reconcile schema before deployment."
        )


if __name__ == "__main__":
    asyncio.run(main())
