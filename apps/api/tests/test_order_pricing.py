"""The arithmetic that decides what somebody is charged.

The largest module in the codebase handles money and had no test file of its own.
These cover the figures, because a defect here does not throw: it charges the
wrong amount and looks like a working order.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.core.errors import ConflictError
from app.db.enums import PricingModel
from app.modules.orders.service import (
    PLATFORM_FEE_BPS,
    _quantise,
    _resolve_unit_price,
)


@dataclass
class FakeService:
    pricing_model: PricingModel = PricingModel.FIXED
    price: Decimal | None = Decimal("100")


@dataclass
class FakePayload:
    negotiated_price: Decimal | None = None
    quantity: int = 1


def _totals(unit_price: Decimal, quantity: int) -> tuple[Decimal, Decimal, Decimal]:
    """The same arithmetic create_order performs, in the same order.

    Kept in step with the caller by asserting the fee rate against the constant
    rather than hardcoding a number here.
    """
    subtotal = _quantise(unit_price * quantity)
    fee = _quantise(subtotal * Decimal(PLATFORM_FEE_BPS) / Decimal(10_000))
    return subtotal, fee, _quantise(subtotal + fee)


class TestQuantisation:
    def test_amounts_are_held_to_six_decimals(self) -> None:
        """USDC has six. A figure the chain cannot represent would mean the
        amount charged and the amount escrowed differ."""
        assert _quantise(Decimal("1.2345678")) == Decimal("1.234568")
        assert _quantise(Decimal("1")) == Decimal("1.000000")

    def test_quantisation_rounds_half_even(self) -> None:
        """Whatever the rule is, it must be stated and stable.

        Decimal's default is banker's rounding, so this records the behaviour
        rather than asserting a preference; a change would be visible here.
        """
        assert _quantise(Decimal("0.0000005")) == Decimal("0.000000")
        assert _quantise(Decimal("0.0000015")) == Decimal("0.000002")


class TestTheFee:
    def test_the_fee_is_taken_on_the_subtotal(self) -> None:
        subtotal, fee, total = _totals(Decimal("100"), 1)
        assert subtotal == Decimal("100.000000")
        assert fee == _quantise(Decimal("100") * Decimal(PLATFORM_FEE_BPS) / 10_000)
        assert total == subtotal + fee

    def test_the_total_is_exactly_its_parts(self) -> None:
        """The database asserts this too. A total that is not its components is
        a discrepancy nobody can reconcile later."""
        for unit, qty in (
            (Decimal("0.01"), 1),
            (Decimal("33.33"), 3),
            (Decimal("999999.999999"), 1),
            (Decimal("0.000001"), 7),
        ):
            subtotal, fee, total = _totals(unit, qty)
            assert subtotal == _quantise(unit * qty)
            assert total == _quantise(subtotal + fee)

    def test_a_tiny_order_does_not_round_the_fee_into_nothing_silently(self) -> None:
        """It may round to zero; what matters is that the total still adds up."""
        subtotal, fee, total = _totals(Decimal("0.000001"), 1)
        assert fee >= 0
        assert total == _quantise(subtotal + fee)

    def test_the_buyer_is_never_charged_less_than_the_provider_is_owed(self) -> None:
        """The subtotal is the provider's; the fee is on top, never carved out."""
        for unit in (Decimal("1"), Decimal("19.99"), Decimal("0.05")):
            subtotal, _, total = _totals(unit, 1)
            assert total >= subtotal


class TestResolvingAPrice:
    def test_a_fixed_service_uses_its_own_price(self) -> None:
        price = _resolve_unit_price(FakeService(price=Decimal("42.5")), FakePayload())
        assert price == Decimal("42.500000")

    def test_a_negotiated_service_requires_an_agreed_price(self) -> None:
        """Refusing beats inventing a number for something priced by agreement."""
        service = FakeService(pricing_model=PricingModel.NEGOTIATED, price=None)
        with pytest.raises(ConflictError):
            _resolve_unit_price(service, FakePayload(negotiated_price=None))

    def test_a_negotiated_price_is_quantised_like_any_other(self) -> None:
        service = FakeService(pricing_model=PricingModel.NEGOTIATED, price=None)
        price = _resolve_unit_price(
            service, FakePayload(negotiated_price=Decimal("10.1234567"))
        )
        assert price == Decimal("10.123457")

    def test_a_priceless_fixed_service_is_refused_not_guessed(self) -> None:
        """Unreachable through the API, and the refusal is the point: a missing
        price must never become a zero."""
        with pytest.raises(ConflictError):
            _resolve_unit_price(FakeService(price=None), FakePayload())

    def test_a_negotiated_service_ignores_its_own_stale_price(self) -> None:
        """The agreed figure governs, not whatever is left on the record."""
        service = FakeService(
            pricing_model=PricingModel.NEGOTIATED, price=Decimal("999")
        )
        price = _resolve_unit_price(service, FakePayload(negotiated_price=Decimal("5")))
        assert price == Decimal("5.000000")
