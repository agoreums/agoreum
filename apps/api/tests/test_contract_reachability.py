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

    def test_the_settlement_options_builder_exists_and_is_wired(self) -> None:
        assert callable(service.settlement_options)
