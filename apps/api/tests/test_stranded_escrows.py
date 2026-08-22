"""Money held against a listing that can no longer deliver must be noticed.

**Two real orders were funded against a paused agent on 2026-08-22.** A wallet
that is not ours found a rehearsal listing in the marketplace, funded two
escrows against it, and 2.05 USDC sat there against work that could never
happen. Pausing an agent does nothing to an escrow that is already funded.

Nothing noticed. It was found by reading the chain for an unrelated reason.

Every other failure the monitor watches is loud: a stalled indexer stops every
order, a dead worker stops every email. This one is silent by construction,
because from the platform's side nothing is broken at all. One buyer is simply
waiting for something that will not come, and the only evidence is their money.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.modules.health import service

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def row(*, reference="AGO-TEST", hours=1, amount="1.025000", funded_hours_ago=2):
    """A row shaped exactly like the query's, with real types."""
    return SimpleNamespace(
        reference=reference,
        delivery_time_hours=hours,
        amount=Decimal(amount),
        funded_at=NOW - timedelta(hours=funded_hours_ago),
        status="paused",
    )


class TestNothingHeldIsHealthy:
    def test_no_rows_is_ok(self) -> None:
        verdict = service.stranded_verdict([], now=NOW)
        assert verdict.status == "ok"
        assert verdict.detail["held"] == "0"

    def test_healthy_carries_no_error(self) -> None:
        """An `ok` with an error attached is what teaches people to skim past."""
        assert service.stranded_verdict([], now=NOW).error is None


class TestHeldMoneyIsReported:
    def test_an_escrow_within_its_window_is_degraded_not_down(self) -> None:
        """The buyer is waiting, and has not yet waited longer than agreed."""
        verdict = service.stranded_verdict([row(funded_hours_ago=0)], now=NOW)
        assert verdict.status == "degraded"
        assert verdict.detail["overdue"] == "0"

    def test_an_escrow_past_its_window_is_down(self) -> None:
        """Past this point the buyer could reclaim it and nobody has told them."""
        verdict = service.stranded_verdict([row(funded_hours_ago=2)], now=NOW)
        assert verdict.status == "down"
        assert verdict.detail["overdue"] == "1"

    def test_exactly_at_the_deadline_counts_as_reached(self) -> None:
        """The contract uses `>=` for the same boundary, and a monitor that
        disagreed with it would page a minute after the fact or not at all."""
        assert service.stranded_verdict([row(funded_hours_ago=1)], now=NOW).status == "down"

    def test_the_money_held_is_summed_not_counted(self) -> None:
        """The amount is the part that says how bad it is. Two orders of 1.025
        is the real figure from 2026-08-22."""
        verdict = service.stranded_verdict(
            [row(reference="AGO-DB4Q4YQA"), row(reference="AGO-JCX8G6WJ")], now=NOW
        )
        assert verdict.detail["held"] == "2.050000"
        assert verdict.detail["stranded"] == "2"

    def test_the_references_are_named_so_somebody_can_act(self) -> None:
        """An alert that says "2 escrows" and not which ones is a second
        investigation, at the point where somebody's money is already waiting."""
        verdict = service.stranded_verdict(
            [row(reference="AGO-JCX8G6WJ"), row(reference="AGO-DB4Q4YQA")], now=NOW
        )
        assert verdict.detail["references"] == "AGO-DB4Q4YQA,AGO-JCX8G6WJ"

    def test_a_mix_reports_down_and_counts_only_the_late_ones(self) -> None:
        verdict = service.stranded_verdict(
            [row(reference="AGO-LATE", funded_hours_ago=5),
             row(reference="AGO-FRESH", funded_hours_ago=0)],
            now=NOW,
        )
        assert verdict.status == "down"
        assert verdict.detail["stranded"] == "2"
        assert verdict.detail["overdue"] == "1"


class TestAMissingWindowDoesNotInventOne:
    """An order with no recorded delivery window cannot be judged late.

    Reporting `down` on a row whose deadline is unknown would page on missing
    data rather than on a real condition, and an alert that fires for reasons
    nobody can act on is one people learn to close.
    """

    def test_no_delivery_hours_is_held_but_not_overdue(self) -> None:
        verdict = service.stranded_verdict([row(hours=None)], now=NOW)
        assert verdict.status == "degraded"
        assert verdict.detail["overdue"] == "0"
        assert verdict.detail["stranded"] == "1"

    def test_no_funded_at_is_held_but_not_overdue(self) -> None:
        entry = row()
        entry.funded_at = None
        verdict = service.stranded_verdict([entry], now=NOW)
        assert verdict.status == "degraded"
        assert verdict.detail["overdue"] == "0"


class TestTheAlertSaysEnoughToActOn:
    def test_the_error_names_the_condition_and_the_counts(self) -> None:
        verdict = service.stranded_verdict(
            [row(funded_hours_ago=5), row(funded_hours_ago=0)], now=NOW
        )
        assert "not" in verdict.error and "active" in verdict.error
        assert "2" in verdict.error
        assert "1" in verdict.error
