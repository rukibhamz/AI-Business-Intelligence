"""Referential cleanup for records the schema does not cascade.

Dashboard widgets point at queries by id inside a JSON layout, so the database
cannot enforce the link. Whenever queries are deleted — with their data source,
or with their conversation — the widgets referencing them must go too, or the
dashboard renders permanent loading placeholders.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dashboard


async def prune_dashboard_widgets(db: AsyncSession, query_ids: Iterable[int]) -> int:
    """Remove widgets pointing at the given queries. Returns how many went."""
    ids = set(query_ids)
    if not ids:
        return 0

    removed = 0
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
            w for w in widgets if not (isinstance(w, dict) and w.get("query_id") in ids)
        ]
        if len(kept) != len(widgets):
            removed += len(widgets) - len(kept)
            layout["widgets"] = kept
            dash.layout_json = json.dumps(layout)

    return removed
