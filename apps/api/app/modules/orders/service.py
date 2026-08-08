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
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.enums import (
    AgentStatus,
    OrderStatus,
    PricingModel,
    ServiceStatus,
)
from app.modules.agents.models import Agent
from app.modules.orders.models import Order, OrderEvent
from app.modules.orders.schemas import OrderCreate, PaymentInstructions
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

    service = (
        await db.execute(select(Service).where(Service.id == order.service_id))
    ).scalar_one()
    order.auto_release_at = now + timedelta(hours=service.auto_release_hours)

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
    """
    now = datetime.now(UTC)
    stale = (
        await db.execute(
            select(Order).where(
                Order.status == OrderStatus.PENDING_PAYMENT,
                Order.funding_deadline < now,
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
