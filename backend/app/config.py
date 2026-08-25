from __future__ import annotations

import secrets

from pydantic_settings import BaseSettings, SettingsConfigDict

# Values shipped for local convenience that must never reach a live deployment.
INSECURE_SECRET_KEY = "dev-secret-change-in-production"
INSECURE_ADMIN_PASSWORD = "admin123"


class ConfigurationError(RuntimeError):
    """Raised when production settings are unsafe. Startup aborts."""


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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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
