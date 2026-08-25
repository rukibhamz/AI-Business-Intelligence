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
    # A Supabase-provisioned account carries no local password. An empty hash
    # must never authenticate, whatever is typed against it.
    if not user or not user.hashed_password:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


ADMIN = "admin"
MEMBER = "member"


def is_admin(user: User) -> bool:
    return user.is_admin


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str | None = None,
    role: str = MEMBER,
) -> User:
    user = User(
        email=email.lower().strip(),
        hashed_password=hash_password(password),
        full_name=full_name,
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def count_users(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(User))
    return int(result.scalar_one())


async def ensure_bootstrap_admin(db: AsyncSession) -> None:
    """Create the default admin account if the users table is empty.

    Skipped when Supabase is running sign-in: accounts come from there, and a
    local account with a password would be a way around it.
    """
    if settings.supabase_enabled:
        return
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
        role=ADMIN,
    )


async def count_admins(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).select_from(User).where(User.role == ADMIN)
    )
    return int(result.scalar_one())


async def get_user_by_supabase_id(db: AsyncSession, subject: str) -> User | None:
    result = await db.execute(select(User).where(User.supabase_id == subject))
    return result.scalar_one_or_none()


async def ensure_user_from_claims(db: AsyncSession, claims) -> User:
    """Find or create the local account behind a verified Supabase token.

    Sign-up happens in Supabase, so the first time someone arrives with a valid
    token there is no local row to attach their uploads to. This creates one.

    Who becomes an admin: the address in ADMIN_EMAIL, and — so a fresh
    deployment is never locked out of Settings — whoever signs in first.
    """
    user = await get_user_by_supabase_id(db, claims.subject)

    if user is None:
        # An address that already exists locally (the bootstrap admin, say) is
        # claimed rather than duplicated: same person, new identity provider.
        user = await get_user_by_email(db, claims.email)
        if user is not None:
            user.supabase_id = claims.subject

    admin_email = settings.admin_email.strip().lower()
    if user is None:
        first_ever = await count_admins(db) == 0
        role = ADMIN if (claims.email == admin_email or first_ever) else MEMBER
        user = User(
            email=claims.email,
            hashed_password="",
            full_name=claims.full_name,
            supabase_id=claims.subject,
            role=role,
        )
        db.add(user)
    else:
        if claims.email and user.email != claims.email:
            user.email = claims.email
        if claims.full_name and not user.full_name:
            user.full_name = claims.full_name
        if claims.email == admin_email and not is_admin(user):
            user.role = ADMIN

    await db.commit()
    await db.refresh(user)
    return user
