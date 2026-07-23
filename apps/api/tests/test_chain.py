"""Chain client, ABI binding, and indexer tests.

Tests marked `anvil` run against a local Anvil node with a genuinely deployed
AgoreumEscrow. They exercise real EVM execution and real logs — nothing about
the chain is mocked, because a mocked chain would prove nothing about whether
the platform can read the one it actually settles on.

Start the fixture chain with:

    python scripts/anvil_fixture.py

Tests skip cleanly when it is not running.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from app.chain import escrow as contract
from app.chain.client import ChainClient

# Applied per-class: the ABI binding tests are synchronous and need no loop.
asyncio_test = pytest.mark.asyncio

FIXTURE_PATH = Path(
    os.environ.get("ANVIL_FIXTURE", "") or Path(__file__).parent / "anvil_fixture.json"
)


def _fixture() -> dict:
    if not FIXTURE_PATH.exists():
        pytest.skip(f"no Anvil fixture at {FIXTURE_PATH}")
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def deployment() -> dict:
    return _fixture()


@pytest.fixture
async def client(deployment: dict):
    c = ChainClient(deployment["rpc"], chain_id=31337)
    try:
        async with c:
            await c.chain_id()
            yield c
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Anvil unreachable: {type(exc).__name__}")


# --- ABI binding (no chain needed) ------------------------------------------


class TestAbiBinding:
    def test_abi_loads_with_expected_events(self) -> None:
        events = {e["name"] for e in contract.load_abi() if e["type"] == "event"}
        assert {
            "EscrowCreated",
            "EscrowReleased",
            "EscrowRefunded",
            "EscrowDisputed",
            "EscrowSettled",
        } <= events

    def test_escrow_id_round_trips_with_order_id(self) -> None:
        """The link between an order and its on-chain escrow must be reversible,
        so the two can always be reconciled without a stored mapping."""
        import uuid

        order_id = str(uuid.uuid4())
        escrow_id = contract.escrow_id_for_order(order_id)

        assert escrow_id.startswith("0x")
        assert len(escrow_id) == 66  # 0x + 32 bytes
        assert contract.order_id_from_escrow_id(escrow_id) == order_id

    def test_escrow_id_is_deterministic(self) -> None:
        order_id = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
        assert contract.escrow_id_for_order(order_id) == contract.escrow_id_for_order(
            order_id
        )

    @pytest.mark.parametrize(
        ("amount", "expected"),
        [
            ("25.50", 25_500_000),
            ("0.000001", 1),
            ("1000", 1_000_000_000),
            ("0.1", 100_000),
        ],
    )
    def test_amounts_convert_exactly(self, amount: str, expected: int) -> None:
        assert contract.to_base_units(Decimal(amount)) == expected
        assert contract.from_base_units(expected) == Decimal(amount)

    def test_sub_unit_precision_is_rejected_not_truncated(self) -> None:
        """Silently dropping a fraction of a payment is a correctness bug that
        only shows up in someone's balance."""
        with pytest.raises(ValueError, match="decimal places"):
            contract.to_base_units(Decimal("1.0000001"))

    def test_contract_address_raises_when_unconfigured(self, monkeypatch) -> None:
        from app.core.config import settings

        monkeypatch.setattr(settings, "ESCROW_CONTRACT_ADDRESS", None)
        assert contract.is_configured() is False
        with pytest.raises(contract.EscrowNotConfiguredError):
            contract.contract_address()

    def test_address_comes_from_configuration_not_code(self, monkeypatch) -> None:
        """Wiring in a freshly deployed contract must be an environment change."""
        from app.core.config import settings

        monkeypatch.setattr(
            settings, "ESCROW_CONTRACT_ADDRESS", "0x" + "AB" * 20
        )
        assert contract.contract_address() == "0x" + "ab" * 20

    def test_unknown_log_is_skipped_not_raised(self) -> None:
        """The contract emits inherited events the platform ignores; an indexer
        must not stall on them."""
        assert contract.decode_log({"topics": ["0x" + "ff" * 32], "data": "0x"}) is None
        assert contract.decode_log({"topics": []}) is None


# --- Against a real chain ---------------------------------------------------


