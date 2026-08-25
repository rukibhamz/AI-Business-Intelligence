from __future__ import annotations

import secrets
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values shipped for local convenience that must never reach a live deployment.
INSECURE_SECRET_KEY = "dev-secret-change-in-production"
INSECURE_ADMIN_PASSWORD = "admin123"


class ConfigurationError(RuntimeError):
    """Raised when production settings are unsafe. Startup aborts."""


def normalize_database_url(url: str) -> str:
    """Supabase/Neon copy URIs as postgresql:// — this app needs an async driver."""
    value = (url or "").strip()
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://") :]
    if value.startswith("postgresql://"):
        value = "postgresql+asyncpg://" + value[len("postgresql://") :]
    elif value.startswith("postgresql+psycopg2://"):
        value = "postgresql+asyncpg://" + value[len("postgresql+psycopg2://") :]
    elif value.startswith("postgresql+psycopg://"):
        value = "postgresql+asyncpg://" + value[len("postgresql+psycopg://") :]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "mysql+aiomysql://root:@localhost:3306/ai_bi"
    secret_key: str = INSECURE_SECRET_KEY
    access_token_expire_minutes: int = 60 * 12
    admin_email: str = "admin@local.dev"
    admin_password: str = INSECURE_ADMIN_PASSWORD
    admin_full_name: str = "Admin"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    cors_origins: str = "http://localhost:5173"
    app_env: str = "development"
    upload_dir: str = "uploads"

    # --- Supabase authentication -------------------------------------------
    #: Project URL, e.g. https://abcdefgh.supabase.co. Setting this (with a key
    #: below) switches sign-in from local accounts to Supabase.
    supabase_url: str = ""
    #: Publishable anon key. Public by design — the browser needs it to sign in.
    supabase_anon_key: str = ""
    #: Legacy shared JWT secret. Only needed for projects still issuing HS256
    #: tokens; projects on signing keys verify against the JWKS endpoint.
    supabase_jwt_secret: str = ""

    # --- operational limits -------------------------------------------------
    #: Questions per user per minute against the AI query endpoint. Each one can
    #: call a paid provider, so this caps both spend and abuse.
    query_rate_limit_per_minute: int = 20
    #: Maximum rows any generated SQL may return.
    max_query_rows: int = 200
    #: Log every SQL statement. Leaks data and credentials — never on in prod.
    sql_echo: bool = False
    #: Serve /docs and /redoc. Off in production by default.
    expose_api_docs: bool = True

    @field_validator("database_url", mode="before")
    @classmethod
    def _async_postgres_url(cls, value: Any) -> Any:
        if isinstance(value, str):
            return normalize_database_url(value)
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def supabase_enabled(self) -> bool:
        """True when sign-in should go through Supabase rather than local accounts.

        Both values are required: the browser cannot sign in without the anon
        key, and the API cannot verify what it gets back without the URL.
        """
        return bool(self.supabase_url.strip() and self.supabase_anon_key.strip())

    @property
    def auth_provider(self) -> str:
        return "supabase" if self.supabase_enabled else "local"

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in ("production", "prod")

    def validate_runtime(self) -> list[str]:
        """Return fatal misconfigurations for the current environment."""
        problems: list[str] = []
        if not self.is_production:
            return problems

        if self.secret_key == INSECURE_SECRET_KEY or len(self.secret_key) < 32:
            problems.append(
                "SECRET_KEY is the shipped default or shorter than 32 characters. "
                "Anyone could forge a login token. Generate one with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )

        if self.admin_password == INSECURE_ADMIN_PASSWORD:
            problems.append(
                "ADMIN_PASSWORD is the shipped default 'admin123'. Set a strong "
                "password before the first start — it seeds the admin account."
            )
        elif len(self.admin_password) < 12:
            problems.append("ADMIN_PASSWORD must be at least 12 characters in production.")

        origins = self.cors_origin_list
        if not origins:
            problems.append("CORS_ORIGINS is empty; the frontend will be blocked.")
        if "*" in origins:
            problems.append(
                "CORS_ORIGINS contains '*', which cannot be combined with credentials. "
                "List the exact frontend origins."
            )
        if any(o.startswith("http://") and "localhost" not in o for o in origins):
            problems.append("CORS_ORIGINS contains a non-local plain-http origin; use https.")

        if self.sql_echo:
            problems.append("SQL_ECHO must be off in production — it logs query data.")

        return problems


def generate_secret_key() -> str:
    """Helper for operators bootstrapping a deployment."""
    return secrets.token_urlsafe(48)


settings = Settings()
