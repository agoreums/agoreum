"""Binding to the AgoreumEscrow contract.

The contract address is **configuration, never a constant**: it is read from
`ESCROW_CONTRACT_ADDRESS` at call time, so pointing the platform at a freshly
deployed contract is an environment change and nothing more. Nothing in this
package embeds an address.

The ABI is loaded from `packages/contracts/AgoreumEscrow.abi.json`, which is
generated from the compiled artefact. Backend and frontend consume the same
file, so a contract change cannot leave one side decoding a stale shape.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from eth_abi import decode as abi_decode
from eth_utils import event_abi_to_log_topic, function_abi_to_4byte_selector

from app.core.config import settings
from app.core.errors import AgoreumError
from app.core.logging import get_logger

logger = get_logger(__name__)

# app/chain/escrow.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_ABI_PATH = REPO_ROOT / "packages" / "contracts" / "AgoreumEscrow.abi.json"


def abi_path() -> Path:
    """Where to read the contract ABI from.

    Configuration wins over the repo-relative default: the container image does
    not preserve the source tree depth, so the default lands in the wrong place
    there and the image supplies CONTRACT_ABI_PATH instead.
    """
    return Path(settings.CONTRACT_ABI_PATH) if settings.CONTRACT_ABI_PATH else _DEFAULT_ABI_PATH

# USDC uses 6 decimals on every network Agoreum settles on.
TOKEN_DECIMALS = 6


class EscrowNotConfiguredError(AgoreumError):
    """No escrow contract address is configured for this environment."""

    status_code = 503
    code = "escrow_not_configured"
    message = (
        "On-chain settlement is not available: no escrow contract is configured "
        "for this network."
    )


class OnChainStatus(IntEnum):
    """Mirrors AgoreumEscrow.Status. Order is part of the ABI contract."""

    NONE = 0
    FUNDED = 1
    RELEASED = 2
    REFUNDED = 3
    DISPUTED = 4
    SETTLED = 5


@lru_cache(maxsize=1)
def load_abi() -> list[dict[str, Any]]:
    path = abi_path()
    if not path.exists():
        raise RuntimeError(
            f"Contract ABI not found at {path}. Run `forge build` and export it."
        )
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _events_by_name() -> dict[str, dict[str, Any]]:
    return {e["name"]: e for e in load_abi() if e["type"] == "event"}


@lru_cache(maxsize=1)
def _functions_by_name() -> dict[str, dict[str, Any]]:
    return {f["name"]: f for f in load_abi() if f["type"] == "function"}


@lru_cache(maxsize=1)
def topic_to_event() -> dict[str, str]:
    """Maps a log's topic0 to the event name it identifies."""
    return {
        "0x" + event_abi_to_log_topic(event).hex(): name
        for name, event in _events_by_name().items()
    }


def event_topic(name: str) -> str:
    event = _events_by_name().get(name)
    if event is None:
        raise KeyError(f"No such event in the ABI: {name}")
    return "0x" + event_abi_to_log_topic(event).hex()


def function_selector(name: str) -> str:
    fn = _functions_by_name().get(name)
    if fn is None:
        raise KeyError(f"No such function in the ABI: {name}")
    return "0x" + function_abi_to_4byte_selector(fn).hex()


def contract_address() -> str:
    """The configured escrow address, or raise.

    Raising rather than returning None is deliberate: a caller that reaches here
    intends to touch the chain, and proceeding without an address would mean
    silently doing nothing while appearing to succeed.
    """
    address = settings.ESCROW_CONTRACT_ADDRESS
    if not address:
        raise EscrowNotConfiguredError()
    return address.lower()


def is_configured() -> bool:
    """Whether on-chain settlement is available in this environment."""
    return bool(settings.ESCROW_CONTRACT_ADDRESS)


# --- Amount conversion ------------------------------------------------------


def to_base_units(amount: Decimal) -> int:
    """Human-readable USDC to integer base units.

    Rejects anything with more precision than the token can represent instead of
    truncating: quietly dropping a fraction of a payment is a correctness bug
    that only shows up in someone's balance.
    """
    scaled = amount.scaleb(TOKEN_DECIMALS)
    if scaled != scaled.to_integral_value():
        raise ValueError(
            f"{amount} has more than {TOKEN_DECIMALS} decimal places and cannot "
            "be represented exactly."
        )
    return int(scaled)


def from_base_units(units: int | str) -> Decimal:
    return Decimal(int(units)).scaleb(-TOKEN_DECIMALS)


# --- Event decoding ---------------------------------------------------------


@dataclass(frozen=True)
class DecodedEvent:
    name: str
    escrow_id: str
    args: dict[str, Any]
    block_number: int
    block_hash: str
    tx_hash: str
    log_index: int


def _decode_indexed(type_: str, topic: str) -> Any:
    """Decode a single indexed topic value."""
    raw = bytes.fromhex(topic[2:] if topic.startswith("0x") else topic)
    if type_ == "address":
        return "0x" + raw[-20:].hex()
    if type_ == "bytes32":
        return "0x" + raw.hex()
    if type_.startswith(("uint", "int")):
        return int.from_bytes(raw, "big")
    # Dynamic indexed types are stored as a hash of their value, not the value.
    return "0x" + raw.hex()


