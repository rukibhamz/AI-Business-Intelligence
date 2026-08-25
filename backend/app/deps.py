from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User
from app.services.auth import decode_access_token, ensure_user_from_claims, is_admin
from app.services.supabase_auth import SupabaseAuthError, verify_token

bearer_scheme = HTTPBearer(auto_error=False)

UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def _rejected(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _user_from_supabase(token: str, db: AsyncSession) -> User:
    try:
        claims = await verify_token(token)
    except SupabaseAuthError as exc:
        raise _rejected(str(exc)) from None
    return await ensure_user_from_claims(db, claims)


async def _user_from_local_token(token: str, db: AsyncSession) -> User:
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub", "0"))
    except (JWTError, ValueError, TypeError):
        # `from None` keeps the token-decoding internals out of the response.
        raise _rejected("Invalid or expired token") from None

    user = await db.get(User, user_id)
    if not user:
        raise _rejected("User not found")
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """The account behind this request.

    Which token is expected depends on how the deployment is configured: a
    Supabase access token when a project is wired up, otherwise a token this
    service issued itself. Only one is accepted at a time — accepting both
    would leave the local password path open as a way around Supabase.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UNAUTHENTICATED

    if settings.supabase_enabled:
        return await _user_from_supabase(credentials.credentials, db)
    return await _user_from_local_token(credentials.credentials, db)


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Gate for the settings a normal member must not change.

    Admin is not a data privilege: it unlocks configuration, nothing else.
    Every account still sees only what it uploaded.
    """
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This setting is managed by an administrator.",
        )
    return current_user
