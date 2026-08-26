from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import parse_qsl, urlencode

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values shipped for local convenience that must never reach a live deployment.
INSECURE_SECRET_KEY = "dev-secret-change-in-production"
INSECURE_ADMIN_PASSWORD = "admin123"


class ConfigurationError(RuntimeError):
    """Raised when production settings are unsafe. Startup aborts."""


#: Query parameters libpq understands and asyncpg does not. SQLAlchemy hands
#: every unrecognised parameter to `asyncpg.connect()` as a keyword argument, so
#: leaving one in place ends the deploy with
#: `connect() got an unexpected keyword argument 'sslmode'`.
_LIBPQ_ONLY_PARAMS = (
    "channel_binding",
    "sslrootcert",
    "sslcert",
    "sslkey",
    "sslpassword",
    "gssencmode",
    "options",
    "application_name",
    "keepalives",
    "keepalives_idle",
    "keepalives_interval",
    "keepalives_count",
)


def normalize_database_url(url: str) -> str:
    """Make a hosted Postgres connection string usable by asyncpg.

    Supabase, Neon and Render all hand out libpq-style URIs. Three things have
    to change before SQLAlchemy can open them:

    * the scheme becomes `postgresql+asyncpg://`;
    * `sslmode=require` becomes `ssl=require`, which is the same instruction in
      the spelling asyncpg accepts;
    * parameters only libpq knows are dropped rather than forwarded into a
      `TypeError` at startup.
    """
    value = (url or "").strip()
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://") :]
    if value.startswith("postgresql://"):
        value = "postgresql+asyncpg://" + value[len("postgresql://") :]
    elif value.startswith("postgresql+psycopg2://"):
        value = "postgresql+asyncpg://" + value[len("postgresql+psycopg2://") :]
    elif value.startswith("postgresql+psycopg://"):
        value = "postgresql+asyncpg://" + value[len("postgresql+psycopg://") :]

    if not value.startswith("postgresql+asyncpg://"):
        return value

    value = _unwrap_bracketed_host(value)

    # Supabase's transaction pooler (port 6543) multiplexes connections, so a
    # prepared statement created on one does not exist on the next. asyncpg
    # caches them by default, which surfaces later as
    # `prepared statement "__asyncpg_stmt_1__" does not exist`.
    if _is_transaction_pooler(value):
        value = _with_param(value, "prepared_statement_cache_size", "0")

    if "?" not in value:
        return value

    base, _, query = value.partition("?")
    kept: list[tuple[str, str]] = []
    for key, raw in parse_qsl(query, keep_blank_values=True):
        name = key.lower()
        if name in _LIBPQ_ONLY_PARAMS:
            continue
        if name == "sslmode":
            # "disable" is the one mode that means "do not use SSL at all".
            if raw.lower() != "disable":
                kept.append(("ssl", raw))
            continue
        kept.append((key, raw))

    return f"{base}?{urlencode(kept)}" if kept else base


def _split_netloc(url: str) -> tuple[str, str, str]:
    """(prefix, netloc, suffix) without going through urlsplit.

    urlsplit is what raises on a malformed URL, so it cannot be used to
    diagnose one.
    """
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url, "", ""
    netloc, slash, path = rest.partition("/")
    return f"{scheme}://", netloc, f"{slash}{path}"


def _unwrap_bracketed_host(url: str) -> str:
    """Remove square brackets around a hostname that is not an IPv6 literal.

    Brackets in a URL mean "this is an IPv6 address". Around a DNS name they
    make the whole URL unparseable, and the error blames the hostname rather
    than the brackets.
    """
    prefix, netloc, suffix = _split_netloc(url)
    if "[" not in netloc:
        return url
    userinfo, at, host = netloc.rpartition("@")
    if not host.startswith("["):
        return url
    inside, closed, port = host[1:].partition("]")
    if not closed or ":" in inside:  # a real IPv6 literal keeps its brackets
        return url
    return f"{prefix}{userinfo}{at}{inside}{port}{suffix}"


def _is_transaction_pooler(url: str) -> bool:
    _, netloc, _ = _split_netloc(url)
    host = netloc.rpartition("@")[2]
    return host.endswith(":6543") or "pooler.supabase.com" in host


def _with_param(url: str, key: str, value: str) -> str:
    base, sep, query = url.partition("?")
    if key in query:
        return url
    joined = f"{query}&{key}={value}" if sep else f"{key}={value}"
    return f"{base}?{joined}"


def describe_database_url_problem(url: str) -> str | None:
    """A readable reason the connection string cannot be used, or None.

    Without this the first sign of trouble is a ValueError from deep inside
    urllib saying a Supabase hostname "does not appear to be an IPv4 or IPv6
    address" — which is true, and completely misleading: the brackets it is
    complaining about are usually an unreplaced password placeholder.
    """
    value = (url or "").strip()
    if not value:
        return "DATABASE_URL is empty."

    prefix, netloc, _ = _split_netloc(value)
    if not prefix:
        return (
            "DATABASE_URL is not a connection URL. It should look like "
            "postgresql://user:password@host:5432/database"
        )

    # SQLite addresses a file, not a server: no host, no credentials, nothing
    # here applies.
    if value.startswith("sqlite"):
        return None

    userinfo = netloc.rpartition("@")[0]
    if "[" in userinfo or "]" in userinfo:
        return (
            "DATABASE_URL still contains the password placeholder from the "
            "Supabase dashboard. Replace [YOUR-PASSWORD] with the real database "
            "password, and percent-encode any of @ : / ? # [ ] it contains "
            "(@ becomes %40)."
        )

    try:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if not parsed.hostname:
            return "DATABASE_URL has no host. Check it was pasted in full."
    except ValueError as exc:
        return f"DATABASE_URL could not be parsed: {exc}"

    return None


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
    #: Service role key — server only. Required to put dataset files in Storage.
    #: Never expose this to the browser or put it in SUPABASE_ANON_KEY.
    supabase_service_role_key: str = ""
    #: Private Storage bucket for uploaded CSV/Excel files.
    supabase_storage_bucket: str = "datasets"

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
    def object_storage_enabled(self) -> bool:
        """True when dataset uploads should go to Supabase Storage."""
        return bool(
            self.supabase_url.strip()
            and self.supabase_service_role_key.strip()
            and self.supabase_storage_bucket.strip()
        )

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
