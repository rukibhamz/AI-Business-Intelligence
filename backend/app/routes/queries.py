from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import DataSource, Query
from app.schemas import QueryCreate, QueryResponse

router = APIRouter(prefix="/queries", tags=["queries"])


@router.post("", response_model=QueryResponse, status_code=status.HTTP_201_CREATED)
async def create_query(payload: QueryCreate, db: AsyncSession = Depends(get_db)) -> Query:
    source = await db.get(DataSource, payload.data_source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")

    query = Query(
        data_source_id=payload.data_source_id,
        natural_language=payload.natural_language,
        status="pending",
    )
    db.add(query)
    await db.commit()
    await db.refresh(query)
    return query


@router.get("/{query_id}", response_model=QueryResponse)
async def get_query(query_id: int, db: AsyncSession = Depends(get_db)) -> Query:
    query = await db.get(Query, query_id)
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")
    return query
