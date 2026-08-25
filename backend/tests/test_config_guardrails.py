"""Production must refuse to start with the shipped development defaults."""

from app.config import INSECURE_ADMIN_PASSWORD, INSECURE_SECRET_KEY, Settings

STRONG_SECRET = "x" * 48
STRONG_ADMIN = "a-strong-admin-password"


def prod(**overrides) -> Settings:
    base = {
        "app_env": "production",
        "secret_key": STRONG_SECRET,
        "admin_password": STRONG_ADMIN,
        "cors_origins": "https://app.example.com",
        "sql_echo": False,
    }
    base.update(overrides)
    return Settings(**base)


def test_development_defaults_are_allowed_locally():
    assert Settings(app_env="development").validate_runtime() == []


def test_a_clean_production_config_passes():
    assert prod().validate_runtime() == []


def test_default_secret_key_blocks_production():
    problems = prod(secret_key=INSECURE_SECRET_KEY).validate_runtime()
    assert any("SECRET_KEY" in p for p in problems)


def test_short_secret_key_blocks_production():
    assert any("SECRET_KEY" in p for p in prod(secret_key="short").validate_runtime())


def test_default_admin_password_blocks_production():
    problems = prod(admin_password=INSECURE_ADMIN_PASSWORD).validate_runtime()
    assert any("ADMIN_PASSWORD" in p for p in problems)


def test_short_admin_password_blocks_production():
    assert any("ADMIN_PASSWORD" in p for p in prod(admin_password="short").validate_runtime())


def test_wildcard_cors_blocks_production():
    assert any("CORS" in p for p in prod(cors_origins="*").validate_runtime())


def test_empty_cors_blocks_production():
    assert any("CORS" in p for p in prod(cors_origins="").validate_runtime())


def test_plain_http_origin_blocks_production():
    assert any("https" in p for p in prod(cors_origins="http://app.example.com").validate_runtime())


def test_localhost_http_origin_is_tolerated():
    assert prod(cors_origins="https://app.example.com,http://localhost:5173").validate_runtime() == []


def test_sql_echo_blocks_production():
    assert any("SQL_ECHO" in p for p in prod(sql_echo=True).validate_runtime())


def test_is_production_detection():
    assert Settings(app_env="production").is_production
    assert Settings(app_env="PROD").is_production
    assert not Settings(app_env="development").is_production
