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


@dataclass
class FakeEscrow:
    """The decision lives here, beside the fields that were already here.

    Its `amount` is what settleDispute divides, which is why the split is bounded
    by it rather than by the order total.
    """

    amount: Decimal = Decimal("100")
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
        order, escrow, db = FakeOrder(), FakeEscrow(), FakeSession()
        await service.record_dispute_decision(
            db, order=order, escrow=escrow, arbiter=FakeUser(),
            provider_amount=Decimal("100"), reasoning="delivered as agreed",
        )
        assert escrow.dispute_resolution == DisputeResolution.RELEASED_TO_PROVIDER

    async def test_nothing_to_the_provider_is_a_refund(self) -> None:
        order, escrow, db = FakeOrder(), FakeEscrow(), FakeSession()
        await service.record_dispute_decision(
            db, order=order, escrow=escrow, arbiter=FakeUser(),
            provider_amount=Decimal("0"), reasoning="never delivered",
        )
        assert escrow.dispute_resolution == DisputeResolution.REFUNDED_TO_BUYER

    async def test_anything_between_is_a_split(self) -> None:
        order, escrow, db = FakeOrder(), FakeEscrow(), FakeSession()
        await service.record_dispute_decision(
            db, order=order, escrow=escrow, arbiter=FakeUser(),
            provider_amount=Decimal("60"), reasoning="partial delivery",
        )
        assert escrow.dispute_resolution == DisputeResolution.SPLIT
        assert escrow.dispute_provider_amount == Decimal("60")

    async def test_more_than_the_escrow_is_refused(self) -> None:
        """The contract would revert; refusing here says why."""
        order, escrow, db = FakeOrder(), FakeEscrow(), FakeSession()
        with pytest.raises(ConflictError):
            await service.record_dispute_decision(
                db, order=order, escrow=escrow, arbiter=FakeUser(),
                provider_amount=Decimal("101"), reasoning="x",
            )

    async def test_a_negative_share_is_refused(self) -> None:
        order, escrow, db = FakeOrder(), FakeEscrow(), FakeSession()
        with pytest.raises(ConflictError):
            await service.record_dispute_decision(
                db, order=order, escrow=escrow, arbiter=FakeUser(),
                provider_amount=Decimal("-1"), reasoning="x",
            )

    async def test_only_the_provider_share_is_stored(self) -> None:
        """The buyer's is derived, because the contract derives it too.

        Storing both would create two sources of truth for one decision, and the
        chain ignores one of them.
        """
        order, escrow, db = FakeOrder(), FakeEscrow(), FakeSession()
        await service.record_dispute_decision(
            db, order=order, escrow=escrow, arbiter=FakeUser(),
            provider_amount=Decimal("40"), reasoning="x",
        )
        assert not hasattr(escrow, "dispute_buyer_amount")
        assert escrow.dispute_provider_amount == Decimal("40")


