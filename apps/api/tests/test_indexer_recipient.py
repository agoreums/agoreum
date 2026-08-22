"""Every escrow event must be recordable, not only the one that carries a provider.

Written after a settled dispute put the production indexer into a crash loop on
2026-08-21. `to_address` was derived as `str(event.args.get("provider") or "")`,
which is correct for EscrowReleased and wrong for every other event, because
they do not all carry a `provider`. A settlement pays both parties and names
neither. The empty string reached an address column that refuses it, the
exception escaped the handler, and the container restarted into the same block
forever with all chain projection stopped.

Neither EscrowSettled nor EscrowRefunded had ever been emitted in production, so
both were latent from the day the line was written. That is why this is written
over the ABI rather than over the one event that failed: the next event added
gets the same coverage without anybody remembering to add it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.chain import indexer

ABI = json.loads(
    (Path(__file__).resolve().parents[3] / "packages" / "contracts" /
     "AgoreumEscrow.abi.json").read_text(encoding="utf-8")
)
ESCROW_EVENTS = [
    e["name"] for e in ABI
    if e.get("type") == "event" and e["name"].startswith("Escrow")
]

PROVIDER = "0x00000000000000000000000000000000000a1ice"
BUYER = "0x00000000000000000000000000000000000000b0"


@dataclass
class FakeEscrow:
    provider_address: str | None = PROVIDER


@dataclass
class FakeEvent:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeUser:
    primary_address: str = BUYER


@dataclass
class FakeOrder:
    escrow: FakeEscrow | None = field(default_factory=FakeEscrow)
    buyer: FakeUser = field(default_factory=FakeUser)


def _args_for(name: str) -> dict[str, Any]:
    """The event's real arguments, from the ABI, with plausible values."""
    event = next(e for e in ABI if e.get("type") == "event" and e["name"] == name)
    args: dict[str, Any] = {}
    for item in event["inputs"]:
        if item["type"] == "address":
            args[item["name"]] = PROVIDER if item["name"] == "provider" else BUYER
        elif item["type"].startswith("uint"):
            args[item["name"]] = 1000
        elif item["type"] == "bytes32":
            args[item["name"]] = b"\x00" * 32
        else:
            args[item["name"]] = "x"
    return args


class TestEveryEscrowEventIsRecordable:
    def test_the_abi_actually_has_events_to_check(self) -> None:
        """A run that checks nothing must not report success."""
        assert len(ESCROW_EVENTS) >= 4, ESCROW_EVENTS

    @pytest.mark.parametrize("name", ESCROW_EVENTS)
    def test_a_recipient_is_never_an_empty_string(self, name: str) -> None:
        """The exact value the address column refuses, and the crash's cause."""
        result = indexer._recipient(FakeEvent(name, _args_for(name)), FakeOrder())
        assert result != "", (
            f"{name} produced an empty recipient, which the EthereumAddress "
            "column rejects. That escaped the handler and crash-looped the "
            "indexer the first time a dispute was settled."
        )
        assert result is None or result.startswith("0x"), result

    def test_an_event_naming_nobody_falls_back_to_the_escrow(self) -> None:
        """EscrowSettled names only the arbiter, and the escrow knows the provider."""
        event = FakeEvent("EscrowSettled", _args_for("EscrowSettled"))
        event.args.pop("provider", None)
        event.args.pop("buyer", None)
        assert indexer._recipient(event, FakeOrder()) == PROVIDER

    def test_it_returns_none_rather_than_something_invalid(self) -> None:
        """With no escrow and no named party there is nothing true to record.

        None is correct because the column is nullable. The empty string that
        replaced it was never necessary and was what broke production.
        """
        event = FakeEvent("EscrowSettled", {})
        assert indexer._recipient(event, FakeOrder(escrow=None)) is None


