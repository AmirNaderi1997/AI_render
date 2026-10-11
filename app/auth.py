"""Authentication module: user registration, JWT tokens, password reset."""
from __future__ import annotations
import hashlib
import json
import logging
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import AsyncSessionLocal, DB_AVAILABLE
from app.models import UserModel

log = logging.getLogger(__name__)
USE_DB = DB_AVAILABLE

USERS_FILE = Path(__file__).resolve().parent.parent / "jobs" / "users.json"
JWT_SECRET_FILE = Path(__file__).resolve().parent.parent / ".jwt_secret"
ACCESS_TOKEN_EXPIRES = settings.JWT_ACCESS_HOURS * 3600
REFRESH_TOKEN_EXPIRES = settings.JWT_REFRESH_DAYS * 24 * 3600
RESET_TOKEN_EXPIRES = 3600                # 1 hour
JWT_ALGORITHM = "HS256"


def _jwt_secret() -> str:
    env = settings.JWT_SECRET or os.environ.get("JWT_SECRET")
    if env:
        return env
    if JWT_SECRET_FILE.exists():
        return JWT_SECRET_FILE.read_text().strip()
    secret = secrets.token_hex(32)
    JWT_SECRET_FILE.write_text(secret)
    return secret


_secret: Optional[str] = None


def jwt_secret() -> str:
    global _secret
    if _secret is None:
        _secret = _jwt_secret()
    return _secret


@dataclass
class User:
    id: str
    email: str
    name: str
    password_hash: str
    created_at: float
    is_active: bool = True
    reset_token: Optional[str] = None
    reset_expires: Optional[float] = None
    refresh_tokens: list[str] | None = None

    def public_dict(self) -> dict:
        return {"id": self.id, "email": self.email, "name": self.name}


def _load_users() -> dict[str, dict]:
    if not USERS_FILE.exists():
        return {}
    try:
        return json.loads(USERS_FILE.read_text())
    except Exception:
        return {}


def _save_users(users: dict[str, dict]) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2))


def _user_from_dict(d: dict) -> User:
    return User(
        id=d["id"], email=d["email"], name=d["name"],
        password_hash=d["password_hash"], created_at=d["created_at"],
        is_active=d.get("is_active", True),
        reset_token=d.get("reset_token"),
        reset_expires=d.get("reset_expires"),
        refresh_tokens=d.get("refresh_tokens"),
    )


def _user_to_dict(u: User) -> dict:
    d = asdict(u)
    return d


def _find_by_email(email: str) -> Optional[User]:
    users = _load_users()
    for u in users.values():
        if u["email"].lower() == email.lower():
            return _user_from_dict(u)
    return None


def _find_by_id(uid: str) -> Optional[User]:
    users = _load_users()
    d = users.get(uid)
    return _user_from_dict(d) if d else None


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def register(email: str, name: str, password: str) -> User:
    email = email.strip().lower()
    name = name.strip()
    if not EMAIL_RE.match(email):
        raise ValueError("Invalid email format")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not name:
        raise ValueError("Name is required")
    if _find_by_email(email):
        raise ValueError("DUPLICATE_EMAIL")

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user = User(
        id=uuid.uuid4().hex[:16],
        email=email,
        name=name,
        password_hash=pw_hash,
        created_at=time.time(),
    )
    users = _load_users()
    users[user.id] = _user_to_dict(user)
    _save_users(users)
    return user


def _create_access_token(user_id: str, email: str, name: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "exp": time.time() + ACCESS_TOKEN_EXPIRES,
        "type": "access",
    }
    return jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM)


def _create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": time.time() + REFRESH_TOKEN_EXPIRES,
        "type": "refresh",
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM)


