"""What a service is allowed to say about its own price.

These run after a partial update, where a patch touching only one field can leave
the record disagreeing with fields it never touched. The database would reject
that with an opaque constraint error; these produce something the caller can act
on, which is only useful if they actually fire.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.core.errors import ConflictError
from app.db.enums import PricingModel
from app.modules.services.service import _validate_pricing_coherence


@dataclass
class FakeService:
    pricing_model: PricingModel = PricingModel.FIXED
    price: Decimal | None = Decimal("10")
    price_unit: str | None = None
    min_quantity: int = 1
    max_quantity: int | None = None


class TestAPriceIsRequiredUnlessNegotiated:
    def test_a_fixed_service_without_a_price_is_refused(self) -> None:
        """The failure this prevents is a published service that cannot be
        ordered, or worse, one ordered at nothing."""
        with pytest.raises(ConflictError):
            _validate_pricing_coherence(FakeService(price=None))

    def test_a_negotiated_service_may_have_no_price(self) -> None:
        _validate_pricing_coherence(
            FakeService(pricing_model=PricingModel.NEGOTIATED, price=None)
        )

    def test_switching_to_negotiated_does_not_require_clearing_the_price(self) -> None:
        """A leftover price is not an inconsistency; the order flow ignores it."""
        _validate_pricing_coherence(
            FakeService(pricing_model=PricingModel.NEGOTIATED, price=Decimal("99"))
        )


class TestPerUnitNeedsAUnit:
    def test_per_unit_without_a_unit_is_refused(self) -> None:
        """"12 USDC" per what, is a question a buyer should never have to ask."""
        with pytest.raises(ConflictError):
            _validate_pricing_coherence(
                FakeService(pricing_model=PricingModel.PER_UNIT, price_unit=None)
            )

    def test_an_empty_unit_counts_as_missing(self) -> None:
        """A blank string is the shape a form sends, and it means nothing."""
        with pytest.raises(ConflictError):
            _validate_pricing_coherence(
                FakeService(pricing_model=PricingModel.PER_UNIT, price_unit="")
            )

    def test_per_unit_with_a_unit_is_accepted(self) -> None:
        _validate_pricing_coherence(
            FakeService(pricing_model=PricingModel.PER_UNIT, price_unit="1000 tokens")
        )


class TestQuantityRange:
    def test_a_maximum_below_the_minimum_is_refused(self) -> None:
        """An impossible range means nothing can be ordered, which is a silent
        way for a service to be broken while looking published."""
        with pytest.raises(ConflictError):
            _validate_pricing_coherence(FakeService(min_quantity=5, max_quantity=2))

    def test_an_equal_range_is_allowed(self) -> None:
        """Exactly one quantity is a legitimate offer."""
        _validate_pricing_coherence(FakeService(min_quantity=3, max_quantity=3))

    def test_no_maximum_means_unbounded_rather_than_zero(self) -> None:
        _validate_pricing_coherence(FakeService(min_quantity=2, max_quantity=None))
