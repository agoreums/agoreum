"""Ingestion of subscription events from the chain into the database.

Same three rules as the escrow indexer, confirmation depth, reorg safety, and
idempotence keyed by `(tx_hash, log_index)`, applied to the subscription
contract. It only ever reads the chain, and it is the only thing that may write a
subscription's coverage window: coverage moves forward because a real `Subscribed`
event settled, never because the application decided it should.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chain import subscriptions as contract
from app.chain.client import ChainClient
from app.chain.models import IndexerCursor
from app.core.config import settings
from app.core.logging import get_logger
from app.modules.subscriptions.models import Subscription, SubscriptionPayment
from app.modules.users.models import Wallet

logger = get_logger(__name__)

SCAN_CHUNK_SIZE = 2_000
REORG_DEPTH = 64


@dataclass
class ScanResult:
    from_block: int
    to_block: int
    events_seen: int
    events_applied: int

    def __str__(self) -> str:
        return (
            f"blocks {self.from_block}-{self.to_block}: "
            f"{self.events_applied}/{self.events_seen} applied"
        )


class SubscriptionIndexerStartUnknown(RuntimeError):
    """No cursor exists and SUBSCRIPTIONS_DEPLOY_BLOCK is not configured."""


def _ts(value: int) -> datetime:
    return datetime.fromtimestamp(int(value), tz=UTC)


async def _resolve_user_id(db: AsyncSession, address: str):
    """Link a paying wallet to a known user, if it is a verified wallet."""
    return (
        await db.execute(select(Wallet.user_id).where(Wallet.address == address.lower()))
    ).scalar_one_or_none()


async def apply_event(db: AsyncSession, event: contract.DecodedEvent) -> str:
    """Apply one decoded subscription event. Returns applied/duplicate/reorged/skipped."""
    if event.name == "Subscribed":
        return await _apply_subscribed(db, event)
    if event.name == "SubscriptionCancelled":
        return await _apply_cancelled(db, event)
    # PlanCreated/PlanUpdated and inherited events are not coverage changes.
    return "skipped"


async def _apply_subscribed(db: AsyncSession, event: contract.DecodedEvent) -> str:
    subscriber = str(event.args["subscriber"]).lower()
    plan_id = int(event.args["planId"])

    existing = (
        await db.execute(
            select(SubscriptionPayment).where(
                SubscriptionPayment.tx_hash == event.tx_hash.lower(),
                SubscriptionPayment.log_index == event.log_index,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.block_hash.lower() != event.block_hash.lower():
            logger.warning(
                "reorg_detected",
                extra={"tx_hash": event.tx_hash, "context": "subscription"},
            )
            existing.block_hash = event.block_hash
            existing.block_number = event.block_number
            await db.flush()
            return "reorged"
        return "duplicate"

    period_start = _ts(event.args["periodStart"])
    period_end = _ts(event.args["periodEnd"])
    amount = contract.from_base_units(event.args["amountPaid"])

    db.add(
        SubscriptionPayment(
            tx_hash=event.tx_hash.lower(),
            log_index=event.log_index,
            subscriber_address=subscriber,
            plan_id=plan_id,
            amount=amount,
            period_start=period_start,
            period_end=period_end,
            block_number=event.block_number,
            block_hash=event.block_hash,
        )
    )

    sub = (
        await db.execute(
            select(Subscription).where(
                Subscription.subscriber_address == subscriber,
                Subscription.plan_id == plan_id,
            )
        )
    ).scalar_one_or_none()

    user_id = await _resolve_user_id(db, subscriber)
    if sub is None:
        db.add(
            Subscription(
                subscriber_address=subscriber,
                plan_id=plan_id,
                user_id=user_id,
                current_period_start=period_start,
                current_period_end=period_end,
                auto_renew_cancelled=False,
                last_payment_tx=event.tx_hash.lower(),
            )
        )
    else:
        # The contract stacks periods; the event's periodEnd is already the new
        # coverage end, so mirror it rather than recomputing.
        sub.current_period_start = period_start
        sub.current_period_end = period_end
        sub.auto_renew_cancelled = False
        sub.last_payment_tx = event.tx_hash.lower()
        if user_id is not None:
            sub.user_id = user_id

    await db.flush()
    logger.info(
        "subscription_payment_applied",
        extra={"subscriber": subscriber, "plan_id": plan_id, "tx_hash": event.tx_hash},
    )
    return "applied"


async def _apply_cancelled(db: AsyncSession, event: contract.DecodedEvent) -> str:
    subscriber = str(event.args["subscriber"]).lower()
    plan_id = int(event.args["planId"])
    sub = (
        await db.execute(
            select(Subscription).where(
                Subscription.subscriber_address == subscriber,
                Subscription.plan_id == plan_id,
            )
        )
    ).scalar_one_or_none()
    if sub is None:
        # A cancel for a subscription we have not indexed. Not fabricated into
        # existence; the Subscribed event that precedes it will create it on a
        # later pass if it was simply seen out of order.
        logger.warning(
            "cancel_for_unknown_subscription",
            extra={"subscriber": subscriber, "plan_id": plan_id},
        )
        return "skipped"
    sub.auto_renew_cancelled = True
    await db.flush()
    return "applied"


# --- Scanning ---------------------------------------------------------------


async def scan(
    db: AsyncSession,
    client: ChainClient,
    *,
    from_block: int,
    to_block: int | None = None,
    confirmations: int | None = None,
) -> ScanResult:
    if not contract.is_configured():
        raise contract.SubscriptionsNotConfiguredError()

    address = contract.contract_address()
    depth = confirmations if confirmations is not None else settings.CHAIN_CONFIRMATIONS

    head = await client.block_number()
    safe_head = max(0, head - depth + 1)
    target = min(to_block if to_block is not None else safe_head, safe_head)
    if target < from_block:
        return ScanResult(from_block, from_block, 0, 0)

    seen = applied = 0
    for chunk_start in range(from_block, target + 1, SCAN_CHUNK_SIZE):
        chunk_end = min(chunk_start + SCAN_CHUNK_SIZE - 1, target)
        logs = await client.get_logs(
            address=address, from_block=chunk_start, to_block=chunk_end
        )
        for log in logs:
            event = contract.decode_log(log)
            if event is None or event.name not in ("Subscribed", "SubscriptionCancelled"):
                continue
            seen += 1
            if await apply_event(db, event) in ("applied", "reorged"):
                applied += 1

    logger.info(
        "subscription_scan_complete",
        extra={"from_block": from_block, "to_block": target, "events_applied": applied},
    )
    return ScanResult(from_block, target, seen, applied)


async def _cursor(db: AsyncSession, chain_id: int, address: str) -> IndexerCursor | None:
    return (
        await db.execute(
            select(IndexerCursor).where(
                IndexerCursor.chain_id == chain_id,
                IndexerCursor.contract_address == address.lower(),
            )
        )
    ).scalar_one_or_none()


async def resume_point(db: AsyncSession, *, chain_id: int, address: str) -> int:
    cursor = await _cursor(db, chain_id, address)
    if cursor is not None:
        return max(0, cursor.last_scanned_block - REORG_DEPTH)
    if settings.SUBSCRIPTIONS_DEPLOY_BLOCK is None:
        raise SubscriptionIndexerStartUnknown(
            "No cursor exists and SUBSCRIPTIONS_DEPLOY_BLOCK is not set."
        )
    return settings.SUBSCRIPTIONS_DEPLOY_BLOCK


async def run_once(db: AsyncSession, client: ChainClient) -> ScanResult:
    if not contract.is_configured():
        raise contract.SubscriptionsNotConfiguredError()
    address = contract.contract_address()
    chain_id = settings.CHAIN_ID
    await client.verify_network()

    from_block = await resume_point(db, chain_id=chain_id, address=address)
    result = await scan(db, client, from_block=from_block)

    cursor = await _cursor(db, chain_id, address)
    if cursor is None:
        db.add(
            IndexerCursor(
                chain_id=chain_id,
                contract_address=address.lower(),
                last_scanned_block=result.to_block,
            )
        )
    elif result.to_block > cursor.last_scanned_block:
        cursor.last_scanned_block = result.to_block
    await db.commit()
    return result
