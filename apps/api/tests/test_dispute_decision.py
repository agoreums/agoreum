"""Deciding a disputed order.

The rules here divide money between two people who disagree, so they are asserted
rather than described. Most of these are about what the arbiter is not allowed to
do.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from app.core.config import settings
from app.core.errors import ConflictError, PermissionDeniedError
from app.db.enums import DisputeResolution, OrderStatus
from app.modules.orders import service

pytestmark = pytest.mark.asyncio

ARBITER = "0x00000000000000000000000000000000000ab1e5"


@dataclass
class FakeAgent:
    org_id: uuid.UUID | None = None


@dataclass
class FakeOrder:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    buyer_id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: OrderStatus = OrderStatus.DISPUTED
    total_amount: Decimal = Decimal("100")
    provider_agent: FakeAgent | None = field(default_factory=FakeAgent)
    dispute_resolved_at: object = None
    dispute_provider_amount: Decimal | None = None
    dispute_reasoning: str | None = None
    dispute_resolution: DisputeResolution | None = None
    dispute_resolved_by: uuid.UUID | None = None


@dataclass
class FakeUser:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    primary_address: str = ARBITER


class FakeSession:
    """Enough of a session to record without a database."""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


class TestWhoMayArbitrate:
    def test_the_arbiter_is_the_address_the_contract_accepts(self, monkeypatch) -> None:
        """Not a flag on a user.

        A separate flag could authorise somebody the chain would then refuse,
        which is worse than having no arbiter at all.
        """
        monkeypatch.setattr(settings, "ESCROW_ARBITER_ADDRESS", ARBITER)
        assert service.is_arbiter(FakeUser()) is True

    def test_a_different_address_is_not_an_arbiter(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ESCROW_ARBITER_ADDRESS", ARBITER)
        assert service.is_arbiter(FakeUser(primary_address="0xdead")) is False

    def test_case_does_not_decide_authority(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ESCROW_ARBITER_ADDRESS", ARBITER.upper())
        assert service.is_arbiter(FakeUser(primary_address=ARBITER)) is True

    def test_nobody_arbitrates_when_unconfigured(self, monkeypatch) -> None:
        """Fails closed. An unset address must not mean everybody."""
        monkeypatch.setattr(settings, "ESCROW_ARBITER_ADDRESS", None)
        assert service.is_arbiter(FakeUser()) is False
        monkeypatch.setattr(settings, "ESCROW_ARBITER_ADDRESS", "")
        assert service.is_arbiter(FakeUser(primary_address="")) is False


class TestTheSplit:
    async def test_the_whole_amount_to_the_provider_is_a_release(self) -> None:
        order, db = FakeOrder(), FakeSession()
        await service.record_dispute_decision(
            db, order=order, arbiter=FakeUser(),
            provider_amount=Decimal("100"), reasoning="delivered as agreed",
        )
        assert order.dispute_resolution == DisputeResolution.RELEASED_TO_PROVIDER

    async def test_nothing_to_the_provider_is_a_refund(self) -> None:
        order, db = FakeOrder(), FakeSession()
        await service.record_dispute_decision(
            db, order=order, arbiter=FakeUser(),
            provider_amount=Decimal("0"), reasoning="never delivered",
        )
        assert order.dispute_resolution == DisputeResolution.REFUNDED_TO_BUYER

    async def test_anything_between_is_a_split(self) -> None:
        order, db = FakeOrder(), FakeSession()
        await service.record_dispute_decision(
            db, order=order, arbiter=FakeUser(),
            provider_amount=Decimal("60"), reasoning="partial delivery",
        )
        assert order.dispute_resolution == DisputeResolution.SPLIT
        assert order.dispute_provider_amount == Decimal("60")

    async def test_more_than_the_escrow_is_refused(self) -> None:
        """The contract would revert; refusing here says why."""
        order, db = FakeOrder(), FakeSession()
        with pytest.raises(ConflictError):
            await service.record_dispute_decision(
                db, order=order, arbiter=FakeUser(),
                provider_amount=Decimal("101"), reasoning="x",
            )

    async def test_a_negative_share_is_refused(self) -> None:
        order, db = FakeOrder(), FakeSession()
        with pytest.raises(ConflictError):
            await service.record_dispute_decision(
                db, order=order, arbiter=FakeUser(),
                provider_amount=Decimal("-1"), reasoning="x",
            )

    async def test_only_the_provider_share_is_stored(self) -> None:
        """The buyer's is derived, because the contract derives it too.

        Storing both would create two sources of truth for one decision, and the
        chain ignores one of them.
        """
        order, db = FakeOrder(), FakeSession()
        await service.record_dispute_decision(
            db, order=order, arbiter=FakeUser(),
            provider_amount=Decimal("40"), reasoning="x",
        )
        assert not hasattr(order, "dispute_buyer_amount")
        assert order.dispute_provider_amount == Decimal("40")


class TestWhatAnArbiterCannotDo:
    async def test_an_arbiter_cannot_decide_their_own_case(self) -> None:
        """Refused by the system rather than left to their judgement."""
        arbiter = FakeUser()
        order = FakeOrder(buyer_id=arbiter.id)
        with pytest.raises(PermissionDeniedError):
            await service.record_dispute_decision(
                FakeSession(), order=order, arbiter=arbiter,
                provider_amount=Decimal("50"), reasoning="x",
            )

    async def test_an_order_not_in_dispute_cannot_be_decided(self) -> None:
        order = FakeOrder(status=OrderStatus.FUNDED)
        with pytest.raises(ConflictError):
            await service.record_dispute_decision(
                FakeSession(), order=order, arbiter=FakeUser(),
                provider_amount=Decimal("50"), reasoning="x",
            )

    async def test_a_decided_dispute_cannot_be_decided_again(self) -> None:
        """Settlement is final on chain, so a second decision is meaningless."""
        from datetime import UTC, datetime

        order = FakeOrder(dispute_resolved_at=datetime.now(UTC))
        with pytest.raises(ConflictError):
            await service.record_dispute_decision(
                FakeSession(), order=order, arbiter=FakeUser(),
                provider_amount=Decimal("50"), reasoning="x",
            )


class TestStatements:
    async def test_a_statement_needs_an_order_in_dispute(self) -> None:
        order = FakeOrder(status=OrderStatus.IN_PROGRESS)
        with pytest.raises(ConflictError):
            await service.submit_dispute_statement(
                FakeSession(), order=order, actor=FakeUser(), text="hello"
            )

    async def test_statements_close_once_it_is_decided(self) -> None:
        from datetime import UTC, datetime

        order = FakeOrder(dispute_resolved_at=datetime.now(UTC))
        with pytest.raises(ConflictError):
            await service.submit_dispute_statement(
                FakeSession(), order=order, actor=FakeUser(), text="hello"
            )

    async def test_a_statement_joins_the_order_timeline(self) -> None:
        """Not a separate store, which would be a second version of events."""
        db = FakeSession()
        await service.submit_dispute_statement(
            db, order=FakeOrder(), actor=FakeUser(), text="it never arrived"
        )
        assert len(db.added) == 1
        assert db.added[0].event_type == "order.dispute_statement"
        assert db.added[0].detail["text"] == "it never arrived"
