"""Shared column types and domain primitives.

These exist so that concepts with strict on-chain semantics — EVM addresses,
token amounts, transaction hashes — are represented one way across every table
rather than being re-invented per module.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from sqlalchemy import CHAR, Numeric, String, TypeDecorator
from sqlalchemy.engine import Dialect

# --- EVM primitives ---------------------------------------------------------

EVM_ADDRESS_LENGTH = 42  # "0x" + 20 bytes hex
TX_HASH_LENGTH = 66  # "0x" + 32 bytes hex

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TX_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


def is_evm_address(value: str) -> bool:
    return bool(_ADDRESS_RE.match(value))


def is_tx_hash(value: str) -> bool:
    return bool(_TX_HASH_RE.match(value))


class EthereumAddress(TypeDecorator[str]):
    """An EVM address, normalised to lowercase on write.

    Addresses are case-insensitive on-chain but EIP-55 checksums vary by source.
    Storing one canonical casing is what makes uniqueness constraints and lookups
    correct — otherwise the same wallet could register twice under different casing.
    """

    impl = CHAR(EVM_ADDRESS_LENGTH)
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if not is_evm_address(value):
            raise ValueError(f"Not a valid EVM address: {value!r}")
        return value.lower()

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        return value


class TransactionHash(TypeDecorator[str]):
    """A 32-byte transaction hash, normalised to lowercase on write."""

    impl = CHAR(TX_HASH_LENGTH)
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if not is_tx_hash(value):
            raise ValueError(f"Not a valid transaction hash: {value!r}")
        return value.lower()

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        return value


class LowercaseString(TypeDecorator[str]):
    """A string stored casefolded, for case-insensitive uniqueness (emails, slugs)."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        return value.strip().lower() if value is not None else None

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        return value


# --- Money ------------------------------------------------------------------

# USDC has 6 decimals. Amounts are stored as exact NUMERIC, never as float:
# binary floating point cannot represent decimal money exactly, and this column
# is the basis of what people get paid.
TOKEN_DECIMALS = 6
TOKEN_PRECISION = 38  # comfortably exceeds any uint256 value we will settle

TokenAmount = Numeric(precision=TOKEN_PRECISION, scale=TOKEN_DECIMALS, asdecimal=True)


def to_base_units(amount: Decimal, decimals: int = TOKEN_DECIMALS) -> int:
    """Convert a human-readable token amount to integer base units for the chain."""
    return int(amount.scaleb(decimals).to_integral_value())


def from_base_units(units: int | str, decimals: int = TOKEN_DECIMALS) -> Decimal:
    """Convert integer base units from the chain to a human-readable amount."""
    return Decimal(units).scaleb(-decimals)


def _unused(*_args: Any) -> None:  # pragma: no cover - typing helper
    return None
