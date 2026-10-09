"""Small async repository with PostgreSQL and atomic local JSON modes."""
import json
import os
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hermes.config import settings
from hermes.models import TABLES

_engine = create_async_engine(settings.DATABASE_URL) if settings.DATABASE_URL else None
Session = async_sessionmaker(_engine, expire_on_commit=False) if _engine else None
_lock = threading.RLock()


async def init_db(*, create_schema=True):
    if _engine:
        async with _engine.begin() as conn:
            if create_schema:
                await conn.run_sync(lambda sync: TABLES["accounts"].metadata.create_all(
                    sync, tables=[model.__table__ for model in TABLES.values()]))
            else:
                await conn.execute(text("SELECT 1"))


def _path():
    return Path(settings.HERMES_DATA_DIR) / "data.json"


def _read():
    path = _path()
    return json.loads(path.read_text()) if path.exists() else {name: {} for name in TABLES}


def _write(data):
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.chmod(0o600)
    os.replace(tmp, path)


def _serial(row):
    return {column.name: (value.isoformat() if isinstance(value, (date, datetime)) else value)
            for column in row.__table__.columns if (value := getattr(row, column.name)) is not None} | {
                column.name: None for column in row.__table__.columns if getattr(row, column.name) is None}


def _db_value(column, value):
    if value is not None and isinstance(value, str):
        if column.type.__class__.__name__ == "DateTime":
            return datetime.fromisoformat(value)
        if column.type.__class__.__name__ == "Date":
            return date.fromisoformat(value)
    return value


async def list_rows(table):
    if Session:
        async with Session() as session:
            rows = (await session.scalars(select(TABLES[table]))).all()
            return [_serial(row) for row in rows]
    with _lock:
        return list(_read().get(table, {}).values())


async def get_row(table, row_id):
    if Session:
        async with Session() as session:
            row = await session.get(TABLES[table], row_id)
            return _serial(row) if row else None
    with _lock:
        return _read().get(table, {}).get(row_id)


async def save_row(table, data):
    data = dict(data)
    if Session:
        model = TABLES[table]
        async with Session() as session:
            row = await session.get(model, data["id"])
            if row is None:
                row = model(id=data["id"])
                session.add(row)
            for key, value in data.items():
                if key != "id":
                    setattr(row, key, _db_value(model.__table__.columns[key], value))
            await session.commit()
            return _serial(row)
    with _lock:
        all_data = _read()
        all_data.setdefault(table, {})[data["id"]] = data
        _write(all_data)
    return data


async def delete_row(table, row_id):
    if Session:
        async with Session() as session:
            row = await session.get(TABLES[table], row_id)
            if row:
                await session.delete(row)
                await session.commit()
                return True
            return False
    with _lock:
        all_data = _read()
        found = all_data.setdefault(table, {}).pop(row_id, None) is not None
        if found:
            _write(all_data)
        return found


async def claim_post(row_id, statuses):
    """Atomic claim prevents a beat worker and a manual request publishing twice."""
    if Session:
        model = TABLES["posts"]
        async with Session() as session:
            result = await session.execute(update(model).where(model.id == row_id, model.status.in_(statuses)).values(status="publishing"))
            await session.commit()
            return result.rowcount == 1
    with _lock:
        data = _read()
        row = data.setdefault("posts", {}).get(row_id)
        if not row or row["status"] not in statuses:
            return False
        row["status"] = "publishing"
        _write(data)
        return True
