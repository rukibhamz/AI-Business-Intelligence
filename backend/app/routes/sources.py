import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import DataSource, User
from app.models import Query as QueryModel
from app.schemas import (
    DataSourceCreate,
    DataSourceResponse,
    DataSourceUpdate,
    FieldMappingUpdate,
    MySQLSourceCreate,
    PreviewResponse,
    PrimaryTableUpdate,
)
from app.services.ai_mapping import ai_suggest_mapping, mapping_is_useful
from app.services.app_settings import get_ai_runtime
from app.services.cleanup import prune_dashboard_widgets
from app.services.connectors import detect_file_format, save_upload
from app.services.field_mapping import (
    CANONICAL_FIELDS,
    columns_from_schema,
    enrich_config_with_mapping,
    resolve_conflicts,
)
from app.services.ownership import fetch_owned, owned_by
from app.services.profiling import PROFILE_SAMPLE_ROWS, attach_profiles, profile_rows
from app.services.schema_context import pick_primary_table
from app.services.schema_registry import (
    introspect_source,
    parse_connection_config,
    preview_source_data,
    serialize_schema,
    test_mysql_connection,
)
from app.services.schema_types import parse_schema_json

router = APIRouter(prefix="/sources", tags=["data-sources"])


# Never sent to the client. `connection_config` is surfaced so the UI can show
# host/database, but the credentials in it must not leave the server.
_SECRET_CONFIG_KEYS = ("password", "passwd", "secret", "token", "api_key", "private_key")
_REDACTED = "********"


def _redact_config(config: dict[str, Any]) -> str | None:
    """Serialize connection config with every credential masked."""
    if not config:
        return None
    safe: dict[str, Any] = {}
    for key, value in config.items():
        if key.lower() in _SECRET_CONFIG_KEYS:
            safe[key] = _REDACTED if value else ""
        else:
            safe[key] = value
    return json.dumps(safe)


def _to_response(source: DataSource) -> DataSourceResponse:
    config = parse_connection_config(source)
    mapping = config.get("field_mapping") if isinstance(config.get("field_mapping"), dict) else None
    status_val = config.get("mapping_status")
    row_count = config.get("row_count")
    if row_count is not None:
        try:
            row_count = int(row_count)
        except (TypeError, ValueError):
            row_count = None
    return DataSourceResponse(
        id=source.id,
        name=source.name,
        source_type=source.source_type,
        connection_config=_redact_config(config),
        schema_json=source.schema_json,
        created_at=source.created_at,
        updated_at=source.updated_at,
        field_mapping=mapping,
        mapping_status=str(status_val) if status_val else None,
        mapping_source=str(config.get("mapping_source") or "") or None,
        mapping_conflicts=list(config.get("mapping_conflicts") or []) or None,
        tables=[t["name"] for t in (parse_schema_json(source.schema_json) or {"tables": []})["tables"]],
        primary_table=config.get("primary_table"),
        row_count=row_count,
    )


async def _apply_schema_and_mapping(
    source: DataSource,
    *,
    reset_mapping: bool = False,
    db: AsyncSession | None = None,
) -> None:
    schema = await introspect_source(source)
    source.schema_json = serialize_schema(schema)

    config = parse_connection_config(source)
    # A database connection exposes many tables; analytics reads one. Keep the
    # operator's choice, otherwise pick the table carrying the most meaning.
    available = [t["name"] for t in schema["tables"]]
    primary = config.get("primary_table")
    # Auto-pick only when there is no valid choice on file; an operator who
    # selected a table explicitly must keep it across recomputes.
    if primary not in available:
        primary = pick_primary_table(source)
    config["primary_table"] = primary

    # Profile real values so the SQL planner knows the date span and the
    # category values, instead of inventing them.
    sample: dict[str, Any] = {}
    try:
        sample = await preview_source_data(
            source, table=primary, limit=PROFILE_SAMPLE_ROWS, offset=0
        )
        schema = attach_profiles(
            dict(schema),
            profile_rows(sample.get("columns") or [], sample.get("rows") or []),
            primary,
        )
    except Exception:
        # Profiling is an optimisation; never block ingestion on it.
        pass

    source.schema_json = serialize_schema(schema)
    cols = columns_from_schema(source.schema_json, primary)
    config = enrich_config_with_mapping(config, cols, force_reset=reset_mapping)

    # Let the model map the columns when a provider is configured. It sees the
    # profiles and real values, so it beats name matching; the heuristic result
    # above stays as the fallback.
    if db is not None and (reset_mapping or config.get("mapping_source") != "ai"):
        await _apply_ai_mapping(db, source, schema, sample, config, table=primary)

    try:
        preview = await preview_source_data(source, table=primary, limit=1, offset=0)
        config["row_count"] = preview.get("total", config.get("row_count"))
    except Exception:
        pass

    source.connection_config = json.dumps(config)


