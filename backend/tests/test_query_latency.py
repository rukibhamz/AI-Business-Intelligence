"""What the answer path is allowed to wait for, in series.

An advisory answer makes two model calls and one web search. Only the model
calls depend on each other; the search depends solely on the diagnosis, which is
already computed by then. Running it in series anyway put its whole round trip
on the critical path for nothing, which is what these guard against.
"""

import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.deps import get_current_user
from app.main import app
from app.models import DataSource, User
from app.services.analytics import Dataset
from app.services.conversation_context import Turn, build_context_block
from tests.test_diagnostics import sales_rows

MAPPING = {
    "order_date": "Date",
    "region": "Region",
    "revenue": "Revenue",
    "cost": "Cost",
    "units": "Quantity",
}

#: How long the fake search and the fake model call each take. Long enough that
#: series and parallel are unmistakably different, short enough not to drag.
STEP = 0.25


@pytest.fixture
async def session_factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'lat.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def wired(session_factory, monkeypatch):
    """The real route, with the model, the search and the dataset swapped out."""
    async with session_factory() as setup:
        user = User(email="boss@nexasphere.test", hashed_password="", full_name="Boss")
        setup.add(user)
        await setup.commit()
        await setup.refresh(user)
        source = DataSource(
            user_id=user.id,
            name="Sales",
            source_type="file",
            connection_config=json.dumps({"file_path": "x.csv", "format": "csv"}),
            schema_json=json.dumps({"tables": []}),
        )
        setup.add(source)
        await setup.commit()

    rows = sales_rows()
    dataset = Dataset(
        source=None,
        columns=list(rows[0].keys()),
        rows=rows,
        total=len(rows),
        truncated=False,
        mapping=MAPPING,
    )

    calls: dict[str, int] = {"search": 0, "answer": 0, "practices": 0}

    async def fake_load_dataset(src, **kwargs):
        return dataset

    async def fake_answer(*args, **kwargs):
        calls["answer"] += 1
        await asyncio.sleep(STEP)
        return "Measured answer.", []

    async def fake_search(query, **kwargs):
        calls["search"] += 1
        await asyncio.sleep(STEP)
        return []

    async def fake_research_runtime(db):
        return {"api_key": "brave-key", "country": ""}

    async def fake_practices(*args, **kwargs):
        calls["practices"] += 1
        return []

    import app.routes.queries as route

    monkeypatch.setattr(route, "load_dataset", fake_load_dataset)
    monkeypatch.setattr(route, "generate_diagnostic_answer", fake_answer)
    monkeypatch.setattr(route, "web_search", fake_search)
    monkeypatch.setattr(route, "get_research_runtime", fake_research_runtime)
    monkeypatch.setattr(route, "generate_practices", fake_practices)

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c, calls
    app.dependency_overrides.clear()


async def test_the_search_runs_alongside_the_answer_not_after_it(wired):
    """In series this costs 2 x STEP; overlapped it costs about one."""
    client, calls = wired
    started = time.perf_counter()
    response = await client.post(
        "/api/queries/run",
        json={"natural_language": "what should we do about the margin?"},
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 201
    assert calls["answer"] == 1
    assert calls["search"] == 1
    # Generous headroom for the rest of the request; the point is that it is
    # nowhere near the 2 x STEP a serial version would cost.
    assert elapsed < STEP * 1.8, f"search appears to be serialised: {elapsed:.2f}s"


async def test_a_question_that_did_not_ask_for_advice_never_searches(wired):
    """"Why did it fall" wants the cause. Paying for a search there is waste."""
    client, calls = wired
    response = await client.post(
        "/api/queries/run",
        json={"natural_language": "why did the margin fall?"},
    )
    assert response.status_code == 201
    assert calls["search"] == 0
    assert calls["practices"] == 0


async def test_an_empty_search_skips_the_second_model_call(wired):
    """No results means nothing to summarise, so the extra round trip is skipped."""
    client, calls = wired
    await client.post(
        "/api/queries/run",
        json={"natural_language": "what should we do about the margin?"},
    )
    assert calls["search"] == 1
    assert calls["practices"] == 0


# --- prompt size ------------------------------------------------------------


def test_older_turns_are_summarised_rather_than_reproduced():
    """Every character here is paid for in time-to-first-token."""
    full = Turn(
        question="which store had the highest revenue in February?",
        answer="Ikeja led at 12,400. " * 20,
        columns=["store", "revenue", "profit"],
        rows=[{"store": f"Store {n}", "revenue": n} for n in range(5)],
        sql="SELECT store, SUM(revenue) FROM sales GROUP BY store ORDER BY 2 DESC",
    )
    block = build_context_block([full, full, full])

    # Only the turn immediately before the question carries its full shape.
    assert block.count("Result columns:") == 1
    assert block.count("SQL:") == 1
    assert block.count("Named in the result:") == 1
    # All three still place the thread's subject.
    assert block.count("Asked:") == 3


def test_the_block_stays_within_a_sane_budget():
    """A transcript must not crowd the schema out of the prompt.

    ~1.6k characters is roughly 400 tokens: the ceiling with every field at its
    maximum, which real turns are nowhere near. It is also paid on one call now
    rather than two, since the SQL prompt takes the planner's resolved question
    instead of the raw history.
    """
    turn = Turn(
        question="q" * 500,
        answer="a" * 2000,
        columns=[f"col_{n}" for n in range(30)],
        rows=[{"col_0": f"value {n}"} for n in range(5)],
        sql="SELECT " + "x, " * 200,
    )
    block = build_context_block([turn, turn, turn])
    # Roughly a tenth of what was handed in, and bounded regardless of input.
    assert len(block) < 1600, f"context block is {len(block)} chars"
    assert len(block) < len(turn.answer + turn.question + turn.sql) // 2
