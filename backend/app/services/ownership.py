"""Every row belongs to the account that created it.

A dataset someone uploads is theirs: nobody else lists it, previews it, asks a
question against it, or sees it in findings. Admin is not an exception — it
unlocks Settings, not other people's data.

The rules live here rather than in each route so there is one place to read
when the question is "who can see this", and one place to change if that ever
becomes a sharing model.
"""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi import HTTPException, status
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Dashboard, DataSource, User
from app.models import Query as QueryModel

T = TypeVar("T")

#: The owner column for each thing a request can ask for by id.
_OWNER_COLUMN = {
    DataSource: DataSource.user_id,
    QueryModel: QueryModel.user_id,
    Dashboard: Dashboard.user_id,
    Conversation: Conversation.user_id,
}

_LABEL = {
    DataSource: "Data source",
    QueryModel: "Query",
    Dashboard: "Dashboard",
    Conversation: "Conversation",
}


def owned_by(stmt: Select, model: type, user: User) -> Select:
    """Restrict a listing to rows this account owns."""
    column = _OWNER_COLUMN[model]
    return stmt.where(column == user.id)


def belongs_to(row: Any, user: User) -> bool:
    """True when the row was created by this account.

    A row with no owner belongs to nobody. That is deliberate: rows left over
    from before accounts were isolated stay invisible rather than leaking to
    whoever signs in next.
    """
    return getattr(row, "user_id", None) == user.id


async def fetch_owned(
    db: AsyncSession,
    model: type[T],
    row_id: Any,
    user: User,
) -> T:
    """Load a row by id, or 404.

    Someone else's id is reported as missing, not as forbidden — "this exists
    but is not yours" is itself information about another account's data.
    """
    row = await db.get(model, row_id)
    if row is None or not belongs_to(row, user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{_LABEL.get(model, 'Resource')} not found",
        )
    return row
