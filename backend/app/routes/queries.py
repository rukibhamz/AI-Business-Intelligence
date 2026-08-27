import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_config
from app.database import get_db
from app.deps import get_current_user
from app.models import DataSource, User
from app.models import Query as QueryModel
from app.schemas import (
    ChartRecommendation,
    Diagnosis,
    Practice,
    QueryCreate,
    QueryResponse,
    QueryResultPayload,
    Recommendation,
)
from app.services.ai_query import (
    UNTARGETED,
    build_question_plan,
    execute_sql_with_repair,
    generate_diagnostic_answer,
    generate_narrative,
    generate_partial_answer,
    generate_practices,
    generate_sql,
    generate_workspace_sql,
    pack_result,
    with_failover,
)
from app.services.analytics import load_dataset
from app.services.app_settings import (
    get_ai_runtime,
    get_currency,
    get_research_runtime,
    list_failover_runtimes,
    load_app_settings,
)
from app.services.conversation_context import (
    build_context_block,
    context_questions,
    load_recent_turns,
)
from app.services.conversation_context import (
    previous_question as last_question,
)
from app.services.diagnostics import (
    build_partial_context,
    build_recommendations,
    diagnose,
    diagnosis_result_payload,
    partial_result_payload,
    render_advice,
    render_diagnosis,
    render_partial,
)
from app.services.ownership import fetch_owned, owned_by
from app.services.profiling import schema_date_range
from app.services.rate_limit import RateLimiter
from app.services.response_planner import (
    answer_meta_question,
    classify_intent,
    describe_result,
    expand_question_with_context,
    plan_response,
)
from app.services.schema_context import pick_source_for_question, schema_as_json
from app.services.web_research import build_research_query
from app.services.web_research import search as web_search

router = APIRouter(prefix="/queries", tags=["queries"])

# Each run can call a paid AI provider, so cap it per user.
_query_limiter = RateLimiter(limit=app_config.query_rate_limit_per_minute)


def query_to_response(
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

    # The presentation guardrail decides chart vs prose vs table. Replay it for
    # stored queries so history renders the same way the answer first did.
    chart: ChartRecommendation | None = None
    response_format = query.response_format
    if result:
        plan = plan_response(
            query.natural_language, result.columns, result.rows, sql=result.sql
        )
        response_format = response_format or plan["format"]
        if response_format in ("chart", "narrative", "diagnostic") and plan.get("chart"):
            chart = ChartRecommendation(**plan["chart"])

    # A "why" answer carries its evidence with it, so History replays the
    # drivers and the recommended actions, not just the sentence.
    diagnosis: Diagnosis | None = None
    recommendations: list[Recommendation] = []
    practices: list[Practice] = []
    research_query: str | None = None
    if query.diagnosis_json:
        try:
            stored = json.loads(query.diagnosis_json)
        except ValueError:
            stored = {}
        if isinstance(stored.get("diagnosis"), dict):
            diagnosis = Diagnosis(**stored["diagnosis"])
        recommendations = [
            Recommendation(**item)
            for item in stored.get("recommendations", [])
            if isinstance(item, dict)
        ]
        practices = [
            Practice(**item)
            for item in stored.get("practices", [])
            if isinstance(item, dict)
        ]
        research_query = stored.get("research_query")

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
        chart=chart,
        session_id=query.session_id,
        answer=query.answer,
        response_format=response_format,
        diagnosis=diagnosis,
        recommendations=recommendations,
        practices=practices,
        research_query=research_query,
    )




async def _analyse(
    sources: list[DataSource],
    question: str,
    *,
    history: list[str],
    max_sources: int = 3,
) -> tuple[DataSource, dict | None, dict | None] | None:
    """Look for a source that can explain the move; settle for one that can't.

    Returns `(source, diagnosis, None)` when a full period comparison is
    possible. When it is not — no date column, one period, no mapped measure —
    it returns `(source, None, context)`: the comparison the data *does*
    support plus what is missing, which still answers the question honestly.
    Only a workspace with nothing readable in it returns None.
    """
    ordered = list(sources)
    if len(ordered) > 1:
        preferred = pick_source_for_question(ordered, question)
        if preferred is not None:
            ordered = [preferred] + [s for s in ordered if s.id != preferred.id]

    fallback: tuple[DataSource, dict | None, dict | None] | None = None

    for source in ordered[:max_sources]:
        try:
            dataset = await load_dataset(source)
        except Exception:  # an unreadable source should not sink the answer
            continue

        diagnosis = diagnose(dataset, question, history=history)
        if diagnosis:
            return source, diagnosis, None

        if fallback is None:
            context = build_partial_context(dataset, question, history=history)
            if context:
                fallback = (source, None, context)

    return fallback