async def _apply_ai_mapping(
    db: AsyncSession,
    source: DataSource,
    schema: dict[str, Any],
    sample: dict[str, Any],
    config: dict[str, Any],
    table: str | None = None,
) -> None:
    """Overwrite the heuristic mapping with the model's, when it is usable."""
    tables = schema.get("tables") or []
    if not tables:
        return
    chosen = next((t for t in tables if t.get("name") == table), tables[0])

    runtime = await get_ai_runtime(db)
    result = await ai_suggest_mapping(
        chosen.get("columns", []),
        sample.get("rows") or [],
        source_name=source.name,
        api_key=runtime["api_key"],
        model=runtime["model"],
        base_url=runtime["base_url"],
    )
    if not result:
        config["mapping_source"] = "heuristic"
        return

    config["field_mapping"] = result["mapping"]
    config["mapping_source"] = "ai"
    config["mapping_notes"] = result["rejected"][:5]
    conflicts = result.get("conflicts") or []
    if conflicts:
        config["mapping_conflicts"] = conflicts
    else:
        config.pop("mapping_conflicts", None)
    # Auto-confirm only when the mapping can actually drive a metric; otherwise
    # leave it for review rather than silently claiming the dataset is ready.
    config["mapping_status"] = (
        "confirmed" if mapping_is_useful(result["mapping"]) else "pending"
    )


@router.get("/canonical-fields")
async def list_canonical_fields(_: User = Depends(get_current_user)) -> dict[str, list[str]]:
    return {"fields": CANONICAL_FIELDS}


@router.get("", response_model=list[DataSourceResponse])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DataSourceResponse]:
    result = await db.execute(
        owned_by(select(DataSource), DataSource, current_user).order_by(
            DataSource.created_at.desc()
        )
    )
    return [_to_response(s) for s in result.scalars().all()]