class TestALedgerRowNamesBothEndsOfTheTransfer:
    """A refund recorded the buyer paying themselves.

    `from_address` read the event's `buyer`, which `EscrowRefunded` does carry,
    and `to_address` fell through to the same value because the event names no
    provider. Both ends were the buyer, on the one event where the direction is
    the entire meaning of the row.

    It survived because no refund had ever been emitted in production and
    neither column is exposed by any endpoint, so nothing anybody could look at
    would have shown it. Predicted from the event signatures while designing the
    refund rehearsal of 2026-08-22, then checked here against the ABI's real
    shapes rather than against a guess rewritten in the test.
    """

    @pytest.mark.parametrize("name", ESCROW_EVENTS)
    def test_the_two_ends_are_never_the_same_party(self, name: str) -> None:
        payer, payee = indexer._counterparties(FakeEvent(name, _args_for(name)), FakeOrder())
        assert payer, f"{name} produced no payer, and the column is not nullable"
        if payee is not None:
            assert payer != payee, (
                f"{name} recorded the same address at both ends, which describes "
                "somebody paying themselves rather than a transfer between two "
                "parties."
            )

    def test_a_refund_runs_from_the_provider_back_to_the_buyer(self) -> None:
        """The direction is the point, and it is the reverse of every other event."""
        payer, payee = indexer._counterparties(
            FakeEvent("EscrowRefunded", _args_for("EscrowRefunded")), FakeOrder()
        )
        assert payer == PROVIDER
        assert payee == BUYER

    def test_funding_and_release_still_run_from_the_buyer_to_the_provider(self) -> None:
        """The convention the refund reverses, so the reversal cannot spread."""
        for name in ("EscrowCreated", "EscrowReleased"):
            payer, payee = indexer._counterparties(FakeEvent(name, _args_for(name)), FakeOrder())
            assert (payer, payee) == (BUYER, PROVIDER), name

    def test_a_refund_with_no_provider_anywhere_still_names_the_buyer(self) -> None:
        """Degraded rather than broken. The column refuses null and empty alike."""
        event = FakeEvent("EscrowRefunded", _args_for("EscrowRefunded"))
        payer, payee = indexer._counterparties(event, FakeOrder(escrow=None))
        assert payer == BUYER
        assert payee == BUYER


class TestARefundRecordsTheChainsFigure:
    """A refund wrote whatever the database already believed the escrow was.

    `refund` returns the whole escrow, so the emitted `amount` is the chain's own
    view of the total. Taking the figure from `escrow.amount` instead meant that
    where the two had drifted, the refund carried the drift forward and reconcile
    would keep reporting a divergence that nothing corrected.

    Same shape as the settlement defect: the chain states a number and the code
    writes a different one it happens to hold.
    """

    @staticmethod
    def _apply(recorded: Decimal, emitted_units: int) -> tuple[Decimal, Decimal]:
        """Drive the real handler over a real event payload.

        Returns the escrow's amount and refunded amount afterwards. Deliberately
        not arithmetic rewritten in the test.
        """
        from types import SimpleNamespace

        escrow = SimpleNamespace(amount=recorded, refunded_amount=Decimal("0"))
        event = FakeEvent("EscrowRefunded", {"amount": emitted_units, "buyer": BUYER})
        indexer.apply_refund(escrow, event)
        return escrow.amount, escrow.refunded_amount

    def test_the_refunded_figure_comes_from_the_event(self) -> None:
        amount, refunded = self._apply(Decimal("2.050000"), 2_050_000)
        assert refunded == Decimal("2.050000")
        assert amount == Decimal("2.050000")

    def test_a_drifted_amount_is_corrected_rather_than_perpetuated(self) -> None:
        """The case the old code got wrong, and the reason it must correct both.

        Writing the chain's larger figure into `refunded_amount` alone would
        breach `payouts_cannot_exceed_deposit` and crash-loop the indexer, which
        is exactly how the first settled dispute took chain projection down.
        """
        amount, refunded = self._apply(Decimal("0.999375"), 1_025_000)
        assert refunded == Decimal("1.025000")
        assert amount == Decimal("1.025000")
        assert refunded <= amount, "the row would be refused by the check constraint"

    def test_an_event_carrying_no_amount_falls_back_to_the_record(self) -> None:
        """Never zero. A refund of nothing is a worse claim than a stale one."""
        amount, refunded = self._apply(Decimal("2.050000"), 0)
        assert refunded == Decimal("2.050000")
        assert amount == Decimal("2.050000")