async def _finalize(
    db: AsyncSession,
    query: QueryModel,
    payload: QueryCreate,
    current_user: User,
) -> None:
    """Persist the answer and materialize the chat thread History lists."""
    from app.routes.conversations import ensure_conversation

    opening = payload.natural_language
    if payload.session_id:
        first = (
            await db.execute(
                owned_by(
                    select(QueryModel).where(QueryModel.session_id == payload.session_id),
                    QueryModel,
                    current_user,
                )
                .order_by(QueryModel.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if first is not None:
            opening = first.natural_language
    await ensure_conversation(
        db,
        session_id=payload.session_id,
        first_question=opening,
        user_id=current_user.id,
    )

    await db.commit()
    await db.refresh(query)


@router.get("", response_model=list[QueryResponse])
async def list_queries(
    data_source_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[QueryResponse]:
    stmt = (
        owned_by(select(QueryModel), QueryModel, current_user)
        .order_by(QueryModel.created_at.desc())
        .limit(limit)
    )
    if data_source_id is not None:
        stmt = stmt.where(QueryModel.data_source_id == data_source_id)
    rows = list((await db.execute(stmt)).scalars().all())
    return [query_to_response(q) for q in rows]


@router.post("/run", response_model=QueryResponse, status_code=status.HTTP_201_CREATED)
async def run_query(
    payload: QueryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QueryResponse:
    allowed, retry_after = _query_limiter.check(str(current_user.id))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Too many questions in a short period. Try again in {retry_after}s."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    pinned: DataSource | None = None
    sources: list[DataSource]

    if payload.data_source_id is not None:
        pinned = await fetch_owned(db, DataSource, payload.data_source_id, current_user)
        sources = [pinned]
    else:
        # Workspace-wide questions still only reach this account's datasets.
        sources = list(
            (
                await db.execute(
                    owned_by(select(DataSource), DataSource, current_user).order_by(DataSource.id)
                )
            )
            .scalars()
            .all()
        )

    intent = classify_intent(payload.natural_language)

    if not sources and intent != "meta":
        raise HTTPException(
            status_code=400,
            detail="No data sources ingested yet. Add a dataset under Data Sources first.",
        )
    if not sources:
        raise HTTPException(
            status_code=400,
            detail=(
                "Connect a dataset under Data Sources first. After that you can ask "
                "about your business — or who I am — in plain language."
            ),
        )

    # Product/identity questions never touch the warehouse — management gets a
    # sentence, not SQL chrome.
    if intent == "meta":
        query = QueryModel(
            user_id=current_user.id,
            data_source_id=sources[0].id,
            natural_language=payload.natural_language,
            status="running",
            session_id=payload.session_id,
        )
        db.add(query)
        await db.commit()
        await db.refresh(query)

        settings_data = await load_app_settings(db)
        answer = answer_meta_question(
            payload.natural_language,
            platform_name=str(settings_data.get("platform_name") or "Cognitive Logic"),
        )
        query.generated_sql = None
        query.result_json = pack_result({"columns": [], "rows": [], "sql": None})
        query.status = "completed"
        query.response_format = "meta"
        query.answer = answer
        await _finalize(db, query, payload, current_user)
        return query_to_response(query, mode="meta", explanation="Product answer — no data query.")

    query = QueryModel(
        user_id=current_user.id,
        data_source_id=sources[0].id,
        natural_language=payload.natural_language,
        status="running",
        session_id=payload.session_id,
    )
    db.add(query)
    await db.commit()
    await db.refresh(query)

    mode = "heuristic"
    try:
        runtime = await get_ai_runtime(db)

        # "Why did revenue fall?" and "what do we do about it?" cannot be
        # answered by one SELECT over one period. Those go to the diagnostic
        # path, which compares periods and attributes the change before it
        # writes a word. Anything it cannot diagnose falls through to SQL.
        # The chat so far. Loaded once: the diagnostic path resolves the
        # measure from it, and the SQL path resolves what "it" refers to.
        turns = await load_recent_turns(db, payload.session_id, current_user)
        history = context_questions(turns)
        previous = last_question(turns)
        context_block = build_context_block(turns)

        analysis = None
        if intent in ("diagnostic", "advisory"):
            analysis = await _analyse(
                sources,
                payload.natural_language,
                history=history,
            )

        if analysis is not None and analysis[1] is not None:
            source, diagnosis, _ = analysis
            query.data_source_id = source.id
            # "Why" gets the explanation and a prompt to ask for the remedy;
            # only a question that asked for advice gets handed the actions.
            advisory = intent == "advisory"
            candidates = build_recommendations(diagnosis) if advisory else []

            answer, recommendations = await generate_diagnostic_answer(
                payload.natural_language,
                diagnosis,
                advisory=advisory,
                candidates=candidates,
                api_key=runtime["api_key"],
                model=runtime["model"],
                base_url=runtime["base_url"],
                source_name=source.name,
                currency=await get_currency(db),
                context_block=context_block,
            )
            mode = "diagnostic+model" if answer else "diagnostic"
            # The measured actions stand on their own; the model only rewords them.
            if not recommendations:
                recommendations = candidates
            if not answer:
                answer = (
                    render_advice(diagnosis, recommendations, source_name=source.name)
                    if advisory
                    else render_diagnosis(diagnosis, source_name=source.name)
                )

            # The practice lane. It runs only for a question that asked for
            # advice, only after the measured answer is written, and only when a
            # search key is configured. Nothing it returns can change a figure:
            # the model on this path never sees a row, and every practice it
            # keeps must cite a URL the search actually returned.
            practices: list[dict[str, str]] = []
            research_query: str | None = None
            if advisory:
                research = await get_research_runtime(db)
                if research:
                    research_query = build_research_query(
                        payload.natural_language, diagnosis
                    )
                    results = await web_search(
                        research_query,
                        api_key=research["api_key"],
                        country=research["country"] or None,
                    )
                    practices = await generate_practices(
                        payload.natural_language,
                        render_diagnosis(diagnosis, source_name=source.name),
                        results,
                        api_key=runtime["api_key"],
                        model=runtime["model"],
                        base_url=runtime["base_url"],
                    )

            result = diagnosis_result_payload(diagnosis)
            query.generated_sql = None
            query.result_json = pack_result(result)
            query.status = "completed"
            query.response_format = "diagnostic"
            query.answer = answer
            query.diagnosis_json = json.dumps(
                {
                    "diagnosis": diagnosis,
                    "recommendations": recommendations,
                    "practices": practices,
                    "research_query": research_query,
                },
                default=str,
            )

            explanation = (
                f"Diagnosed from “{source.name}”: {diagnosis['period_label']} versus "
                f"{diagnosis['previous_label']} across "
                f"{diagnosis['rows_analyzed']:,} row(s)."
            )
            await _finalize(db, query, payload, current_user)
            return query_to_response(query, mode=mode, explanation=explanation)

        if analysis is not None and analysis[2] is not None:
            # The data cannot support the comparison that was asked for. Say so
            # and give what it does show — dropping back to "write a SELECT and
            # summarise it" is what returned nothing for these questions.
            source, _, context = analysis
            query.data_source_id = source.id

            answer = await generate_partial_answer(
                payload.natural_language,
                context,
                api_key=runtime["api_key"],
                model=runtime["model"],
                base_url=runtime["base_url"],
                source_name=source.name,
                currency=await get_currency(db),
            )
            mode = "analysis+model" if answer else "analysis"
            if not answer:
                answer = render_partial(context, source_name=source.name)

            result = partial_result_payload(context)
            query.generated_sql = None
            query.result_json = pack_result(result)
            query.status = "completed"
            query.response_format = "narrative" if result["rows"] else "empty"
            query.answer = answer

            explanation = (
                f"Answered from “{source.name}” across "
                f"{context['rows_analyzed']:,} row(s); a period comparison was "
                "not available."
            )
            await _finalize(db, query, payload, current_user)
            return query_to_response(query, mode=mode, explanation=explanation)

        async def plan_and_write_sql(active: dict[str, str]):
            """Everything that needs a model. Retried against the next provider."""
            plan_for_question = await build_question_plan(
                pinned,
                sources,
                payload.natural_language,
                previous_question=previous,
                context_block=context_block,
                api_key=active["api_key"],
                model=active["model"],
                base_url=active["base_url"],
            )
            if pinned is not None:
                written, written_mode = await generate_sql(
                    pinned,
                    payload.natural_language,
                    api_key=active["api_key"],
                    model=active["model"],
                    base_url=active["base_url"],
                    previous_question=previous,
                    context_block=context_block,
                    analysis_plan=plan_for_question,
                )
                return pinned, written, written_mode, plan_for_question
            chosen, written, written_mode = await generate_workspace_sql(
                sources,
                payload.natural_language,
                api_key=active["api_key"],
                model=active["model"],
                base_url=active["base_url"],
                previous_question=previous,
                analysis_plan=plan_for_question,
            )
            return chosen, written, written_mode, plan_for_question

        # One provider rate-limiting should not end the question when another
        # is configured and idle.
        providers = await list_failover_runtimes(db) or [runtime]
        source, sql, mode, analysis_plan = await with_failover(providers, plan_and_write_sql)
        if pinned is None:
            query.data_source_id = source.id

        # Prefer the planner rewrite; fall back to follow-up expansion.
        resolved_question = (
            analysis_plan.get("resolved_question")
            or expand_question_with_context(payload.natural_language, previous)
        )

        result, final_sql, repairs = await execute_sql_with_repair(
            source,
            sql,
            resolved_question,
            analysis_plan=analysis_plan,
            api_key=runtime["api_key"],
            model=runtime["model"],
            base_url=runtime["base_url"],
        )
        query.generated_sql = final_sql
        query.result_json = pack_result(result)
        query.status = "completed"
        if repairs:
            mode = f"{mode}+repair"

        columns = result["columns"]
        rows = result["rows"]

        # Guardrail: choose how to present this before writing the answer.
        # Use the resolved follow-up so "what about the least?" still plans as
        # a ranked product answer, not an empty/meta shape.
        plan = plan_response(resolved_question, columns, rows, sql=result.get("sql"))
        query.response_format = plan["format"]

        # When nothing matched, say so and name the range that does exist —
        # a model asked to summarise an empty result just says "no data".
        coverage = None
        if plan["format"] == "empty":
            span = schema_date_range(schema_as_json(source))
            if span:
                coverage = f"{source.name} covers {span[0]} to {span[1]}."
            answer = describe_result(
                resolved_question,
                columns,
                rows,
                plan,
                source_name=source.name,
                coverage=coverage,
            )
        elif mode.startswith(UNTARGETED):
            # The offline planner did not understand the question, so these are
            # simply the first rows of the table. Summarising them as though
            # they answered it is how a wrong number reaches a decision.
            query.response_format = "table"
            answer = (
                f"I could not turn that question into a query without an AI model, so "
                f"this is a sample of {source.name} rather than an answer. Add an AI key "
                "under Settings, or ask for a specific measure and grouping — for "
                "example “revenue by product” or “average delivery days by partner”."
            )
        else:
            answer = await generate_narrative(
                resolved_question,
                columns,
                rows,
                api_key=runtime["api_key"],
                model=runtime["model"],
                base_url=runtime["base_url"],
                source_name=source.name,
                currency=await get_currency(db),
            )
            if not answer:
                answer = describe_result(
                    resolved_question, columns, rows, plan, source_name=source.name
                )
        query.answer = answer

        repair_note = f" ({repairs} repair{'s' if repairs != 1 else ''})" if repairs else ""
        explanation = (
            f"Answered from “{source.name}” via {mode}{repair_note}. "
            f"Returned {len(rows)} row(s)."
        )
    except Exception as exc:
        query.status = "failed"
        query.result_json = pack_result(
            {"columns": [], "rows": [], "sql": query.generated_sql, "error": str(exc)}
        )
        await db.commit()
        await db.refresh(query)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await _finalize(db, query, payload, current_user)
    return query_to_response(query, mode=mode, explanation=explanation)


@router.post("", response_model=QueryResponse, status_code=status.HTTP_201_CREATED)
async def create_query(
    payload: QueryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QueryResponse:
    """Create a pending query record without executing (legacy). Prefer POST /queries/run."""
    if payload.data_source_id is None:
        raise HTTPException(
            status_code=400, detail="data_source_id is required for pending queries"
        )
    await fetch_owned(db, DataSource, payload.data_source_id, current_user)

    query = QueryModel(
        user_id=current_user.id,
        data_source_id=payload.data_source_id,
        natural_language=payload.natural_language,
        status="pending",
    )
    db.add(query)
    await db.commit()
    await db.refresh(query)
    return query_to_response(query)


@router.get("/{query_id}/export")
async def export_query_csv(
    query_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    query = await fetch_owned(db, QueryModel, query_id, current_user)
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
    current_user: User = Depends(get_current_user),
) -> QueryResponse:
    query = await fetch_owned(db, QueryModel, query_id, current_user)
    return query_to_response(query)
