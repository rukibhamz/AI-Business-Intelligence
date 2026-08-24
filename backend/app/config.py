from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "mysql+aiomysql://root:@localhost:3306/ai_bi"
    secret_key: str = "dev-secret-change-in-production"
    access_token_expire_minutes: int = 60 * 12
    admin_email: str = "admin@local.dev"
    admin_password: str = "admin123"
    admin_full_name: str = "Admin"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    cors_origins: str = "http://localhost:5173"
    app_env: str = "development"
    upload_dir: str = "uploads"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
