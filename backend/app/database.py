from collections.abc import AsyncGenerator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, echo=settings.app_env == "development")
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


# Columns added after a table was first created. `create_all` only creates
# missing *tables*, so existing installs need these applied explicitly.
# Phase 6 replaces this with Alembic.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "queries": {
        "session_id": "VARCHAR(64) NULL",
        "answer": "TEXT NULL",
        "response_format": "VARCHAR(20) NULL",
    },
}

_ADDED_INDEXES: dict[str, dict[str, str]] = {
    "queries": {"ix_queries_session_id": "session_id"},
}


def _apply_pending_columns(connection) -> None:
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    for table, columns in _ADDED_COLUMNS.items():
        if table not in existing_tables:
            continue
        present = {col["name"] for col in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name in present:
                continue
            connection.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{name}` {ddl}"))

    for table, indexes in _ADDED_INDEXES.items():
        if table not in existing_tables:
            continue
        present = {idx["name"] for idx in inspector.get_indexes(table)}
        columns_present = {col["name"] for col in inspect(connection).get_columns(table)}
        for name, column in indexes.items():
            if name in present or column not in columns_present:
                continue
            connection.execute(
                text(f"CREATE INDEX `{name}` ON `{table}` (`{column}`)")
            )


async def init_db() -> None:
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_pending_columns)