class TestWhatAnArbiterCannotDo:
    async def test_an_arbiter_cannot_decide_their_own_case(self) -> None:
        """Refused by the system rather than left to their judgement."""
        arbiter = FakeUser()
        order = FakeOrder(buyer_id=arbiter.id)
        with pytest.raises(PermissionDeniedError):
            await service.record_dispute_decision(
                FakeSession(), order=order, escrow=FakeEscrow(), arbiter=arbiter,
                provider_amount=Decimal("50"), reasoning="x",
            )

    async def test_an_order_not_in_dispute_cannot_be_decided(self) -> None:
        order = FakeOrder(status=OrderStatus.FUNDED)
        with pytest.raises(ConflictError):
            await service.record_dispute_decision(
                FakeSession(), order=order, escrow=FakeEscrow(), arbiter=FakeUser(),
                provider_amount=Decimal("50"), reasoning="x",
            )

    async def test_a_decided_dispute_cannot_be_decided_again(self) -> None:
        """Settlement is final on chain, so a second decision is meaningless."""
        from datetime import UTC, datetime

        escrow = FakeEscrow(dispute_resolved_at=datetime.now(UTC))
        with pytest.raises(ConflictError):
            await service.record_dispute_decision(
                FakeSession(), order=FakeOrder(), escrow=escrow, arbiter=FakeUser(),
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

        escrow = FakeEscrow(dispute_resolved_at=datetime.now(UTC))
        with pytest.raises(ConflictError):
            await service.submit_dispute_statement(
                FakeSession(), order=FakeOrder(), actor=FakeUser(),
                text="hello", escrow=escrow,
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


class TestAnArbiterCannotDecideTheirOwnCase:
    """The guard that decides who may divide contested money.

    Found by using the product rather than reading it: the dispute rehearsal on
    2026-08-21 used one wallet as both buyer and arbiter, and the platform
    correctly refused with `arbiter_is_party`.

    It was reported at the time as having no test, which was wrong.
    `test_an_arbiter_cannot_decide_their_own_case` above has covered the buyer
    case since it was written; the search that missed it looked for the error
    code string, which that test never uses. A grep for a name is not a search
    for a behaviour, which is the same mistake in miniature as everything else
    this sweep keeps finding.

    What was genuinely missing is the other half, and writing it exposed that
    the other half could never fire. `_dispute_parties`
    returns the buyer's **user** id together with the provider agent's
    **organization** id, and the caller compares the arbiter's user id against
    that set. A user id and an organization id are separate identifiers from
    separate tables, so the provider half can never match, whatever the
    relationship actually is.

    The buyer half works, which is why the rehearsal hit it. The provider half
    is the more dangerous one to lose: an arbiter who owns the agent being
    disputed decides how much to pay themselves.
    """

    async def test_the_buyer_cannot_arbitrate_their_own_dispute(self) -> None:
        buyer = FakeUser()
        order = FakeOrder(buyer_id=buyer.id)
        with pytest.raises(PermissionDeniedError) as caught:
            await service.record_dispute_decision(
                FakeSession(), order=order, escrow=FakeEscrow(), arbiter=buyer,
                provider_amount=Decimal("50"), reasoning="deciding my own case",
            )
        assert caught.value.code == "arbiter_is_party"

    async def test_an_unrelated_arbiter_may_decide(self) -> None:
        """The control. A guard that refused everybody would pass the test above."""
        escrow = await service.record_dispute_decision(
            FakeSession(), order=FakeOrder(), escrow=FakeEscrow(), arbiter=FakeUser(),
            provider_amount=Decimal("50"), reasoning="an unrelated arbiter deciding",
        )
        assert escrow.dispute_provider_amount == Decimal("50")

    async def test_the_provider_side_is_decided_by_membership(
        self, monkeypatch
    ) -> None:
        """The half that could never fire, with a realistic organization id.

        The first version of this test set the agent's org_id to the arbiter's
        own user id, which made the old comparison match and the test pass. That
        state cannot occur: the ids come from different tables. Written with a
        distinct organization id, as reality has it, the old guard allowed the
        decision and this now asks the question that actually decides it.

        The conflict is the clearest one available. The arbiter belongs to the
        organization behind the provider agent, so a decision in the provider's
        favour pays their own side.
        """
        owner = FakeUser()
        org_id = uuid.uuid4()
        assert org_id != owner.id, "the point is that these are different ids"
        order = FakeOrder(provider_agent=FakeAgent(org_id=org_id))

        async def member_of_that_org(db, *, org_id: uuid.UUID, user_id: uuid.UUID):
            return org_id == order.provider_agent.org_id and user_id == owner.id

        monkeypatch.setattr(service, "is_member", member_of_that_org)

        with pytest.raises(PermissionDeniedError) as caught:
            await service.record_dispute_decision(
                FakeSession(), order=order, escrow=FakeEscrow(), arbiter=owner,
                provider_amount=Decimal("100"),
                reasoning="awarding the whole escrow to my own side",
            )
        assert caught.value.code == "arbiter_is_party"

    async def test_an_outsider_is_still_allowed_when_membership_is_checked(
        self, monkeypatch
    ) -> None:
        """The control for the membership lookup itself.

        Without this, a guard that treated everybody as a member would pass the
        test above and refuse every arbiter on the platform.
        """
        async def never_a_member(db, *, org_id: uuid.UUID, user_id: uuid.UUID):
            return False

        monkeypatch.setattr(service, "is_member", never_a_member)
        escrow = await service.record_dispute_decision(
            FakeSession(), order=FakeOrder(), escrow=FakeEscrow(), arbiter=FakeUser(),
            provider_amount=Decimal("40"), reasoning="an unrelated arbiter deciding",
        )
        assert escrow.dispute_provider_amount == Decimal("40")
