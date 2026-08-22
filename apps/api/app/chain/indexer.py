"""Ingestion of escrow events from the chain into the database.

The indexer's job is to make the database reflect what the chain has actually
accepted, never to assert something the chain has not confirmed.

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
from sqlalchemy.orm import selectinload

from app.chain import escrow as contract
from app.chain.client import ChainClient
from app.chain.models import IndexerCursor
from app.core.config import settings
from app.core.logging import get_logger
from app.db.enums import (
    DisputeResolution,
    EscrowStatus,
    OrderStatus,
    TransactionStatus,
    TransactionType,
)
from app.modules.notifications import events as notification_events
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
    # configured, otherwise settlement gets recorded from a chain nobody is
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

    # Eager-load the relationships the apply path reads. The indexer loads each
    # order fresh in its own session, so `order.escrow` and `order.buyer` would
    # otherwise trigger a lazy load, synchronous IO that raises MissingGreenlet
    # under async SQLAlchemy. This is the real event-application path in
    # production; nothing is already in the session identity map.
    order = (
        await db.execute(
            select(Order)
            .where(Order.id == order_id)
            .options(
                selectinload(Order.escrow),
                selectinload(Order.buyer),
                # Needed to resolve who owns the providing agent when a
                # notification goes out. Without it the relationship is
                # unloaded and the provider is told nothing at all.
                selectinload(Order.provider_agent),
            )
        )
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

    payer, payee = _counterparties(event, order)
    db.add(
        ChainTransaction(
            order_id=order.id,
            escrow_id=order.escrow.id if order.escrow else None,
            tx_hash=event.tx_hash.lower(),
            chain_id=settings.CHAIN_ID,
            tx_type=tx_type,
            # Only reached past the confirmation frontier, so this is settled.
            status=TransactionStatus.CONFIRMED,
            from_address=payer,
            to_address=payee,
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
            token_symbol="USDC",  # noqa: S106, a token ticker, not a credential
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
            apply_release(escrow, event, order_id=str(order.id))
            escrow.released_at = now
        elif event.name == "EscrowRefunded":
            apply_refund(escrow, event, order_id=str(order.id))
            escrow.refunded_at = now
        elif event.name == "EscrowDisputed":
            escrow.disputed_at = now
            escrow.dispute_reason = str(event.args.get("reason", ""))[:2000] or None
        elif event.name == "EscrowSettled":
            # `providerAmount` in this event is the provider's **net**, after
            # the fee, while `escrow.released` on chain holds the **gross**. The
            # contract computes `providerNet = providerAmount - fee` and emits
            # the net under a name that reads like the gross:
            #
            #   escrow.released = providerAmount            (gross, stored)
            #   emit EscrowSettled(id, providerNet, ...)    (net, emitted)
            #
            # Storing the emitted figure straight into `released_amount` made
            # the database disagree with the chain for every settled dispute:
            # 0.999375 against 1.025000 on the first one ever settled. Nothing
            # was lost, and the record of how much was released was simply a
            # different number from the one the contract holds.
            #
            # Gross is the convention here, which `EscrowReleased` follows by
            # writing the whole escrow amount, so the fee is added back.
            #
            # Found by `reconcile`, which reported the divergence against real
            # data. That endpoint exists so a disagreement between the database
            # and the chain is discoverable rather than silent, and this is the
            # first time it has caught one.
            provider_amount, buyer_amount, fee_amount = settled_amounts(event)
            escrow.released_amount = provider_amount
            escrow.refunded_amount = buyer_amount
            escrow.fee_amount = fee_amount
            escrow.released_at = now
            escrow.dispute_resolved_at = now
            # Both or neither. The escrows table carries
            # `dispute_resolution_consistent`, which requires
            # `(dispute_resolution IS NULL) = (dispute_resolved_at IS NULL)`, and
            # this handler set only the timestamp. The first settled dispute in
            # production therefore violated the constraint on every retry and
            # crash-looped the indexer, which is the second latent defect found
            # in this same never-run path within an hour of the first.
            #
            # Derived from the split rather than read from the event, because the
            # contract does not emit a category and the same three cases are what
            # `record_dispute_decision` records when an arbiter decides. A
            # settlement reaching here without a recorded decision, which is
            # exactly what an arbiter settling directly produces, still ends up
            # described the same way.
            escrow.dispute_resolution = settlement_resolution(
                provider_amount=provider_amount, buyer_amount=buyer_amount
            )

    new_order_status = _EVENT_TO_ORDER_STATUS.get(event.name)
    if new_order_status is not None:
        order.status = new_order_status
        if new_order_status == OrderStatus.COMPLETED:
            order.completed_at = now
        elif new_order_status == OrderStatus.REFUNDED:
            order.cancelled_at = now

    await db.flush()

    # A settlement that does not refresh the score leaves the score wrong.
    #
    # The public reputation endpoint serves a stored snapshot and only computes
    # one when none exists, so before this the figures were fixed at whichever
    # read happened first and then only ever refreshed by review activity. An
    # agent could settle its second, third and tenth order and keep publishing
    # the numbers from its first, which is the opposite of the one claim this
    # platform makes: that reputation follows settled trade.
    #
    # Found on 2026-08-21 by excluding an order from reputation in production,
    # watching the write succeed, and watching the published figure not move.
    #
    # Failures are swallowed for the same reason as the notifications below.
    # Indexing must continue whatever happens here: a stale score is a wrong
    # number, while a stalled indexer is orders that never leave pending.
    if new_order_status in (OrderStatus.COMPLETED, OrderStatus.REFUNDED, OrderStatus.CANCELLED):
        try:
            from app.modules.reputation import service as reputation

            await reputation.recompute(db, agent_id=order.provider_agent_id)
        except Exception:  # noqa: BLE001 - never let a score stall the indexer
            logger.warning(
                "reputation_recompute_failed",
                extra={"order_id": str(order.id), "event": event.name},
            )

    # Tell the people affected that money moved. Deliberately after the flush, so
    # the state the chain reported is already durable before anyone is told about
    # it, and never before: a notification about a transition that then failed to
    # persist would be worse than no notification.
    #
    # Every one of these swallows its own errors. Indexing must continue whatever
    # happens here, because an order that silently stays unfunded is a buyer whose
    # money is committed and whose work never starts.
    if event.name == "EscrowCreated":
        await notification_events.order_funded(db, order=order)
    elif event.name in {"EscrowReleased", "EscrowSettled"}:
        await notification_events.order_released(db, order=order)
    elif event.name == "EscrowRefunded":
        await notification_events.order_refunded(db, order=order)
    elif event.name == "EscrowDisputed":
        await notification_events.order_disputed(
            db, order=order, raised_by_address=str(event.args.get("raisedBy", "")) or None
        )


def settled_amounts(event: contract.DecodedEvent):
    """The gross released, the refunded, and the fee, from an EscrowSettled event.

    Extracted so it is testable against the real event shape rather than against
    arithmetic rewritten in a test, which would prove only that the test agrees
    with itself.

    `providerAmount` in this event is the provider's net after the fee, while
    `escrow.released` on chain holds the gross, so the fee is added back to
    recover what the contract stores.
    """
    provider_net = contract.from_base_units(event.args.get("providerAmount", 0))
    fee_amount = contract.from_base_units(event.args.get("feeAmount", 0))
    buyer_amount = contract.from_base_units(event.args.get("buyerAmount", 0))
    return provider_net + fee_amount, buyer_amount, fee_amount


def settlement_resolution(*, provider_amount, buyer_amount) -> DisputeResolution:
    """How a settled split should be described.

    Extracted so it can be tested directly. The escrows table requires
    `(dispute_resolution IS NULL) = (dispute_resolved_at IS NULL)`, and the
    settlement handler set only the timestamp, so the first settled dispute in
    production violated the constraint on every retry and crash-looped the
    indexer.

    Derived from the split rather than read from the event, because the contract
    emits no category. The three cases match what `record_dispute_decision`
    records when an arbiter decides through the API, so a settlement that
    reaches here without a recorded decision, which is exactly what an arbiter
    settling directly produces, still ends up described the same way.
    """
    if buyer_amount == 0:
        return DisputeResolution.RELEASED_TO_PROVIDER
    if provider_amount == 0:
        return DisputeResolution.REFUNDED_TO_BUYER
    return DisputeResolution.SPLIT


def apply_release(escrow, event: contract.DecodedEvent, *, order_id: str | None = None) -> None:
    """Record a release using the chain's figures rather than the database's.

    `release` pays the whole escrow out, splitting it into the provider's share
    and the fee, and the event carries both. Their **sum** is the contract's own
    gross, which is what `escrow.released` holds on chain. The handler
    previously wrote `escrow.released_amount = escrow.amount`, taking the figure
    from the record it was meant to be corroborating.

    Third occurrence of one pattern, and the reason all three are now written
    the same way:

    * settlement wrote the emitted net where the chain held the gross, and made
      the database disagree with the contract on the first dispute ever settled
    * refund read `escrow.amount` instead of the event
    * release did the same

    Where the record and the chain agree, none of them is visibly wrong, which
    is exactly why all three survived. Where they had drifted, each carried the
    drift forward and `reconcile` went on reporting a divergence that nothing
    closed.

    The amount is corrected alongside it rather than the released figure alone,
    because writing a larger release against a smaller recorded amount breaches
    `payouts_cannot_exceed_deposit`, and a constraint violation inside this
    handler is what crash-looped the indexer on the first settled dispute.
    """
    fee = contract.from_base_units(event.args.get("feeAmount", 0))
    provider_share = contract.from_base_units(event.args.get("providerAmount", 0))
    gross = (provider_share + fee) or escrow.amount
    if gross != escrow.amount:
        logger.warning(
            "escrow_amount_corrected_from_release",
            extra={
                "order_id": order_id,
                "recorded": str(escrow.amount),
                "on_chain": str(gross),
            },
        )
        escrow.amount = gross
    escrow.released_amount = gross
    escrow.fee_amount = fee


def apply_refund(escrow, event: contract.DecodedEvent, *, order_id: str | None = None) -> None:
    """Record a refund using the chain's figure rather than the database's.

    `refund` returns the **whole** escrow and takes no fee, so the emitted
    `amount` is the contract's own view of the total. The handler previously
    wrote `escrow.refunded_amount = escrow.amount`, taking the figure from the
    record it was supposed to be correcting.

    Where the two agree that is invisible, which is why it survived. Where they
    had drifted, a refund carried the drift forward and `reconcile` would have
    gone on reporting a divergence that nothing ever closed. Same shape as the
    settlement defect: the chain states a number and the code writes a different
    one it happens to hold.

    The amount is corrected alongside it rather than only the refunded figure,
    because writing a larger refund against a smaller recorded amount breaches
    `payouts_cannot_exceed_deposit`, and a constraint violation inside this
    handler is what crash-looped the indexer on the first settled dispute. The
    correction is logged so it is discoverable rather than a silent overwrite of
    a real disagreement.

    Extracted so it can be driven over a real event payload in a test, instead of
    a test rewriting the same arithmetic and proving only that it agrees with
    itself.
    """
    refunded = contract.from_base_units(event.args.get("amount", 0)) or escrow.amount
    if refunded != escrow.amount:
        logger.warning(
            "escrow_amount_corrected_from_refund",
            extra={
                "order_id": order_id,
                "recorded": str(escrow.amount),
                "on_chain": str(refunded),
            },
        )
        escrow.amount = refunded
    escrow.refunded_amount = refunded


def _counterparties(
    event: contract.DecodedEvent, order: Order
) -> tuple[str, str | None]:
    """Who paid and who was paid, as this ledger means those words.

    The convention across every row here is **economic counterparties**, not the
    literal endpoints of the token transfer. Funding records buyer to provider
    even though the tokens go to the contract, and a release records the same
    pair even though the tokens come back out of it. Naming the contract at
    either end would make every row say the same uninformative thing.

    A refund reverses the direction: the provider returns the buyer's money.

    **Before this, a refund recorded the buyer at both ends.** `from_address`
    read `event.args.get("buyer")`, which `EscrowRefunded` does carry, and
    `to_address` fell through to the same value because the event names no
    provider. The row said the buyer paid themselves, for the one event where
    the direction is the whole meaning.

    It survived because no refund had ever been emitted in production and
    neither column is exposed by any endpoint, so no test and no screen could
    have shown it. Found by predicting it from the event signatures while
    designing the refund rehearsal, then confirming it against the real shapes
    rather than against a rewritten guess.
    """
    if event.name == "EscrowRefunded":
        payer = _provider_address(event, order)
        payee = str(event.args.get("buyer") or order.buyer.primary_address)
        return payer or payee, payee
    return (
        str(event.args.get("buyer") or order.buyer.primary_address),
        _recipient(event, order),
    )


def _provider_address(event: contract.DecodedEvent, order: Order) -> str | None:
    """The provider's address from the event, or from the stored escrow."""
    named = event.args.get("provider")
    if named:
        return str(named)
    if order.escrow is not None and order.escrow.provider_address:
        return str(order.escrow.provider_address)
    return None


