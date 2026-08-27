"""Each account sees only what it uploaded.

Provisioning decides who someone is; these decide what they can reach. The
HTTP cases run against the real routers with the database and the caller
swapped out, so the assertions are about the code that actually serves a
request rather than about a helper.
"""

import json
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.deps import get_current_user
from app.main import app
from app.models import Conversation, Dashboard, DataSource, User
from app.models import Query as QueryModel
from app.services.auth import ADMIN, MEMBER, ensure_user_from_claims
from app.services.ownership import belongs_to, fetch_owned
from app.services.supabase_auth import SupabaseClaims


@pytest.fixture
async def session_factory(tmp_path: Path):
    """A throwaway database, so these never touch the developer's own."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'iso.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def db(session_factory):
    async with session_factory() as session:
        yield session


def make_user(email: str, role: str = MEMBER) -> User:
    return User(email=email, hashed_password="", full_name=email, role=role)


async def two_users(db) -> tuple[User, User]:
    ada, ben = make_user("ada@nexasphere.test"), make_user("ben@nexasphere.test")
    db.add_all([ada, ben])
    await db.commit()
    await db.refresh(ada)
    await db.refresh(ben)
    return ada, ben


def make_source(owner: User, name: str) -> DataSource:
    return DataSource(
        user_id=owner.id,
        name=name,
        source_type="file",
        connection_config=json.dumps({"file_path": "x.csv", "format": "csv"}),
        schema_json=json.dumps({"tables": []}),
    )


# --- provisioning -----------------------------------------------------------


async def test_the_first_account_becomes_the_admin(db):
    """A fresh deployment must not lock itself out of Settings."""
    user = await ensure_user_from_claims(
        db, SupabaseClaims(subject="sub-1", email="first@nexasphere.test")
    )
    assert user.role == ADMIN
    assert user.is_admin is True


async def test_later_accounts_are_members(db):
    await ensure_user_from_claims(
        db, SupabaseClaims(subject="sub-1", email="first@nexasphere.test")
    )
    second = await ensure_user_from_claims(
        db, SupabaseClaims(subject="sub-2", email="second@nexasphere.test")
    )
    assert second.role == MEMBER
    assert second.is_admin is False


async def test_the_configured_admin_email_is_always_an_admin(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "admin_email", "boss@nexasphere.test")
    await ensure_user_from_claims(
        db, SupabaseClaims(subject="sub-1", email="first@nexasphere.test")
    )
    boss = await ensure_user_from_claims(
        db, SupabaseClaims(subject="sub-2", email="boss@nexasphere.test")
    )
    assert boss.role == ADMIN


async def test_an_existing_local_account_is_claimed_not_duplicated(db):
    """The same person signing in through Supabase keeps their uploads."""
    local = make_user("ada@nexasphere.test", role=ADMIN)
    local.hashed_password = "bcrypt-hash"
    db.add(local)
    await db.commit()
    await db.refresh(local)

    linked = await ensure_user_from_claims(
        db, SupabaseClaims(subject="sub-ada", email="ada@nexasphere.test")
    )
    assert linked.id == local.id
    assert linked.supabase_id == "sub-ada"
    assert linked.role == ADMIN


async def test_a_returning_account_is_matched_on_its_supabase_id(db):
    first = await ensure_user_from_claims(
        db, SupabaseClaims(subject="sub-1", email="ada@nexasphere.test")
    )
    again = await ensure_user_from_claims(
        db, SupabaseClaims(subject="sub-1", email="ada.new@nexasphere.test")
    )
    assert again.id == first.id
    assert again.email == "ada.new@nexasphere.test"


# --- the ownership helpers --------------------------------------------------


async def test_fetching_another_account_s_row_reports_it_missing(db):
    """Not 403: "exists but not yours" is itself a fact about their data."""
    ada, ben = await two_users(db)
    source = make_source(ada, "Ada's sales")
    db.add(source)
    await db.commit()
    await db.refresh(source)

    with pytest.raises(HTTPException) as exc:
        await fetch_owned(db, DataSource, source.id, ben)
    assert exc.value.status_code == 404


async def test_an_unowned_row_belongs_to_nobody(db):
    ada, _ = await two_users(db)
    orphan = make_source(ada, "orphan")
    orphan.user_id = None
    assert belongs_to(orphan, ada) is False


# --- the routes themselves --------------------------------------------------


@pytest.fixture
async def client(session_factory):
    """The real app, with the database and the caller swapped out."""
    state = {}

    async def override_db():
        async with session_factory() as session:
            yield session

    def override_user():
        return state["user"]

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        c.act_as = lambda user: state.update(user=user)  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()


async def test_a_dataset_is_listed_only_for_the_account_that_uploaded_it(client, db):
    ada, ben = await two_users(db)
    db.add_all([make_source(ada, "Ada sales"), make_source(ben, "Ben sales")])
    await db.commit()

    client.act_as(ada)
    names = [s["name"] for s in (await client.get("/api/sources")).json()]
    assert names == ["Ada sales"]

    client.act_as(ben)
    names = [s["name"] for s in (await client.get("/api/sources")).json()]
    assert names == ["Ben sales"]


async def test_reading_another_account_s_dataset_is_a_404(client, db):
    ada, ben = await two_users(db)
    source = make_source(ada, "Ada sales")
    db.add(source)
    await db.commit()
    await db.refresh(source)

    client.act_as(ben)
    assert (await client.get(f"/api/sources/{source.id}")).status_code == 404
    assert (await client.get(f"/api/sources/{source.id}/preview")).status_code == 404
    assert (await client.delete(f"/api/sources/{source.id}")).status_code == 404


async def test_questions_and_answers_are_not_shared(client, db):
    ada, ben = await two_users(db)
    source = make_source(ada, "Ada sales")
    db.add(source)
    await db.commit()
    await db.refresh(source)

    question = QueryModel(
        user_id=ada.id,
        data_source_id=source.id,
        natural_language="why did revenue fall",
        status="completed",
        session_id="s_ada",
    )
    db.add(question)
    await db.commit()
    await db.refresh(question)

    client.act_as(ben)
    assert (await client.get("/api/queries")).json() == []
    assert (await client.get(f"/api/queries/{question.id}")).status_code == 404
    assert (await client.get(f"/api/queries/{question.id}/export")).status_code == 404

    client.act_as(ada)
    assert len((await client.get("/api/queries")).json()) == 1


async def test_a_question_cannot_be_pinned_to_another_account_s_dataset(client, db):
    ada, ben = await two_users(db)
    source = make_source(ada, "Ada sales")
    db.add(source)
    await db.commit()
    await db.refresh(source)

    client.act_as(ben)
    response = await client.post(
        "/api/queries/run",
        json={"natural_language": "total revenue", "data_source_id": source.id},
    )
    assert response.status_code == 404


async def test_findings_and_overview_only_read_your_own_data(client, db):
    ada, ben = await two_users(db)
    db.add(make_source(ada, "Ada sales"))
    await db.commit()

    client.act_as(ben)
    overview = (await client.get("/api/insights/overview")).json()
    assert overview["source"] is None
    assert overview["available_sources"] == []
    assert (await client.get("/api/insights/findings")).json()["findings"] == []


async def test_conversations_and_dashboards_are_not_shared(client, db):
    ada, ben = await two_users(db)
    db.add_all(
        [
            Conversation(id="s_ada", user_id=ada.id, title="Ada's analysis"),
            Dashboard(id=1, user_id=ada.id, name="Ada's board", layout_json="{}"),
        ]
    )
    await db.commit()

    client.act_as(ben)
    assert (await client.get("/api/conversations")).json() == []
    assert (await client.get("/api/dashboards")).json() == []
    assert (await client.get("/api/dashboards/1")).status_code == 404


# --- what admin actually unlocks -------------------------------------------


async def test_a_member_cannot_change_configuration(client, db):
    ada, _ = await two_users(db)
    client.act_as(ada)
    response = await client.put("/api/settings", json={"platform_name": "Hijacked"})
    assert response.status_code == 403


async def test_a_member_never_sees_provider_configuration(client, db):
    ada, _ = await two_users(db)
    client.act_as(ada)
    view = (await client.get("/api/settings")).json()
    assert view["api_key_set"] is False
    assert view["api_key_masked"] is None
    assert view["llm_providers"] == []
    assert view["openai_model"] == ""
    # What the workspace is wired to is configuration, search included.
    assert view["brave_search_key_set"] is False
    assert view["brave_search_key_masked"] is None
    assert view["web_research_enabled"] is False
    # Branding is still there, or the app cannot render itself.
    assert view["platform_name"]
    assert view["currency"]


async def test_an_admin_may_change_configuration(client, db):
    boss = make_user("boss@nexasphere.test", role=ADMIN)
    db.add(boss)
    await db.commit()
    await db.refresh(boss)

    client.act_as(boss)
    response = await client.put("/api/settings", json={"platform_name": "NexaSphere BI"})
    assert response.status_code == 200
    assert response.json()["platform_name"] == "NexaSphere BI"


async def test_admin_is_not_a_key_to_other_people_s_data(client, db):
    """The difference between admin and member is Settings, and only Settings."""
    ada, _ = await two_users(db)
    boss = make_user("boss@nexasphere.test", role=ADMIN)
    db.add(boss)
    db.add(make_source(ada, "Ada sales"))
    await db.commit()

    client.act_as(boss)
    assert (await client.get("/api/sources")).json() == []
