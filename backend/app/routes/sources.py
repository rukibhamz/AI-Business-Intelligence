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
from app.schemas import (
    DataSourceCreate,
    DataSourceResponse,
    DataSourceUpdate,
    MySQLSourceCreate,
    PreviewResponse,
)
from app.services.connectors import detect_file_format, save_upload
from app.services.schema_registry import (
    introspect_source,
    parse_connection_config,
    preview_source_data,
    serialize_schema,
    test_mysql_connection,
)

router = APIRouter(prefix="/sources", tags=["data-sources"])


@router.get("", response_model=list[DataSourceResponse])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[DataSource]:
    result = await db.execute(select(DataSource).order_by(DataSource.created_at.desc()))
    return list(result.scalars().all())


@router.post("", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: DataSourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DataSource:
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
    return source


@router.post("/upload", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
async def upload_source(
    file: UploadFile = File(...),
    name: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DataSource:
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
        schema = await introspect_source(source)
        source.schema_json = serialize_schema(schema)
    except Exception as exc:
        await db.rollback()
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {exc}") from exc

    await db.commit()
    await db.refresh(source)
    return source


@router.post("/mysql", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_mysql_source(
    payload: MySQLSourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DataSource:
    config = payload.connection_config.model_dump()

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
        schema = await introspect_source(source)
        source.schema_json = serialize_schema(schema)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Schema introspection failed: {exc}") from exc

    await db.commit()
    await db.refresh(source)
    return source


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
) -> DataSource:
    source = await db.get(DataSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")
    return source


@router.patch("/{source_id}", response_model=DataSourceResponse)
async def update_source(
    source_id: int,
    payload: DataSourceUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> DataSource:
    source = await db.get(DataSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")

    if payload.name is not None:
        source.name = payload.name
    if payload.connection_config is not None:
        source.connection_config = json.dumps(payload.connection_config)

    await db.commit()
    await db.refresh(source)
    return source


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> None:
    source = await db.get(DataSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")

    if source.source_type == "file":
        config = parse_connection_config(source)
        file_path = config.get("file_path")
        if file_path:
            Path(file_path).unlink(missing_ok=True)

    await db.delete(source)
    await db.commit()


@router.get("/{source_id}/preview", response_model=PreviewResponse)
async def preview_source(
    source_id: int,
    table: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
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
