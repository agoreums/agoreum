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
class FakeOrder:
    escrow: FakeEscrow | None = field(default_factory=FakeEscrow)


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
