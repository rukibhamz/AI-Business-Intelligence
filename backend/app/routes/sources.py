import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Dashboard, DataSource, Query as QueryModel, User
from app.schemas import (
    DataSourceCreate,
    DataSourceResponse,
    DataSourceUpdate,
    FieldMappingUpdate,
    MySQLSourceCreate,
    PreviewResponse,
)
from app.services.connectors import detect_file_format, save_upload
from app.services.field_mapping import (
    CANONICAL_FIELDS,
    columns_from_schema,
    enrich_config_with_mapping,
)
from app.services.schema_registry import (
    introspect_source,
    parse_connection_config,
    preview_source_data,
    serialize_schema,
    test_mysql_connection,
)

router = APIRouter(prefix="/sources", tags=["data-sources"])


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
        connection_config=source.connection_config,
        schema_json=source.schema_json,
        created_at=source.created_at,
        updated_at=source.updated_at,
        field_mapping=mapping,
        mapping_status=str(status_val) if status_val else None,
        row_count=row_count,
    )


async def _apply_schema_and_mapping(source: DataSource, *, reset_mapping: bool = False) -> None:
    schema = await introspect_source(source)
    source.schema_json = serialize_schema(schema)
    cols = columns_from_schema(source.schema_json)
    config = parse_connection_config(source)
    config = enrich_config_with_mapping(config, cols, force_reset=reset_mapping)

    try:
        preview = await preview_source_data(source, limit=1, offset=0)
        config["row_count"] = preview.get("total", config.get("row_count"))
    except Exception:
        pass

    source.connection_config = json.dumps(config)


@router.get("/canonical-fields")
async def list_canonical_fields(_: User = Depends(get_current_user)) -> dict[str, list[str]]:
    return {"fields": CANONICAL_FIELDS}


@router.get("", response_model=list[DataSourceResponse])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[DataSourceResponse]:
    result = await db.execute(select(DataSource).order_by(DataSource.created_at.desc()))
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
        await _apply_schema_and_mapping(source, reset_mapping=True)
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
        await _apply_schema_and_mapping(source, reset_mapping=True)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Schema introspection failed: {exc}") from exc

    await db.commit()
    await db.refresh(source)
    return _to_response(source)


@router.post("/test-mysql")
async def test_mysql(
    payload: MySQLSourceCreate,
    _: User = Depends(get_current_user),
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
    _: User = Depends(get_current_user),
) -> DataSourceResponse:
    source = await db.get(DataSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")
    return _to_response(source)


@router.put("/{source_id}/mapping", response_model=DataSourceResponse)
async def update_mapping(
    source_id: int,
    payload: FieldMappingUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DataSourceResponse:
    source = await db.get(DataSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")

    cols = set(columns_from_schema(source.schema_json))
    cleaned = {k: v for k, v in payload.field_mapping.items() if k in cols}
    config = parse_connection_config(source)
    config["field_mapping"] = cleaned
    config["mapping_status"] = "confirmed" if payload.confirm else "pending"
    source.connection_config = json.dumps(config)
    await db.commit()
    await db.refresh(source)
    return _to_response(source)


@router.post("/{source_id}/recompute", response_model=DataSourceResponse)
async def recompute_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DataSourceResponse:
    source = await db.get(DataSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")
    try:
        await _apply_schema_and_mapping(source, reset_mapping=False)
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
    _: User = Depends(get_current_user),
) -> DataSourceResponse:
    source = await db.get(DataSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")

    if payload.name is not None:
        source.name = payload.name
    if payload.connection_config is not None:
        source.connection_config = json.dumps(payload.connection_config)

    await db.commit()
    await db.refresh(source)
    return _to_response(source)


async def _purge_dependents(db: AsyncSession, source_id: int) -> None:
    """Remove queries for a source and any dashboard widget pointing at them.

    ``queries.data_source_id`` is NOT NULL, so the ORM default of nulling the
    foreign key raises an IntegrityError. Delete the dependents explicitly.
    """
    result = await db.execute(select(QueryModel).where(QueryModel.data_source_id == source_id))
    queries = list(result.scalars().all())
    query_ids = {q.id for q in queries}

    if query_ids:
        dashboards = list((await db.execute(select(Dashboard))).scalars().all())
        for dash in dashboards:
            if not dash.layout_json:
                continue
            try:
                layout = json.loads(dash.layout_json)
            except json.JSONDecodeError:
                continue
            if not isinstance(layout, dict):
                continue
            widgets = layout.get("widgets")
            if not isinstance(widgets, list):
                continue
            kept = [
                w
                for w in widgets
                if not (isinstance(w, dict) and w.get("query_id") in query_ids)
            ]
            if len(kept) != len(widgets):
                layout["widgets"] = kept
                dash.layout_json = json.dumps(layout)

    for query in queries:
        await db.delete(query)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> None:
    source = await db.get(DataSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")

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
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    source = await db.get(DataSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")
    try:
        return await preview_source_data(source, table=table, limit=limit, offset=offset)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
