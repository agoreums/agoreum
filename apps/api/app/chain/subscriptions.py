"""Binding to the AgoreumSubscriptions contract.

Same discipline as the escrow binding: the address is configuration, never a
constant, and the ABI is the compiled artefact both backend and frontend read, so
a contract change cannot leave one side decoding a stale shape.

Subscription events are keyed by (subscriber, planId) rather than a single id, so
the decoder here returns the raw decoded args and lets the indexer interpret them.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from eth_abi import decode as abi_decode
from eth_utils import event_abi_to_log_topic

from app.chain.escrow import from_base_units, to_base_units  # token-generic helpers
from app.core.config import settings
from app.core.errors import AgoreumError
from app.core.logging import get_logger

logger = get_logger(__name__)

# app/chain/subscriptions.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_ABI_PATH = REPO_ROOT / "packages" / "contracts" / "AgoreumSubscriptions.abi.json"

__all__ = [
    "SubscriptionsNotConfiguredError",
    "DecodedEvent",
    "contract_address",
    "is_configured",
    "load_abi",
    "topic_to_event",
    "event_topic",
    "decode_log",
    "from_base_units",
    "to_base_units",
]


class SubscriptionsNotConfiguredError(AgoreumError):
    """No subscription contract address is configured for this environment."""

    status_code = 503
    code = "subscriptions_not_configured"
    message = (
        "On-chain subscriptions are not available: no subscription contract is "
        "configured for this network."
    )


def abi_path() -> Path:
    return (
        Path(settings.SUBSCRIPTIONS_ABI_PATH)
        if settings.SUBSCRIPTIONS_ABI_PATH
        else _DEFAULT_ABI_PATH
    )


@lru_cache(maxsize=1)
def load_abi() -> list[dict[str, Any]]:
    path = abi_path()
    if not path.exists():
        raise RuntimeError(
            f"Subscription ABI not found at {path}. Run `forge build` and export it."
        )
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _events_by_name() -> dict[str, dict[str, Any]]:
    return {e["name"]: e for e in load_abi() if e["type"] == "event"}


@lru_cache(maxsize=1)
def topic_to_event() -> dict[str, str]:
    return {
        "0x" + event_abi_to_log_topic(event).hex(): name
        for name, event in _events_by_name().items()
    }


def event_topic(name: str) -> str:
    event = _events_by_name().get(name)
    if event is None:
        raise KeyError(f"No such event in the ABI: {name}")
    return "0x" + event_abi_to_log_topic(event).hex()


def contract_address() -> str:
    address = settings.SUBSCRIPTIONS_CONTRACT_ADDRESS
    if not address:
        raise SubscriptionsNotConfiguredError()
    return address.lower()


def is_configured() -> bool:
    return bool(settings.SUBSCRIPTIONS_CONTRACT_ADDRESS)


# --- Event decoding ---------------------------------------------------------


@dataclass(frozen=True)
class DecodedEvent:
    name: str
    args: dict[str, Any]
    block_number: int
    block_hash: str
    tx_hash: str
    log_index: int


def _decode_indexed(type_: str, topic: str) -> Any:
    raw = bytes.fromhex(topic[2:] if topic.startswith("0x") else topic)
    if type_ == "address":
        return "0x" + raw[-20:].hex()
    if type_ == "bytes32":
        return "0x" + raw.hex()
    if type_.startswith(("uint", "int")):
        return int.from_bytes(raw, "big")
    return "0x" + raw.hex()


def _as_int(value: int | str) -> int:
    return int(value, 16) if isinstance(value, str) else int(value)


def decode_log(log: dict[str, Any]) -> DecodedEvent | None:
    """Decode one contract log, or None if it is an event we do not act on.

    Inherited events (role changes, pause, plan admin) decode fine but are simply
    not returned as actionable if we do not recognise them; the indexer skips
    anything it is not looking for rather than stalling.
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
            args[field["name"]] = "0x" + value.hex() if isinstance(value, bytes) else value

    return DecodedEvent(
        name=name,
        args=args,
        block_number=_as_int(log["blockNumber"]),
        block_hash=log["blockHash"],
        tx_hash=log["transactionHash"],
        log_index=_as_int(log["logIndex"]),
    )
