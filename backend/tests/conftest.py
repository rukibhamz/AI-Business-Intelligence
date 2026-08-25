import asyncio
import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

# Tests must never touch the developer's real database or .env.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-for-tests")
os.environ.setdefault("UPLOAD_DIR", str(BACKEND_ROOT / "tests" / ".uploads"))


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_rows():
    """A small, realistic sales result set."""
    return [
        {"order_date": "2026-03-04", "region": "North", "revenue": 1200.5, "cost": 700},
        {"order_date": "2026-04-02", "region": "North", "revenue": 1500.0, "cost": 860},
        {"order_date": "2026-05-09", "region": "South", "revenue": 830.0, "cost": 500},
        {"order_date": "2026-06-30", "region": "West", "revenue": 2200.0, "cost": 600},
    ]


@pytest.fixture
def sample_columns():
    return ["order_date", "region", "revenue", "cost"]
