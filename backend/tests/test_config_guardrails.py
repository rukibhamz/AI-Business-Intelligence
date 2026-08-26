"""Production must refuse to start with the shipped development defaults."""

import pytest

from app.config import (
    INSECURE_ADMIN_PASSWORD,
    INSECURE_SECRET_KEY,
    Settings,
    describe_database_url_problem,
    normalize_database_url,
)

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


def test_supabase_uri_is_rewritten_to_asyncpg():
    assert normalize_database_url(
        "postgresql://user:pass@db.example.com:5432/postgres"
    ).startswith("postgresql+asyncpg://")
    assert normalize_database_url(
        "postgres://user:pass@db.example.com:5432/postgres"
    ).startswith("postgresql+asyncpg://")
    settings = Settings(
        database_url="postgresql://user:pass@db.example.com:5432/postgres"
    )
    assert "+asyncpg" in settings.database_url


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


# --- hosted Postgres connection strings -------------------------------------
#
# Supabase, Neon and Render hand out libpq-style URIs. SQLAlchemy forwards every
# parameter it does not recognise to asyncpg.connect() as a keyword argument, so
# one stray `sslmode` ends the deploy with a TypeError before the first request.


def _connect_kwargs(url: str) -> dict:
    """The keyword arguments asyncpg would actually be called with."""
    from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
    from sqlalchemy.engine import make_url

    return PGDialect_asyncpg().create_connect_args(make_url(url))[1]


def test_a_bare_postgres_scheme_gets_an_async_driver():
    assert normalize_database_url("postgres://u:p@host:5432/db").startswith(
        "postgresql+asyncpg://"
    )
    assert normalize_database_url("postgresql://u:p@host:5432/db").startswith(
        "postgresql+asyncpg://"
    )
    assert normalize_database_url("postgresql+psycopg2://u:p@host/db").startswith(
        "postgresql+asyncpg://"
    )


def test_sslmode_becomes_the_spelling_asyncpg_understands():
    url = normalize_database_url("postgresql://u:p@db.abc.supabase.co:5432/postgres?sslmode=require")
    assert "sslmode" not in url
    assert _connect_kwargs(url)["ssl"] == "require"


def test_parameters_only_libpq_knows_are_dropped():
    """Neon appends channel_binding; asyncpg has no such argument."""
    url = normalize_database_url(
        "postgresql://u:p@ep-x.neon.tech/db?sslmode=require&channel_binding=require"
    )
    kwargs = _connect_kwargs(url)
    assert "channel_binding" not in kwargs
    assert kwargs["ssl"] == "require"


def test_disabling_ssl_is_respected_rather_than_translated():
    url = normalize_database_url("postgresql://u:p@localhost/db?sslmode=disable")
    assert "ssl" not in _connect_kwargs(url)


def test_no_libpq_only_argument_survives_normalisation():
    url = normalize_database_url(
        "postgres://u:p@host/db?sslmode=verify-full&channel_binding=require"
        "&sslrootcert=/ca.pem&application_name=bi&gssencmode=disable"
    )
    leftovers = {"sslmode", "channel_binding", "sslrootcert", "application_name", "gssencmode"}
    assert not (leftovers & set(_connect_kwargs(url)))


def test_other_query_parameters_are_left_alone():
    url = normalize_database_url("postgresql://u:p@host/db?ssl=require&prepared_statement_cache_size=0")
    assert "prepared_statement_cache_size=0" in url


def test_a_mysql_url_is_untouched():
    original = "mysql+aiomysql://root:@localhost:3306/ai_bi"
    assert normalize_database_url(original) == original


# --- diagnosing a bad connection string -------------------------------------
#
# Pasted straight from the Supabase dashboard, the URL still contains
# [YOUR-PASSWORD]. urlsplit reads the brackets as an IPv6 host and raises
# "'aws-0-eu-central-1.pooler.supabase.com' does not appear to be an IPv4 or
# IPv6 address", which sends the reader after the hostname instead of the
# password. This is a real deploy failure, reported verbatim.

