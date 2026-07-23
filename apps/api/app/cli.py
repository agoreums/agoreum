"""Operational command-line entrypoints.

Run with:  python -m app.cli <command>

Commands here are for operators, not for application code paths.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

# Importing the model registry configures every ORM mapper. Without it, loading a
# single module leaves relationships pointing at classes SQLAlchemy has not seen.
import app.db.models  # noqa: F401
from app.core.logging import configure_logging, get_logger
from app.db.seed import seed_categories
from app.db.session import SessionLocal, dispose_engine

logger = get_logger(__name__)


async def _seed() -> int:
    """Insert reference data (marketplace taxonomy). Idempotent."""
    async with SessionLocal() as session:
        created = await seed_categories(session)
        await session.commit()
    await dispose_engine()
    print(f"Seed complete. Categories created: {created}")
    return 0


async def _check_db() -> int:
    """Verify the configured database is reachable and migrated."""
    from sqlalchemy import text

    async with SessionLocal() as session:
        version = (await session.execute(text("SELECT version()"))).scalar_one()
        revision = (
            await session.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
        tables = (
            await session.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables"
                    " WHERE table_schema = 'public'"
                )
            )
        ).scalar_one()
    await dispose_engine()

    print(f"server   : {version.split(',')[0]}")
    print(f"revision : {revision or 'NONE — run alembic upgrade head'}")
    print(f"tables   : {tables}")
    return 0 if revision else 1


COMMANDS = {
    "seed": _seed,
    "check-db": _check_db,
}


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    args = parser.parse_args()
    return asyncio.run(COMMANDS[args.command]())


if __name__ == "__main__":
    sys.exit(main())