def login(email: str, password: str) -> dict:
    user = _find_by_email(email.strip().lower())
    if not user:
        raise ValueError("INVALID_CREDENTIALS")
    if not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
        raise ValueError("INVALID_CREDENTIALS")
    if not user.is_active:
        raise ValueError("ACCOUNT_DISABLED")

    access = _create_access_token(user.id, user.email, user.name)
    refresh = _create_refresh_token(user.id)

    users = _load_users()
    u = users[user.id]
    tokens = u.get("refresh_tokens") or []
    tokens.append(refresh)
    if len(tokens) > 10:
        tokens = tokens[-10:]
    u["refresh_tokens"] = tokens
    _save_users(users)

    return {"access_token": access, "refresh_token": refresh, "user": user.public_dict()}


def verify_token(token: str) -> str:
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise ValueError("TOKEN_EXPIRED")
    except jwt.InvalidTokenError:
        raise ValueError("TOKEN_INVALID")
    if payload.get("type") != "access":
        raise ValueError("TOKEN_INVALID")
    return payload["sub"]


def refresh(refresh_token: str) -> dict:
    try:
        payload = jwt.decode(refresh_token, jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise ValueError("REFRESH_EXPIRED")
    except jwt.InvalidTokenError:
        raise ValueError("REFRESH_INVALID")
    if payload.get("type") != "refresh":
        raise ValueError("REFRESH_INVALID")

    user_id = payload["sub"]
    user = _find_by_id(user_id)
    if not user:
        raise ValueError("USER_NOT_FOUND")

    users = _load_users()
    stored_tokens = users.get(user_id, {}).get("refresh_tokens") or []
    if refresh_token not in stored_tokens:
        raise ValueError("REFRESH_INVALID")

    access = _create_access_token(user.id, user.email, user.name)
    return {"access_token": access}


def logout(refresh_token: str) -> None:
    try:
        payload = jwt.decode(refresh_token, jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return
    user_id = payload.get("sub")
    if not user_id:
        return
    users = _load_users()
    u = users.get(user_id)
    if u:
        tokens = u.get("refresh_tokens") or []
        if refresh_token in tokens:
            tokens.remove(refresh_token)
            u["refresh_tokens"] = tokens
            _save_users(users)


def request_reset(email: str) -> Optional[str]:
    user = _find_by_email(email.strip().lower())
    if not user:
        return None
    token = secrets.token_hex(32)
    users = _load_users()
    users[user.id]["reset_token"] = token
    users[user.id]["reset_expires"] = time.time() + RESET_TOKEN_EXPIRES
    _save_users(users)
    return token


def reset_password(token: str, new_password: str) -> None:
    if len(new_password) < 8:
        raise ValueError("Password must be at least 8 characters")
    users = _load_users()
    for uid, u in users.items():
        if u.get("reset_token") == token:
            if (u.get("reset_expires") or 0) < time.time():
                raise ValueError("RESET_TOKEN_EXPIRED")
            u["password_hash"] = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
            u["reset_token"] = None
            u["reset_expires"] = None
            _save_users(users)
            return
    raise ValueError("RESET_TOKEN_INVALID")


def get_current_user_from_token(token: str) -> User:
    user_id = verify_token(token)
    user = _find_by_id(user_id)
    if not user:
        raise ValueError("USER_NOT_FOUND")
    return user


def _db_user(row: UserModel) -> User:
    return User(
        id=str(row.id), email=row.email, name=row.name,
        password_hash=row.password_hash, created_at=float(row.created_at),
        is_active=row.is_active, reset_token=row.reset_token,
        reset_expires=row.reset_expires, refresh_tokens=row.refresh_tokens,
    )


def _db_sessions():
    if AsyncSessionLocal is None:
        raise RuntimeError("DATABASE_URL is not configured")
    return AsyncSessionLocal


async def db_get_user(email: str) -> Optional[User]:
    async with _db_sessions()() as session:
        row = await session.scalar(select(UserModel).where(UserModel.email == email.strip().lower()))
        return _db_user(row) if row else None


async def db_create_user(email: str, name: str, pw_hash: str) -> User:
    async with _db_sessions()() as session:
        row = UserModel(
            email=email.strip().lower(), name=name.strip(), password_hash=pw_hash,
            created_at=str(time.time()),
        )
        session.add(row)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise ValueError("DUPLICATE_EMAIL") from exc
        await session.refresh(row)
        return _db_user(row)


async def db_list_users() -> list[User]:
    async with _db_sessions()() as session:
        rows = (await session.scalars(select(UserModel).order_by(UserModel.id))).all()
        return [_db_user(row) for row in rows]


async def db_get_user_by_id(user_id: str) -> Optional[User]:
    if not user_id.isdecimal():
        return None
    async with _db_sessions()() as session:
        row = await session.get(UserModel, int(user_id))
        return _db_user(row) if row else None


async def db_register(email: str, name: str, password: str) -> User:
    email = email.strip().lower()
    name = name.strip()
    if not EMAIL_RE.match(email):
        raise ValueError("Invalid email format")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not name:
        raise ValueError("Name is required")
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    return await db_create_user(email, name, pw_hash)


async def db_login(email: str, password: str) -> dict:
    async with _db_sessions()() as session:
        row = await session.scalar(select(UserModel).where(UserModel.email == email.strip().lower()))
        if not row or not bcrypt.checkpw(password.encode(), row.password_hash.encode()):
            raise ValueError("INVALID_CREDENTIALS")
        if not row.is_active:
            raise ValueError("ACCOUNT_DISABLED")
        user = _db_user(row)
        access = _create_access_token(user.id, user.email, user.name)
        refresh_token = _create_refresh_token(user.id)
        row.refresh_tokens = [*(row.refresh_tokens or []), refresh_token][-10:]
        await session.commit()
        return {"access_token": access, "refresh_token": refresh_token, "user": user.public_dict()}


async def db_refresh(refresh_token: str) -> dict:
    try:
        payload = jwt.decode(refresh_token, jwt_secret(), algorithms=[JWT_ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as exc:
        raise ValueError("REFRESH_INVALID") from exc
    if payload.get("type") != "refresh" or not str(payload.get("sub", "")).isdecimal():
        raise ValueError("REFRESH_INVALID")
    async with _db_sessions()() as session:
        row = await session.get(UserModel, int(payload["sub"]))
        if not row or refresh_token not in (row.refresh_tokens or []):
            raise ValueError("REFRESH_INVALID")
        return {"access_token": _create_access_token(str(row.id), row.email, row.name)}


async def db_logout(refresh_token: str) -> None:
    try:
        payload = jwt.decode(refresh_token, jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return
    if not str(payload.get("sub", "")).isdecimal():
        return
    async with _db_sessions()() as session:
        row = await session.get(UserModel, int(payload["sub"]))
        if row and refresh_token in (row.refresh_tokens or []):
            row.refresh_tokens = [token for token in row.refresh_tokens if token != refresh_token]
            await session.commit()


async def db_request_reset(email: str) -> Optional[str]:
    async with _db_sessions()() as session:
        row = await session.scalar(select(UserModel).where(UserModel.email == email.strip().lower()))
        if not row:
            return None
        token = secrets.token_hex(32)
        row.reset_token = token
        row.reset_expires = time.time() + RESET_TOKEN_EXPIRES
        await session.commit()
        return token


async def db_reset_password(token: str, new_password: str) -> None:
    if len(new_password) < 8:
        raise ValueError("Password must be at least 8 characters")
    async with _db_sessions()() as session:
        row = await session.scalar(select(UserModel).where(UserModel.reset_token == token))
        if not row:
            raise ValueError("RESET_TOKEN_INVALID")
        if (row.reset_expires or 0) < time.time():
            raise ValueError("RESET_TOKEN_EXPIRED")
        row.password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        row.reset_token = None
        row.reset_expires = None
        await session.commit()


async def db_get_current_user_from_token(token: str) -> User:
    user = await db_get_user_by_id(verify_token(token))
    if not user:
        raise ValueError("USER_NOT_FOUND")
    return user
