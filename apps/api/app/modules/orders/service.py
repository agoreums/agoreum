"""Order lifecycle.

An order is the off-chain record of an engagement. It never asserts that money
has moved, only the indexer, reading confirmed chain events, may mark an order
funded or completed. Everything here either records intent (create, deliver) or
reflects what the chain has already said.

The platform holds no funds and signs nothing. `payment_instructions` describes
a transaction for the buyer's own wallet to build, sign and broadcast.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.chain import escrow as contract
from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.db.enums import (
    AgentStatus,
    DisputeResolution,
    OrderStatus,
    PricingModel,
    ServiceStatus,
)
from app.modules.agents.models import Agent
from app.modules.orders.models import Escrow, Order, OrderEvent
from app.modules.orders.schemas import (
    OrderCreate,
    PaymentInstructions,
    SettlementAction,
    SettlementArgument,
    SettlementOptions,
)
from app.modules.organizations.authz import is_member
from app.modules.organizations.models import OrganizationMembership
from app.modules.services.models import Service
from app.modules.users.models import User

logger = get_logger(__name__)

# Platform fee, in basis points. Mirrors the contract's configured rate; the
# contract is authoritative and freezes its own value per escrow.
PLATFORM_FEE_BPS = 250

# How long a buyer has to fund an order before it expires.
FUNDING_WINDOW = timedelta(hours=24)

# How long past the deadline the expiry sweep waits before acting. Covers the
# gap between a payment being mined and the indexer seeing it past the
# confirmation frontier, so the sweep cannot expire an order that was in fact
# funded in time. Generous against a five block depth on a two second chain,
# because the cost of waiting is a stale row and the cost of being early is
# telling a buyer who paid that their order expired.
EXPIRY_GRACE = timedelta(minutes=15)

# Windows handed to the contract. The delivery window is when the buyer may
# reclaim unilaterally; auto-release is when the provider may claim.
DEFAULT_DELIVERY_WINDOW = timedelta(days=7)

REFERENCE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alike glyphs


def _generate_reference() -> str:
    body = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(8))
    return f"AGO-{body}"


def _quantise(amount: Decimal) -> Decimal:
    """Round to the settlement token's precision.

    Every figure stored must be exactly representable on-chain, or the amount
    charged and the amount escrowed would differ.
    """
    return amount.quantize(Decimal("0.000001"))


# --- Reads ------------------------------------------------------------------


async def get_order(db: AsyncSession, order_id: uuid.UUID) -> Order | None:
    return (
        await db.execute(
            select(Order)
            .where(Order.id == order_id)
            .options(
                selectinload(Order.escrow),
                selectinload(Order.transactions),
                selectinload(Order.service),
                selectinload(Order.provider_agent),
            )
        )
    ).scalar_one_or_none()


async def require_visible_order(
    db: AsyncSession, order_id: uuid.UUID, *, user: User
) -> Order:
    """Load an order the caller is party to.

    A stranger gets 404 rather than 403: order references are guessable enough
    that confirming existence would leak who is trading with whom.
    """
    order = await get_order(db, order_id)
    if order is None:
        raise NotFoundError("No such order.")

    if order.buyer_id == user.id:
        return order

    agent = (
        await db.execute(select(Agent).where(Agent.id == order.provider_agent_id))
    ).scalar_one_or_none()
    if agent is not None and await is_member(
        db, org_id=agent.org_id, user_id=user.id
    ):
        return order

    raise NotFoundError("No such order.")


async def list_for_buyer(db: AsyncSession, *, user: User, limit: int = 50) -> list[Order]:
    result = await db.execute(
        select(Order)
        .where(Order.buyer_id == user.id)
        .options(selectinload(Order.escrow))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_for_provider(
    db: AsyncSession, *, user: User, limit: int = 50
) -> list[Order]:
    result = await db.execute(
        select(Order)
        .join(Agent, Agent.id == Order.provider_agent_id)
        .join(OrganizationMembership, OrganizationMembership.org_id == Agent.org_id)
        .where(OrganizationMembership.user_id == user.id)
        .options(selectinload(Order.escrow))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


# --- Creation ---------------------------------------------------------------


def resolve_windows(order, service) -> tuple[timedelta, timedelta]:
    """The delivery and auto release windows that govern this order.

    The order's own frozen terms win. The service is consulted only for orders
    created before those columns existed, so historic rows keep working.

    Reading the live service here was the defect this replaces. A provider could
    edit the service after an order was placed and move that order's deadlines,
    and shortening `auto_release_hours` is the dangerous direction: it shrinks the
    window a buyer has to raise a dispute before escrow releases to the provider.
    """
    delivery_hours = order.delivery_time_hours or service.delivery_time_hours
    delivery = timedelta(
        hours=delivery_hours or int(DEFAULT_DELIVERY_WINDOW.total_seconds() // 3600)
    )
    auto_release = timedelta(
        hours=order.auto_release_hours or service.auto_release_hours
    )
    return delivery, auto_release


async def create_order(
    db: AsyncSession, *, buyer: User, payload: OrderCreate
) -> Order:
    """Create an unfunded order.

    Prices are frozen here from the service as it stands right now, so a later
    price change cannot alter what an existing order owes.
    """
    service = (
        await db.execute(
            select(Service)
            .where(Service.id == payload.service_id)
            .options(selectinload(Service.agent))
        )
    ).scalar_one_or_none()

    if service is None or service.status != ServiceStatus.PUBLISHED:
        raise NotFoundError("No such service.")

    agent = service.agent
    if agent.status != AgentStatus.ACTIVE:
        raise ConflictError(
            "This provider is not currently accepting orders.",
            code="provider_unavailable",
        )

    if await is_member(db, org_id=agent.org_id, user_id=buyer.id):
        raise ConflictError(
            "You cannot order from an agent you own.", code="self_dealing"
        )

    if agent.payout_wallet_id is None or not agent.payout_address:
        raise ConflictError(
            "This provider has no verified payout address, so it cannot be paid.",
            code="provider_has_no_payout_address",
        )

    if payload.quantity < service.min_quantity:
        raise ConflictError(
            f"This service has a minimum quantity of {service.min_quantity}.",
            code="below_minimum_quantity",
        )
    if service.max_quantity is not None and payload.quantity > service.max_quantity:
        raise ConflictError(
            f"This service has a maximum quantity of {service.max_quantity}.",
            code="above_maximum_quantity",
        )

    unit_price = _resolve_unit_price(service, payload)

    subtotal = _quantise(unit_price * payload.quantity)
    platform_fee = _quantise(subtotal * Decimal(PLATFORM_FEE_BPS) / Decimal(10_000))
    total = _quantise(subtotal + platform_fee)

    now = datetime.now(UTC)
    order = Order(
        reference=_generate_reference(),
        buyer_id=buyer.id,
        provider_agent_id=agent.id,
        service_id=service.id,
        # Frozen here, not read later. See the model comment.
        delivery_time_hours=service.delivery_time_hours,
        auto_release_hours=service.auto_release_hours,
        status=OrderStatus.PENDING_PAYMENT,
        quantity=payload.quantity,
        unit_price=unit_price,
        subtotal=subtotal,
        platform_fee=platform_fee,
        total_amount=total,
        currency=service.price_currency,
        platform_fee_bps=PLATFORM_FEE_BPS,
        requirements=payload.requirements,
        funding_deadline=now + FUNDING_WINDOW,
    )
    db.add(order)
    await db.flush()

    db.add(
        OrderEvent(
            order_id=order.id,
            event_type="order.created",
            actor_user_id=buyer.id,
            to_status=OrderStatus.PENDING_PAYMENT.value,
            detail={"service_id": str(service.id), "quantity": payload.quantity},
        )
    )

    # The counter tracks orders placed, which is a real event. It is distinct
    # from completed_order_count, which only the chain can advance.
    service.order_count += 1

    await db.flush()

    logger.info(
        "order_created",
        extra={"order": str(order.id), "reference": order.reference},
    )
    # Reload with relationships eagerly loaded. The caller serialises escrow and
    # transactions, and a lazy load there would attempt IO outside the async
    # context and fail.
    return await get_order(db, order.id)


def _resolve_unit_price(service: Service, payload: OrderCreate) -> Decimal:
    if service.pricing_model == PricingModel.NEGOTIATED:
        if payload.negotiated_price is None:
            raise ConflictError(
                "This service is priced by negotiation; an agreed price is required.",
                code="negotiated_price_required",
            )
        return _quantise(payload.negotiated_price)

    if service.price is None:
        # Should be unreachable: a published non-negotiated service must have a
        # price. Refusing beats guessing one.
        raise ConflictError(
            "This service has no price set and cannot be ordered.",
            code="service_has_no_price",
        )
    return _quantise(service.price)


# --- Payment ----------------------------------------------------------------


async def payment_instructions(
    db: AsyncSession, *, order: Order
) -> PaymentInstructions:
    """Describe the transaction the buyer's wallet must make.

    Nothing here is signed or broadcast by the platform. The escrow id is derived
    deterministically from the order id, so the resulting on-chain record can
    always be reconciled back to this order.
    """
    if order.status != OrderStatus.PENDING_PAYMENT:
        raise ConflictError(
            "This order is not awaiting payment.", code="order_not_payable"
        )

    # The funding deadline is what bounds the price freeze. An order fixes the
    # price at the moment it is placed, and without this check that fixed price
    # stayed fundable forever: a buyer could hold an order open, wait for the
    # provider to raise their price, and still pay the old one. The deadline was
    # returned in this very response, and shown to buyers, while nothing
    # enforced it.
    if order.funding_deadline is not None and datetime.now(UTC) >= order.funding_deadline:
        raise ConflictError(
            "The funding window for this order has closed. Place a new order to "
            "pay at the current price.",
            code="order_funding_window_closed",
        )

    if not contract.is_configured():
        raise contract.EscrowNotConfiguredError()

    agent = (
        await db.execute(select(Agent).where(Agent.id == order.provider_agent_id))
    ).scalar_one()

    if not agent.payout_address:
        raise ConflictError(
            "This provider has no payout address.",
            code="provider_has_no_payout_address",
        )

    service = (
        await db.execute(select(Service).where(Service.id == order.service_id))
    ).scalar_one()

    delivery_window, auto_release_window = resolve_windows(order, service)

    return PaymentInstructions(
        order_id=order.id,
        order_reference=order.reference,
        chain_id=settings.CHAIN_ID,
        network_name=settings.chain_name,
        escrow_contract=contract.contract_address(),
        token_address=settings.usdc_address.lower(),
        token_symbol="USDC",  # noqa: S106, a token ticker, not a credential
        token_decimals=contract.TOKEN_DECIMALS,
        escrow_id=contract.escrow_id_for_order(str(order.id)),
        provider_address=agent.payout_address,
        amount=order.total_amount,
        amount_base_units=str(contract.to_base_units(order.total_amount)),
        delivery_window_seconds=int(delivery_window.total_seconds()),
        auto_release_window_seconds=int(auto_release_window.total_seconds()),
        approve_selector="0x095ea7b3",  # ERC-20 approve(address,uint256)
        create_escrow_selector=contract.function_selector("createEscrow"),
        funding_deadline=order.funding_deadline,
        explorer_url=settings.explorer_url,
    )


# --- Getting money back out -------------------------------------------------


async def settlement_options(
    db: AsyncSession, *, order: Order, user: User, client
) -> SettlementOptions:
    """Every on-chain exit from this escrow, for the party asking.

    **This exists because it did not, and that was the most serious defect this
    project has found.** `payment_instructions` told a buyer precisely how to put
    money into an escrow: contract, selector, calldata, amounts, deadline. There
    was no counterpart for taking it out. The web application makes exactly two
    on-chain writes, `createEscrow` and `subscribe`, and no endpoint described
    `release`, `refund` or `dispute` at all.

    So a buyer whose provider vanished held a right the contract genuinely
    enforces and could not reach it. Recovering their own money meant finding the
    contract address, reading the ABI, and building the transaction themselves.
    The contract was correct throughout, which is why no test, no review and no
    audit-readiness document would ever have shown it. Found by trying to use the
    refund path as a real user would, during the rehearsal of 2026-08-22.

    Everything decisive is read from the chain, because the database does not
    store the deadlines at all and because the contract is what will accept or
    refuse the call. `orders.auto_release_at` is a **different quantity**: the
    platform counts that window from actual delivery, while the contract fixes it
    at creation as `deliveryDeadline + autoReleaseWindow`. Reporting the
    platform's figure here would tell a provider they can claim at a moment the
    chain will refuse.

    Availability mirrors the contract's own conditions rather than restating them
    loosely. Where an action is unavailable the reason is returned, because a
    disabled control with no explanation is how somebody concludes that a right
    they hold is not real.
    """
    if not contract.is_configured():
        raise contract.EscrowNotConfiguredError()

    escrow_id = contract.escrow_id_for_order(str(order.id))
    on_chain = contract.decode_get_escrow(
        await client.call(
            to=contract.contract_address(),
            data=contract.encode_get_escrow(escrow_id),
        )
    )
    paused = await _contract_is_paused(client)

    roles = await _roles_of(db, order=order, user=user)
    now = datetime.now(UTC)
    deadline = _as_moment(on_chain.delivery_deadline)
    auto_release = _as_moment(on_chain.auto_release_at)

    actions = [
        _release_action(on_chain, roles, now=now, auto_release=auto_release,
                        escrow_id=escrow_id),
        _refund_action(on_chain, roles, now=now, deadline=deadline,
                       escrow_id=escrow_id),
        _dispute_action(on_chain, roles, paused=paused, escrow_id=escrow_id),
    ]

    return SettlementOptions(
        order_id=order.id,
        order_reference=order.reference,
        chain_id=settings.CHAIN_ID,
        network_name=settings.chain_name,
        escrow_contract=contract.contract_address(),
        escrow_id=escrow_id,
        onchain_status=on_chain.status.name.lower(),
        contract_paused=paused,
        delivery_deadline=deadline,
        auto_release_at=auto_release,
        your_roles=sorted(roles),
        actions=actions,
        explorer_url=settings.explorer_url,
        note=(
            "The platform holds no funds and signs nothing. Each action below is "
            "a transaction for your own wallet to build, sign and broadcast, and "
            "the calldata is published so you can do that without this interface. "
            "The contract decides whether a call succeeds; these deadlines are "
            "read from it, not from our records."
        ),
    )


async def _contract_is_paused(client) -> bool:
    """Whether the escrow contract is paused.

    Read rather than assumed because `dispute` is gated on `whenNotPaused` and
    `refund` deliberately is not. Offering a dispute that would revert, while
    hiding a refund that would succeed, would be exactly backwards during the one
    situation a pause exists for.
    """
    try:
        result = await client.call(
            to=contract.contract_address(), data=contract.function_selector("paused")
        )
    except Exception:  # noqa: BLE001 - an unreadable pause flag must not hide the exits
        logger.warning("escrow_paused_unreadable")
        return False
    return bool(int(result, 16)) if result and result != "0x" else False


async def _roles_of(db: AsyncSession, *, order: Order, user: User) -> set[str]:
    """Which parties this caller is. Plural, because one person can be both.

    The settlement exercise held the buyer and provider wallets at once, and the
    dispute rehearsal held the buyer and arbiter. Collapsing this to one role
    would hide half of what the caller can actually do.
    """
    roles: set[str] = set()
    if user.id == order.buyer_id:
        roles.add("buyer")
    agent = order.provider_agent
    if agent is not None and agent.org_id is not None and await is_member(
        db, org_id=agent.org_id, user_id=user.id
    ):
        roles.add("provider")
    if is_arbiter(user):
        roles.add("arbiter")
    return roles


def _as_moment(timestamp: int) -> datetime | None:
    return datetime.fromtimestamp(timestamp, UTC) if timestamp else None


def _terminal_reason(status: contract.OnChainStatus) -> str | None:
    """Why no exit is open, when none is. None means the escrow is still live."""
    if status == contract.OnChainStatus.NONE:
        return "This escrow does not exist on chain yet. Fund the order first."
    if status == contract.OnChainStatus.DISPUTED:
        return (
            "This escrow is frozen pending arbitration. Only an arbiter can move "
            "it now, by splitting it between the two parties."
        )
    if status != contract.OnChainStatus.FUNDED:
        return "This escrow has already settled. Nothing further can move it."
    return None


def _action(
    *, name: str, who: str, available: bool, reason: str | None,
    available_at: datetime | None, escrow_id: str,
    arguments: list[SettlementArgument], calldata: str | None,
) -> SettlementAction:
    return SettlementAction(
        action=name,
        available=available,
        who=who,
        reason=reason,
        available_at=available_at,
        function=name,
        selector=contract.function_selector(name),
        arguments=arguments,
        calldata=calldata,
    )


def _escrow_id_argument(escrow_id: str) -> list[SettlementArgument]:
    return [SettlementArgument(name="escrowId", type="bytes32", value=escrow_id)]


def _release_action(
    on_chain, roles: set[str], *, now: datetime, auto_release: datetime | None,
    escrow_id: str,
) -> SettlementAction:
    """Pay the provider. The buyer may at any time; anyone once auto-release is due.

    The permissionless path after the deadline is deliberate in the contract: a
    provider must not depend on the buyer, or on the platform, in order to be
    paid. Reported to everyone for that reason, not only to the two parties.
    """
    who = (
        "The buyer, at any time, accepting the work. Anyone at all once the "
        "auto-release time has passed, so payment never depends on the buyer "
        "staying reachable."
    )
    terminal = _terminal_reason(on_chain.status)
    due = auto_release is not None and now >= auto_release
    available = terminal is None and ("buyer" in roles or due)
    reason = terminal
    if reason is None and not available:
        reason = (
            "Only the buyer can release before the auto-release time. After it, "
            "anyone can."
        )
    return _action(
        name="release", who=who, available=available, reason=reason,
        available_at=None if "buyer" in roles else auto_release,
        escrow_id=escrow_id, arguments=_escrow_id_argument(escrow_id),
        calldata=contract.encode_escrow_id_call("release", escrow_id),
    )


def _refund_action(
    on_chain, roles: set[str], *, now: datetime, deadline: datetime | None,
    escrow_id: str,
) -> SettlementAction:
    """Return the whole amount to the buyer. No fee is taken.

    The buyer's branch is the guarantee that makes escrow worth using: a provider
    who disappears cannot keep the money. It was proven for real on 2026-08-22
    and was unreachable from the product on the same day.
    """
    who = (
        "The provider, at any time, declining the work. The buyer, once the "
        "delivery deadline has passed with nothing delivered. The full amount "
        "goes back and no platform fee is taken."
    )
    terminal = _terminal_reason(on_chain.status)
    overdue = deadline is not None and now >= deadline
    available = terminal is None and ("provider" in roles or ("buyer" in roles and overdue))
    reason = terminal
    if reason is None and not available:
        if "buyer" in roles:
            reason = (
                "The delivery deadline has not passed yet. Until it does, only "
                "the provider can return the money."
            )
        else:
            reason = "Only the provider, or the buyer after the delivery deadline, can refund."
    return _action(
        name="refund", who=who, available=available, reason=reason,
        available_at=None if "provider" in roles else deadline,
        escrow_id=escrow_id, arguments=_escrow_id_argument(escrow_id),
        calldata=contract.encode_escrow_id_call("refund", escrow_id),
    )


def _dispute_action(
    on_chain, roles: set[str], *, paused: bool, escrow_id: str
) -> SettlementAction:
    """Freeze the escrow for arbitration.

    No calldata is published, and that is not an omission. `dispute` takes a
    free-text reason, so complete calldata cannot exist before the caller has
    written one. Publishing calldata with an empty or invented reason would put
    words in their mouth in a document they are about to sign.
    """
    who = (
        "Either party, while the escrow still holds funds. Raising a dispute "
        "closes the automatic release, so a disagreement cannot resolve itself "
        "in one side's favour purely by time passing."
    )
    terminal = _terminal_reason(on_chain.status)
    is_party = bool(roles & {"buyer", "provider"})
    available = terminal is None and is_party and not paused
    reason = terminal
    if reason is None and not available:
        if paused:
            reason = (
                "The contract is paused, so a dispute cannot be raised right now. "
                "A refund is still possible: taking your own money out is "
                "deliberately never blocked by a pause."
            )
        else:
            reason = "Only the buyer or the provider can raise a dispute."
    return _action(
        name="dispute", who=who, available=available, reason=reason,
        available_at=None, escrow_id=escrow_id,
        arguments=[
            SettlementArgument(name="escrowId", type="bytes32", value=escrow_id),
            SettlementArgument(name="reason", type="string", value=None),
        ],
        calldata=None,
    )


# --- Provider actions -------------------------------------------------------


async def mark_delivered(
    db: AsyncSession, *, order: Order, actor: User, note: str | None, payload: dict | None
) -> Order:
    """Record that the provider considers the work delivered.

    This does not move money. It starts the acceptance window, after which the
    contract's auto-release path becomes available to the provider.
    """
    if order.status not in {OrderStatus.FUNDED, OrderStatus.IN_PROGRESS}:
        raise ConflictError(
            "Only a funded order in progress can be delivered.",
            code="order_not_deliverable",
        )

    now = datetime.now(UTC)
    order.status = OrderStatus.DELIVERED
    order.delivered_at = now
    order.delivery_note = note
    order.output_payload = payload

    # The order's own frozen window, not the service's current one. This is the
    # moment the auto release deadline becomes real, and the provider both
    # controls the service and chooses when to deliver. Reading the live value
    # here let them shorten the buyer's window to dispute after the order was
    # placed, by editing the service and then marking delivery.
    #
    # The service is still consulted for orders created before the column
    # existed, which the migration backfilled but which may exist in a database
    # restored from an older backup.
    hours = order.auto_release_hours
    if hours is None:
        service = (
            await db.execute(select(Service).where(Service.id == order.service_id))
        ).scalar_one()
        hours = service.auto_release_hours
    order.auto_release_at = now + timedelta(hours=hours)

    db.add(
        OrderEvent(
            order_id=order.id,
            event_type="order.delivered",
            actor_user_id=actor.id,
            from_status=OrderStatus.FUNDED.value,
            to_status=OrderStatus.DELIVERED.value,
        )
    )
    await db.flush()
    await db.refresh(order)

    logger.info("order_delivered", extra={"order": str(order.id)})
    return order


async def start_work(db: AsyncSession, *, order: Order, actor: User) -> Order:
    if order.status != OrderStatus.FUNDED:
        raise ConflictError(
            "Only a funded order can be started.", code="order_not_startable"
        )

    order.status = OrderStatus.IN_PROGRESS
    order.started_at = datetime.now(UTC)
    db.add(
        OrderEvent(
            order_id=order.id,
            event_type="order.started",
            actor_user_id=actor.id,
            from_status=OrderStatus.FUNDED.value,
            to_status=OrderStatus.IN_PROGRESS.value,
        )
    )
    await db.flush()
    await db.refresh(order)
    return order


async def record_dispute_intent(
    db: AsyncSession, *, order: Order, actor: User, reason: str
) -> Order:
    """Record that a party intends to dispute.

    The authoritative dispute is the on-chain one, raised by the party's own
    wallet. This records the reason and makes the intent visible to support; the
    order only becomes DISPUTED when the chain says so.
    """
    if order.status not in {
        OrderStatus.FUNDED,
        OrderStatus.IN_PROGRESS,
        OrderStatus.DELIVERED,
    }:
        raise ConflictError(
            "This order cannot be disputed in its current state.",
            code="order_not_disputable",
        )

    db.add(
        OrderEvent(
            order_id=order.id,
            event_type="order.dispute_intent",
            actor_user_id=actor.id,
            detail={"reason": reason},
        )
    )
    await db.flush()

    logger.info("order_dispute_intent", extra={"order": str(order.id)})
    return order


async def expire_unfunded_orders(db: AsyncSession) -> int:
    """Expire orders whose funding window closed without payment arriving.

    Safe because an unfunded order has no escrow: nothing is being taken away.

    The grace period is the part that matters. A buyer can fund seconds before
    the deadline, and that payment is not visible here until the indexer has
    seen it past the confirmation frontier. Expiring on the deadline itself
    would race a payment that already happened, and although the indexer would
    later move the order back to funded, the buyer would meanwhile have been
    told their order expired. Waiting out the confirmation window removes the
    race rather than relying on it being repaired afterwards.
    """
    now = datetime.now(UTC)
    cutoff = now - EXPIRY_GRACE
    stale = (
        await db.execute(
            select(Order).where(
                Order.status == OrderStatus.PENDING_PAYMENT,
                Order.funding_deadline < cutoff,
            )
        )
    ).scalars().all()

    for order in stale:
        order.status = OrderStatus.EXPIRED
        db.add(
            OrderEvent(
                order_id=order.id,
                event_type="order.expired",
                to_status=OrderStatus.EXPIRED.value,
                detail={"reason": "funding window elapsed"},
            )
        )

    if stale:
        await db.flush()
        logger.info("orders_expired", extra={"count": len(stale)})
    return len(stale)


async def counts_for_agent(db: AsyncSession, agent_id: uuid.UUID) -> dict[str, int]:
    """Real order counts for an agent, computed from orders rather than cached."""
    rows = (
        await db.execute(
            select(Order.status, func.count())
            .where(Order.provider_agent_id == agent_id)
            .group_by(Order.status)
        )
    ).all()
    return {status.value: count for status, count in rows}


# How long each party has to state their case before a decision is made on what
# is available. Silence must not stall the other party's money indefinitely.
DISPUTE_STATEMENT_WINDOW = timedelta(days=5)


def is_arbiter(user: User) -> bool:
    """Whether this account may decide disputes.

    Deliberately the address the contract will accept for settleDispute rather
    than a flag on the user. An API that let somebody record a decision the chain
    would then refuse is worse than one with no arbiter at all, and two sources of
    authority drift apart the moment either is edited.
    """
    configured = (settings.ESCROW_ARBITER_ADDRESS or "").lower()
    if not configured:
        return False
    return (user.primary_address or "").lower() == configured


async def _arbiter_is_party(db: AsyncSession, *, order: Order, arbiter: User) -> bool:
    """Whether this arbiter is one of the two sides of this dispute.

    **The provider half of this could never fire before 2026-08-21.** The old
    version returned a set containing the buyer's *user* id together with the
    provider agent's *organization* id, and the caller compared an arbiter's
    user id against it. Those are identifiers from different tables and never
    collide, so an arbiter who owned the agent being disputed passed the check
    every time.

    The buyer half worked, which is how the guard looked alive: the dispute
    rehearsal hit it immediately. The half that could not fire is the more
    dangerous one, because an arbiter who owns the provider decides how much of
    the contested escrow is paid to themselves.

    Membership is the right question rather than identity. An agent belongs to
    an organization, and anyone in that organization benefits from a decision in
    the provider's favour, so the test is the same one `create_order` already
    uses to refuse self-dealing.
    """
    if arbiter.id == order.buyer_id:
        return True
    agent = order.provider_agent
    if agent is not None and agent.org_id is not None:
        return await is_member(db, org_id=agent.org_id, user_id=arbiter.id)
    return False


async def submit_dispute_statement(
    db: AsyncSession,
    *,
    order: Order,
    actor: User,
    text: str,
    escrow: Escrow | None = None,
) -> OrderEvent:
    """Record one party's account of a disputed order.

    Appended to the order's existing timeline rather than kept in a separate
    place, because that timeline is already the record an arbiter reads and a
    second store would mean two versions of what happened.

    Both parties see every statement. A decision made on evidence one side never
    saw is not defensible, whoever made it.
    """
    if order.status != OrderStatus.DISPUTED:
        raise ConflictError(
            "This order is not in dispute.", code="order_not_disputed"
        )
    if escrow is not None and escrow.dispute_resolved_at is not None:
        raise ConflictError(
            "This dispute has already been decided.", code="dispute_decided"
        )

    event = OrderEvent(
        order_id=order.id,
        event_type="order.dispute_statement",
        actor_user_id=actor.id,
        detail={"text": text},
    )
    db.add(event)
    await db.flush()
    return event


async def record_dispute_decision(
    db: AsyncSession,
    *,
    order: Order,
    escrow: Escrow,
    arbiter: User,
    provider_amount: Decimal,
    reasoning: str,
) -> Escrow:
    """Record how a disputed escrow should be divided, before it is executed.

    This writes the decision. It does not move money and does not sign anything:
    the platform holds no keys, so the arbiter's own wallet calls settleDispute
    with the figures this returns, and the indexer confirms the result. Recording
    first is what makes an unexpected settlement detectable, since there is
    something to compare the chain against.

    Only the provider's share is taken. The buyer's is derived, because the
    contract derives it too and accepting a second figure would allow a recorded
    decision that differs from what the chain actually pays.
    """
    if order.status != OrderStatus.DISPUTED:
        raise ConflictError(
            "This order is not in dispute.", code="order_not_disputed"
        )
    if escrow.dispute_resolved_at is not None:
        raise ConflictError(
            "This dispute has already been decided.", code="dispute_decided"
        )

    # The escrow's own amount, not the order total. The escrow is what
    # settleDispute divides, and bounding a split by anything else risks recording
    # a decision the contract would refuse, or one that pays a different figure.
    escrow_total = escrow.amount
    if provider_amount < 0 or provider_amount > escrow_total:
        raise ConflictError(
            "The provider's share must be between zero and the escrow amount.",
            code="split_out_of_range",
        )

    # An arbiter who is also a party decides their own case. Refused by the
    # system rather than left to their judgement.
    if await _arbiter_is_party(db, order=order, arbiter=arbiter):
        raise PermissionDeniedError(
            "An arbiter cannot decide a dispute they are party to.",
            code="arbiter_is_party",
        )

    buyer_amount = escrow_total - provider_amount
    if provider_amount == escrow_total:
        resolution = DisputeResolution.RELEASED_TO_PROVIDER
    elif provider_amount == 0:
        resolution = DisputeResolution.REFUNDED_TO_BUYER
    else:
        resolution = DisputeResolution.SPLIT

    escrow.dispute_provider_amount = provider_amount
    escrow.dispute_reasoning = reasoning
    escrow.dispute_resolution = resolution
    escrow.dispute_resolved_at = datetime.now(UTC)
    escrow.dispute_resolved_by = arbiter.id

    db.add(
        OrderEvent(
            order_id=order.id,
            event_type="order.dispute_decided",
            actor_user_id=arbiter.id,
            detail={
                "provider_amount": str(provider_amount),
                "buyer_amount": str(buyer_amount),
                "resolution": resolution.value,
            },
        )
    )
    await db.flush()
    return escrow


async def build_dispute_view(
    db: AsyncSession, *, order: Order, escrow: Escrow | None
):
    """The dispute as the two parties and the arbiter all see it.

    One view for all three on purpose. Divergent views would mean somebody is
    deciding, or being decided about, on a different set of facts.
    """
    from app.modules.orders.schemas import DisputeStatementView, DisputeView

    rows = (
        await db.execute(
            select(OrderEvent)
            .where(
                OrderEvent.order_id == order.id,
                OrderEvent.event_type == "order.dispute_statement",
            )
            .order_by(OrderEvent.created_at)
        )
    ).scalars().all()

    disputed_at = escrow.disputed_at if escrow else None
    closes = (
        disputed_at + DISPUTE_STATEMENT_WINDOW if disputed_at is not None else None
    )
    provider_amount = escrow.dispute_provider_amount if escrow else None
    buyer_amount = (
        escrow.amount - provider_amount
        if escrow is not None and provider_amount is not None
        else None
    )

    return DisputeView(
        order_id=order.id,
        order_reference=order.reference,
        status=order.status.value,
        disputed_at=disputed_at,
        reason=escrow.dispute_reason if escrow else None,
        statements_close_at=closes,
        statements=[
            DisputeStatementView(
                id=r.id,
                author_user_id=r.actor_user_id,
                text=(r.detail or {}).get("text", ""),
                created_at=r.created_at,
            )
            for r in rows
        ],
        resolution=(
            escrow.dispute_resolution.value
            if escrow and escrow.dispute_resolution
            else None
        ),
        provider_amount=provider_amount,
        buyer_amount=buyer_amount,
        reasoning=escrow.dispute_reasoning if escrow else None,
        decided_at=escrow.dispute_resolved_at if escrow else None,
    )


def build_settlement_instructions(*, order: Order, escrow: Escrow):
    """The exact call the arbiter's wallet should send.

    The buyer's share is derived here rather than accepted from the caller. The
    contract computes it the same way and uses its own buyerAmount argument only
    as a bounds check, so a supplied pair could pass validation while paying
    something other than what was decided.
    """
    from app.modules.orders.schemas import SettlementInstructions

    provider_amount = escrow.dispute_provider_amount or Decimal("0")
    buyer_amount = escrow.amount - provider_amount
    return SettlementInstructions(
        order_id=order.id,
        order_reference=order.reference,
        chain_id=settings.CHAIN_ID,
        escrow_contract=settings.ESCROW_CONTRACT_ADDRESS or "",
        escrow_id=contract.escrow_id_for_order(str(order.id)),
        provider_amount=provider_amount,
        provider_amount_base_units=str(contract.to_base_units(provider_amount)),
        buyer_amount=buyer_amount,
        buyer_amount_base_units=str(contract.to_base_units(buyer_amount)),
    )