SUPABASE_POOLER = "aws-0-eu-central-1.pooler.supabase.com"


def test_an_unreplaced_password_placeholder_is_named_as_such():
    problem = describe_database_url_problem(
        f"postgresql://postgres:[YOUR-PASSWORD]@{SUPABASE_POOLER}:6543/postgres"
    )
    assert problem is not None
    assert "placeholder" in problem.lower()
    assert "percent-encode" in problem.lower()
    # The hostname is not the problem and must not be blamed.
    assert SUPABASE_POOLER not in problem


def test_a_working_connection_string_reports_no_problem():
    assert (
        describe_database_url_problem(
            f"postgresql://postgres.abc:s3cret@{SUPABASE_POOLER}:6543/postgres"
        )
        is None
    )


def test_an_empty_or_malformed_url_is_reported():
    assert "empty" in (describe_database_url_problem("") or "").lower()
    assert describe_database_url_problem("just-a-host-name") is not None


def test_a_bracketed_hostname_is_unwrapped_rather_than_left_to_fail():
    """Brackets mean IPv6. Around a DNS name they make the URL unparseable."""
    url = normalize_database_url(f"postgresql://u:p@[{SUPABASE_POOLER}]:6543/postgres")
    assert f"@{SUPABASE_POOLER}:6543" in url
    assert describe_database_url_problem(url) is None


def test_a_real_ipv6_literal_keeps_its_brackets():
    url = normalize_database_url("postgresql://u:p@[2001:db8::1]:5432/db")
    assert "[2001:db8::1]" in url


def test_the_transaction_pooler_disables_prepared_statement_caching():
    """Port 6543 multiplexes connections; a cached statement will not be there."""
    url = normalize_database_url(f"postgresql://u:p@{SUPABASE_POOLER}:6543/postgres")
    assert "prepared_statement_cache_size=0" in url


def test_a_direct_connection_keeps_the_cache():
    url = normalize_database_url("postgresql://u:p@db.abc.supabase.co:5432/postgres")
    assert "prepared_statement_cache_size" not in url


def test_a_sqlite_url_is_not_judged_by_server_rules():
    """SQLite addresses a file. No host is correct, not a misconfiguration."""
    for url in ("sqlite+aiosqlite:///:memory:", "sqlite+aiosqlite:///./local.db"):
        assert describe_database_url_problem(url) is None


# --- the provider saying "slow down" ----------------------------------------


async def test_a_rate_limited_provider_is_retried_then_explained():
    """Three questions in a row hit Mistral's limit mid-demo and 400'd."""
    import httpx

    from app.services.ai_query import ProviderBusy, _post_with_backoff

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"retry-after": "0"}, json={"error": "slow down"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ProviderBusy) as exc:
            await _post_with_backoff(client, "https://api.test/v1", {}, {})

    assert calls["n"] == 4  # three retries, then give up
    assert "rate-limiting" in str(exc.value)
    assert "http" not in str(exc.value).lower()  # no raw URL in the user's face


async def test_a_recovered_rate_limit_returns_the_answer():
    import httpx

    from app.services.ai_query import _post_with_backoff

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await _post_with_backoff(client, "https://api.test/v1", {}, {})
    assert res.status_code == 200
    assert calls["n"] == 2


async def test_a_busy_provider_falls_over_to_the_next_one():
    """Settings lets you configure several providers; this is what makes the
    priority order mean something."""
    from app.services.ai_query import ProviderBusy, with_failover

    tried = []

    async def call(runtime):
        tried.append(runtime["label"])
        if runtime["label"] == "busy":
            raise ProviderBusy("rate limited")
        return f"answered by {runtime['label']}"

    result = await with_failover([{"label": "busy"}, {"label": "spare"}], call)
    assert result == "answered by spare"
    assert tried == ["busy", "spare"]


async def test_every_provider_busy_reports_it_once():
    from app.services.ai_query import ProviderBusy, with_failover

    async def call(runtime):
        raise ProviderBusy("rate limited")

    with pytest.raises(ProviderBusy):
        await with_failover([{"label": "a"}, {"label": "b"}], call)
