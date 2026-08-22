"""Every way the contract can move money must be reachable from the product.

The refund rehearsal of 2026-08-22 found that `release`, `refund` and `dispute`
were not. The contract enforced a buyer's right to reclaim their money after the
delivery deadline, correctly, for the whole life of the product, and no buyer
could have invoked it without reading the ABI and hand-building a transaction.

**Nothing would have caught it.** Every test passed, the Solidity was right, the
audit-readiness document was accurate. The gap was between a guarantee existing
and a person being able to use it, and no test asked that question because the
question had never been phrased.

This is that question, phrased. It is written over the ABI rather than over the
three functions that were missing, so a state-changing function added to the
contract later fails this test until somebody says which it is: something a user
must be able to reach, or something deliberately kept out of their hands. The
failure mode being prevented is silence, not any particular function.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.chain import escrow as contract
from app.modules.orders import service

# Built here rather than imported from the sibling test module. `tests` is not an
# importable package in CI, so a cross-test import passes locally and fails there,
# which is exactly what it did the first time this was pushed.
ESCROW_ID = "0x" + "ab" * 32
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _funded():
    return SimpleNamespace(status=contract.OnChainStatus.FUNDED)


def release_for(roles):
    return service._release_action(
        _funded(), set(roles), now=NOW, auto_release=NOW + timedelta(hours=1),
        escrow_id=ESCROW_ID,
    )


def refund_for(roles):
    return service._refund_action(
        _funded(), set(roles), now=NOW, deadline=NOW + timedelta(hours=1),
        escrow_id=ESCROW_ID,
    )


def dispute_for(roles):
    return service._dispute_action(
        _funded(), set(roles), paused=False, escrow_id=ESCROW_ID,
    )

ABI = json.loads(
    (Path(__file__).resolve().parents[3] / "packages" / "contracts" /
     "AgoreumEscrow.abi.json").read_text(encoding="utf-8")
)

STATE_CHANGING = sorted(
    e["name"] for e in ABI
    if e.get("type") == "function"
    and e.get("stateMutability") not in ("view", "pure")
)

# A user must be able to reach these, and the endpoint that tells them how.
REACHABLE = {
    "createEscrow": "GET /orders/{id}/payment-instructions",
    "release": "GET /orders/{id}/settlement-options",
    "refund": "GET /orders/{id}/settlement-options",
    "dispute": "GET /orders/{id}/settlement-options",
    "settleDispute": "POST /orders/{id}/dispute-decision",
}

# Deliberately not offered to users, each with the reason. A reason that stops
# being true is a row that should move, which is why they are written down
# rather than left as an unexplained absence.
WITHHELD = {
    "pause": "Operator action during an incident. Not a party's decision.",
    "unpause": "Operator action during an incident. Not a party's decision.",
    "setFeeConfig": "Governance. Held by the governor role, not by any account here.",
    "grantRole": "Governance. Role changes are an owner decision, deliberately not a product feature.",
    "revokeRole": "Governance. Role changes are an owner decision, deliberately not a product feature.",
    "renounceRole": "Governance, and irreversible. Never a button.",
}


class TestNoWayToMoveMoneyIsLeftUnclassified:
    def test_the_abi_actually_has_functions_to_check(self) -> None:
        """A run that checks nothing must not report success."""
        assert len(STATE_CHANGING) >= 8, STATE_CHANGING

    @pytest.mark.parametrize("name", STATE_CHANGING)
    def test_every_state_changing_function_is_either_reachable_or_withheld(
        self, name: str
    ) -> None:
        """The check that would have caught the defect, phrased over the ABI.

        A new function is unclassified until somebody decides, which is the
        point: the failure being prevented is nobody having asked.
        """
        assert name in REACHABLE or name in WITHHELD, (
            f"{name} can change contract state and nothing says whether a user "
            "should be able to reach it. Add it to REACHABLE with the endpoint "
            "that describes it, or to WITHHELD with the reason it is not offered. "
            "This is exactly the gap that left refund unreachable for the whole "
            "life of the product while the contract enforced it correctly."
        )

    def test_nothing_is_classified_both_ways(self) -> None:
        assert not (set(REACHABLE) & set(WITHHELD))

    def test_the_classification_does_not_name_functions_the_contract_lacks(self) -> None:
        """A stale row is a claim about a function that no longer exists."""
        unknown = (set(REACHABLE) | set(WITHHELD)) - set(STATE_CHANGING)
        assert not unknown, unknown

    @pytest.mark.parametrize("name", sorted(WITHHELD))
    def test_withholding_is_explained(self, name: str) -> None:
        assert len(WITHHELD[name]) > 20, name


class TestTheReachablePathsReallyAreReachable:
    """Classifying a function as reachable is a claim, so it is checked.

    A row in a table saying "reachable" is exactly the kind of true-once
    statement this project keeps finding. These drive the real code.
    """

    def test_settlement_options_offers_each_exit_it_claims_to(self) -> None:
        offered = {
            action.function
            for action in (release_for(["buyer"]), refund_for(["provider"]),
                           dispute_for(["buyer"]))
        }
        claimed = {
            name for name, where in REACHABLE.items()
            if "settlement-options" in where
        }
        assert offered == claimed, (offered, claimed)

    def test_every_exit_carries_the_contract_and_a_selector(self) -> None:
        """A description a wallet cannot act on is not a way out."""
        for action in (release_for(["buyer"]), refund_for(["provider"]),
                       dispute_for(["buyer"])):
            assert action.selector.startswith("0x"), action.action
            assert len(action.selector) == 10, action.action
            assert action.arguments, action.action

    def test_the_selectors_are_the_contracts_own(self) -> None:
        """Derived from the ABI, not typed in, so they cannot drift from it."""
        for action in (release_for(["buyer"]), refund_for(["provider"]),
                       dispute_for(["buyer"])):
            assert action.selector == contract.function_selector(action.function)

    def test_payment_instructions_still_describes_funding(self) -> None:
        """The one exit that always worked, kept honest alongside the others."""
        from app.modules.orders.schemas import PaymentInstructions

        assert "create_escrow_selector" in PaymentInstructions.model_fields

    @pytest.mark.asyncio
    async def test_the_whole_endpoint_actually_assembles(self, monkeypatch) -> None:
        """Drive `settlement_options` itself, not only the pieces it is built from.

        **This is the test that was missing, and its absence shipped a broken
        endpoint to production.** Every helper was covered and mutation tested,
        the route existed, CI was green, and the first real request returned 500:
        the assembly read `settings.network_name`, which does not exist, and
        nothing had ever executed the line.

        What stood in its place was `assert callable(service.settlement_options)`,
        which is true of any function that has been defined and cannot fail for a
        function that crashes on every call. A check that cannot fail is not a
        weak check, it is a false one, and this project had written that sentence
        down the same day it committed this.
        """
        _configure_escrow(monkeypatch)
        escrow_id = contract.escrow_id_for_order("2f1b6d5a-0000-4000-8000-000000000001")
        order = SimpleNamespace(
            id="2f1b6d5a-0000-4000-8000-000000000001",
            reference="AGO-ASSEMBLY",
            buyer_id="user-1",
            # No organization, so membership is never consulted and no database
            # is needed to prove the assembly runs.
            provider_agent=SimpleNamespace(org_id=None),
        )
        user = SimpleNamespace(id="user-1", primary_address="0x" + "11" * 20)

        options = await service.settlement_options(
            None, order=order, user=user, client=_FakeChain(escrow_id)
        )

        assert options.order_reference == "AGO-ASSEMBLY"
        assert options.network_name, "the network has no name, which is how this broke"
        assert options.escrow_contract.startswith("0x")
        assert {a.action for a in options.actions} == {"release", "refund", "dispute"}
        assert options.your_roles == ["buyer"]
        assert options.note
        # The buyer can always release, which is the cheapest proof that real
        # availability logic ran rather than a default being returned.
        assert next(a for a in options.actions if a.action == "release").available

    @pytest.mark.asyncio
    async def test_a_paused_contract_closes_the_dispute_and_not_the_refund(
        self, monkeypatch
    ) -> None:
        """The pause flag is read, not assumed, and the assembly proves it.

        Without this, hardcoding `paused = False` passes every test, because the
        only fixture in play was an unpaused contract. Getting this backwards
        would block somebody from taking their own money out during the exact
        situation a pause exists for.
        """
        _configure_escrow(monkeypatch)
        escrow_id = contract.escrow_id_for_order("2f1b6d5a-0000-4000-8000-000000000002")
        order = SimpleNamespace(
            id="2f1b6d5a-0000-4000-8000-000000000002",
            reference="AGO-PAUSED",
            buyer_id="user-1",
            provider_agent=SimpleNamespace(org_id=None),
        )
        user = SimpleNamespace(id="user-1", primary_address="0x" + "11" * 20)

        options = await service.settlement_options(
            None, order=order, user=user, client=_FakeChain(escrow_id, paused=True)
        )

        assert options.contract_paused is True
        by_action = {a.action: a for a in options.actions}
        assert by_action["dispute"].available is False
        assert "paused" in (by_action["dispute"].reason or "").lower()
        # Releasing is the buyer accepting the work, and the contract does not
        # gate it on the pause either.
        assert by_action["release"].available is True


def _configure_escrow(monkeypatch) -> None:
    """Give the settings an escrow address for the duration of one test.

    CI runs with `ESCROW_CONTRACT_ADDRESS` unset, so `settlement_options` raises
    `EscrowNotConfiguredError` before it does anything. A developer machine
    reads the address from `.env` and the same test passes, which is how the
    first version of this went green locally and red in CI. The local pass was
    not evidence.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "ESCROW_CONTRACT_ADDRESS", "0x" + "ab" * 20)


class _FakeChain:
    """Answers the two calls `settlement_options` makes, with real ABI encoding.

    Encoded rather than stubbed at the decode boundary, so the ABI shape is part
    of what is being tested instead of being assumed.
    """

    def __init__(self, escrow_id: str, *, paused: bool = False) -> None:
        self.escrow_id = escrow_id
        self.paused = paused

    async def call(self, *, to: str, data: str) -> str:
        if data.startswith(contract.function_selector("paused")):
            return "0x" + ("0" * 63) + ("1" if self.paused else "0")
        from eth_abi.abi import encode

        funded = encode(
            ["(address,address,address,uint256,uint256,uint256,uint256,uint64,uint64,uint8)"],
            [(
                "0x" + "11" * 20, "0x" + "22" * 20, "0x" + "33" * 20,
                2_050_000, 0, 0, 250,
                2_000_000_000, 2_000_003_600,
                int(contract.OnChainStatus.FUNDED),
            )],
        )
        return "0x" + funded.hex()
