"""Structured analysis plan for factual NL→SQL questions.

Before writing SQL, rewrite the question into slots the model can follow:
measure, dimension, time window, ranking, and limit. The same plan is fed
into the SQL prompt and into the repair loop when a query fails or returns
nothing useful.
"""

from __future__ import annotations

import json
import re
from typing import Any, TypedDict

import httpx

from app.services.response_planner import expand_question_with_context


class AnalysisPlan(TypedDict):
    resolved_question: str
    intent_summary: str
    measure: str | None
    dimension: str | None
    time_window: str | None
    order: str | None  # "asc" | "desc" | None
    limit: int | None
    filters: list[str]


PLANNER_SYSTEM = """You plan factual business-intelligence questions before SQL is written.
Return ONLY valid JSON with these keys:
{
  "resolved_question": "standalone rewrite of what to answer",
  "intent_summary": "one short clause, e.g. 'top product by revenue in June'",
  "measure": "primary metric or null",
  "dimension": "group-by entity or null",
  "time_window": "period constraint in plain English or null",
  "order": "asc" | "desc" | null,
  "limit": number or null,
  "filters": ["any other constraints as short phrases"]
}

Rules:
- resolved_question must stand alone (expand follow-ups; flip highest↔lowest when asked).
- Prefer null over guessing columns that are not implied by the question.
- Do not invent years; leave time_window as the user stated it (e.g. "June").
- No markdown, no commentary — JSON only.
"""


def empty_plan(question: str) -> AnalysisPlan:
    q = (question or "").strip()
    return {
        "resolved_question": q,
        "intent_summary": q[:120] if q else "",
        "measure": None,
        "dimension": None,
        "time_window": None,
        "order": None,
        "limit": None,
        "filters": [],
    }


def heuristic_analysis_plan(
    question: str,
    *,
    previous_question: str | None = None,
) -> AnalysisPlan:
    """Offline slot fill from the resolved question text."""
    resolved = expand_question_with_context(question, previous_question)
    plan = empty_plan(resolved)
    q = resolved.lower()

    measures = (
        "return rate",
        "revenue",
        "sales",
        "profit",
        "margin",
        "cost",
        "spend",
        "budget",
        "quantity",
        "units",
        "orders",
        "stock",
        "inventory",
        "delivery",
        "returns",
    )
    for m in measures:
        if m in q:
            plan["measure"] = m
            break

    dimensions = (
        "product",
        "category",
        "region",
        "store",
        "partner",
        "campaign",
        "channel",
        "customer",
        "sku",
    )
    for d in dimensions:
        if re.search(rf"\b{d}s?\b", q):
            plan["dimension"] = d
            break

    time_match = re.search(
        r"\b("
        r"last\s+(?:month|week|quarter|year)|"
        r"this\s+(?:month|week|quarter|year)|"
        r"ytd|year[\s-]?to[\s-]?date|"
        r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
        r"nov(?:ember)?|dec(?:ember)?)"
        r"(?:\s+\d{4})?|"
        r"q[1-4](?:\s+\d{4})?|"
        r"\d{4}"
        r")\b",
        q,
    )
    if time_match:
        plan["time_window"] = time_match.group(1)

    if re.search(r"\b(highest|top|most|best|largest|biggest)\b", q):
        plan["order"] = "desc"
    elif re.search(r"\b(lowest|bottom|least|worst|smallest)\b", q):
        plan["order"] = "asc"

    lim = re.search(r"\b(?:top|bottom)\s+(\d+)\b", q)
    if lim:
        plan["limit"] = int(lim.group(1))
    elif plan["order"] and re.search(r"\b(product|region|store|campaign|partner)\b", q):
        plan["limit"] = 1

    bits = [b for b in (plan["measure"], plan["dimension"], plan["time_window"]) if b]
    if bits:
        plan["intent_summary"] = " / ".join(bits)
    return plan


