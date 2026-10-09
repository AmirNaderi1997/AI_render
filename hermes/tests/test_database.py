"""Exercise the SQLAlchemy path without requiring PostgreSQL in local tests."""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import UserModel
from hermes import database
from hermes.config import settings
from hermes.models import TABLES
from hermes.security import encrypt_token


def test_async_sql_repository(client, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(database, "Session", async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    async def exercise():
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync: UserModel.__table__.create(sync))
        await database.init_db()
        async with database.Session() as session:
            session.add(UserModel(id=1, email="u@example.com", name="U", password_hash="x", created_at="0"))
            await session.commit()
        now = datetime.now(timezone.utc)
        account = {
            "id": "account-db", "user_id": 1, "ig_user_id": "ig-db", "username": "db",
            "access_token": encrypt_token("secret"), "token_expires_at": (now + timedelta(days=1)).isoformat(),
            "created_at": now.isoformat(), "updated_at": now.isoformat(),
        }
        await database.save_row("accounts", account)
        await database.save_row("posts", {
            "id": "post-db", "account_id": account["id"], "caption": "", "hashtags": [],
            "media_urls": ["https://example.com/a.jpg"], "scheduled_at": now.isoformat(),
            "posted_at": None, "status": "scheduled", "ig_post_id": None,
            "error_message": None, "created_at": now.isoformat(),
        })
        assert (await database.get_row("accounts", "account-db"))["username"] == "db"
        assert len(await database.list_rows("posts")) == 1
        assert await database.claim_post("post-db", ("scheduled",)) is True
        assert await database.claim_post("post-db", ("scheduled",)) is False
        assert await database.delete_row("posts", "post-db") is True
        await engine.dispose()

    asyncio.run(exercise())
