"""The parts of analytics that are easy to get quietly wrong.

Not the totals, which are a sum and hard to misread, but the derived figures: a
percentage against nothing, and the boundary between money earned and money
merely committed.
"""
from __future__ import annotations

from decimal import Decimal

from app.db.enums import OrderStatus
from app.modules.analytics.service import ACTIVE_STATUSES, _change_pct


class TestChangeAgainstNothing:
    """Growth from zero has no percentage.

    Reporting one anyway, as an infinity or a flat hundred, reads as a real
    measurement and is not one.
    """

    def test_a_previous_period_of_zero_reports_no_percentage(self) -> None:
        assert _change_pct(10, 0) is None
        assert _change_pct(Decimal("500"), Decimal("0")) is None

    def test_no_change_reports_zero_rather_than_nothing(self) -> None:
        """Flat is a real answer and must be distinguishable from unknown."""
        assert _change_pct(10, 10) == 0.0

    def test_growth_and_decline_are_signed(self) -> None:
        assert _change_pct(150, 100) == 50.0
        assert _change_pct(50, 100) == -50.0

    def test_decimal_and_int_mix_without_error(self) -> None:
        """Revenue is Decimal and purchases are int; both go through here."""
        assert _change_pct(Decimal("150.50"), 100) == 50.5


class TestEarnedVersusCommitted:
    def test_active_statuses_exclude_everything_terminal(self) -> None:
        """Escrow funded but not released is not revenue.

        Counting it as earnings would tell a provider they have money they cannot
        spend, and would double count it once the order completes.
        """
        assert OrderStatus.COMPLETED not in ACTIVE_STATUSES
        assert OrderStatus.REFUNDED not in ACTIVE_STATUSES
        assert OrderStatus.CANCELLED not in ACTIVE_STATUSES
        assert OrderStatus.EXPIRED not in ACTIVE_STATUSES

    def test_disputed_is_not_active(self) -> None:
        """It is reported on its own, because it is the number to act on today."""
        assert OrderStatus.DISPUTED not in ACTIVE_STATUSES

    def test_unfunded_orders_are_not_counted_as_committed(self) -> None:
        """Nothing is committed until escrow is actually funded on chain."""
        assert OrderStatus.PENDING_PAYMENT not in ACTIVE_STATUSES

    def test_the_states_between_funding_and_settlement_are_active(self) -> None:
        for status in (
            OrderStatus.FUNDED,
            OrderStatus.IN_PROGRESS,
            OrderStatus.DELIVERED,
        ):
            assert status in ACTIVE_STATUSES