def parse_analysis_plan(raw: str, *, fallback_question: str) -> AnalysisPlan:
    """Parse model JSON into an AnalysisPlan; fall back to heuristic slots."""
    base = heuristic_analysis_plan(fallback_question)
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return base
        data = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, TypeError, ValueError):
        return base

    if not isinstance(data, dict):
        return base

    resolved = str(data.get("resolved_question") or fallback_question).strip()
    order = data.get("order")
    if order is not None:
        order = str(order).lower().strip()
        if order not in ("asc", "desc"):
            order = None

    limit = data.get("limit")
    if limit is not None:
        try:
            limit = int(limit)
            if limit < 1 or limit > 500:
                limit = None
        except (TypeError, ValueError):
            limit = None

    filters = data.get("filters") or []
    if not isinstance(filters, list):
        filters = []
    filters = [str(f).strip() for f in filters if str(f).strip()][:8]

    def _opt(key: str) -> str | None:
        val = data.get(key)
        if val is None:
            return None
        s = str(val).strip()
        return s or None

    return {
        "resolved_question": resolved or base["resolved_question"],
        "intent_summary": _opt("intent_summary") or base["intent_summary"],
        "measure": _opt("measure") or base["measure"],
        "dimension": _opt("dimension") or base["dimension"],
        "time_window": _opt("time_window") or base["time_window"],
        "order": order if order is not None else base["order"],
        "limit": limit if limit is not None else base["limit"],
        "filters": filters or base["filters"],
    }


def format_plan_for_sql(plan: AnalysisPlan) -> str:
    """Compact block injected into the SQL user message."""
    lines = [
        "ANALYSIS PLAN (follow this; do not invent extra measures):",
        f"- Resolved question: {plan['resolved_question']}",
    ]
    if plan["intent_summary"]:
        lines.append(f"- Intent: {plan['intent_summary']}")
    if plan["measure"]:
        lines.append(f"- Measure: {plan['measure']}")
    if plan["dimension"]:
        lines.append(f"- Dimension / group-by: {plan['dimension']}")
    if plan["time_window"]:
        lines.append(
            f"- Time window: {plan['time_window']} "
            "(map to the real years in the schema date range)"
        )
    if plan["order"]:
        direction = "highest first" if plan["order"] == "desc" else "lowest first"
        lines.append(f"- Ranking: {plan['order']} ({direction})")
    if plan["limit"]:
        lines.append(f"- Limit: {plan['limit']}")
    if plan["filters"]:
        lines.append("- Filters: " + "; ".join(plan["filters"]))
    return "\n".join(lines)


async def plan_analysis(
    question: str,
    *,
    schema_text: str,
    previous_question: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> AnalysisPlan:
    """LLM plan when a key is available; otherwise heuristic slots only."""
    resolved = expand_question_with_context(question, previous_question)
    offline = heuristic_analysis_plan(question, previous_question=previous_question)
    if not api_key:
        return offline

    user_parts = [schema_text, "", f"Question: {question.strip()}"]
    if previous_question and previous_question.strip():
        user_parts.extend(
            [
                f"Previous question: {previous_question.strip()}",
                f"Resolved (heuristic): {resolved}",
            ]
        )
    user_parts.append("\nReturn the analysis plan JSON.")

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 280,
        "messages": [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": "\n".join(user_parts)},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                f"{(base_url or '').rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            res.raise_for_status()
            content = res.json()["choices"][0]["message"]["content"]
        return parse_analysis_plan(content, fallback_question=resolved)
    except Exception:
        return offline


def should_repair_blank(question: str, plan: AnalysisPlan) -> bool:
    """Whether an empty result is worth a SQL rewrite.

    Pure existence counts can legitimately be zero; most ranked / filtered
    questions that come back blank mean the filter was wrong.
    """
    q = (plan.get("resolved_question") or question or "").lower()
    if plan.get("time_window") or plan.get("filters"):
        return True
    if plan.get("order") or plan.get("limit"):
        return True
    if re.search(
        r"\b(between|during|in\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)|"
        r"last\s+|this\s+|where|only|except)\b",
        q,
    ):
        return True
    # "how many … in June" still deserves a repair if blank.
    if re.search(r"\bhow\s+many\b", q) and plan.get("time_window"):
        return True
    return False


def plan_to_dict(plan: AnalysisPlan) -> dict[str, Any]:
    return dict(plan)
