"""Operational command-line entrypoints.

Run with:  python -m app.cli <command>

Commands here are for operators, not for application code paths.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable

# Importing the model registry configures every ORM mapper. Without it, loading a
# single module leaves relationships pointing at classes SQLAlchemy has not seen.
import app.db.models  # noqa: F401
from app.core.config import settings
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


async def _grant_role(args: argparse.Namespace) -> int:
    """Set a user's platform role. Operator-only, run on the host.

    This is the only way an account becomes an admin: there is deliberately no
    self-service path and no API endpoint, so administrative access cannot be
    granted by anything a request can reach. Identify the user by wallet address
    or username.
    """
    from sqlalchemy import func, select

    from app.db.enums import UserRole
    from app.modules.users.models import User

    try:
        role = UserRole(args.role)
    except ValueError:
        allowed = ", ".join(r.value for r in UserRole)
        print(f"error: unknown role {args.role!r}. Choose from: {allowed}")
        return 1

    identifier = args.user.strip()
    async with SessionLocal() as session:
        user = (
            await session.execute(
                select(User).where(
                    func.lower(User.primary_address) == identifier.lower()
                )
            )
        ).scalar_one_or_none()
        if user is None:
            user = (
                await session.execute(
                    select(User).where(User.username == identifier.lower())
                )
            ).scalar_one_or_none()
        if user is None:
            print(f"error: no user matching {identifier!r} (by address or username)")
            await dispose_engine()
            return 1

        previous = user.role
        user.role = role
        await session.commit()
        addr = user.primary_address

    await dispose_engine()
    print(f"{addr}: role {previous.value} -> {role.value}")
    return 0


def _add_grant_role(subparsers: argparse._SubParsersAction) -> None:
    from app.db.enums import UserRole

    parser = subparsers.add_parser(
        "grant-role", help="set a user's platform role (operator only)"
    )
    parser.add_argument("user", help="wallet address or username")
    parser.add_argument(
        "role", choices=[r.value for r in UserRole], help="role to grant"
    )
    parser.set_defaults(handler=_grant_role)


async def _index_chain(args: argparse.Namespace) -> int:
    """Ingest confirmed escrow events from the chain.

    One pass by default. `--follow` polls, which is how this runs in production;
    there is no in-process scheduler because indexing must not stop when the API
    is redeployed, and two API replicas would otherwise both index.
    """
    from app.chain import escrow as contract
    from app.chain.client import ChainClient
    from app.chain.indexer import IndexerStartBlockUnknown, run_once

    if not contract.is_configured():
        print("ESCROW_CONTRACT_ADDRESS is not set. Nothing to index.")
        return 1

    print(f"contract : {contract.contract_address()}")
    print(f"chain    : {settings.CHAIN_ID}")

    try:
        async with ChainClient() as client:
            while True:
                async with SessionLocal() as session:
                    result = await run_once(session, client)
                print(result)
                if not args.follow:
                    return 0
                await asyncio.sleep(args.interval)
    except IndexerStartBlockUnknown as exc:
        print(f"error: {exc}")
        return 1
    except KeyboardInterrupt:  # pragma: no cover - operator interrupt
        print("stopped")
        return 0
    finally:
        await dispose_engine()


def _add_index_chain(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "index-chain", help="ingest confirmed escrow events from the chain"
    )
    parser.add_argument(
        "--follow", action="store_true", help="keep polling instead of one pass"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=15.0,
        help="seconds between polls when following (default: 15)",
    )
    parser.set_defaults(handler=_index_chain)


def _simple(handler: Callable[[], Awaitable[int]]) -> Callable[[argparse.Namespace], Awaitable[int]]:
    """Adapt a no-argument command to the handler signature."""

    async def run(_: argparse.Namespace) -> int:
        return await handler()

    return run


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("seed", help="insert reference data").set_defaults(
        handler=_simple(_seed)
    )
    subparsers.add_parser("check-db", help="verify the database").set_defaults(
        handler=_simple(_check_db)
    )
    _add_grant_role(subparsers)
    _add_index_chain(subparsers)

    args = parser.parse_args()
    return asyncio.run(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
