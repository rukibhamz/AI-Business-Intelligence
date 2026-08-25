import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ConfigurationError, describe_database_url_problem, settings
from app.database import async_session, init_db
from app.routes import (
    auth,
    conversations,
    dashboards,
    insights,
    queries,
    sources,
)
from app.routes import (
    settings as settings_routes,
)
from app.services.auth import ensure_bootstrap_admin

logger = logging.getLogger("app.startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to start a production deployment with unsafe defaults rather than
    # silently serving one that anyone can forge a token for.
    problems = settings.validate_runtime()
    if problems:
        for problem in problems:
            logger.error("Unsafe configuration: %s", problem)
        raise ConfigurationError(
            "Refusing to start with "
            f"{len(problems)} unsafe production setting(s):\n  - "
            + "\n  - ".join(problems)
        )

    # A malformed connection string otherwise surfaces as a ValueError from
    # inside urllib saying a hostname is not an IP address — which is true, and
    # tells the operator nothing about the placeholder they forgot to replace.
    database_problem = describe_database_url_problem(settings.database_url)
    if database_problem:
        logger.error("Database configuration: %s", database_problem)
        raise ConfigurationError(database_problem)

    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    await init_db()
    async with async_session() as session:
        await ensure_bootstrap_admin(session)
    logger.info("Started in %s mode", settings.app_env)
    yield


_docs_enabled = settings.expose_api_docs and not settings.is_production

app = FastAPI(
    title="AI Business Intelligence API",
    description="Natural-language BI platform — see docs/BUILD_AND_HANDOFF.md",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(sources.router, prefix="/api")
app.include_router(queries.router, prefix="/api")
app.include_router(dashboards.router, prefix="/api")
app.include_router(insights.router, prefix="/api")
app.include_router(conversations.router, prefix="/api")
app.include_router(settings_routes.router, prefix="/api")


@app.get("/api/health")
async def health():
    """Liveness probe. Intentionally reveals nothing about configuration."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "environment": settings.app_env,
    }