@asyncio_test
class TestChainClient:
    async def test_reads_chain_id_and_head(self, client: ChainClient) -> None:
        assert await client.chain_id() == 31337
        assert await client.block_number() > 0

    async def test_verify_network_rejects_a_mismatch(self, deployment: dict) -> None:
        """A misconfigured endpoint pointing at the wrong network would let the
        platform record settlement that never happened on the chain it claims."""
        from app.chain.client import ChainUnavailableError

        async with ChainClient(deployment["rpc"], chain_id=8453) as wrong:
            with pytest.raises(ChainUnavailableError, match="chain"):
                await wrong.verify_network()

    async def test_receipt_of_a_real_transaction(
        self, client: ChainClient, deployment: dict
    ) -> None:
        receipt = await client.get_receipt(deployment["createTx"])

        assert receipt is not None
        assert receipt.succeeded
        assert receipt.block_number > 0
        assert receipt.logs

    async def test_unknown_transaction_returns_none_not_failure(
        self, client: ChainClient
    ) -> None:
        """Pending and rejected are different facts and must not collapse."""
        assert await client.get_receipt("0x" + "11" * 32) is None

    async def test_confirmations_increase_with_depth(
        self, client: ChainClient, deployment: dict
    ) -> None:
        create = await client.get_receipt(deployment["createTx"])
        release = await client.get_receipt(deployment["releaseTx"])

        assert await client.confirmations_for(create) > await client.confirmations_for(
            release
        )

    async def test_canonical_check_passes_for_a_live_block(
        self, client: ChainClient, deployment: dict
    ) -> None:
        receipt = await client.get_receipt(deployment["createTx"])
        assert await client.is_canonical(receipt) is True

    async def test_canonical_check_fails_for_a_foreign_block_hash(
        self, client: ChainClient, deployment: dict
    ) -> None:
        """This is what distinguishes a settled transaction from a reorged one."""
        from dataclasses import replace

        receipt = await client.get_receipt(deployment["createTx"])
        orphaned = replace(receipt, block_hash="0x" + "ab" * 32)

        assert await client.is_canonical(orphaned) is False


@asyncio_test
class TestEventDecoding:
    async def test_decodes_real_escrow_created_log(
        self, client: ChainClient, deployment: dict
    ) -> None:
        logs = await client.get_logs(address=deployment["escrow"], from_block=0)
        events = [contract.decode_log(log) for log in logs]
        created = next(e for e in events if e and e.name == "EscrowCreated")

        assert created.escrow_id == deployment["escrowId"]
        assert created.args["buyer"].lower() == deployment["buyer"].lower()
        assert created.args["provider"].lower() == deployment["provider"].lower()
        assert contract.from_base_units(created.args["amount"]) == Decimal("25.500000")
        assert created.args["feeBps"] == 250

    async def test_decodes_real_release_log_with_exact_fee_split(
        self, client: ChainClient, deployment: dict
    ) -> None:
        """The amounts must reconcile to the deposit exactly — no value created
        or destroyed by the decoding path."""
        logs = await client.get_logs(address=deployment["escrow"], from_block=0)
        events = [contract.decode_log(log) for log in logs]
        released = next(e for e in events if e and e.name == "EscrowReleased")

        provider_amount = contract.from_base_units(released.args["providerAmount"])
        fee = contract.from_base_units(released.args["feeAmount"])

        assert provider_amount == Decimal("24.862500")
        assert fee == Decimal("0.637500")
        assert provider_amount + fee == Decimal("25.500000")

    async def test_every_decoded_event_carries_its_provenance(
        self, client: ChainClient, deployment: dict
    ) -> None:
        """Block hash and log index are what make reorg detection and
        idempotence possible."""
        logs = await client.get_logs(address=deployment["escrow"], from_block=0)

        for log in logs:
            event = contract.decode_log(log)
            if event is None:
                continue
            assert event.tx_hash.startswith("0x")
            assert event.block_hash.startswith("0x")
            assert event.block_number > 0
            assert event.log_index >= 0


@asyncio_test
class TestOnChainState:
    async def test_reads_escrow_struct_back_from_the_contract(
        self, client: ChainClient, deployment: dict
    ) -> None:
        data = contract.encode_get_escrow(deployment["escrowId"])
        result = await client.call(to=deployment["escrow"], data=data)
        state = contract.decode_get_escrow(result)

        assert state.exists
        assert state.status == contract.OnChainStatus.RELEASED
        assert state.amount == Decimal("25.500000")
        assert state.released == Decimal("25.500000")
        assert state.refunded == Decimal("0.000000")
        assert state.outstanding == Decimal("0.000000")

    async def test_solvency_invariant_holds_on_chain(
        self, client: ChainClient, deployment: dict
    ) -> None:
        """The same invariant the database enforces, verified against the
        contract that actually holds the money."""
        data = contract.encode_get_escrow(deployment["escrowId"])
        state = contract.decode_get_escrow(
            await client.call(to=deployment["escrow"], data=data)
        )

        assert state.released + state.refunded <= state.amount

    async def test_unknown_escrow_reads_as_nonexistent(
        self, client: ChainClient, deployment: dict
    ) -> None:
        data = contract.encode_get_escrow("0x" + "cd" * 32)
        state = contract.decode_get_escrow(
            await client.call(to=deployment["escrow"], data=data)
        )

        assert state.exists is False
        assert state.status == contract.OnChainStatus.NONE
        assert state.amount == Decimal("0")
