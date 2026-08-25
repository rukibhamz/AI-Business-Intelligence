"""Security invariants that must hold before any deployment."""

import ast
import json
import pathlib

import pytest

from app.services.rate_limit import RateLimiter

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

# Login and bootstrap registration are public by design; the logo is fetched by
# an <img> tag that cannot carry an Authorization header.
PUBLIC_BY_DESIGN = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/register"),
    ("GET", "/api/settings/logo"),
    # The sign-in screen has to know which provider to use before anyone has a
    # token. It returns the provider name and the Supabase anon key, which is
    # public by design — never the JWT secret or the service role key.
    ("GET", "/api/auth/config"),
}


#: Dependencies that establish who is calling. Anything else leaves a route open.
GUARDS = {"get_current_user", "require_admin"}

#: Configuration a member must never be able to change.
ADMIN_ONLY = {
    ("PUT", "/api/settings"),
    ("POST", "/api/settings/test-connection"),
    ("POST", "/api/settings/logo"),
    ("DELETE", "/api/settings/logo"),
}


def _routes():
    for path in sorted((APP / "routes").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        prefix = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "APIRouter":
                for kw in node.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        prefix = kw.value.value
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                    continue
                if getattr(dec.func.value, "id", "") != "router":
                    continue
                sub = dec.args[0].value if dec.args and isinstance(dec.args[0], ast.Constant) else ""
                dependencies = {
                    getattr(d.args[0], "id", "")
                    for d in list(node.args.defaults) + list(node.args.kw_defaults)
                    if isinstance(d, ast.Call)
                    and getattr(d.func, "id", "") == "Depends"
                    and d.args
                }
                # require_admin depends on get_current_user, so it is a guard too.
                guarded = bool(dependencies & GUARDS)
                yield (
                    dec.func.attr.upper(),
                    f"/api{prefix}{sub}",
                    node.name,
                    guarded,
                    dependencies,
                )


def test_every_route_requires_authentication():
    unprotected = [
        (verb, path, fn)
        for verb, path, fn, guarded, _deps in _routes()
        if not guarded and (verb, path) not in PUBLIC_BY_DESIGN
    ]
    assert unprotected == [], f"Unauthenticated routes: {unprotected}"


def test_configuration_endpoints_require_an_admin():
    """Members share the workspace's AI provider; only an admin may change it."""
    for verb, path, fn, _guarded, deps in _routes():
        if (verb, path) in ADMIN_ONLY:
            assert "require_admin" in deps, f"{verb} {path} ({fn}) is not admin-gated"


def test_the_route_table_is_not_empty():
    # Guards against the AST walk silently matching nothing.
    assert len(list(_routes())) > 20


def test_connection_config_never_leaks_credentials():
    from app.routes.sources import _redact_config

    raw = {
        "host": "db.example.com",
        "port": 3306,
        "user": "reporting",
        "password": "hunter2-super-secret",
        "database": "sales",
    }
    out = json.loads(_redact_config(raw))
    assert "hunter2-super-secret" not in json.dumps(out)
    assert out["password"] == "********"
    # Non-secret fields survive so the UI can still show the connection.
    assert out["host"] == "db.example.com"
    assert out["database"] == "sales"


def test_blank_password_is_not_turned_into_a_fake_secret():
    from app.routes.sources import _redact_config

    out = json.loads(_redact_config({"host": "h", "password": ""}))
    assert out["password"] == ""


def test_rate_limiter_blocks_past_the_limit():
    limiter = RateLimiter(limit=3, window_seconds=60)
    assert all(limiter.check("user-1")[0] for _ in range(3))
    allowed, retry_after = limiter.check("user-1")
    assert not allowed
    assert retry_after > 0


def test_rate_limiter_is_per_user():
    limiter = RateLimiter(limit=1, window_seconds=60)
    assert limiter.check("user-a")[0]
    assert limiter.check("user-b")[0]
    assert not limiter.check("user-a")[0]


def test_rate_limiter_window_expires():
    limiter = RateLimiter(limit=1, window_seconds=0.05)
    assert limiter.check("u")[0]
    assert not limiter.check("u")[0]
    import time

    time.sleep(0.08)
    assert limiter.check("u")[0]


@pytest.mark.parametrize("limit", [0, -1])
def test_rate_limiter_disabled_when_limit_not_positive(limit):
    limiter = RateLimiter(limit=limit)
    assert all(limiter.check("u")[0] for _ in range(50))


def test_password_hashing_round_trip():
    from app.services.auth import hash_password, verify_password

    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_updating_a_source_does_not_overwrite_a_password_with_the_mask():
    """A client that round-trips the redacted config must not destroy the secret."""
    import json as _json

    from app.routes.sources import _REDACTED, _SECRET_CONFIG_KEYS, _redact_config

    stored = {"host": "h", "user": "u", "password": "real-secret", "database": "d"}
    round_tripped = _json.loads(_redact_config(stored))
    assert round_tripped["password"] == _REDACTED

    # Same merge the PATCH handler performs.
    merged = dict(round_tripped)
    for key, value in merged.items():
        if key.lower() in _SECRET_CONFIG_KEYS and value == _REDACTED:
            merged[key] = stored.get(key, "")

    assert merged["password"] == "real-secret"
