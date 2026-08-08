"""Order events that warrant telling somebody about.

Same rule as the other event modules: nothing here raises into its caller. A
decision that was recorded but whose notification failed is recoverable, because
both parties can see it on the order. A decision that failed to record because a
notification did would be worse.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.enums import NotificationCategory
from app.modules.notifications import events as notification_events
from app.modules.orders.models import Escrow, Order

logger = get_logger(__name__)


async def dispute_decided(
    db: AsyncSession, *, order: Order, escrow: Escrow
) -> None:
    """Tell both parties a decision has been made, before it is executed.

    Sent on the decision rather than on settlement, deliberately. Settlement
    happens when the arbiter's wallet sends the transaction, which may be minutes
    later, and the party who is about to be paid less should not learn of it from
    a balance change.

    The reasoning is not repeated here. It is shown on the order to the two
    parties and the arbiter, and email is not the place to publish an argument
    about somebody's money.
    """
    recipients = [order.buyer_id]
    agent = order.provider_agent
    if agent is not None and agent.org_id is not None:
        from app.modules.notifications.events import _provider_owner_ids

        recipients.extend(await _provider_owner_ids(db, order=order))

    for user_id in dict.fromkeys(recipients):
        await notification_events._safe_notify(
            db,
            user_id=user_id,
            category=NotificationCategory.PAYMENT,
            event_type="order.dispute_decided",
            message_key="order.dispute_decided",
            message_params={"reference": order.reference},
            action_url=_order_url(order),
            related_order_id=order.id,
        )

    logger.info(
        "dispute_decided",
        extra={
            "order_id": str(order.id),
            "resolution": (
                escrow.dispute_resolution.value if escrow.dispute_resolution else None
            ),
        },
    )


def _order_url(order: Order) -> str:
    from app.core.config import settings

    return f"{settings.APP_URL.rstrip('/')}/orders/{order.reference}"
