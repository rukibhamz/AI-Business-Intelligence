import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import DataSource, Query as QueryModel, User
from app.schemas import ChartRecommendation, QueryCreate, QueryResponse, QueryResultPayload
from app.services.ai_query import execute_sql, generate_sql, pack_result
from app.services.app_settings import get_ai_runtime
from app.services.chart_recommend import recommend_chart

router = APIRouter(prefix="/queries", tags=["queries"])


def _chart_for_result(result: QueryResultPayload | None) -> ChartRecommendation | None:
    if not result:
        return None
    rec = recommend_chart(result.columns, result.rows)
    return ChartRecommendation(**rec)


def _to_response(
    query: QueryModel,
    *,
    mode: str | None = None,
    explanation: str | None = None,
) -> QueryResponse:
    result = None
    if query.result_json:
        raw = json.loads(query.result_json)
        result = QueryResultPayload(
            columns=raw.get("columns", []),
            rows=raw.get("rows", []),
            sql=raw.get("sql") or query.generated_sql,
        )
    return QueryResponse(
        id=query.id,
        data_source_id=query.data_source_id,
        natural_language=query.natural_language,
        generated_sql=query.generated_sql,
        status=query.status,
        created_at=query.created_at,
        result=result,
        explanation=explanation,
        mode=mode,
        chart=_chart_for_result(result),
    )


@router.get("", response_model=list[QueryResponse])
async def list_queries(
    data_source_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[QueryResponse]:
    stmt = select(QueryModel).order_by(QueryModel.created_at.desc()).limit(limit)
    if data_source_id is not None:
        stmt = stmt.where(QueryModel.data_source_id == data_source_id)
    rows = list((await db.execute(stmt)).scalars().all())
    return [_to_response(q) for q in rows]


@router.post("/run", response_model=QueryResponse, status_code=status.HTTP_201_CREATED)
async def run_query(
    payload: QueryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QueryResponse:
    source = await db.get(DataSource, payload.data_source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")

    query = QueryModel(
        user_id=current_user.id,
        data_source_id=payload.data_source_id,
        natural_language=payload.natural_language,
        status="running",
    )
    db.add(query)
    await db.commit()
    await db.refresh(query)

    mode = "heuristic"
    try:
        runtime = await get_ai_runtime(db)
        sql, mode = await generate_sql(
            source,
            payload.natural_language,
            api_key=runtime["api_key"],
            model=runtime["model"],
            base_url=runtime["base_url"],
        )
        result = await execute_sql(source, sql)
        query.generated_sql = result["sql"]
        query.result_json = pack_result(result)
        query.status = "completed"
        explanation = (
            f"Generated with {mode}. Returned {len(result['rows'])} row(s)."
        )
    except Exception as exc:
        query.status = "failed"
        query.result_json = pack_result(
            {"columns": [], "rows": [], "sql": query.generated_sql, "error": str(exc)}
        )
        await db.commit()
        await db.refresh(query)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(query)
    return _to_response(query, mode=mode, explanation=explanation)


@router.post("", response_model=QueryResponse, status_code=status.HTTP_201_CREATED)
async def create_query(
    payload: QueryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QueryResponse:
    """Create a pending query record without executing (legacy). Prefer POST /queries/run."""
    source = await db.get(DataSource, payload.data_source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Data source not found")

    query = QueryModel(
        user_id=current_user.id,
        data_source_id=payload.data_source_id,
        natural_language=payload.natural_language,
        status="pending",
    )
    db.add(query)
    await db.commit()
    await db.refresh(query)
    return _to_response(query)


@router.get("/{query_id}/export")
async def export_query_csv(
    query_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    query = await db.get(QueryModel, query_id)
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")
    if not query.result_json:
        raise HTTPException(status_code=400, detail="Query has no result to export")

    raw = json.loads(query.result_json)
    columns: list[str] = raw.get("columns", [])
    rows: list[dict] = raw.get("rows", [])
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in columns})

    filename = f"query_{query_id}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{query_id}", response_model=QueryResponse)
async def get_query(
    query_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> QueryResponse:
    query = await db.get(QueryModel, query_id)
    if not query:
        raise HTTPException(status_code=404, detail="Query not found")
    return _to_response(query)
