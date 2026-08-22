"""A party must be able to reach the exits the contract already gives them.

Written after the refund rehearsal of 2026-08-22 found that none of them were
reachable. `payment_instructions` described exactly how to put money into an
escrow: contract, selector, calldata, amounts, deadline. Nothing described
`release`, `refund` or `dispute`, and the web application makes exactly two
on-chain writes, neither of them an exit.

The contract was correct the whole time, which is why no test, no review and no
audit-readiness document would have shown it. A buyer whose provider vanished
held a right that genuinely exists and could not reach it without reading the
ABI and hand-building a transaction.

These tests are written against the contract's own conditions. Where they and
`AgoreumEscrow.sol` disagree the contract wins, because it is what accepts or
refuses the call.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.chain import escrow as contract
from app.modules.orders import service

ESCROW_ID = "0x" + "ab" * 32
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(hours=1)
LATER = NOW + timedelta(hours=1)


def funded(status: contract.OnChainStatus = contract.OnChainStatus.FUNDED):
    return SimpleNamespace(status=status)


def release_for(roles, *, auto_release=LATER, status=contract.OnChainStatus.FUNDED):
    return service._release_action(
        funded(status), set(roles), now=NOW, auto_release=auto_release,
        escrow_id=ESCROW_ID,
    )


def refund_for(roles, *, deadline=LATER, status=contract.OnChainStatus.FUNDED):
    return service._refund_action(
        funded(status), set(roles), now=NOW, deadline=deadline, escrow_id=ESCROW_ID,
    )


def dispute_for(roles, *, paused=False, status=contract.OnChainStatus.FUNDED):
    return service._dispute_action(
        funded(status), set(roles), paused=paused, escrow_id=ESCROW_ID,
    )


class TestTheBuyerCanGetTheirMoneyBack:
    """The guarantee that makes escrow worth using, and the one that was unreachable."""

    def test_a_buyer_may_reclaim_once_the_delivery_deadline_has_passed(self) -> None:
        action = refund_for(["buyer"], deadline=EARLIER)
        assert action.available is True
        assert action.calldata is not None

    def test_a_buyer_may_not_reclaim_before_the_deadline(self) -> None:
        """The contract refuses this with DeadlineNotReached, as production proved."""
        action = refund_for(["buyer"], deadline=LATER)
        assert action.available is False
        assert "deadline" in (action.reason or "").lower()

    def test_the_moment_it_becomes_possible_is_returned_not_only_the_refusal(self) -> None:
        """A refusal with no date is what makes somebody think the right is not real."""
        action = refund_for(["buyer"], deadline=LATER)
        assert action.available_at == LATER

    def test_exactly_at_the_deadline_counts_as_reached(self) -> None:
        """The contract uses `>=`. An off-by-one here refuses a call that succeeds."""
        assert refund_for(["buyer"], deadline=NOW).available is True


class TestTheProviderCanDecline:
    def test_a_provider_may_refund_at_any_time(self) -> None:
        assert refund_for(["provider"], deadline=LATER).available is True

    def test_a_provider_is_not_told_to_wait_for_a_deadline_that_does_not_bind_them(
        self,
    ) -> None:
        assert refund_for(["provider"], deadline=LATER).available_at is None


class TestReleasingToTheProvider:
    def test_the_buyer_may_release_at_any_time(self) -> None:
        assert release_for(["buyer"], auto_release=LATER).available is True

    def test_a_provider_must_wait_for_the_auto_release_time(self) -> None:
        action = release_for(["provider"], auto_release=LATER)
        assert action.available is False
        assert action.available_at == LATER

    def test_after_the_auto_release_time_anyone_may_release(self) -> None:
        """Deliberately permissionless in the contract, so payment never depends
        on the buyer staying reachable. Reported to everyone for that reason."""
        assert release_for([], auto_release=EARLIER).available is True
        assert release_for(["provider"], auto_release=EARLIER).available is True


class TestAPauseMustNotHideTheExit:
    """`refund` is not gated on `whenNotPaused` and `dispute` is.

    Getting this backwards would block somebody from taking their own money out
    during the exact situation a pause exists for.
    """

    def test_a_dispute_cannot_be_raised_while_paused(self) -> None:
        action = dispute_for(["buyer"], paused=True)
        assert action.available is False
        assert "paused" in (action.reason or "").lower()

    def test_a_refund_is_still_available_while_paused(self) -> None:
        """The contract does not gate `refund` on the pause, and neither does this."""
        assert refund_for(["provider"]).available is True
        assert refund_for(["buyer"], deadline=EARLIER).available is True

    def test_the_refusal_says_the_refund_is_still_open(self) -> None:
        """Being told 'paused' and nothing else reads as 'your money is stuck'."""
        assert "refund" in (dispute_for(["buyer"], paused=True).reason or "").lower()


class TestDisputing:
    def test_either_party_may_dispute_while_funds_are_held(self) -> None:
        assert dispute_for(["buyer"]).available is True
        assert dispute_for(["provider"]).available is True

    def test_a_stranger_may_not(self) -> None:
        assert dispute_for(["arbiter"]).available is False

    def test_no_calldata_is_published_for_a_dispute(self) -> None:
        """Not an omission. `dispute` takes a free-text reason, so complete
        calldata cannot exist before the caller has written one, and inventing
        one would put words in their mouth in a document they are about to sign."""
        action = dispute_for(["buyer"])
        assert action.calldata is None
        reason = next(a for a in action.arguments if a.name == "reason")
        assert reason.value is None


class TestAnEscrowThatCannotMove:
    @pytest.mark.parametrize(
        "status",
        [contract.OnChainStatus.RELEASED, contract.OnChainStatus.REFUNDED,
         contract.OnChainStatus.SETTLED],
    )
    def test_nothing_is_offered_once_it_has_settled(self, status) -> None:
        for action in (release_for(["buyer"], status=status),
                       refund_for(["provider"], status=status),
                       dispute_for(["buyer"], status=status)):
            assert action.available is False, action.action
            assert "settled" in (action.reason or "").lower()

    def test_a_disputed_escrow_offers_nothing_and_says_why(self) -> None:
        status = contract.OnChainStatus.DISPUTED
        for action in (release_for(["buyer"], status=status),
                       refund_for(["provider"], status=status),
                       dispute_for(["buyer"], status=status)):
            assert action.available is False, action.action
            assert "arbitration" in (action.reason or "").lower()

    def test_an_escrow_that_does_not_exist_says_so(self) -> None:
        action = refund_for(["buyer"], deadline=EARLIER,
                            status=contract.OnChainStatus.NONE)
        assert action.available is False
        assert "fund the order first" in (action.reason or "").lower()


class TestThePublishedCalldataIsTheCalldataThatWorks:
    """Byte-identical to two transactions that actually succeeded on Base Sepolia.

    `0x7249fbb6...` is the input of the real refunds in orders AGO-RPBSNQXC and
    AGO-XNE2SADX. Comparing against a known-good answer from the chain rather
    than re-encoding the same way twice, which would prove only self-agreement.
    """

    R1 = "0x7249fbb60000000000000000000000000000000065afe02de1d04eb2a35c9efb802d8953"
    R1_ESCROW = "0x0000000000000000000000000000000065afe02de1d04eb2a35c9efb802d8953"

    def test_a_refund_matches_the_transaction_that_settled_in_production(self) -> None:
        assert contract.encode_escrow_id_call("refund", self.R1_ESCROW) == self.R1

    def test_the_escrow_id_is_carried_whole(self) -> None:
        data = contract.encode_escrow_id_call("release", ESCROW_ID)
        assert data.endswith(ESCROW_ID[2:])
        assert len(data) == 2 + 8 + 64

    def test_encoding_refuses_a_function_it_does_not_match(self) -> None:
        """`dispute(bytes32,string)` encoded as a lone bytes32 is well formed,
        wrong, and accepted by a wallet, so the caller would sign a transaction
        that does something other than what they were shown."""
        with pytest.raises(ValueError, match="not a single bytes32"):
            contract.encode_escrow_id_call("dispute", ESCROW_ID)

    def test_it_refuses_a_function_that_is_not_in_the_abi(self) -> None:
        with pytest.raises(KeyError):
            contract.encode_escrow_id_call("drainEverything", ESCROW_ID)


class TestEveryActionExplainsItself:
    """A disabled control with no explanation is how somebody concludes that a
    right they hold is not real. That is the whole failure being fixed here."""

    @pytest.mark.parametrize("roles", [[], ["buyer"], ["provider"], ["buyer", "provider"]])
    def test_an_unavailable_action_always_says_why(self, roles) -> None:
        for action in (release_for(roles), refund_for(roles), dispute_for(roles)):
            if not action.available:
                assert action.reason, f"{action.action} refused without a reason"

    @pytest.mark.parametrize("roles", [[], ["buyer"], ["provider"]])
    def test_every_action_says_who_may_take_it(self, roles) -> None:
        for action in (release_for(roles), refund_for(roles), dispute_for(roles)):
            assert action.who and len(action.who) > 20, action.action