class TestASettledDisputeIsDescribedAsWellAsRecorded:
    """The second landmine in the same never-run path, found an hour after the first.

    The escrows table requires `(dispute_resolution IS NULL) = (dispute_resolved_at
    IS NULL)`. The settlement handler set only the timestamp, so the first
    settled dispute in production violated the constraint on every retry and
    crash-looped the indexer a second time, after the address fix had cleared
    the first crash.

    The constraint was right. The handler was incomplete, and had been since it
    was written, because no dispute had ever been settled.
    """

    def test_a_full_award_to_the_provider(self) -> None:
        from app.db.enums import DisputeResolution

        assert indexer.settlement_resolution(
            provider_amount=Decimal("100"), buyer_amount=Decimal("0")
        ) == DisputeResolution.RELEASED_TO_PROVIDER

    def test_a_full_refund_to_the_buyer(self) -> None:
        from app.db.enums import DisputeResolution

        assert indexer.settlement_resolution(
            provider_amount=Decimal("0"), buyer_amount=Decimal("100")
        ) == DisputeResolution.REFUNDED_TO_BUYER

    def test_a_split(self) -> None:
        from app.db.enums import DisputeResolution

        assert indexer.settlement_resolution(
            provider_amount=Decimal("60"), buyer_amount=Decimal("40")
        ) == DisputeResolution.SPLIT

    def test_it_never_returns_none(self) -> None:
        """The property the constraint actually cares about.

        A None here pairs a resolved timestamp with no resolution, which is the
        exact row the database refused. Checked across the boundaries rather
        than at one convenient point.
        """
        for provider, buyer in (
            (Decimal("0"), Decimal("0")),
            (Decimal("0"), Decimal("100")),
            (Decimal("100"), Decimal("0")),
            (Decimal("0.000001"), Decimal("99.999999")),
            (Decimal("99.999999"), Decimal("0.000001")),
        ):
            assert indexer.settlement_resolution(
                provider_amount=provider, buyer_amount=buyer
            ) is not None, f"no resolution for provider={provider} buyer={buyer}"


class TestASettledAmountMatchesTheChain:
    """What the database records released must be what the contract holds.

    The contract stores the gross and emits the net under a name that reads like
    the gross:

        escrow.released = providerAmount             gross, stored on chain
        emit EscrowSettled(id, providerNet, ...)     net, emitted

    Writing the emitted figure straight into `released_amount` made the database
    disagree with the chain on the first dispute ever settled in production,
    0.999375 against 1.025000. Nothing was lost. The platform's record of how
    much was released was simply a different number from the contract's.

    Found by `reconcile` against real data, which is the first time that
    endpoint has caught a genuine divergence.
    """

    @staticmethod
    def _settled(provider_net: Decimal, fee: Decimal, buyer: Decimal) -> Decimal:
        """The gross the indexer records, computed by the indexer itself.

        Deliberately not arithmetic rewritten here. A test that recomputes the
        formula proves only that it agrees with itself, which is the shape this
        whole sweep exists to catch, so it drives the real function over a real
        event payload in base units.
        """
        gross, _refunded, _fee = indexer.settled_amounts(
            FakeEvent("EscrowSettled", {
                "providerAmount": int(provider_net * 10 ** 6),
                "feeAmount": int(fee * 10 ** 6),
                "buyerAmount": int(buyer * 10 ** 6),
            })
        )
        return gross

    def test_the_recorded_gross_matches_the_chain(self) -> None:
        # The real figures from the first settled dispute, order AGO-DT2TPSZL.
        gross = self._settled(Decimal("0.999375"), Decimal("0.025625"), Decimal("1.025000"))
        assert gross == Decimal("1.025000"), gross

    def test_the_parts_still_sum_to_the_escrow(self) -> None:
        """The property that makes the figures trustworthy at all.

        Released plus refunded must equal the escrow, or the record describes
        money appearing or vanishing.
        """
        provider_net, fee, buyer = Decimal("0.999375"), Decimal("0.025625"), Decimal("1.025000")
        gross = self._settled(provider_net, fee, buyer)
        assert gross + buyer == Decimal("2.050000")

    def test_a_full_award_records_the_whole_escrow(self) -> None:
        """The boundary the net form gets most visibly wrong.

        A provider awarded everything should show the entire escrow released,
        not the escrow minus the fee.
        """
        amount, fee = Decimal("100.000000"), Decimal("2.500000")
        gross = self._settled(amount - fee, fee, Decimal("0"))
        assert gross == amount

    def test_a_full_refund_releases_nothing(self) -> None:
        assert self._settled(Decimal("0"), Decimal("0"), Decimal("100")) == Decimal("0")
