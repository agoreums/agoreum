"""Signed settlement receipts: a portable pointer to on-chain evidence.

The problem this exists to solve is specific and measured. An empirical study of
ERC-8004 across three chains found that between 98.7% and 100% of on-chain
reputation records carry no proof of payment and no link to a task, and that
moving an agent's score costs fractions of a cent. Reputation in that ecosystem
is assertion, and assertion is cheap.

Agoreum's reputation is computed only from orders that settled through escrow,
which fixes the evidence problem *for anyone who trusts Agoreum's database*.
That is a smaller claim than it sounds. A receipt closes the gap by making a
settled order checkable by somebody who trusts nothing we say.

**What a receipt is, and what it deliberately is not.**

It is not proof that a payment happened. Our signature cannot make that true, and
a receipt whose value rests on "trust Agoreum" would be worth roughly what the
ERC-8004 records are worth.

It is an attributable claim plus the coordinates to check it. The signature binds
Agoreum to a specific statement about a specific transaction, so a false receipt
is a forgery we can be held to rather than a number that appeared. The chain
remains the authority, and every receipt says so and carries the transaction hash,
block number, contract address and chain id needed to verify it independently.

That distinction is the whole design. A verifier that checks only our signature
has learned that we said something. A verifier that follows the transaction hash
has learned what happened.

**The signing key holds no funds and no on-chain authority.** It is an Ed25519
key used for nothing else. Compromise of it would let an attacker forge claims,
which is serious, and would not let them move a single cent, which is the
property that matters most. It is deliberately not the deployer key, not an
arbiter key, and not any key the contracts recognise, and that separation is
asserted by a test rather than left as an intention.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError
from app.db.enums import EscrowStatus, TransactionType
from app.modules.orders.models import Order

RECEIPT_TYPE = "https://agoreum.xyz/schemas/settlement-receipt-v1"

# Only these mean money actually moved and stopped moving. A funded escrow is
# not a settlement: the money is committed and its destination is still open.
SETTLED_ESCROW_STATUSES = frozenset({EscrowStatus.RELEASED, EscrowStatus.REFUNDED})


@dataclass(frozen=True)
class Receipt:
    payload: dict[str, Any]
    signature: str | None
    key_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "receipt": self.payload,
            "signature": self.signature,
            "key_id": self.key_id,
            "algorithm": "ed25519" if self.signature else None,
        }


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def canonical(payload: dict[str, Any]) -> bytes:
    """The exact bytes that are signed.

    Sorted keys and no insignificant whitespace, so a verifier reconstructing
    the payload from parsed JSON gets byte-identical input. Without a canonical
    form, a receipt that is genuinely valid fails verification for anybody whose
    JSON library orders keys differently, and the natural response to that is to
    stop checking signatures.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _signing_key():
    """The Ed25519 key, or None when none is configured.

    Absent by default rather than generated on demand. A key invented at startup
    would change on every restart, which would silently invalidate every receipt
    already issued and produce exactly the "signature does not verify" noise that
    teaches people to ignore signatures.
    """
    secret = getattr(settings, "RECEIPT_SIGNING_KEY", None)
    if not secret:
        return None
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(secret + "=="))


def public_key_document() -> dict[str, Any]:
    """The key a verifier needs, in JWK form."""
    key = _signing_key()
    if key is None:
        return {"keys": [], "note": "No receipt signing key is configured."}

    from cryptography.hazmat.primitives import serialization

    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return {
        "keys": [
            {
                "kty": "OKP",
                "crv": "Ed25519",
                "use": "sig",
                "alg": "EdDSA",
                "kid": key_id(),
                "x": _b64(raw),
            }
        ],
        "verification": (
            "Verify the signature over the canonical JSON of the receipt object "
            "(sorted keys, no whitespace). Then verify the settlement itself on "
            "chain using transaction_hash and chain_id. The signature attests "
            "that Agoreum made this claim; the chain is what makes it true."
        ),
    }