@router.post("", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: DataSourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DataSourceResponse:
    source = DataSource(
        user_id=current_user.id,
        name=payload.name,
        source_type=payload.source_type,
        connection_config=json.dumps(payload.connection_config)
        if payload.connection_config
        else None,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return _to_response(source)


@router.post("/upload", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
async def upload_source(
    file: UploadFile = File(...),
    name: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DataSourceResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    try:
        file_format = detect_file_format(file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    upload_dir = Path(settings.upload_dir)
    dest, _ = save_upload(upload_dir, file.filename, content)

    config = {
        "file_path": str(dest),
        "original_name": file.filename,
        "format": file_format,
        "mapping_status": "pending",
    }

    source = DataSource(
        user_id=current_user.id,
        name=name.strip(),
        source_type="file",
        connection_config=json.dumps(config),
    )
    db.add(source)
    await db.flush()

    try:
        await _apply_schema_and_mapping(source, reset_mapping=True, db=db)
    except Exception as exc:
        await db.rollback()
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {exc}") from exc

    await db.commit()
    await db.refresh(source)
    return _to_response(source)


@router.post("/mysql", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_mysql_source(
    payload: MySQLSourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DataSourceResponse:
    config = payload.connection_config.model_dump()
    config["mapping_status"] = "pending"

    try:
        await test_mysql_connection(config)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"MySQL connection failed: {exc}") from exc

    source = DataSource(
        user_id=current_user.id,
        name=payload.name,
        source_type="mysql",
        connection_config=json.dumps(config),
    )
    db.add(source)
    await db.flush()

    try:
        await _apply_schema_and_mapping(source, reset_mapping=True, db=db)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Schema introspection failed: {exc}") from exc

    await db.commit()
    await db.refresh(source)
    return _to_response(source)


@router.post("/test-mysql")
async def test_mysql(
    payload: MySQLSourceCreate,
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    try:
        await test_mysql_connection(payload.connection_config.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"MySQL connection failed: {exc}") from exc
    return {"status": "ok"}


@router.get("/{source_id}", response_model=DataSourceResponse)
async def get_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DataSourceResponse:
    source = await fetch_owned(db, DataSource, source_id, current_user)
    return _to_response(source)


@router.put("/{source_id}/mapping", response_model=DataSourceResponse)
async def update_mapping(
    source_id: int,
    payload: FieldMappingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DataSourceResponse:
    source = await fetch_owned(db, DataSource, source_id, current_user)

    cols = set(
        columns_from_schema(
            source.schema_json, parse_connection_config(source).get("primary_table")
        )
    )
    cleaned = {k: v for k, v in payload.field_mapping.items() if k in cols}
    cleaned, conflicts = resolve_conflicts(cleaned)
    config = parse_connection_config(source)
    config["field_mapping"] = cleaned
    config["mapping_source"] = "manual"
    config["mapping_status"] = "confirmed" if payload.confirm else "pending"
    if conflicts:
        config["mapping_conflicts"] = conflicts
    else:
        config.pop("mapping_conflicts", None)
    source.connection_config = json.dumps(config)
    await db.commit()
    await db.refresh(source)
    return _to_response(source)


@router.post("/{source_id}/primary-table", response_model=DataSourceResponse)
async def set_primary_table(
    source_id: int,
    payload: PrimaryTableUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DataSourceResponse:
    """Choose which table the dashboard and findings analyse."""
    source = await fetch_owned(db, DataSource, source_id, current_user)

    schema = parse_schema_json(source.schema_json) or {"tables": []}
    available = [t["name"] for t in schema.get("tables", [])]
    if payload.table not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown table. This source exposes: {', '.join(available) or 'none'}",
        )

    config = parse_connection_config(source)
    config["primary_table"] = payload.table
    source.connection_config = json.dumps(config)

    # Columns differ per table, so the schema profile and mapping are rebuilt.
    try:
        await _apply_schema_and_mapping(source, reset_mapping=True, db=db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(source)
    return _to_response(source)


@router.post("/{source_id}/automap", response_model=DataSourceResponse)
async def automap_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DataSourceResponse:
    """Ask the model to re-map this source's columns from scratch."""
    source = await fetch_owned(db, DataSource, source_id, current_user)

    runtime = await get_ai_runtime(db)
    if not runtime["api_key"]:
        raise HTTPException(
            status_code=400,
            detail=(
                "No AI provider is configured, so columns cannot be mapped "
                "automatically. Add a key under Settings, or map the fields by hand."
            ),
        )

    schema = parse_schema_json(source.schema_json) or {"tables": []}
    if not schema.get("tables"):
        raise HTTPException(status_code=400, detail="This source has no schema to map")

    try:
        sample = await preview_source_data(source, limit=PROFILE_SAMPLE_ROWS, offset=0)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read the data: {exc}") from exc

    config = parse_connection_config(source)
    await _apply_ai_mapping(db, source, schema, sample, config)
    if config.get("mapping_source") != "ai":
        raise HTTPException(
            status_code=502,
            detail="The AI provider did not return a usable mapping. Try again, or map by hand.",
        )

    source.connection_config = json.dumps(config)
    await db.commit()
    await db.refresh(source)
    return _to_response(source)


@router.post("/{source_id}/recompute", response_model=DataSourceResponse)
async def recompute_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DataSourceResponse:
    source = await fetch_owned(db, DataSource, source_id, current_user)
    try:
        await _apply_schema_and_mapping(source, reset_mapping=False, db=db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    await db.refresh(source)
    return _to_response(source)


@router.patch("/{source_id}", response_model=DataSourceResponse)
async def update_source(
    source_id: int,
    payload: DataSourceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DataSourceResponse:
    source = await fetch_owned(db, DataSource, source_id, current_user)

    if payload.name is not None:
        source.name = payload.name
    if payload.connection_config is not None:
        # Reads get a redacted config, so a client round-tripping it would
        # otherwise overwrite the real password with the mask.
        existing = parse_connection_config(source)
        merged = dict(payload.connection_config)
        for key, value in merged.items():
            if key.lower() in _SECRET_CONFIG_KEYS and value == _REDACTED:
                merged[key] = existing.get(key, "")
        source.connection_config = json.dumps(merged)

    await db.commit()
    await db.refresh(source)
    return _to_response(source)


async def _purge_dependents(db: AsyncSession, source_id: int) -> None:
    """Remove queries for a source and any dashboard widget pointing at them.

    ``queries.data_source_id`` is NOT NULL, so the ORM default of nulling the
    foreign key raises an IntegrityError. Delete the dependents explicitly.
    """
    # No owner filter here on purpose: the source was ownership-checked before
    # this ran, and every query against it belongs to that same owner. Filtering
    # again would leave orphans behind and re-raise the IntegrityError.
    result = await db.execute(select(QueryModel).where(QueryModel.data_source_id == source_id))
    queries = list(result.scalars().all())

    await prune_dashboard_widgets(db, (q.id for q in queries))
    for query in queries:
        await db.delete(query)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    source = await fetch_owned(db, DataSource, source_id, current_user)

    await _purge_dependents(db, source_id)
    await db.delete(source)
    await db.commit()

    if source.source_type == "file":
        config = parse_connection_config(source)
        file_path = config.get("file_path")
        if file_path:
            Path(file_path).unlink(missing_ok=True)


@router.get("/{source_id}/preview", response_model=PreviewResponse)
async def preview_source(
    source_id: int,
    table: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    source = await fetch_owned(db, DataSource, source_id, current_user)
    try:
        return await preview_source_data(source, table=table, limit=limit, offset=offset)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