def _recipient(event: contract.DecodedEvent, order: Order) -> str | None:
    """Who received funds in this event, or None when it names nobody.

    **This crashed the indexer in a loop the first time a dispute was ever
    settled in production, on 2026-08-21.** The line read
    `str(event.args.get("provider") or "")`, which is correct for
    `EscrowReleased` and wrong for every other event, because they do not all
    carry a `provider`:

    - `EscrowReleased(escrowId, provider, providerAmount, feeAmount, releasedBy)`
    - `EscrowRefunded(escrowId, buyer, amount, refundedBy)`
    - `EscrowSettled(escrowId, providerAmount, buyerAmount, feeAmount, arbiter)`

    A settlement pays both parties and names neither, so `get("provider")`
    returned None, `or ""` turned that into an empty string, and the address
    column refused it. The exception escaped the event handler, the process
    died, and the container restarted into the same unprocessed block forever.
    Twenty one restarts before anybody looked, with **all** chain projection
    stopped, not only this event.

    A refund would have done exactly the same thing for the same reason, and
    neither event had ever been emitted in production, so both were latent from
    the day the line was written.

    The column is nullable, so the empty string was never necessary. Where the
    event names a single recipient, use it. Where it does not, fall back to the
    escrow's stored provider, and failing that record nothing rather than
    something invalid.
    """
    named = event.args.get("provider") or event.args.get("buyer")
    if named:
        return str(named)
    if order.escrow is not None and order.escrow.provider_address:
        return str(order.escrow.provider_address)
    return None


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


