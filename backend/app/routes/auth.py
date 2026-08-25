from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import AuthConfig, LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.auth import (
    authenticate_user,
    count_users,
    create_access_token,
    create_user,
    get_user_by_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/config", response_model=AuthConfig)
async def auth_config() -> AuthConfig:
    """How to sign in to this deployment.

    Called before the login screen renders, so the browser knows whether to
    talk to Supabase or to this service. Unauthenticated by necessity — and it
    exposes nothing private: the anon key is meant for the browser.
    """
    return AuthConfig(
        provider=settings.auth_provider,
        supabase_url=settings.supabase_url if settings.supabase_enabled else "",
        supabase_anon_key=settings.supabase_anon_key if settings.supabase_enabled else "",
        # Local mode only ever allows the one bootstrap account.
        allow_signup=settings.supabase_enabled,
    )


def _reject_when_supabase_runs_auth() -> None:
    """Local password endpoints must close when Supabase is in charge.

    Leaving them open would be a second front door with different rules.
    """
    if settings.supabase_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This workspace signs in through Supabase. Create the account "
                "there instead of on this endpoint."
            ),
        )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)) -> User:
    """Bootstrap registration — only allowed when no users exist yet."""
    _reject_when_supabase_runs_auth()
    if await count_users(db) > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is closed. Ask an admin for access.",
        )

    existing = await get_user_by_email(db, payload.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    return await create_user(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    _reject_when_supabase_runs_auth()
    user = await authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    token = create_access_token(user_id=user.id, email=user.email)
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
