"""Chat threading: how queries group into conversations and get titled."""

from types import SimpleNamespace

import pytest

from app.routes.conversations import LEGACY_PREFIX, conversation_key, derive_title


def query(**kwargs):
    base = {"id": 1, "session_id": None, "natural_language": "q"}
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_queries_in_a_session_share_a_key():
    a = query(id=1, session_id="s_abc")
    b = query(id=2, session_id="s_abc")
    assert conversation_key(a) == conversation_key(b) == "s_abc"


def test_different_sessions_do_not_merge():
    assert conversation_key(query(id=1, session_id="s_a")) != conversation_key(
        query(id=2, session_id="s_b")
    )


def test_questions_without_a_session_stand_alone():
    """Rows written before conversations existed must not clump together."""
    a = conversation_key(query(id=7, session_id=None))
    b = conversation_key(query(id=8, session_id=None))
    assert a != b
    assert a.startswith(LEGACY_PREFIX)


def test_title_comes_from_the_opening_question():
    assert derive_title("revenue by region") == "revenue by region"


def test_title_collapses_whitespace():
    assert derive_title("  revenue   by\n region ") == "revenue by region"


def test_long_title_is_truncated_with_an_ellipsis():
    title = derive_title("x" * 200)
    assert len(title) <= 80
    assert title.endswith("…")


def test_rename_allows_a_longer_title():
    assert len(derive_title("y" * 200, limit=120)) <= 120


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_blank_question_gets_a_fallback_title(text):
    assert derive_title(text) == "Untitled chat"