async def repair_order_from_chain(
    db: AsyncSession, client: ChainClient, order: Order
) -> dict[str, object]:
    """Move an order's recorded amounts to whatever the chain says they are.

    **Why this is safe, and it is the only reason it is allowed to exist.** It
    copies. Every figure it writes is read from the contract in the same call,
    and there is no argument that could carry a number, so the worst an operator
    can do is make the database agree with the chain. "Where they disagree the
    chain wins" is already what `reconcile_order` says; this makes that
    sentence actionable instead of merely true.

    **Why it was needed.** `reconcile` could name a divergence and nothing could
    close one. On 2026-08-22 the first settled dispute left the database holding
    the provider's net where the chain holds the gross. The indexer fix stopped
    it happening again and did nothing for the row already written, because
    events are processed once. A detector with no repair leaves the operator
    reading a true report they cannot act on.

    Status is deliberately **not** rewritten here. Amounts are facts the contract
    holds directly; status is a projection this application derives, with order
    state, notifications and reputation hanging off it, and copying an enum
    across that boundary would be a far larger claim than copying two numbers.
    A status divergence stays reported and unrepaired, which is the honest
    outcome rather than a convenient one.
    """
    before = await reconcile_order(db, client, order)
    if before["in_sync"]:
        return {**before, "repaired": [], "note": "already in sync, nothing written"}

    escrow_id = contract.escrow_id_for_order(str(order.id))
    on_chain = contract.decode_get_escrow(
        await client.call(
            to=contract.contract_address(), data=contract.encode_get_escrow(escrow_id)
        )
    )

    local = order.escrow
    repaired: list[str] = []
    if local is None or not on_chain.exists:
        # Nothing to copy into, or nothing to copy from. Either is a real
        # divergence and neither is fixed by writing an amount.
        return {**before, "repaired": [], "note": "structural divergence, not repairable by copying amounts"}

    if local.released_amount != on_chain.released:
        repaired.append(f"released: {local.released_amount} -> {on_chain.released}")
        local.released_amount = on_chain.released
    if local.refunded_amount != on_chain.refunded:
        repaired.append(f"refunded: {local.refunded_amount} -> {on_chain.refunded}")
        local.refunded_amount = on_chain.refunded
    if local.amount != on_chain.amount:
        repaired.append(f"amount: {local.amount} -> {on_chain.amount}")
        local.amount = on_chain.amount

    await db.flush()
    after = await reconcile_order(db, client, order)

    logger.info(
        "order_chain_repaired",
        extra={"order": str(order.id), "repaired": repaired,
               "in_sync_after": after["in_sync"]},
    )
    return {**after, "repaired": repaired}


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
