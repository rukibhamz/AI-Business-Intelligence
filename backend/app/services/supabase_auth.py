"""Verify Supabase access tokens.

Supabase issues the JWT; this service only checks it. Two signing schemes are
in the wild and a project can be on either, so both are supported:

* **Shared secret (HS256)** — the legacy "JWT Secret" from the project's API
  settings. Set `SUPABASE_JWT_SECRET` and verification is offline.
* **Signing keys (RS256/ES256)** — the current default. Nothing is configured
  beyond `SUPABASE_URL`; the public keys come from the project's JWKS endpoint
  and are cached until an unknown key id shows up.

Nothing here trusts a claim it has not verified: an unsigned or expired token
is rejected before the caller ever sees an email address.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
from jose import jwt
from jose.exceptions import JWTError

from app.config import settings

#: Supabase stamps every logged-in user's token with this audience.
AUDIENCE = "authenticated"

#: How long a fetched key set is trusted before it is refreshed anyway.
JWKS_TTL_SECONDS = 3600


class SupabaseAuthError(Exception):
    """The token is missing, malformed, expired, or not signed by the project."""


@dataclass
class SupabaseClaims:
    """The parts of a verified token this application acts on."""

    subject: str
    email: str
    full_name: str | None = None

    @property
    def is_usable(self) -> bool:
        return bool(self.subject and self.email)


class _JwksCache:
    """Public keys for the project, refetched when a new key id appears."""

    def __init__(self) -> None:
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at: float = 0.0

    def _expired(self) -> bool:
        return time.monotonic() - self._fetched_at > JWKS_TTL_SECONDS

    async def key_for(self, kid: str) -> dict[str, Any] | None:
        if kid in self._keys and not self._expired():
            return self._keys[kid]
        await self.refresh()
        return self._keys.get(kid)

    async def refresh(self) -> None:
        url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # network, DNS, 404 on a wrong project URL
            raise SupabaseAuthError(
                "Could not reach the Supabase key endpoint to verify the token."
            ) from exc

        self._keys = {
            key["kid"]: key for key in payload.get("keys", []) if key.get("kid")
        }
        self._fetched_at = time.monotonic()

    def clear(self) -> None:
        self._keys = {}
        self._fetched_at = 0.0


_jwks = _JwksCache()


def reset_key_cache() -> None:
    """Drop cached signing keys. Used by tests and after a config change."""
    _jwks.clear()


def _claims_from_payload(payload: dict[str, Any]) -> SupabaseClaims:
    metadata = payload.get("user_metadata") or {}
    name = metadata.get("full_name") or metadata.get("name")
    return SupabaseClaims(
        subject=str(payload.get("sub") or ""),
        email=str(payload.get("email") or metadata.get("email") or "").lower().strip(),
        full_name=str(name).strip() if name else None,
    )


async def verify_token(token: str) -> SupabaseClaims:
    """Return the verified claims, or raise `SupabaseAuthError`."""
    if not token:
        raise SupabaseAuthError("No token supplied.")

    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise SupabaseAuthError("Token is not a readable JWT.") from exc

    algorithm = str(header.get("alg") or "")
    options = {"verify_aud": True}

    if algorithm == "HS256":
        secret = settings.supabase_jwt_secret
        if not secret:
            raise SupabaseAuthError(
                "This token is signed with the project's JWT secret, but "
                "SUPABASE_JWT_SECRET is not configured."
            )
        key: Any = secret
    else:
        kid = header.get("kid")
        if not kid:
            raise SupabaseAuthError("Token has no key id, so it cannot be verified.")
        if not settings.supabase_url:
            raise SupabaseAuthError("SUPABASE_URL is not configured.")
        key = await _jwks.key_for(str(kid))
        if key is None:
            raise SupabaseAuthError("Token was signed with a key this project does not publish.")

    try:
        payload = jwt.decode(
            token,
            key,
            algorithms=[algorithm],
            audience=AUDIENCE,
            options=options,
        )
    except JWTError as exc:
        # Expired, wrong audience, bad signature — the caller gets one 401 for
        # all of them; the specifics stay in the log, not in the response.
        raise SupabaseAuthError("Token is invalid or has expired.") from exc

    claims = _claims_from_payload(payload)
    if not claims.is_usable:
        raise SupabaseAuthError("Token carries no subject or email.")
    return claims
