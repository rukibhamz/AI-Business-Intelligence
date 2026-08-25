"""Supabase sign-in: token verification and account provisioning.

The token is the only thing standing between a request and someone else's
datasets, so these cover the ways one can be wrong as well as the way it is
right.
"""

from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt

from app.config import settings
from app.services import supabase_auth
from app.services.supabase_auth import AUDIENCE, SupabaseAuthError, verify_token

SECRET = "test-supabase-jwt-secret-long-enough-to-sign"


def token(**overrides) -> str:
    payload = {
        "sub": "11111111-2222-3333-4444-555555555555",
        "email": "member@nexasphere.test",
        "aud": AUDIENCE,
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "user_metadata": {"full_name": "Ada Member"},
    }
    payload.update(overrides)
    return jwt.encode(payload, SECRET, algorithm="HS256")


@pytest.fixture(autouse=True)
def supabase_configured(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")
    monkeypatch.setattr(settings, "supabase_jwt_secret", SECRET)
    supabase_auth.reset_key_cache()
    yield
    supabase_auth.reset_key_cache()


# --- verification -----------------------------------------------------------


async def test_a_valid_token_yields_its_claims():
    claims = await verify_token(token())
    assert claims.subject == "11111111-2222-3333-4444-555555555555"
    assert claims.email == "member@nexasphere.test"
    assert claims.full_name == "Ada Member"


async def test_a_token_signed_with_another_secret_is_rejected():
    forged = jwt.encode(
        {
            "sub": "attacker",
            "email": "attacker@example.com",
            "aud": AUDIENCE,
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        "not-the-project-secret",
        algorithm="HS256",
    )
    with pytest.raises(SupabaseAuthError):
        await verify_token(forged)


async def test_an_expired_token_is_rejected():
    with pytest.raises(SupabaseAuthError):
        await verify_token(token(exp=datetime.now(UTC) - timedelta(minutes=1)))


async def test_a_token_for_another_audience_is_rejected():
    """A service-role or anon token must not pass as a signed-in user."""
    with pytest.raises(SupabaseAuthError):
        await verify_token(token(aud="anon"))


async def test_a_token_without_an_email_is_rejected():
    with pytest.raises(SupabaseAuthError):
        await verify_token(token(email="", user_metadata={}))


async def test_garbage_is_rejected():
    for value in ("", "not-a-jwt", "a.b.c"):
        with pytest.raises(SupabaseAuthError):
            await verify_token(value)


async def test_hs256_without_a_configured_secret_says_so(monkeypatch):
    monkeypatch.setattr(settings, "supabase_jwt_secret", "")
    with pytest.raises(SupabaseAuthError) as exc:
        await verify_token(token())
    assert "SUPABASE_JWT_SECRET" in str(exc.value)


async def test_email_is_normalised():
    claims = await verify_token(token(email="  Mixed.Case@NexaSphere.test "))
    assert claims.email == "mixed.case@nexasphere.test"


# --- the provider switch ----------------------------------------------------


def test_supabase_is_off_until_both_values_are_set(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "")
    assert settings.supabase_enabled is False
    assert settings.auth_provider == "local"

    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")
    assert settings.supabase_enabled is True
    assert settings.auth_provider == "supabase"
