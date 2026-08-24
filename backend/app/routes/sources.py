import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import DataSource
from app.schemas import DataSourceCreate, DataSourceResponse, DataSourceUpdate

router = APIRouter(prefix="/sources", tags=["data-sources"])


@router.get("", response_model=list[DataSourceResponse])
async def list_sources(db: AsyncSession = Depends(get_db)) -> list[DataSource]:
    result = await db.execute(select(DataSource).order_by(DataSource.created_at.desc()))
    return list(result.scalars().all())


@router.post("", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: DataSourceCreate, db: AsyncSession = Depends(get_db)
) -> DataSource:
    source = DataSource(
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


@router.get("/{source_id}", response_model=DataSourceResponse)
async def get_source(source_id: int, db: AsyncSession = Depends(get_db)) -> DataSource:
    source = await db.get(DataSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")
    return source


@router.patch("/{source_id}", response_model=DataSourceResponse)
async def update_source(
    source_id: int, payload: DataSourceUpdate, db: AsyncSession = Depends(get_db)
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
async def delete_source(source_id: int, db: AsyncSession = Depends(get_db)) -> None:
    source = await db.get(DataSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")
    await db.delete(source)
    await db.commit()


@router.get("/{source_id}/preview")
async def preview_source(source_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    source = await db.get(DataSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")

    return {
        "source_id": source_id,
        "message": "Preview not implemented yet — Phase 2 task 2.4",
        "schema": json.loads(source.schema_json) if source.schema_json else None,
    }