def decode_log(log: dict[str, Any]) -> DecodedEvent | None:
    """Decode one contract log, or None if it is not an event we know.

    Unknown logs are skipped rather than raising: the contract emits inherited
    events (role changes, pause) that the platform does not act on, and an
    indexer must not stall on them.
    """
    topics = log.get("topics") or []
    if not topics:
        return None

    name = topic_to_event().get(topics[0].lower())
    if name is None:
        return None

    event = _events_by_name()[name]
    indexed = [i for i in event["inputs"] if i["indexed"]]
    unindexed = [i for i in event["inputs"] if not i["indexed"]]

    args: dict[str, Any] = {}

    for position, field in enumerate(indexed, start=1):
        if position >= len(topics):
            logger.warning("event_topic_count_mismatch", extra={"event": name})
            return None
        args[field["name"]] = _decode_indexed(field["type"], topics[position])

    data_hex = log.get("data", "0x")
    if unindexed:
        try:
            values = abi_decode(
                [i["type"] for i in unindexed],
                bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex),
            )
        except Exception as exc:
            logger.warning(
                "event_data_decode_failed",
                extra={"event": name, "error_type": type(exc).__name__},
            )
            return None
        for field, value in zip(unindexed, values, strict=True):
            args[field["name"]] = (
                "0x" + value.hex() if isinstance(value, bytes) else value
            )

    escrow_id = args.get("escrowId")
    if escrow_id is None:
        return None

    return DecodedEvent(
        name=name,
        escrow_id=escrow_id if isinstance(escrow_id, str) else "0x" + escrow_id.hex(),
        args=args,
        block_number=int(log["blockNumber"], 16)
        if isinstance(log["blockNumber"], str)
        else log["blockNumber"],
        block_hash=log["blockHash"],
        tx_hash=log["transactionHash"],
        log_index=int(log["logIndex"], 16)
        if isinstance(log["logIndex"], str)
        else log["logIndex"],
    )


# --- Read calls -------------------------------------------------------------


def encode_escrow_id_call(function: str, escrow_id: str) -> str:
    """Calldata for any escrow function whose only argument is the escrow id.

    The ABI is consulted rather than trusted from the name. Encoding a lone
    bytes32 for a function that takes anything else produces calldata that is
    well formed, wrong, and accepted by a wallet, so a caller would sign a
    transaction that does something other than what they were shown. The check
    turns that into an error here instead.
    """
    fn = _functions_by_name().get(function)
    if fn is None:
        raise KeyError(f"No such function in the ABI: {function}")
    types = [i["type"] for i in fn.get("inputs", [])]
    if types != ["bytes32"]:
        raise ValueError(
            f"{function} takes {types or 'no arguments'}, not a single bytes32, "
            "so this encoding would describe a different call than the one made."
        )
    raw = escrow_id[2:] if escrow_id.startswith("0x") else escrow_id
    return function_selector(function) + raw.rjust(64, "0")


def encode_get_escrow(escrow_id: str) -> str:
    """Calldata for `getEscrow(bytes32)`."""
    return encode_escrow_id_call("getEscrow", escrow_id)


@dataclass(frozen=True)
class OnChainEscrow:
    """The contract's own view of an escrow.

    Used to reconcile the database against the chain. Where the two disagree,
    the chain is authoritative, it is the record that actually holds the money.
    """

    buyer: str
    provider: str
    token: str
    amount: Decimal
    released: Decimal
    refunded: Decimal
    fee_bps: int
    delivery_deadline: int
    auto_release_at: int
    status: OnChainStatus

    @property
    def exists(self) -> bool:
        return self.status != OnChainStatus.NONE

    @property
    def outstanding(self) -> Decimal:
        return self.amount - self.released - self.refunded


def decode_get_escrow(result: str) -> OnChainEscrow:
    raw = bytes.fromhex(result[2:] if result.startswith("0x") else result)
    # A struct return is ABI-encoded as a tuple, offset-prefixed.
    (values,) = abi_decode(
        ["(address,address,address,uint256,uint256,uint256,uint256,uint64,uint64,uint8)"],
        raw,
    )
    return OnChainEscrow(
        buyer=values[0].lower(),
        provider=values[1].lower(),
        token=values[2].lower(),
        amount=from_base_units(values[3]),
        released=from_base_units(values[4]),
        refunded=from_base_units(values[5]),
        fee_bps=values[6],
        delivery_deadline=values[7],
        auto_release_at=values[8],
        status=OnChainStatus(values[9]),
    )


# --- Identifier derivation --------------------------------------------------


def escrow_id_for_order(order_id: str) -> str:
    """Derive the on-chain escrow id from an order's UUID.

    Deterministic so the two records can always be reconciled without trusting
    log ordering or storing a mapping that could drift. A UUID is 16 bytes and
    the contract takes bytes32, so it is left-padded, no hashing, which keeps
    the relationship reversible and obvious when reading a block explorer.
    """
    import uuid as _uuid

    value = _uuid.UUID(str(order_id))
    return "0x" + value.bytes.rjust(32, b"\x00").hex()


def order_id_from_escrow_id(escrow_id: str) -> str:
    import uuid as _uuid

    raw = bytes.fromhex(escrow_id[2:] if escrow_id.startswith("0x") else escrow_id)
    return str(_uuid.UUID(bytes=raw[-16:]))