def key_id() -> str | None:
    key = _signing_key()
    if key is None:
        return None
    from cryptography.hazmat.primitives import serialization

    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return _b64(raw)[:16]


async def build(db: AsyncSession, *, order_id: Any) -> Receipt:
    """Build a receipt for a settled order, or refuse to."""
    from app.modules.orders.models import Escrow

    order = (
        await db.execute(select(Order).where(Order.id == order_id))
    ).scalar_one_or_none()
    if order is None:
        raise NotFoundError("No such order.")

    escrow = (
        await db.execute(select(Escrow).where(Escrow.order_id == order.id))
    ).scalar_one_or_none()
    if escrow is None or escrow.status not in SETTLED_ESCROW_STATUSES:
        # Refused rather than issued as "pending". A receipt that can exist
        # before settlement is a receipt whose presence means nothing, and the
        # entire point is that its presence means something.
        raise ConflictError(
            "This order has not settled on chain, so there is nothing to attest.",
            code="not_settled",
        )

    tx = await _settlement_transaction(db, escrow_id=escrow.id)

    payload: dict[str, Any] = {
        "type": RECEIPT_TYPE,
        "issuer": "agoreum.xyz",
        "issued_at": datetime.now(UTC).isoformat(),
        "order": {
            "id": str(order.id),
            "reference": order.reference,
            "status": getattr(order.status, "value", order.status),
        },
        "settlement": {
            "chain_id": escrow.chain_id,
            "network": _network_name(escrow.chain_id),
            "is_testnet": escrow.chain_id != 8453,
            "escrow_contract": escrow.contract_address,
            "onchain_escrow_id": escrow.onchain_escrow_id,
            "status": getattr(escrow.status, "value", escrow.status),
            "token_address": escrow.token_address,
            "token_symbol": escrow.token_symbol,
            "amount": str(escrow.amount),
            "released_amount": str(escrow.released_amount),
            "refunded_amount": str(escrow.refunded_amount),
            "fee_amount": str(escrow.fee_amount),
            "buyer_address": escrow.buyer_address,
            "provider_address": escrow.provider_address,
            "transaction_hash": tx.tx_hash if tx else None,
            "block_number": tx.block_number if tx else None,
        },
        # Carried in the document rather than in documentation, for the same
        # reason the MCP tools carry it: whoever reads this may be software.
        "verify": {
            "authority": "chain",
            "instructions": (
                "This receipt is a signed claim, not proof. Verify the signature "
                "against the published key, then verify transaction_hash on the "
                "named chain. If the two disagree, the chain is correct."
            ),
        },
    }

    key = _signing_key()
    if key is None:
        # An unsigned receipt is still useful: it carries the coordinates. It is
        # returned without a signature rather than with a fake one, and the
        # absence is visible.
        return Receipt(payload=payload, signature=None, key_id=None)

    return Receipt(
        payload=payload,
        signature=_b64(key.sign(canonical(payload))),
        key_id=key_id(),
    )


async def _settlement_transaction(db: AsyncSession, *, escrow_id: Any):
    from app.modules.orders.models import ChainTransaction

    rows = (
        await db.execute(
            select(ChainTransaction)
            .where(ChainTransaction.escrow_id == escrow_id)
            .order_by(ChainTransaction.block_number.desc().nullslast())
        )
    ).scalars().all()

    # A dispute settlement lands as a release: `settleDispute` pays the escrow's
    # own buyer and provider, so the transaction that ends the escrow is the one
    # worth pointing at either way.
    settling = {TransactionType.ESCROW_RELEASE, TransactionType.ESCROW_REFUND}
    for row in rows:
        if row.tx_type in settling:
            return row
    return None


def _network_name(chain_id: int | None) -> str:
    return {8453: "base", 84532: "base-sepolia"}.get(chain_id or 0, f"chain-{chain_id}")
