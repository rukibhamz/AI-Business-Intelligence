import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import Dashboard, User
from app.models import Query as QueryModel
from app.schemas import (
    DashboardCreate,
    DashboardResponse,
    DashboardUpdate,
    DashboardWidgetCreate,
    DashboardWidgetPayload,
)
from app.services.chart_recommend import recommend_chart
from app.services.ownership import fetch_owned, owned_by

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


def _parse_layout(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {"widgets": []}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"widgets": []}
    if not isinstance(data, dict):
        return {"widgets": []}
    widgets = data.get("widgets")
    if not isinstance(widgets, list):
        data["widgets"] = []
    return data


def _to_response(dash: Dashboard) -> DashboardResponse:
    layout = _parse_layout(dash.layout_json)
    widgets = [
        DashboardWidgetPayload(**w) if isinstance(w, dict) else w
        for w in layout.get("widgets", [])
        if isinstance(w, dict) and "id" in w and "query_id" in w
    ]
    return DashboardResponse(
        id=dash.id,
        name=dash.name,
        layout_json=dash.layout_json,
        widgets=widgets,
        created_at=dash.created_at,
        updated_at=dash.updated_at,
    )


@router.get("", response_model=list[DashboardResponse])
async def list_dashboards(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DashboardResponse]:
    rows = list(
        (await db.execute(owned_by(select(Dashboard), Dashboard, current_user).order_by(Dashboard.updated_at.desc())))
        .scalars()
        .all()
    )
    return [_to_response(d) for d in rows]


@router.post("", response_model=DashboardResponse, status_code=status.HTTP_201_CREATED)
async def create_dashboard(
    payload: DashboardCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardResponse:
    dash = Dashboard(
        user_id=current_user.id,
        name=payload.name,
        layout_json=json.dumps({"widgets": []}),
    )
    db.add(dash)
    await db.commit()
    await db.refresh(dash)
    return _to_response(dash)


@router.post("/ensure-default", response_model=DashboardResponse)
async def ensure_default_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardResponse:
    """Return the first dashboard, or create 'Main Dashboard'."""
    existing = (
        await db.execute(owned_by(select(Dashboard), Dashboard, current_user).order_by(Dashboard.created_at.asc()).limit(1))
    ).scalar_one_or_none()
    if existing:
        return _to_response(existing)
    dash = Dashboard(
        user_id=current_user.id,
        name="Main Dashboard",
        layout_json=json.dumps({"widgets": []}),
    )
    db.add(dash)
    await db.commit()
    await db.refresh(dash)
    return _to_response(dash)


@router.get("/{dashboard_id}", response_model=DashboardResponse)
async def get_dashboard(
    dashboard_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardResponse:
    dash = await fetch_owned(db, Dashboard, dashboard_id, current_user)
    return _to_response(dash)


@router.patch("/{dashboard_id}", response_model=DashboardResponse)
async def update_dashboard(
    dashboard_id: int,
    payload: DashboardUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardResponse:
    dash = await fetch_owned(db, Dashboard, dashboard_id, current_user)
    if payload.name is not None:
        dash.name = payload.name
    if payload.layout_json is not None:
        dash.layout_json = json.dumps(payload.layout_json)
    await db.commit()
    await db.refresh(dash)
    return _to_response(dash)


@router.delete("/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard(
    dashboard_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    dash = await fetch_owned(db, Dashboard, dashboard_id, current_user)
    await db.delete(dash)
    await db.commit()


@router.post(
    "/{dashboard_id}/widgets",
    response_model=DashboardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_widget(
    dashboard_id: int,
    payload: DashboardWidgetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardResponse:
    dash = await fetch_owned(db, Dashboard, dashboard_id, current_user)

    query = await db.get(QueryModel, payload.query_id)
    if not query or query.status != "completed":
        raise HTTPException(status_code=400, detail="Query not found or not completed")

    chart_type = payload.chart_type
    title = payload.title or query.natural_language[:80]
    if not chart_type and query.result_json:
        raw = json.loads(query.result_json)
        rec = recommend_chart(raw.get("columns", []), raw.get("rows", []))
        chart_type = rec["type"]
    chart_type = chart_type or "table"

    layout = _parse_layout(dash.layout_json)
    widgets: list[dict[str, Any]] = list(layout.get("widgets", []))
    widgets.append(
        {
            "id": str(uuid.uuid4()),
            "query_id": query.id,
            "title": title,
            "chart_type": chart_type,
        }
    )
    layout["widgets"] = widgets
    dash.layout_json = json.dumps(layout)
    await db.commit()
    await db.refresh(dash)
    return _to_response(dash)


@router.delete("/{dashboard_id}/widgets/{widget_id}", response_model=DashboardResponse)
async def remove_widget(
    dashboard_id: int,
    widget_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardResponse:
    dash = await fetch_owned(db, Dashboard, dashboard_id, current_user)
    layout = _parse_layout(dash.layout_json)
    widgets = [
        w
        for w in layout.get("widgets", [])
        if isinstance(w, dict) and w.get("id") != widget_id
    ]
    layout["widgets"] = widgets
    dash.layout_json = json.dumps(layout)
    await db.commit()
    await db.refresh(dash)
    return _to_response(dash)
