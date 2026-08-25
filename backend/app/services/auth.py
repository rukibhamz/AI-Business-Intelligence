from __future__ import annotations

from datetime import UTC, datetime, timedelta

import bcrypt
from jose import jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import User

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(*, user_id: int, email: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "email": email, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    user = await get_user_by_email(db, email.lower().strip())
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


async def create_user(
    db: AsyncSession, *, email: str, password: str, full_name: str | None = None
) -> User:
    user = User(
        email=email.lower().strip(),
        hashed_password=hash_password(password),
        full_name=full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def count_users(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(User))
    return int(result.scalar_one())


async def ensure_bootstrap_admin(db: AsyncSession) -> None:
    """Create the default admin account if the users table is empty."""
    if await count_users(db) > 0:
        return
    email = settings.admin_email.strip().lower()
    if not email or not settings.admin_password:
        return
    await create_user(
        db,
        email=email,
        password=settings.admin_password,
        full_name=settings.admin_full_name,
    )
