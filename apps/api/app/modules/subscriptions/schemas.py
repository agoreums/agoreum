"""Request and response models for subscriptions."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import SubscriptionInterval


class PlanPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plan_id: int
    name: str
    description: str | None
    tier: str
    interval: SubscriptionInterval
    token_symbol: str
    price: Decimal
    period_seconds: int
    active: bool


class PlanCreate(BaseModel):
    plan_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=400)
    tier: str = Field(min_length=1, max_length=40)
    interval: SubscriptionInterval
    token_address: str = Field(min_length=42, max_length=42)
    token_symbol: str = Field(default="USDC", max_length=12)
    token_decimals: int = Field(default=6, ge=0, le=36)
    price: Decimal = Field(gt=0)
    period_seconds: int = Field(ge=86_400, le=63_072_000)  # 1 day .. 2 years


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=400)
    price: Decimal | None = Field(default=None, gt=0)
    period_seconds: int | None = Field(default=None, ge=86_400, le=63_072_000)
    active: bool | None = None


class SubscriptionPublic(BaseModel):
    plan_id: int
    tier: str
    status: str  # active | cancelled | expired
    subscriber_address: str
    current_period_start: datetime
    current_period_end: datetime
    auto_renew_cancelled: bool
    plan: PlanPublic | None = None


class PaymentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tx_hash: str
    plan_id: int
    amount: Decimal
    token_symbol: str
    period_start: datetime
    period_end: datetime
    block_number: int
    created_at: datetime


class SubscribeInstructions(BaseModel):
    """Exactly what a wallet must do to subscribe: approve, then subscribe.

    The platform never signs or broadcasts; it only says what to send. The
    frontend encodes the two calls from these values.
    """

    chain_id: int
    subscription_contract: str
    plan_id: int
    token_address: str
    token_symbol: str
    token_decimals: int
    price: Decimal
    price_base_units: str
    # What to pass as `subscribe(planId, maxPrice)`. Equals the price: the caller
    # agrees to exactly the current price and nothing more.
    max_price_base_units: str
    note: str
