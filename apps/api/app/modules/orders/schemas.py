"""Request and response models for orders and payments."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import EscrowStatus, OrderStatus


class OrderCreate(BaseModel):
    service_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=10_000)
    requirements: str | None = Field(default=None, max_length=8_000)
    # Only meaningful for services priced by negotiation; ignored otherwise so a
    # buyer cannot name their own price on a fixed-price listing.
    negotiated_price: Decimal | None = Field(default=None, gt=0)


class EscrowSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: EscrowStatus
    chain_id: int
    contract_address: str | None
    onchain_escrow_id: str | None
    token_address: str
    token_symbol: str
    amount: Decimal
    released_amount: Decimal
    refunded_amount: Decimal
    fee_amount: Decimal
    buyer_address: str
    provider_address: str
    funded_at: datetime | None
    released_at: datetime | None
    refunded_at: datetime | None
    disputed_at: datetime | None


class ChainTransactionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tx_hash: str
    chain_id: int
    tx_type: str
    status: str
    amount: Decimal | None
    block_number: int | None
    confirmations: int
    confirmed_at: datetime | None
    explorer_url: str | None = None


class OrderSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    status: OrderStatus
    quantity: int
    unit_price: Decimal
    subtotal: Decimal
    platform_fee: Decimal
    total_amount: Decimal
    currency: str
    platform_fee_bps: int
    created_at: datetime
    funding_deadline: datetime | None
    funded_at: datetime | None
    delivered_at: datetime | None
    auto_release_at: datetime | None
    completed_at: datetime | None


class OrderDetail(OrderSummary):
    requirements: str | None
    delivery_note: str | None
    buyer_id: uuid.UUID
    provider_agent_id: uuid.UUID
    service_id: uuid.UUID
    escrow: EscrowSummary | None = None
    transactions: list[ChainTransactionSummary] = Field(default_factory=list)


class PaymentInstructions(BaseModel):
    """Everything a wallet needs to fund an order itself.

    The platform never holds funds and never signs. It describes the transaction;
    the buyer's own wallet builds, signs and broadcasts it.
    """

    order_id: uuid.UUID
    order_reference: str

    chain_id: int
    network_name: str
    escrow_contract: str
    token_address: str
    token_symbol: str
    token_decimals: int

    # The exact bytes32 the contract expects, derived from the order id.
    escrow_id: str
    provider_address: str

    # Human-readable and base-unit forms of the same figure. Both are returned so
    # a client never has to do the conversion and risk getting it wrong.
    amount: Decimal
    amount_base_units: str

    delivery_window_seconds: int
    auto_release_window_seconds: int

    # The two calls the buyer's wallet must make, in order.
    approve_selector: str
    create_escrow_selector: str

    funding_deadline: datetime | None
    explorer_url: str


class DeliverRequest(BaseModel):
    delivery_note: str | None = Field(default=None, max_length=8_000)
    output_payload: dict | None = None


class DisputeRequest(BaseModel):
    reason: str = Field(min_length=10, max_length=2_000)


class ChainStatus(BaseModel):
    """What the platform can actually do on-chain right now.

    Reported plainly so a client never presents a payment flow that cannot
    complete because no contract is configured.
    """

    chain_id: int
    network_name: str
    escrow_configured: bool
    escrow_contract: str | None
    token_address: str
    token_symbol: str
    confirmations_required: int
    explorer_url: str
    rpc_reachable: bool
    head_block: int | None = None
    note: str | None = None


class ReconciliationReport(BaseModel):
    """Comparison of the database against the chain's own view of an escrow."""

    order_id: str
    escrow_id: str
    exists_on_chain: bool
    chain_status: str
    chain_amount: str
    chain_released: str
    chain_refunded: str
    in_sync: bool
    divergences: list[str]
