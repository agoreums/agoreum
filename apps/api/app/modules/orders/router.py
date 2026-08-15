"""Order and payment endpoints.

The platform describes payments; it never makes them. There is no endpoint here
that signs or broadcasts a transaction, and no code path that could: the buyer's
wallet funds the escrow directly, and the indexer learns about it by reading
confirmed chain events.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, OrdersRead, OrdersWrite
from app.chain import escrow as contract
from app.chain.client import ChainClient
from app.chain.indexer import reconcile_order
from app.core.config import settings
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.rate_limit import limiter
from app.modules.agents.models import Agent
from app.modules.orders import events as dispute_events
from app.modules.orders import service
from app.modules.orders.schemas import (
    ChainStatus,
    ChainTransactionSummary,
    DeliverRequest,
    DisputeDecisionRequest,
    DisputeRequest,
    DisputeStatementRequest,
    DisputeView,
    EscrowSummary,
    OrderCreate,
    OrderDetail,
    OrderSummary,
    PaymentInstructions,
    ReconciliationReport,
    SettlementInstructions,
)
from app.modules.organizations.authz import OrgAction, require_permission

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
    """Confirm the caller may act as the provider for this order.

    The provider is the organization that owns the agent; any member with the
    order-acting role may perform provider actions on its behalf.
    """
    from sqlalchemy import select

    agent = (
        await db.execute(select(Agent).where(Agent.id == order.provider_agent_id))
    ).scalar_one_or_none()
    if agent is None:
        raise PermissionDeniedError("Only the provider can do this.")
    await require_permission(
        db, org_id=agent.org_id, user_id=user.id, action=OrgAction.ACT_ON_ORDERS
    )
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
        token_symbol="USDC",  # noqa: S106, a token ticker, not a credential
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
    dependencies=[Depends(limiter("orders:create"))],
)
async def create_order(
    payload: OrderCreate, principal: OrdersWrite, db: DbSession
) -> OrderDetail:
    """Creates an unfunded order with prices frozen as they stand now."""
    user = principal.user
    order = await service.create_order(db, buyer=user, payload=payload)
    return _to_detail(order)


@router.get(
    "/orders", response_model=list[OrderSummary], summary="Orders you placed"
)
async def my_orders(principal: OrdersRead, db: DbSession) -> list[OrderSummary]:
    orders = await service.list_for_buyer(db, user=principal.user)
    return [OrderSummary.model_validate(o) for o in orders]


@router.get(
    "/orders/received",
    response_model=list[OrderSummary],
    summary="Orders placed with your agents",
)
async def received_orders(
    principal: OrdersRead, db: DbSession
) -> list[OrderSummary]:
    orders = await service.list_for_provider(db, user=principal.user)
    return [OrderSummary.model_validate(o) for o in orders]


@router.get("/orders/{order_id}", response_model=OrderDetail, summary="An order")
async def get_order(
    order_id: uuid.UUID, principal: OrdersRead, db: DbSession
) -> OrderDetail:
    order = await service.require_visible_order(db, order_id, user=principal.user)
    return _to_detail(order)


@router.get(
    "/orders/{order_id}/payment-instructions",
    response_model=PaymentInstructions,
    summary="How to fund this order from your own wallet",
)
async def payment_instructions(
    order_id: uuid.UUID, principal: OrdersRead, db: DbSession
) -> PaymentInstructions:
    """Describes the approve + createEscrow calls the buyer's wallet must make.

    The platform neither signs nor broadcasts; it only says what to send.
    """
    user = principal.user
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
    order_id: uuid.UUID, principal: OrdersWrite, db: DbSession
) -> OrderDetail:
    user = principal.user
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
    principal: OrdersWrite,
    db: DbSession,
) -> OrderDetail:
    """Starts the acceptance window. Moves no money, release happens on-chain,
    either when the buyer accepts or when the auto-release deadline passes."""
    user = principal.user
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
    dependencies=[Depends(limiter("orders:dispute_intent"))],
)
async def dispute_intent(
    order_id: uuid.UUID,
    payload: DisputeRequest,
    principal: OrdersWrite,
    db: DbSession,
) -> OrderDetail:
    """Records the reason and alerts support.

    The authoritative dispute is raised on-chain by the party's own wallet; the
    order only becomes disputed when the chain says so.
    """
    user = principal.user
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
    order_id: uuid.UUID, principal: OrdersRead, db: DbSession
) -> ReconciliationReport:
    """Reads the contract's own view and reports any divergence.

    Exists so a disagreement between the database and the chain is discoverable
    rather than silent. The chain is authoritative.
    """
    user = principal.user
    order = await service.require_visible_order(db, order_id, user=user)
    async with ChainClient() as client:
        report = await reconcile_order(db, client, order)
    return ReconciliationReport(**report)


async def _dispute_context(db, order_id, user):
    """The order, its escrow, and whether this caller may see the dispute.

    Visible to the two parties and to the arbiter. `require_visible_order` already
    refuses anybody else, so arbiter access is added rather than party access
    being re-derived.
    """
    if service.is_arbiter(user):
        order = await service.get_order(db, order_id)
        if order is None:
            raise NotFoundError("No such order.")
    else:
        order = await service.require_visible_order(db, order_id, user=user)
    return order, order.escrow


@router.get(
    "/orders/{order_id}/dispute",
    response_model=DisputeView,
    summary="The dispute on this order",
)
async def get_dispute(
    order_id: uuid.UUID, principal: OrdersRead, db: DbSession
) -> DisputeView:
    """Both parties and the arbiter see the same thing, including each other's
    statements and, once decided, the reasoning. A decision made on evidence one
    side never saw is not defensible."""
    user = principal.user
    order, escrow = await _dispute_context(db, order_id, user)
    return await service.build_dispute_view(db, order=order, escrow=escrow)


@router.post(
    "/orders/{order_id}/dispute-statements",
    response_model=DisputeView,
    status_code=status.HTTP_201_CREATED,
    summary="State your case",
    dependencies=[Depends(limiter("orders:dispute_statement"))],
)
async def submit_dispute_statement(
    order_id: uuid.UUID,
    payload: DisputeStatementRequest,
    principal: OrdersWrite,
    db: DbSession,
) -> DisputeView:
    """Only the two parties. The arbiter reads; it does not testify."""
    user = principal.user
    order = await service.require_visible_order(db, order_id, user=user)
    await service.submit_dispute_statement(
        db, order=order, actor=user, text=payload.text, escrow=order.escrow
    )
    return await service.build_dispute_view(db, order=order, escrow=order.escrow)


@router.post(
    "/orders/{order_id}/dispute-decision",
    response_model=SettlementInstructions,
    summary="Decide a dispute, and get what to send",
)
async def decide_dispute(
    order_id: uuid.UUID,
    payload: DisputeDecisionRequest,
    principal: OrdersWrite,
    db: DbSession,
) -> SettlementInstructions:
    """Records the decision and returns the call to make.

    It does not settle. The platform holds no keys, so the arbiter's own wallet
    sends the transaction and the indexer confirms the result. Recording first is
    what lets an unexpected settlement be noticed at all.
    """
    user = principal.user
    if not service.is_arbiter(user):
        raise PermissionDeniedError(
            "Only the arbiter can decide a dispute.", code="not_arbiter"
        )
    order = await service.get_order(db, order_id)
    if order is None:
        raise NotFoundError("No such order.")

    await service.record_dispute_decision(
        db,
        order=order,
        escrow=order.escrow,
        arbiter=user,
        provider_amount=payload.provider_amount,
        reasoning=payload.reasoning,
    )
    await dispute_events.dispute_decided(db, order=order, escrow=order.escrow)
    return service.build_settlement_instructions(order=order, escrow=order.escrow)
