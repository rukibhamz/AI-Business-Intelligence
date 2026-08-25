"""Chat threads: list, open, rename, delete.

A conversation groups the questions asked in one chat. Rows written before
conversations existed have a `session_id` but no `conversations` row, so the
listing is built by grouping queries and joining titles in — no backfill needed.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import Conversation, User
from app.models import Query as QueryModel
from app.routes.queries import query_to_response
from app.schemas import (
    ConversationDetail,
    ConversationSummary,
    ConversationUpdate,
)
from app.services.cleanup import prune_dashboard_widgets
from app.services.ownership import belongs_to, owned_by

router = APIRouter(prefix="/conversations", tags=["conversations"])

#: Questions that predate conversations get a stable synthetic thread id.
LEGACY_PREFIX = "q"


def conversation_key(query: QueryModel) -> str:
    return query.session_id or f"{LEGACY_PREFIX}{query.id}"


def derive_title(text: str, limit: int = 80) -> str:
    """A chat is titled by the question that opened it."""
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned or "Untitled chat"
    return cleaned[: limit - 1].rstrip() + "…"


async def ensure_conversation(
    db: AsyncSession,
    *,
    session_id: str | None,
    first_question: str,
    user_id: int | None,
) -> Conversation | None:
    """Create the thread row on its first question; touch it on later ones."""
    if not session_id:
        return None

    existing = await db.get(Conversation, session_id)
    if existing:
        existing.updated_at = datetime.now()
        return existing

    conversation = Conversation(
        id=session_id,
        user_id=user_id,
        title=derive_title(first_question),
    )
    db.add(conversation)
    return conversation


async def _load_queries(db: AsyncSession, user: User, limit: int = 1000) -> list[QueryModel]:
    """This account's questions. A chat thread never spans two people."""
    stmt = (
        owned_by(select(QueryModel), QueryModel, user)
        .order_by(QueryModel.created_at.desc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ConversationSummary]:
    queries = await _load_queries(db, current_user)
    titles = {
        c.id: c.title
        for c in (
            await db.execute(owned_by(select(Conversation), Conversation, current_user))
        )
        .scalars()
        .all()
    }

    grouped: dict[str, list[QueryModel]] = {}
    for query in queries:
        grouped.setdefault(conversation_key(query), []).append(query)

    summaries: list[ConversationSummary] = []
    for key, items in grouped.items():
        # `queries` is newest-first, so the opening question is last.
        ordered = sorted(items, key=lambda q: q.created_at)
        opening = ordered[0]
        latest = ordered[-1]
        summaries.append(
            ConversationSummary(
                id=key,
                title=titles.get(key) or derive_title(opening.natural_language),
                message_count=len(ordered),
                created_at=opening.created_at,
                updated_at=latest.created_at,
                last_question=latest.natural_language,
                last_answer=latest.answer,
                is_legacy=key.startswith(LEGACY_PREFIX) and not latest.session_id,
            )
        )

    summaries.sort(key=lambda c: c.updated_at, reverse=True)
    return summaries[:limit]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationDetail:
    queries = await _load_queries(db, current_user)
    items = sorted(
        (q for q in queries if conversation_key(q) == conversation_id),
        key=lambda q: q.created_at,
    )
    if not items:
        raise HTTPException(status_code=404, detail="Conversation not found")

    stored = await db.get(Conversation, conversation_id)
    if stored is not None and not belongs_to(stored, current_user):
        stored = None
    return ConversationDetail(
        id=conversation_id,
        title=(stored.title if stored else derive_title(items[0].natural_language)),
        message_count=len(items),
        created_at=items[0].created_at,
        updated_at=items[-1].created_at,
        messages=[query_to_response(q) for q in items],
    )


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationSummary:
    queries = await _load_queries(db, current_user)
    items = sorted(
        (q for q in queries if conversation_key(q) == conversation_id),
        key=lambda q: q.created_at,
    )
    if not items:
        raise HTTPException(status_code=404, detail="Conversation not found")

    stored = await db.get(Conversation, conversation_id)
    if stored is not None and not belongs_to(stored, current_user):
        stored = None
    if not stored:
        # Renaming an older thread materializes its row.
        stored = Conversation(
            id=conversation_id,
            user_id=current_user.id,
            title=derive_title(items[0].natural_language),
        )
        db.add(stored)

    stored.title = derive_title(payload.title, limit=120)
    await db.commit()

    return ConversationSummary(
        id=conversation_id,
        title=stored.title,
        message_count=len(items),
        created_at=items[0].created_at,
        updated_at=items[-1].created_at,
        last_question=items[-1].natural_language,
        last_answer=items[-1].answer,
        is_legacy=not items[-1].session_id,
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    queries = await _load_queries(db, current_user)
    items = [q for q in queries if conversation_key(q) == conversation_id]
    if not items:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await prune_dashboard_widgets(db, (q.id for q in items))
    for query in items:
        await db.delete(query)

    stored = await db.get(Conversation, conversation_id)
    if stored is not None and belongs_to(stored, current_user):
        await db.delete(stored)

    await db.commit()
