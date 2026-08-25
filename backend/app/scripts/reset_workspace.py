"""Delete every dataset, question, dashboard and chat in the workspace.

Switching sign-in to Supabase changes who owns what. Rows created under the old
local accounts have no Supabase identity behind them, so with per-account
isolation on they belong to nobody and stay invisible. This clears them out.

It is a script and not a startup step on purpose: wiping a live database is not
something that should happen because a service restarted with a new setting.

    python -m app.scripts.reset_workspace --dry-run   # count what would go
    python -m app.scripts.reset_workspace --yes       # actually delete

Uploaded files on disk are left alone; remove `uploads/` yourself if you want
the bytes gone too.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import delete, func, select

from app.database import async_session
from app.models import Conversation, Dashboard, DataSource, User
from app.models import Query as QueryModel

#: Deleted in this order so a foreign key never points at a missing row.
TARGETS = (
    ("dashboards", Dashboard),
    ("conversations", Conversation),
    ("questions", QueryModel),
    ("data sources", DataSource),
)


async def counts() -> dict[str, int]:
    async with async_session() as db:
        out = {}
        for label, model in TARGETS:
            total = await db.execute(select(func.count()).select_from(model))
            out[label] = int(total.scalar_one())
        users = await db.execute(select(func.count()).select_from(User))
        out["accounts (kept)"] = int(users.scalar_one())
        return out


async def wipe() -> dict[str, int]:
    removed: dict[str, int] = {}
    async with async_session() as db:
        for label, model in TARGETS:
            result = await db.execute(delete(model))
            removed[label] = int(result.rowcount or 0)
        await db.commit()
    return removed


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="perform the deletion")
    parser.add_argument("--dry-run", action="store_true", help="only report what is there")
    args = parser.parse_args()

    before = await counts()
    print("Currently in the workspace:")
    for label, total in before.items():
        print(f"  {total:>6,}  {label}")

    if args.dry_run or not args.yes:
        print("\nNothing was deleted. Re-run with --yes to clear it.")
        return

    removed = await wipe()
    print("\nDeleted:")
    for label, total in removed.items():
        print(f"  {total:>6,}  {label}")
    print("\nAccounts were kept. Sign in and upload again.")


if __name__ == "__main__":
    asyncio.run(main())
