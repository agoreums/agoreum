"""The operational surface: who may use it, and what it can see.

Built because several things the platform can already do had no way to be done.
Suppressing an address is permanent until a human lifts it, and there was no way
for a human to lift it. A dispute can be decided, and there was no way to find one
waiting. Both were reachable only by opening a database session against
production, which works for one person and does not survive a second.

Authority here is an address the chain already recognises, matching how the
arbiter is identified. Authority that lives in two places drifts apart the moment
either is edited, and an API that authorises somebody the chain does not is a
second, weaker truth about who is in charge.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.enums import OrderStatus
from app.modules.notifications.models import EmailSuppression
from app.modules.orders.models import Escrow, Order
from app.modules.users.models import User

logger = get_logger(__name__)


def _matches(address: str | None, configured: str | None) -> bool:
    if not configured or not address:
        return False
    return address.lower() == configured.lower()


def is_platform_admin(user: User) -> bool:
    """Whether this account may use the operational surface.

    Unset configuration means nobody, never everybody. A deployment that forgets
    to set an admin address should be closed, not wide open.
    """
    return _matches(user.primary_address, settings.ESCROW_ADMIN_ADDRESS)


async def open_disputes(db: AsyncSession, *, limit: int = 50) -> list[dict]:
    """Disputes waiting for a decision, oldest first.

    Oldest first because a queue worked newest first leaves the person who has
    waited longest waiting longer, and every row here is somebody's money held
    while they wait.

    Undecided only. A dispute that has been decided but not yet settled is not
    waiting on the arbiter, it is waiting on a transaction, and mixing the two
    would make the queue a list of things that mostly need nothing.
    """
    rows = (
        await db.execute(
            select(Order, Escrow)
            .join(Escrow, Escrow.order_id == Order.id)
            .where(
                Order.status == OrderStatus.DISPUTED,
                Escrow.dispute_resolved_at.is_(None),
            )
            .order_by(Escrow.disputed_at)
            .limit(limit)
        )
    ).all()

    now = datetime.now(UTC)
    out = []
    for order, escrow in rows:
        waiting = (
            int((now - escrow.disputed_at).total_seconds() // 3600)
            if escrow.disputed_at
            else None
        )
        out.append(
            {
                "order_id": order.id,
                "order_reference": order.reference,
                "amount": escrow.amount,
                "currency": order.currency,
                "disputed_at": escrow.disputed_at,
                "hours_waiting": waiting,
                "reason": escrow.dispute_reason,
            }
        )
    return out


async def list_suppressions(db: AsyncSession, *, limit: int = 100) -> list[dict]:
    """Addresses the platform refuses to mail, newest first."""
    rows = (
        await db.execute(
            select(EmailSuppression)
            .order_by(EmailSuppression.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "email": r.email,
            "reason": r.reason,
            "detail": r.detail,
            "created_at": r.created_at,
        }
        for r in rows
    ]
