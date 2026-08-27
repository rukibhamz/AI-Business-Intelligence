"""What has already been said in this chat, in a shape a prompt can use.

A follow-up is only answerable against what came before. "Why?", "what about
the least?", "what should we do about it?" name no measure, no period and no
segment — the turn before them does.

Until now only the previous question's *text* travelled forward, and only one
turn of it. That lost two things worth keeping:

* **The answer.** "Which store led in February?" returned a ranking; "why?"
  then re-derived from the whole dataset, with no idea which store or which
  month the user meant.
* **Everything before the last turn.** The third question in a chat could not
  refer to the first.

All of it is already persisted on `queries` — question, answer, result, SQL and
diagnosis. This module reads it back and renders it compactly enough to sit in
a prompt without crowding out the schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Query as QueryModel
from app.models import User
from app.services.ownership import owned_by

#: How many turns of history travel with a question. Three covers the follow-up
#: chains people actually ask ("…", "why?", "what do we do?") without pushing
#: the schema out of the prompt.
MAX_TURNS = 3

#: Result rows kept per turn. Enough to name what was on screen, not so many
#: that the model starts answering from stale rows instead of fresh ones.
MAX_RESULT_ROWS = 5


@dataclass(frozen=True)
class Turn:
    """One question and what came back from it."""

    question: str
    answer: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    sql: str | None = None
    response_format: str | None = None
    #: The measure a diagnostic turn was about, when there was one.
    measure_label: str | None = None

    @property
    def label_column(self) -> str | None:
        """The column that names the entities in this turn's result."""
        for column in self.columns:
            values = [row.get(column) for row in self.rows]
            if values and all(
                v is not None and not isinstance(v, (int, float)) and str(v).strip()
                for v in values
            ):
                return column
        return None

    @property
    def entities(self) -> list[str]:
        """The things this turn's answer was about — "Ikeja", "Electronics"."""
        column = self.label_column
        if not column:
            return []
        seen: list[str] = []
        for row in self.rows:
            value = str(row.get(column, "")).strip()
            if value and value not in seen:
                seen.append(value)
        return seen


def _turn_from_query(query: QueryModel) -> Turn:
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    sql: str | None = query.generated_sql
    if query.result_json:
        try:
            raw = json.loads(query.result_json)
        except ValueError:
            raw = {}
        columns = list(raw.get("columns") or [])
        rows = list(raw.get("rows") or [])[:MAX_RESULT_ROWS]
        sql = raw.get("sql") or sql

    measure_label: str | None = None
    if query.diagnosis_json:
        try:
            stored = json.loads(query.diagnosis_json)
        except ValueError:
            stored = {}
        diagnosis = stored.get("diagnosis")
        if isinstance(diagnosis, dict):
            measure_label = diagnosis.get("measure_label")

    return Turn(
        question=query.natural_language,
        answer=query.answer,
        columns=columns,
        rows=rows,
        sql=sql,
        response_format=query.response_format,
        measure_label=measure_label,
    )


async def load_recent_turns(
    db: AsyncSession,
    session_id: str | None,
    user: User,
    *,
    limit: int = MAX_TURNS,
) -> list[Turn]:
    """The last few completed turns of this chat, oldest first.

    A turn still running is skipped: it is the question being asked right now.
    """
    if not session_id:
        return []
    rows = (
        (
            await db.execute(
                owned_by(
                    select(QueryModel).where(QueryModel.session_id == session_id),
                    QueryModel,
                    user,
                )
                .order_by(QueryModel.created_at.desc())
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    turns = [
        _turn_from_query(query)
        for query in rows
        if query.natural_language and query.status != "running"
    ]
    return list(reversed(turns[:limit]))


def previous_question(turns: list[Turn]) -> str | None:
    """The last thing asked, which is what a bare follow-up refers to."""
    return turns[-1].question if turns else None


def _truncate(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_context_block(turns: list[Turn], *, max_answer_chars: int = 300) -> str:
    """The recent turns as prompt text, or "" when there are none.

    Detail is tiered by recency, because every character here is paid for twice:
    the block goes into the planner call *and* the SQL call, on every question
    in a chat that has history, and prompt size is time-to-first-token. A
    pronoun almost always refers to the turn immediately before, so that one
    carries its full shape — answer, columns, entities, SQL — and older turns
    carry only enough to place the thread's subject.

    Explicitly labelled as history: the model needs it to resolve what "it"
    refers to, and must not answer *from* it.
    """
    if not turns:
        return ""

    lines = [
        "RECENT CONVERSATION (context for resolving references only — the "
        "current question must be answered from a fresh query, never from the "
        "figures below):"
    ]
    last = len(turns)
    for index, turn in enumerate(turns, start=1):
        latest = index == last
        lines.append(f"[{index}] Asked: {_truncate(turn.question, 200 if latest else 110)}")
        if turn.answer:
            lines.append(
                f"    Answered: "
                f"{_truncate(turn.answer, max_answer_chars if latest else 110)}"
            )
        if not latest:
            continue
        # The shape of the last result is what resolves "the same but…".
        if turn.columns:
            lines.append(f"    Result columns: {', '.join(turn.columns[:8])}")
        entities = turn.entities
        if entities:
            lines.append(f"    Named in the result: {', '.join(entities[:6])}")
        if turn.sql:
            lines.append(f"    SQL: {_truncate(turn.sql, 220)}")
    return "\n".join(lines)


def context_questions(turns: list[Turn]) -> list[str]:
    """The recent questions, newest first — what measure resolution reads.

    Newest first because the current turn's subject wins over an older one: a
    chat that moves from revenue to margin is asking about margin now.
    """
    return [turn.question for turn in reversed(turns) if turn.question]
