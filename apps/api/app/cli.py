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
    print(f"revision : {revision or 'NONE, run alembic upgrade head'}")
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
    from app.modules.orders.service import expire_unfunded_orders

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

                # Expiring unfunded orders belongs to whichever process knows
                # the chain is current, and this is that process. Running it
                # only after a successful scan means a stalled indexer stops
                # expiring, rather than expiring orders whose payments it has
                # simply not caught up with yet. That coupling is the safety
                # property, not an accident of where the code sits.
                async with SessionLocal() as session:
                    expired = await expire_unfunded_orders(session)
                    if expired:
                        await session.commit()
                        print(f"expired {expired} unfunded order(s)")

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


async def _deliver_webhooks(args: argparse.Namespace) -> int:
    """Drain the webhook outbox: sign and POST due deliveries, retrying failures.

    Runs single-instance as its own service, the same shape as the indexer. Makes
    no outbound request unless WEBHOOK_DELIVERY_ENABLED is set; until then it marks
    due deliveries suppressed so the queue does not grow unbounded.
    """
    import contextlib
    import time

    import httpx

    from app.core.redis import create_client
    from app.modules.health.service import WEBHOOK_HEARTBEAT_KEY
    from app.modules.webhooks import service as webhooks

    print(f"webhook delivery: enabled={settings.WEBHOOK_DELIVERY_ENABLED}")
    # The worker has no chain cursor to trail, so it records a heartbeat each pass.
    # A stalled loop is then visible to /health/workers even while the container is
    # up. A Redis blip must never stop delivery, so the write is best-effort.
    redis = create_client()
    try:
        async with httpx.AsyncClient(
            timeout=settings.WEBHOOK_TIMEOUT_SECONDS, follow_redirects=False
        ) as client:
            while True:
                processed = 0
                async with SessionLocal() as session:
                    due = await webhooks.claim_due(session, limit=args.batch)
                    for delivery in due:
                        await webhooks.deliver_one(session, client, delivery)
                        processed += 1
                if processed:
                    print(f"attempted {processed} deliver(y/ies)")
                # A redis blip must never stop delivery, so the write is best-effort.
                with contextlib.suppress(Exception):
                    await redis.set(WEBHOOK_HEARTBEAT_KEY, str(int(time.time())))
                if not args.follow:
                    return 0
                await asyncio.sleep(args.interval)
    except KeyboardInterrupt:  # pragma: no cover - operator interrupt
        print("stopped")
    finally:
        with contextlib.suppress(Exception):
            await redis.aclose()
        await dispose_engine()
    return 0


def _add_deliver_webhooks(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "deliver-webhooks", help="send queued webhook deliveries"
    )
    parser.add_argument(
        "--follow", action="store_true", help="keep polling instead of one pass"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="seconds between polls when following (default: 5)",
    )
    parser.add_argument(
        "--batch", type=int, default=50, help="max deliveries per pass (default: 50)"
    )
    parser.set_defaults(handler=_deliver_webhooks)



async def _deliver_emails(args: argparse.Namespace) -> int:
    """Drain the email outbox: send due deliveries, retrying transient failures.

    Exists so that no request ever waits on Resend. `_deliver` applies the cheap
    database gates inline and queues the row; everything after that happens here,
    off the request path, which also means a transaction that rolls back cannot
    have mailed anybody, because this only sees committed rows.

    Same shape as deliver-webhooks, single instance, committing each attempt as it
    goes so a crash mid-batch loses at most the attempt in flight.
    """
    import contextlib
    import time

    from app.core.redis import create_client
    from app.modules.health.service import EMAIL_HEARTBEAT_KEY
    from app.modules.notifications import service as notifications

    print(f"email delivery: enabled={settings.EMAIL_SENDING_ENABLED}")
    # Like the webhooks worker, this has no chain cursor to trail, so it records a
    # heartbeat each pass and /health/workers can tell a stalled loop from a
    # healthy idle one. It had none until 2026-08-15: the container being up was
    # the only evidence anyone had that sign-in alerts and verification links were
    # still going out. A Redis blip must never stop delivery, so the write is
    # best-effort, exactly as it is next door.
    redis = create_client()
    try:
        while True:
            processed = 0
            async with SessionLocal() as session:
                due = await notifications.claim_due_emails(session, limit=args.batch)
                for delivery in due:
                    await notifications.send_one(session, delivery=delivery)
                    # Committed per delivery, so an attempt already made is never
                    # repeated because of a later failure in the same batch.
                    await session.commit()
                    processed += 1
            # Written after the work, not before, so the heartbeat means "a pass
            # completed" rather than "a pass started".
            with contextlib.suppress(Exception):
                await redis.set(EMAIL_HEARTBEAT_KEY, str(int(time.time())))
            if processed:
                print(f"attempted {processed} email deliver(y/ies)")
            if not args.follow:
                return 0
            await asyncio.sleep(args.interval)
    except KeyboardInterrupt:  # pragma: no cover - operator interrupt
        print("stopped")
    finally:
        with contextlib.suppress(Exception):
            await redis.aclose()
        with contextlib.suppress(Exception):
            await dispose_engine()
    return 0


def _add_deliver_emails(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "deliver-emails", help="send queued email deliveries"
    )
    parser.add_argument(
        "--follow", action="store_true", help="keep polling instead of one pass"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="seconds between polls when following (default: 5)",
    )
    parser.add_argument(
        "--batch", type=int, default=50, help="max deliveries per pass (default: 50)"
    )
    parser.set_defaults(handler=_deliver_emails)


async def _index_subscriptions(args: argparse.Namespace) -> int:
    """Ingest confirmed subscription events from the chain.

    The same shape as index-chain, against the subscription contract. It only ever
    reads the chain and is the only thing that may activate a subscription.
    """
    from app.chain import subscriptions as contract
    from app.chain.client import ChainClient
    from app.chain.subscription_indexer import SubscriptionIndexerStartUnknown, run_once

    if not contract.is_configured():
        print("SUBSCRIPTIONS_CONTRACT_ADDRESS is not set. Nothing to index.")
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
    except SubscriptionIndexerStartUnknown as exc:
        print(f"error: {exc}")
        return 1
    except KeyboardInterrupt:  # pragma: no cover - operator interrupt
        print("stopped")
        return 0
    finally:
        await dispose_engine()


def _add_index_subscriptions(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "index-subscriptions", help="ingest confirmed subscription events from the chain"
    )
    parser.add_argument(
        "--follow", action="store_true", help="keep polling instead of one pass"
    )
    parser.add_argument(
        "--interval", type=float, default=15.0, help="seconds between polls (default: 15)"
    )
    parser.set_defaults(handler=_index_subscriptions)


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
    _add_index_subscriptions(subparsers)
    _add_deliver_webhooks(subparsers)
    _add_deliver_emails(subparsers)

    args = parser.parse_args()
    return asyncio.run(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
