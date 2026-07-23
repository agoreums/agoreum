"""Order and payment endpoints.

The platform describes payments; it never makes them. There is no endpoint here
that signs or broadcasts a transaction, and no code path that could: the buyer's
wallet funds the escrow directly, and the indexer learns about it by reading
confirmed chain events.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.chain import escrow as contract
from app.chain.client import ChainClient
from app.chain.indexer import reconcile_order
from app.core.config import settings
from app.core.errors import NotFoundError, PermissionDeniedError
from app.modules.agents.models import Agent
from app.modules.orders import service
from app.modules.orders.schemas import (
    ChainStatus,
    ChainTransactionSummary,
    DeliverRequest,
    DisputeRequest,
    EscrowSummary,
    OrderCreate,
    OrderDetail,
    OrderSummary,
    PaymentInstructions,
    ReconciliationReport,
)

router = APIRouter(tags=["orders"])


def _to_detail(order) -> OrderDetail:
    detail = OrderDetail.model_validate(order)
    if order.escrow is not None:
        detail.escrow = EscrowSummary.model_validate(order.escrow)
    detail.transactions = [
        ChainTransactionSummary(
            **ChainTransactionSummary.model_validate(tx).model_dump(
                exclude={"explorer_url"}
            ),
            explorer_url=f"{settings.explorer_url}/tx/{tx.tx_hash}",
        )
        for tx in order.transactions
    ]
    return detail


async def _require_provider(db, order, user) -> Agent:
    """Confirm the caller owns the agent providing this order."""
    from sqlalchemy import select

    agent = (
        await db.execute(select(Agent).where(Agent.id == order.provider_agent_id))
    ).scalar_one_or_none()
    if agent is None or agent.owner_id != user.id:
        raise PermissionDeniedError("Only the provider can do this.")
    return agent


@router.get(
    "/chain/status",
    response_model=ChainStatus,
    summary="What on-chain settlement is available right now",
)
async def chain_status() -> ChainStatus:
    """Reported honestly so a client never opens a payment flow that cannot
    complete because no contract is configured for this environment."""
    configured = contract.is_configured()

    reachable = False
    head: int | None = None
    if settings.rpc_url:
        try:
            async with ChainClient() as client:
                head = await client.block_number()
                reachable = True
        except Exception:
            reachable = False

    note = None
    if not configured:
        note = (
            "No escrow contract is configured for this network, so orders "
            "cannot be funded yet."
        )
    elif not reachable:
        note = "The escrow contract is configured but the RPC endpoint is unreachable."

    return ChainStatus(
        chain_id=settings.CHAIN_ID,
        network_name=settings.chain_name,
        escrow_configured=configured,
        escrow_contract=settings.ESCROW_CONTRACT_ADDRESS,
        token_address=settings.usdc_address,
        token_symbol="USDC",  # noqa: S106 — a token ticker, not a credential
        confirmations_required=settings.CHAIN_CONFIRMATIONS,
        explorer_url=settings.explorer_url,
        rpc_reachable=reachable,
        head_block=head,
        note=note,
    )


@router.post(
    "/orders",
    response_model=OrderDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Place an order",
)
async def create_order(
    payload: OrderCreate, user: CurrentUser, db: DbSession
) -> OrderDetail:
    """Creates an unfunded order with prices frozen as they stand now."""
    order = await service.create_order(db, buyer=user, payload=payload)
    return _to_detail(order)


@router.get(
    "/orders", response_model=list[OrderSummary], summary="Orders you placed"
)
async def my_orders(user: CurrentUser, db: DbSession) -> list[OrderSummary]:
    orders = await service.list_for_buyer(db, user=user)
    return [OrderSummary.model_validate(o) for o in orders]


@router.get(
    "/orders/received",
    response_model=list[OrderSummary],
    summary="Orders placed with your agents",
)
async def received_orders(user: CurrentUser, db: DbSession) -> list[OrderSummary]:
    orders = await service.list_for_provider(db, user=user)
    return [OrderSummary.model_validate(o) for o in orders]


@router.get("/orders/{order_id}", response_model=OrderDetail, summary="An order")
async def get_order(
    order_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> OrderDetail:
    order = await service.require_visible_order(db, order_id, user=user)
    return _to_detail(order)


@router.get(
    "/orders/{order_id}/payment-instructions",
    response_model=PaymentInstructions,
    summary="How to fund this order from your own wallet",
)
async def payment_instructions(
    order_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> PaymentInstructions:
    """Describes the approve + createEscrow calls the buyer's wallet must make.

    The platform neither signs nor broadcasts; it only says what to send.
    """
    order = await service.require_visible_order(db, order_id, user=user)
    if order.buyer_id != user.id:
        raise NotFoundError("No such order.")
    return await service.payment_instructions(db, order=order)


@router.post(
    "/orders/{order_id}/start",
    response_model=OrderDetail,
    summary="Provider: begin work",
)
async def start_work(
    order_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> OrderDetail:
    order = await service.require_visible_order(db, order_id, user=user)
    await _require_provider(db, order, user)
    await service.start_work(db, order=order, actor=user)
    return _to_detail(await service.get_order(db, order_id))


@router.post(
    "/orders/{order_id}/deliver",
    response_model=OrderDetail,
    summary="Provider: mark delivered",
)
async def deliver(
    order_id: uuid.UUID,
    payload: DeliverRequest,
    user: CurrentUser,
    db: DbSession,
) -> OrderDetail:
    """Starts the acceptance window. Moves no money — release happens on-chain,
    either when the buyer accepts or when the auto-release deadline passes."""
    order = await service.require_visible_order(db, order_id, user=user)
    await _require_provider(db, order, user)
    await service.mark_delivered(
        db,
        order=order,
        actor=user,
        note=payload.delivery_note,
        payload=payload.output_payload,
    )
    return _to_detail(await service.get_order(db, order_id))


@router.post(
    "/orders/{order_id}/dispute-intent",
    response_model=OrderDetail,
    summary="Record an intent to dispute",
)
async def dispute_intent(
    order_id: uuid.UUID,
    payload: DisputeRequest,
    user: CurrentUser,
    db: DbSession,
) -> OrderDetail:
    """Records the reason and alerts support.

    The authoritative dispute is raised on-chain by the party's own wallet; the
    order only becomes disputed when the chain says so.
    """
    order = await service.require_visible_order(db, order_id, user=user)
    await service.record_dispute_intent(
        db, order=order, actor=user, reason=payload.reason
    )
    return _to_detail(await service.get_order(db, order_id))


@router.get(
    "/orders/{order_id}/reconcile",
    response_model=ReconciliationReport,
    summary="Compare this order against the chain",
)
async def reconcile(
    order_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> ReconciliationReport:
    """Reads the contract's own view and reports any divergence.

    Exists so a disagreement between the database and the chain is discoverable
    rather than silent. The chain is authoritative.
    """
    order = await service.require_visible_order(db, order_id, user=user)
    async with ChainClient() as client:
        report = await reconcile_order(db, client, order)
    return ReconciliationReport(**report)
