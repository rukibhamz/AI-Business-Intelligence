from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import async_session, init_db
from app.routes import auth, queries, sources
from app.services.auth import ensure_bootstrap_admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    await init_db()
    async with async_session() as session:
        await ensure_bootstrap_admin(session)
    yield


app = FastAPI(
    title="AI Business Intelligence API",
    description="Natural-language BI platform — see docs/BUILD_AND_HANDOFF.md",
    version="0.1.0",
    lifespan=lifespan,
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


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "environment": settings.app_env,
    }
