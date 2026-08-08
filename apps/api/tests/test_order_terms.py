"""The commercial terms an order is placed under, and who may move them.

An order froze its price from the start. It did not freeze the two windows that
decide *when* money moves, and those were read from the live service every time
payment instructions were built. So the provider, who is one of the two parties,
could edit the service afterwards and move the other party's deadlines.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.modules.orders.service import DEFAULT_DELIVERY_WINDOW, resolve_windows


@dataclass
class FakeOrder:
    delivery_time_hours: int | None
    auto_release_hours: int | None


@dataclass
class FakeService:
    delivery_time_hours: int | None
    auto_release_hours: int


class TestFrozenTerms:
    def test_a_later_service_edit_cannot_move_an_existing_order(self) -> None:
        """The property this exists to enforce."""
        order = FakeOrder(delivery_time_hours=48, auto_release_hours=168)
        # The provider edits the service after the order was placed.
        service = FakeService(delivery_time_hours=2, auto_release_hours=1)

        delivery, auto_release = resolve_windows(order, service)

        assert delivery == timedelta(hours=48)
        assert auto_release == timedelta(hours=168)

    def test_shortening_auto_release_cannot_shrink_the_dispute_window(self) -> None:
        """The dangerous direction, called out on its own.

        Auto release is when escrow pays the provider without the buyer acting.
        Shortening it after the fact takes away time the buyer had to object.
        """
        order = FakeOrder(delivery_time_hours=24, auto_release_hours=336)
        service = FakeService(delivery_time_hours=24, auto_release_hours=1)

        _, auto_release = resolve_windows(order, service)

        assert auto_release == timedelta(hours=336), "the buyer keeps the window agreed"

    def test_orders_predating_the_columns_still_resolve(self) -> None:
        """Backfill covers these, but a null must not become a zero window."""
        order = FakeOrder(delivery_time_hours=None, auto_release_hours=None)
        service = FakeService(delivery_time_hours=72, auto_release_hours=96)

        delivery, auto_release = resolve_windows(order, service)

        assert delivery == timedelta(hours=72)
        assert auto_release == timedelta(hours=96)

    def test_a_service_with_no_delivery_time_falls_back_to_the_default(self) -> None:
        order = FakeOrder(delivery_time_hours=None, auto_release_hours=None)
        service = FakeService(delivery_time_hours=None, auto_release_hours=96)

        delivery, _ = resolve_windows(order, service)

        assert delivery == DEFAULT_DELIVERY_WINDOW
        assert delivery > timedelta(0), "a zero window would be instantly overdue"
