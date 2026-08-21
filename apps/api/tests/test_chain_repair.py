"""Repairing a divergence the reconciliation can only report.

`reconcile_order` could name a disagreement between the database and the chain
and nothing could close one. The first settled dispute in production left the
database holding the provider's net where the chain holds the gross, and fixing
the indexer did nothing for the row already written, because events are
processed once.

The property that makes an operator-triggered repair safe is that it copies.
Every figure written is read from the contract in the same call and no argument
could carry a number, so the only reachable outcome is the database agreeing
with the chain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from app.chain import indexer
from app.db.enums import EscrowStatus


@dataclass
class FakeOnChain:
    exists: bool = True
    amount: Decimal = Decimal("2.050000")
    released: Decimal = Decimal("1.025000")
    refunded: Decimal = Decimal("1.025000")
    status: object = field(default=None)


@dataclass
class FakeEscrow:
    amount: Decimal = Decimal("2.050000")
    released_amount: Decimal = Decimal("0.999375")
    refunded_amount: Decimal = Decimal("1.025000")
    status: EscrowStatus = EscrowStatus.RELEASED


@dataclass
class FakeOrder:
    id: object = "616a5318-3d19-464f-9912-dee1f0c0e7ae"
    escrow: FakeEscrow | None = field(default_factory=FakeEscrow)


class FakeSession:
    async def flush(self) -> None:
        return None


@pytest.fixture
def chain(monkeypatch):
    """A contract that reports the figures the real settlement produced."""
    state = FakeOnChain()

    class Status:
        name = "SETTLED"

    state.status = Status()

    monkeypatch.setattr(indexer.contract, "is_configured", lambda: True)
    monkeypatch.setattr(indexer.contract, "contract_address", lambda: "0xabc")
    monkeypatch.setattr(indexer.contract, "escrow_id_for_order", lambda oid: "0xdead")
    monkeypatch.setattr(indexer.contract, "encode_get_escrow", lambda eid: "0x")
    monkeypatch.setattr(indexer.contract, "decode_get_escrow", lambda raw: state)

    class Client:
        async def call(self, **kwargs):
            return "0x"

    return state, Client()


class TestRepairingAgainstTheChain:
    async def test_it_closes_the_divergence_the_first_settlement_left(
        self, chain
    ) -> None:
        """The exact figures from order AGO-DT2TPSZL."""
        _state, client = chain
        order = FakeOrder()
        assert order.escrow.released_amount == Decimal("0.999375")

        result = await indexer.repair_order_from_chain(FakeSession(), client, order)

        assert order.escrow.released_amount == Decimal("1.025000")
        assert result["in_sync"] is True, result
        assert any("released" in line for line in result["repaired"]), result

    async def test_it_writes_nothing_when_already_in_sync(self, chain) -> None:
        """The control. A repair that always writes would pass the test above
        while rewriting rows that were correct."""
        _state, client = chain
        order = FakeOrder(escrow=FakeEscrow(released_amount=Decimal("1.025000")))

        result = await indexer.repair_order_from_chain(FakeSession(), client, order)

        assert result["repaired"] == []
        assert "nothing written" in str(result.get("note", ""))

    async def test_it_only_ever_copies_the_chain(self, chain) -> None:
        """The property that makes this safe to expose at all.

        Whatever the database held, the result is the chain's figure and never
        anything else, so the endpoint cannot be used to author a number.
        """
        state, client = chain
        for wrong in (Decimal("0"), Decimal("999.999999"), Decimal("0.000001")):
            order = FakeOrder(escrow=FakeEscrow(released_amount=wrong))
            await indexer.repair_order_from_chain(FakeSession(), client, order)
            assert order.escrow.released_amount == state.released

    async def test_a_structural_divergence_is_not_papered_over(self, chain) -> None:
        """An escrow the chain does not have is not fixed by copying amounts,
        and saying so beats writing zeroes and calling it repaired."""
        state, client = chain
        state.exists = False
        order = FakeOrder()

        result = await indexer.repair_order_from_chain(FakeSession(), client, order)
        assert result["repaired"] == []
        assert "structural" in str(result.get("note", ""))

    async def test_status_is_left_alone(self, chain) -> None:
        """Amounts are facts the contract holds. Status is a projection this
        application derives, with order state, notifications and reputation
        hanging off it, so copying it across that boundary is a larger claim
        than this endpoint is allowed to make.
        """
        _state, client = chain
        order = FakeOrder()
        before = order.escrow.status
        await indexer.repair_order_from_chain(FakeSession(), client, order)
        assert order.escrow.status == before
