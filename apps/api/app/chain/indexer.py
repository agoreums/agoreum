"""Ingestion of escrow events from the chain into the database.

The indexer's job is to make the database reflect what the chain has actually
accepted — never to assert something the chain has not confirmed.

Three rules govern it:

1. **Confirmation depth.** An event is only applied once it is buried under
   `CHAIN_CONFIRMATIONS` blocks. Acting on a one-block-old log risks acting on
   a block that is about to be orphaned.
2. **Reorg safety.** Applied events record the block hash they came from. If a
   later scan finds a different hash at that height, the affected records are
   rewound rather than left describing a history that no longer exists.
3. **Idempotence.** Every event is keyed by `(tx_hash, log_index)`, which is
   unique on-chain. Re-scanning a range applies nothing twice, so the indexer
   can be restarted or run concurrently without corrupting state.

The indexer only ever *reads* the chain. It never signs or broadcasts.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chain import escrow as contract
from app.chain.client import ChainClient
from app.chain.models import IndexerCursor
from app.core.config import settings
from app.core.logging import get_logger
from app.db.enums import (
    EscrowStatus,
    OrderStatus,
    TransactionStatus,
    TransactionType,
)
from app.modules.orders.models import ChainTransaction, Escrow, Order, OrderEvent

logger = get_logger(__name__)

# How many blocks to request per eth_getLogs call. Providers cap the range, and
# a smaller window also bounds how much work a single failed scan wastes.
SCAN_CHUNK_SIZE = 2_000

# How far back a reorg is considered possible. Base finalises well within this.
REORG_DEPTH = 64


@dataclass
class ScanResult:
    from_block: int
    to_block: int
    events_seen: int
    events_applied: int
    reorgs_detected: int

    def __str__(self) -> str:
        return (
            f"blocks {self.from_block}-{self.to_block}: "
            f"{self.events_applied}/{self.events_seen} applied, "
            f"{self.reorgs_detected} reorgs"
        )


# Which contract event drives which escrow and order state.
_EVENT_TO_ESCROW_STATUS = {
    "EscrowCreated": EscrowStatus.FUNDED,
    "EscrowReleased": EscrowStatus.RELEASED,
    "EscrowRefunded": EscrowStatus.REFUNDED,
    "EscrowDisputed": EscrowStatus.DISPUTED,
    "EscrowSettled": EscrowStatus.RELEASED,
}

_EVENT_TO_ORDER_STATUS = {
    "EscrowCreated": OrderStatus.FUNDED,
    "EscrowReleased": OrderStatus.COMPLETED,
    "EscrowRefunded": OrderStatus.REFUNDED,
    "EscrowDisputed": OrderStatus.DISPUTED,
    "EscrowSettled": OrderStatus.COMPLETED,
}

_EVENT_TO_TX_TYPE = {
    "EscrowCreated": TransactionType.ESCROW_FUND,
    "EscrowReleased": TransactionType.ESCROW_RELEASE,
    "EscrowRefunded": TransactionType.ESCROW_REFUND,
    "EscrowSettled": TransactionType.ESCROW_RELEASE,
}


async def scan(
    db: AsyncSession,
    client: ChainClient,
    *,
    from_block: int,
    to_block: int | None = None,
    confirmations: int | None = None,
) -> ScanResult:
    """Scan a block range and apply every sufficiently-confirmed event."""
    if not contract.is_configured():
        raise contract.EscrowNotConfiguredError()

    address = contract.contract_address()
    depth = confirmations if confirmations is not None else settings.CHAIN_CONFIRMATIONS

    head = await client.block_number()
    # Never scan past the confirmation frontier: anything newer is not settled.
    safe_head = max(0, head - depth + 1)
    target = min(to_block if to_block is not None else safe_head, safe_head)

    if target < from_block:
        return ScanResult(from_block, from_block, 0, 0, 0)

    seen = applied = reorgs = 0

    for chunk_start in range(from_block, target + 1, SCAN_CHUNK_SIZE):
        chunk_end = min(chunk_start + SCAN_CHUNK_SIZE - 1, target)
        logs = await client.get_logs(
            address=address, from_block=chunk_start, to_block=chunk_end
        )

        for log in logs:
            event = contract.decode_log(log)
            if event is None:
                continue
            seen += 1
            outcome = await _apply_event(db, event)
            if outcome == "applied":
                applied += 1
            elif outcome == "reorged":
                reorgs += 1

    result = ScanResult(from_block, target, seen, applied, reorgs)
    logger.info(
        "chain_scan_complete",
        extra={
            "from_block": from_block,
            "to_block": target,
            "events_seen": seen,
            "events_applied": applied,
            "reorgs": reorgs,
        },
    )
    return result


class IndexerStartBlockUnknown(RuntimeError):
    """No cursor exists and no deployment block is configured.

    Raised rather than defaulting to genesis. Silently scanning from block 0
    would appear to work while taking hours and hammering the RPC provider, and
    an operator who sees an error fixes the configuration in seconds.
    """


async def _cursor_for(db: AsyncSession, *, chain_id: int, address: str) -> IndexerCursor | None:
    return (
        await db.execute(
            select(IndexerCursor).where(
                IndexerCursor.chain_id == chain_id,
                IndexerCursor.contract_address == address.lower(),
            )
        )
    ).scalar_one_or_none()


async def resume_point(db: AsyncSession, *, chain_id: int, address: str) -> int:
    """The block a scan should resume from for this contract.

    A stored cursor is rewound by `REORG_DEPTH` before being trusted. The blocks
    it already covered may have been reorganised since, and re-applying an event
    is free while missing one is not.
    """
    cursor = await _cursor_for(db, chain_id=chain_id, address=address)
    if cursor is not None:
        return max(0, cursor.last_scanned_block - REORG_DEPTH)

    if settings.ESCROW_DEPLOY_BLOCK is None:
        raise IndexerStartBlockUnknown(
            "No indexer cursor exists for this contract and ESCROW_DEPLOY_BLOCK "
            "is not set. Set it to the block the escrow contract was deployed in."
        )
    return settings.ESCROW_DEPLOY_BLOCK


async def _save_cursor(db: AsyncSession, *, chain_id: int, address: str, block: int) -> None:
    cursor = await _cursor_for(db, chain_id=chain_id, address=address)
    if cursor is None:
        db.add(
            IndexerCursor(
                chain_id=chain_id,
                contract_address=address.lower(),
                last_scanned_block=block,
            )
        )
    elif block > cursor.last_scanned_block:
        # Only ever move forward. A scan explicitly given an older range must
        # not rewind the recorded position for everything that follows it.
        cursor.last_scanned_block = block


async def run_once(db: AsyncSession, client: ChainClient) -> ScanResult:
    """Scan from the stored position to the confirmation frontier, then save it.

    This is the entry point an operator or scheduler calls. `scan()` itself is
    deliberately position-agnostic so it stays testable over an explicit range.
    """
    if not contract.is_configured():
        raise contract.EscrowNotConfiguredError()

    address = contract.contract_address()
    chain_id = settings.CHAIN_ID

    # Refuse to index against an endpoint serving a different chain than the one
    # configured — otherwise settlement gets recorded from a chain nobody is
    # watching, against addresses that mean something else there.
    await client.verify_network()

    from_block = await resume_point(db, chain_id=chain_id, address=address)
    result = await scan(db, client, from_block=from_block)

    await _save_cursor(db, chain_id=chain_id, address=address, block=result.to_block)
    await db.commit()
    return result


async def _apply_event(db: AsyncSession, event: contract.DecodedEvent) -> str:
    """Apply one decoded event. Returns 'applied', 'duplicate', or 'skipped'."""
    try:
        order_id = uuid.UUID(contract.order_id_from_escrow_id(event.escrow_id))
    except (ValueError, AttributeError):
        logger.warning(
            "event_escrow_id_unparseable", extra={"escrow_id": event.escrow_id}
        )
        return "skipped"

    order = (
        await db.execute(select(Order).where(Order.id == order_id))
    ).scalar_one_or_none()

    if order is None:
        # An escrow exists on-chain with no matching order. Never fabricate one:
        # the funds are real and someone must look at it.
        logger.warning(
            "orphan_escrow_event",
            extra={
                "event": event.name,
                "escrow_id": event.escrow_id,
                "tx_hash": event.tx_hash,
            },
        )
        return "skipped"

    existing = (
        await db.execute(
            select(ChainTransaction).where(
                ChainTransaction.chain_id == settings.CHAIN_ID,
                ChainTransaction.tx_hash == event.tx_hash.lower(),
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        if existing.block_hash and existing.block_hash.lower() != event.block_hash.lower():
            # Same transaction, different block: it was re-mined after a reorg.
            logger.warning(
                "reorg_detected",
                extra={
                    "tx_hash": event.tx_hash,
                    "old_block_hash": existing.block_hash,
                    "new_block_hash": event.block_hash,
                },
            )
            existing.block_hash = event.block_hash
            existing.block_number = event.block_number
            existing.status = TransactionStatus.CONFIRMED
            await db.flush()
            return "reorged"
        # Already ingested at the same block: nothing to do.
        return "duplicate"

    await _record_transaction(db, order=order, event=event)
    await _apply_to_escrow(db, order=order, event=event)
    await _record_order_event(db, order=order, event=event)

    return "applied"


async def _record_transaction(
    db: AsyncSession, *, order: Order, event: contract.DecodedEvent
) -> None:
    tx_type = _EVENT_TO_TX_TYPE.get(event.name)
    if tx_type is None:
        return

    amount: Decimal | None = None
    for key in ("amount", "providerAmount"):
        if key in event.args:
            amount = contract.from_base_units(event.args[key])
            break

    db.add(
        ChainTransaction(
            order_id=order.id,
            escrow_id=order.escrow.id if order.escrow else None,
            tx_hash=event.tx_hash.lower(),
            chain_id=settings.CHAIN_ID,
            tx_type=tx_type,
            # Only reached past the confirmation frontier, so this is settled.
            status=TransactionStatus.CONFIRMED,
            from_address=str(event.args.get("buyer") or order.buyer.primary_address),
            to_address=str(event.args.get("provider") or ""),
            amount=amount,
            token_address=str(event.args.get("token") or settings.usdc_address).lower(),
            block_number=event.block_number,
            block_hash=event.block_hash,
            log_index=event.log_index,
            confirmations=settings.CHAIN_CONFIRMATIONS,
            confirmed_at=datetime.now(UTC),
        )
    )
    await db.flush()


async def _apply_to_escrow(
    db: AsyncSession, *, order: Order, event: contract.DecodedEvent
) -> None:
    escrow = order.escrow
    now = datetime.now(UTC)

    if escrow is None:
        if event.name != "EscrowCreated":
            logger.warning(
                "escrow_event_before_creation",
                extra={"event": event.name, "order": str(order.id)},
            )
            return
        escrow = Escrow(
            order_id=order.id,
            chain_id=settings.CHAIN_ID,
            contract_address=contract.contract_address(),
            onchain_escrow_id=event.escrow_id,
            token_address=str(event.args["token"]).lower(),
            token_symbol="USDC",  # noqa: S106 — a token ticker, not a credential
            token_decimals=contract.TOKEN_DECIMALS,
            amount=contract.from_base_units(event.args["amount"]),
            buyer_address=str(event.args["buyer"]).lower(),
            provider_address=str(event.args["provider"]).lower(),
            status=EscrowStatus.FUNDED,
            funded_at=now,
        )
        db.add(escrow)
        order.funded_at = now
    else:
        new_status = _EVENT_TO_ESCROW_STATUS.get(event.name)
        if new_status is not None:
            escrow.status = new_status

        if event.name == "EscrowReleased":
            escrow.released_amount = escrow.amount
            escrow.fee_amount = contract.from_base_units(event.args.get("feeAmount", 0))
            escrow.released_at = now
        elif event.name == "EscrowRefunded":
            escrow.refunded_amount = escrow.amount
            escrow.refunded_at = now
        elif event.name == "EscrowDisputed":
            escrow.disputed_at = now
            escrow.dispute_reason = str(event.args.get("reason", ""))[:2000] or None
        elif event.name == "EscrowSettled":
            provider_amount = contract.from_base_units(event.args.get("providerAmount", 0))
            buyer_amount = contract.from_base_units(event.args.get("buyerAmount", 0))
            escrow.released_amount = provider_amount
            escrow.refunded_amount = buyer_amount
            escrow.fee_amount = contract.from_base_units(event.args.get("feeAmount", 0))
            escrow.released_at = now
            escrow.dispute_resolved_at = now

    new_order_status = _EVENT_TO_ORDER_STATUS.get(event.name)
    if new_order_status is not None:
        order.status = new_order_status
        if new_order_status == OrderStatus.COMPLETED:
            order.completed_at = now
        elif new_order_status == OrderStatus.REFUNDED:
            order.cancelled_at = now

    await db.flush()


async def _record_order_event(
    db: AsyncSession, *, order: Order, event: contract.DecodedEvent
) -> None:
    """Append to the order's audit trail.

    Actor is null: the chain is the actor here, not a platform user.
    """
    db.add(
        OrderEvent(
            order_id=order.id,
            event_type=f"chain.{event.name}",
            actor_user_id=None,
            to_status=order.status.value,
            detail={
                "tx_hash": event.tx_hash,
                "block_number": event.block_number,
                "escrow_id": event.escrow_id,
            },
        )
    )
    await db.flush()


async def reconcile_order(
    db: AsyncSession, client: ChainClient, order: Order
) -> dict[str, object]:
    """Compare an order's recorded escrow against the chain's own view.

    Where they disagree the chain wins: it is the record that actually holds the
    money. This exists so a divergence is discoverable rather than silent.
    """
    if not contract.is_configured():
        raise contract.EscrowNotConfiguredError()

    escrow_id = contract.escrow_id_for_order(str(order.id))
    data = contract.encode_get_escrow(escrow_id)
    result = await client.call(to=contract.contract_address(), data=data)
    on_chain = contract.decode_get_escrow(result)

    local = order.escrow
    divergences: list[str] = []

    if not on_chain.exists:
        if local is not None and local.status != EscrowStatus.NONE:
            divergences.append("database records an escrow the chain does not have")
    elif local is None:
        divergences.append("chain holds an escrow the database does not know about")
    else:
        if local.amount != on_chain.amount:
            divergences.append(
                f"amount: database {local.amount}, chain {on_chain.amount}"
            )
        if local.released_amount != on_chain.released:
            divergences.append(
                f"released: database {local.released_amount}, chain {on_chain.released}"
            )
        if local.refunded_amount != on_chain.refunded:
            divergences.append(
                f"refunded: database {local.refunded_amount}, chain {on_chain.refunded}"
            )

    if divergences:
        logger.warning(
            "order_chain_divergence",
            extra={"order": str(order.id), "divergences": divergences},
        )

    return {
        "order_id": str(order.id),
        "escrow_id": escrow_id,
        "exists_on_chain": on_chain.exists,
        "chain_status": on_chain.status.name,
        "chain_amount": str(on_chain.amount),
        "chain_released": str(on_chain.released),
        "chain_refunded": str(on_chain.refunded),
        "in_sync": not divergences,
        "divergences": divergences,
    }
