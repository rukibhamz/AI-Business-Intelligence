from collections.abc import AsyncGenerator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.sql_echo,
    pool_pre_ping=True,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


# Columns added after a table was first created. `create_all` only creates
# missing *tables*, so existing installs need these applied explicitly.
# Types are given per dialect because MySQL and Postgres disagree.
_ADDED_COLUMNS: dict[str, dict[str, dict[str, str]]] = {
    "users": {
        "supabase_id": {"default": "VARCHAR(64) NULL", "postgresql": "VARCHAR(64)"},
        "role": {
            "default": "VARCHAR(20) NOT NULL DEFAULT 'member'",
            "postgresql": "VARCHAR(20) NOT NULL DEFAULT 'member'",
        },
    },
    "queries": {
        "session_id": {"default": "VARCHAR(64) NULL", "postgresql": "VARCHAR(64)"},
        "answer": {"default": "TEXT NULL", "postgresql": "TEXT"},
        "response_format": {"default": "VARCHAR(20) NULL", "postgresql": "VARCHAR(20)"},
        "diagnosis_json": {"default": "TEXT NULL", "postgresql": "TEXT"},
    },
}

_ADDED_INDEXES: dict[str, dict[str, str]] = {
    "queries": {"ix_queries_session_id": "session_id"},
    "users": {"ix_users_supabase_id": "supabase_id"},
}


def _quote(dialect: str, identifier: str) -> str:
    """Quote an identifier for the running dialect (MySQL uses backticks)."""
    if dialect == "mysql":
        return f"`{identifier}`"
    return f'"{identifier}"'


def _apply_pending_columns(connection) -> None:
    dialect = connection.dialect.name
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())

    for table, columns in _ADDED_COLUMNS.items():
        if table not in existing_tables:
            continue
        present = {col["name"] for col in inspector.get_columns(table)}
        for name, ddl_by_dialect in columns.items():
            if name in present:
                continue
            ddl = ddl_by_dialect.get(dialect, ddl_by_dialect["default"])
            connection.execute(
                text(
                    f"ALTER TABLE {_quote(dialect, table)} "
                    f"ADD COLUMN {_quote(dialect, name)} {ddl}"
                )
            )

    # Re-inspect so indexes see the columns just added.
    inspector = inspect(connection)
    for table, indexes in _ADDED_INDEXES.items():
        if table not in existing_tables:
            continue
        present_indexes = {idx["name"] for idx in inspector.get_indexes(table)}
        present_columns = {col["name"] for col in inspector.get_columns(table)}
        for name, column in indexes.items():
            if name in present_indexes or column not in present_columns:
                continue
            connection.execute(
                text(
                    f"CREATE INDEX {_quote(dialect, name)} "
                    f"ON {_quote(dialect, table)} ({_quote(dialect, column)})"
                )
            )


async def init_db() -> None:
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_pending_columns)
