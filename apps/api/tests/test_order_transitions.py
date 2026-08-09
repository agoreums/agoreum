"""What each order transition refuses.

The permissive half of a state machine gets exercised by ordinary use. The
refusals do not, so they are the half worth asserting: a guard that has quietly
stopped guarding looks exactly like one that works until somebody starts work on
an unfunded order or delivers one that was already refunded.

Written against the guards rather than through the database, so every status is
covered rather than only the ones a fixture happens to reach.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.core.errors import ConflictError
from app.db.enums import OrderStatus
from app.modules.orders import service

pytestmark = pytest.mark.asyncio

TERMINAL = (
    OrderStatus.COMPLETED,
    OrderStatus.CANCELLED,
    OrderStatus.REFUNDED,
    OrderStatus.EXPIRED,
)


@dataclass
class FakeOrder:
    id: object = None
    status: OrderStatus = OrderStatus.FUNDED
    total_amount: Decimal = Decimal("100")
    delivered_at: object = None
    started_at: object = None
    buyer_id: object = None
    provider_agent: object = None
    service_id: object = None
    delivery_note: object = None
    output_payload: object = None
    auto_release_at: object = None
    # Frozen at purchase. Delivering must use this rather than whatever the
    # service says now.
    auto_release_hours: int | None = 168
    funding_deadline: object = None


@dataclass
class FakeUser:
    id: object = None
    primary_address: str = "0xabc"


class FakeSession:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def execute(self, *a, **k):  # pragma: no cover - only reached on the
        # legacy path, where an order predates the frozen column.
        raise AssertionError(
            "delivering must not read the live service when the order has its "
            "own frozen window"
        )

    async def refresh(self, obj) -> None:
        """A no-op. Refresh reloads from the database; there is no database here,
        and the object under test already holds the values just written."""
        return None


class TestStartingWork:
    async def test_only_a_funded_order_can_be_started(self) -> None:
        await service.start_work(
            FakeSession(), order=FakeOrder(status=OrderStatus.FUNDED), actor=FakeUser()
        )

    @pytest.mark.parametrize(
        "status",
        [
            OrderStatus.PENDING_PAYMENT,
            OrderStatus.IN_PROGRESS,
            OrderStatus.DELIVERED,
            OrderStatus.DISPUTED,
            *TERMINAL,
        ],
    )
    async def test_anything_else_is_refused(self, status: OrderStatus) -> None:
        """Starting an unfunded order is the one that costs money: it tells a
        provider to begin work nobody has paid for."""
        with pytest.raises(ConflictError):
            await service.start_work(
                FakeSession(), order=FakeOrder(status=status), actor=FakeUser()
            )


class TestDelivering:
    @pytest.mark.parametrize(
        "status", [OrderStatus.FUNDED, OrderStatus.IN_PROGRESS]
    )
    async def test_a_funded_or_started_order_can_be_delivered(
        self, status: OrderStatus
    ) -> None:
        """Delivering straight from funded is allowed on purpose: a provider who
        finishes before marking a start should not be blocked by bookkeeping."""
        await service.mark_delivered(
            FakeSession(),
            order=FakeOrder(status=status),
            actor=FakeUser(),
            note=None,
            payload=None,
        )

    @pytest.mark.parametrize(
        "status",
        [OrderStatus.PENDING_PAYMENT, OrderStatus.DELIVERED, OrderStatus.DISPUTED, *TERMINAL],
    )
    async def test_anything_else_is_refused(self, status: OrderStatus) -> None:
        """Delivering a refunded or disputed order would start an acceptance
        window on money that has already moved or is already contested."""
        with pytest.raises(ConflictError):
            await service.mark_delivered(
                FakeSession(),
                order=FakeOrder(status=status),
                actor=FakeUser(),
                note=None,
                payload=None,
            )


class TestDisputing:
    @pytest.mark.parametrize(
        "status",
        [OrderStatus.FUNDED, OrderStatus.IN_PROGRESS, OrderStatus.DELIVERED],
    )
    async def test_a_live_order_can_be_disputed(self, status: OrderStatus) -> None:
        await service.record_dispute_intent(
            FakeSession(),
            order=FakeOrder(status=status),
            actor=FakeUser(),
            reason="it never arrived",
        )

    @pytest.mark.parametrize(
        "status", [OrderStatus.PENDING_PAYMENT, OrderStatus.DISPUTED, *TERMINAL]
    )
    async def test_anything_else_is_refused(self, status: OrderStatus) -> None:
        """Nothing is at stake before funding, and a settled order cannot be
        reopened, since the chain has already paid somebody."""
        with pytest.raises(ConflictError):
            await service.record_dispute_intent(
                FakeSession(),
                order=FakeOrder(status=status),
                actor=FakeUser(),
                reason="x",
            )


class TestTerminalStatesStayTerminal:
    @pytest.mark.parametrize("status", TERMINAL)
    async def test_no_transition_reopens_a_finished_order(
        self, status: OrderStatus
    ) -> None:
        """The property that matters most, asserted across every entry point at
        once. Money has already moved, or was never taken; either way there is
        nothing left to decide."""
        order = FakeOrder(status=status)
        for call in (
            lambda: service.start_work(FakeSession(), order=order, actor=FakeUser()),
            lambda: service.mark_delivered(
                FakeSession(), order=order, actor=FakeUser(), note=None, payload=None
            ),
            lambda: service.record_dispute_intent(
                FakeSession(), order=order, actor=FakeUser(), reason="x"
            ),
        ):
            with pytest.raises(ConflictError):
                await call()


class TestTheAutoReleaseDeadlineIsFrozen:
    """When escrow pays the provider without the buyer acting.

    The provider controls the service and chooses when to deliver, so reading the
    service's current window at delivery let them shorten the buyer's window to
    dispute after the order was placed.
    """

    async def test_delivery_uses_the_order_s_own_window(self) -> None:
        from datetime import UTC, datetime

        order = FakeOrder(status=OrderStatus.FUNDED, auto_release_hours=168)
        before = datetime.now(UTC)
        # FakeSession.execute raises, so touching the live service fails loudly
        # rather than passing quietly with the wrong number.
        await service.mark_delivered(
            FakeSession(), order=order, actor=FakeUser(), note=None, payload=None
        )
        # Measured from a moment just before the call, so the delta is a shade
        # over the window rather than under it.
        hours = (order.auto_release_at - before).total_seconds() / 3600
        assert 168 <= hours < 168.01

    async def test_a_shortened_service_cannot_shrink_an_existing_order(self) -> None:
        """The attack this prevents, stated as a test."""
        from datetime import UTC, datetime

        order = FakeOrder(status=OrderStatus.FUNDED, auto_release_hours=336)
        before = datetime.now(UTC)
        await service.mark_delivered(
            FakeSession(), order=order, actor=FakeUser(), note=None, payload=None
        )
        hours = (order.auto_release_at - before).total_seconds() / 3600
        assert hours > 300, "the buyer keeps the window agreed at purchase"


class TestTheFundingWindowIsEnforced:
    """The deadline bounds the price freeze, so it has to actually bind.

    An order fixes its price when it is placed. The funding deadline is what
    stops that fixed price being fundable forever, which would let a buyer hold
    an order open, wait for the provider to raise their price, and still pay the
    old one. The deadline was returned in the payment instructions and shown to
    buyers while nothing enforced it.
    """

    async def test_instructions_are_refused_once_the_window_has_closed(self) -> None:
        from datetime import UTC, datetime, timedelta

        order = FakeOrder(
            status=OrderStatus.PENDING_PAYMENT,
            funding_deadline=datetime.now(UTC) - timedelta(seconds=1),
        )
        with pytest.raises(ConflictError) as exc:
            await service.payment_instructions(FakeSession(), order=order)
        assert exc.value.code == "order_funding_window_closed"

    @staticmethod
    async def _blocked_by_the_deadline(order) -> bool:
        """Whether the deadline check is what stopped this call.

        Everything after that check needs a real database, so the call fails
        either way. What matters is which guard fired, not that one did.
        """
        try:
            await service.payment_instructions(FakeSession(), order=order)
        except ConflictError as exc:
            return exc.code == "order_funding_window_closed"
        except Exception:
            return False
        return False

    async def test_instructions_are_issued_while_the_window_is_open(self) -> None:
        from datetime import UTC, datetime, timedelta

        order = FakeOrder(
            status=OrderStatus.PENDING_PAYMENT,
            funding_deadline=datetime.now(UTC) + timedelta(hours=1),
        )
        assert not await self._blocked_by_the_deadline(order), (
            "an open funding window was treated as closed"
        )

    async def test_an_order_with_no_deadline_is_not_blocked(self) -> None:
        """Older rows predate the column and must not become unfundable."""
        order = FakeOrder(status=OrderStatus.PENDING_PAYMENT, funding_deadline=None)
        assert not await self._blocked_by_the_deadline(order)


class TestTheExpirySweepWaitsOutTheConfirmationWindow:
    """The sweep must not race a payment that already happened.

    A buyer can fund seconds before the deadline, and that payment is invisible
    until the indexer has seen it past the confirmation frontier. Expiring on
    the deadline itself would tell a buyer who paid that their order expired.
    """

    async def test_the_cutoff_is_the_deadline_plus_the_grace_period(self) -> None:
        from datetime import UTC, datetime

        captured: list = []

        class CapturingResult:
            def scalars(self):
                return self

            def all(self):
                return []

        class CapturingSession(FakeSession):
            async def execute(self, statement, *a, **k):
                captured.append(statement)
                return CapturingResult()

        before = datetime.now(UTC)
        count = await service.expire_unfunded_orders(CapturingSession())
        assert count == 0

        # The bound datetime in the query is what decides which orders are
        # expired, so that is the thing worth asserting rather than the code
        # that computes it.
        params = captured[0].compile().params
        cutoffs = [v for v in params.values() if isinstance(v, datetime)]
        assert cutoffs, "the sweep issued no time-bounded query"
        lag = (before - cutoffs[0]).total_seconds()
        expected = service.EXPIRY_GRACE.total_seconds()
        assert expected - 5 <= lag <= expected + 5, (
            f"sweep cutoff was {lag}s back, expected about {expected}s "
            "(a smaller value races payments still confirming)"
        )

    async def test_the_grace_period_is_longer_than_the_confirmation_depth(self) -> None:
        """A grace shorter than confirmation would not remove the race at all."""
        from app.core.config import settings

        # Base produces a block roughly every two seconds.
        confirmation_seconds = settings.CHAIN_CONFIRMATIONS * 2
        assert service.EXPIRY_GRACE.total_seconds() > confirmation_seconds * 10, (
            "the grace period leaves no margin over the confirmation window"
        )
