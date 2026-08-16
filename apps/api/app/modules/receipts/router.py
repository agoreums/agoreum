"""Receipt endpoints: one per order, plus the key needed to check them."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter

from app.api.deps import DbSession, OrdersRead
from app.modules.orders import service as orders
from app.modules.receipts import service as receipts

router = APIRouter(tags=["receipts"])

# The key document is public and unauthenticated on purpose. A verifier checking
# somebody else's receipt is exactly the person who has no account here, and
# requiring a credential to fetch a public key would make the receipts
# unverifiable by the only people who need to verify them.
well_known = APIRouter(tags=["receipts"])


@well_known.get(
    "/.well-known/agoreum-receipts.json",
    include_in_schema=False,
    summary="Public keys for verifying settlement receipts",
)
async def receipt_keys() -> dict[str, Any]:
    return receipts.public_key_document()


@router.get(
    "/orders/{order_id}/receipt",
    summary="A signed, independently checkable record of settlement",
)
async def order_receipt(
    order_id: uuid.UUID, principal: OrdersRead, db: DbSession
) -> dict[str, Any]:
    """Issued only once the escrow has actually settled.

    Scoped to a party of the order rather than public, because the receipt
    names both counterparties and their addresses. The verification path is
    public: anyone given a receipt can check it against the published key and
    the chain without an account here.
    """
    order = await orders.require_visible_order(db, order_id, user=principal.user)
    receipt = await receipts.build(db, order_id=order.id)
    return receipt.as_dict()
