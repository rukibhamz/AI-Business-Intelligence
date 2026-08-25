"""Live overview + findings computed from connected data sources."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import DataSource, User
from app.schemas import FindingsResponse, OverviewResponse
from app.services.analytics import (
    build_findings,
    build_overview,
    coverage_report,
    load_dataset,
    summarize_sources,
)

router = APIRouter(prefix="/insights", tags=["insights"])


async def _list_sources(db: AsyncSession) -> list[DataSource]:
    result = await db.execute(select(DataSource).order_by(DataSource.created_at.desc()))
    return list(result.scalars().all())


async def _resolve_source(db: AsyncSession, source_id: int | None) -> DataSource | None:
    sources = await _list_sources(db)
    if not sources:
        return None
    if source_id is not None:
        match = next((s for s in sources if s.id == source_id), None)
        if match is None:
            raise HTTPException(status_code=404, detail="Data source not found")
        return match

    summaries = {s["id"]: s for s in summarize_sources(sources)}
    confirmed = [
        s
        for s in sources
        if summaries[s.id]["analyzable"] and summaries[s.id]["mapping_status"] == "confirmed"
    ]
    if confirmed:
        return confirmed[0]
    analyzable = [s for s in sources if summaries[s.id]["analyzable"]]
    return analyzable[0] if analyzable else sources[0]


def _source_meta(source: DataSource, dataset) -> dict:
    return {
        "id": source.id,
        "name": source.name,
        "source_type": source.source_type,
        "rows_analyzed": len(dataset.rows),
        "total_rows": dataset.total,
        "truncated": dataset.truncated,
    }


@router.get("/overview", response_model=OverviewResponse)
async def get_overview(
    source_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    sources = await _list_sources(db)
    available = summarize_sources(sources)
    generated_at = datetime.now(timezone.utc).isoformat()

    source = await _resolve_source(db, source_id)
    if source is None:
        return {
            "generated_at": generated_at,
            "source": None,
            "available_sources": available,
            "kpis": [],
            "charts": [],
            "coverage": None,
            "notices": [],
            "period": None,
            "error": None,
        }

    try:
        dataset = await load_dataset(source)
    except Exception as exc:  # connector/IO failures should not blank the page
        return {
            "generated_at": generated_at,
            "source": {
                "id": source.id,
                "name": source.name,
                "source_type": source.source_type,
                "rows_analyzed": 0,
                "total_rows": 0,
                "truncated": False,
            },
            "available_sources": available,
            "kpis": [],
            "charts": [],
            "coverage": None,
            "notices": [],
            "period": None,
            "error": f"Could not read this data source: {exc}",
        }

    overview = build_overview(dataset)
    return {
        "generated_at": generated_at,
        "source": _source_meta(source, dataset),
        "available_sources": available,
        "kpis": overview["kpis"],
        "charts": overview["charts"],
        "coverage": coverage_report(dataset),
        "notices": overview["notices"],
        "period": overview["period"],
        "error": None,
    }


@router.get("/findings", response_model=FindingsResponse)
async def get_findings(
    source_id: int | None = Query(None),
    scope: str = Query("all", pattern="^(all|source)$"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    sources = await _list_sources(db)
    available = summarize_sources(sources)
    generated_at = datetime.now(timezone.utc).isoformat()

    if scope == "source" or source_id is not None:
        source = await _resolve_source(db, source_id)
        targets = [source] if source else []
    else:
        analyzable = {s["id"] for s in available if s["analyzable"]}
        targets = [s for s in sources if s.id in analyzable] or sources

    findings: list[dict] = []
    errors: list[str] = []
    for source in targets:
        if source is None:
            continue
        try:
            dataset = await load_dataset(source)
        except Exception as exc:
            errors.append(f"{source.name}: {exc}")
            continue
        for item in build_findings(dataset):
            item["source_id"] = source.id
            item["source_name"] = source.name
            findings.append(item)

    order = {"critical": 0, "warning": 1, "opportunity": 2, "info": 3}
    findings.sort(key=lambda f: order.get(f["severity"], 9))

    return {
        "generated_at": generated_at,
        "findings": findings,
        "available_sources": available,
        "errors": errors,
    }
