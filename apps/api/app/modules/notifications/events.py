"""Platform events that warrant telling somebody about.

One place that decides *which* events earn a notification and who receives them,
kept separate from `service.notify`, which only knows how to deliver one.

Two rules govern everything here.

Nothing in this module may raise into its caller. These are invoked from the
chain indexer and from request handlers, and a notification is never worth
failing the thing that caused it: an order must still be marked funded even if
telling the provider fails. Every entry point swallows and logs.

The set of events is deliberately small. Every email is an interruption, and a
platform that mails people about everything trains them to ignore the one message
that mattered. In-app notifications are cheap and get more events; email is
reserved for money moving, a deadline starting, or a security fact.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.enums import NotificationCategory, NotificationChannel, OrgRole
from app.modules.notifications import service as notifications
from app.modules.orders.models import Order
from app.modules.organizations.models import OrganizationMembership
from app.modules.users.models import User

logger = get_logger(__name__)


def _order_url(order: Order) -> str:
    from app.core.config import settings

    return f"{settings.APP_URL.rstrip('/')}/orders/{order.reference}"


async def _provider_owner_ids(db: AsyncSession, *, order: Order) -> list[uuid.UUID]:
    """Every owner of the organization behind the order's agent.

    Ownership is an organization concern, not a single user, so a notification
    about work goes to whoever actually owns the agent rather than to whichever
    person happened to create it.
    """
    agent = order.provider_agent
    if agent is None or agent.org_id is None:
        return []
    rows = await db.execute(
        select(OrganizationMembership.user_id).where(
            OrganizationMembership.org_id == agent.org_id,
            OrganizationMembership.role == OrgRole.OWNER,
        )
    )
    return [row[0] for row in rows]


async def _safe_notify(db: AsyncSession, **kwargs) -> None:
    """Deliver, or log and carry on.

    The swallow is the point. These are called from the indexer, which must keep
    projecting chain state whatever happens here, and from request handlers where
    a failed notification must not undo the user's action.

    The savepoint is what makes the swallow true. Catching an exception does not
    repair a session whose flush already failed: every later statement on it
    raises PendingRollbackError, so the caller's own work dies anyway and the
    handler above merely hides the reason. Rolling back to a savepoint discards
    only what this notification wrote and hands the caller a usable transaction.

    This was not theoretical. A delivery row that violated a check constraint
    took down sign-in with a 503 for every returning account, and the swallow
    here reported nothing.
    """
    try:
        async with db.begin_nested():
            await notifications.notify(db, **kwargs)
    except Exception as exc:  # noqa: BLE001 - see docstring
        logger.warning(
            "notification_failed",
            extra={
                "event_type": kwargs.get("event_type"),
                "user_id": str(kwargs.get("user_id")),
                "error": f"{type(exc).__name__}: {exc}",
            },
        )


# --- Email verification -----------------------------------------------------


async def email_verification_requested(
    db: AsyncSession, *, user: User, token: str
) -> None:
    """The one message that may reach an address nobody has proven yet.

    It has to: proving the address is the entire purpose. Every other
    notification requires `email_verified_at` to be set, enforced in `_deliver`.

    In-app is deliberately excluded. Someone who is already looking at the site
    does not need a copy of their own verification link sitting in their
    notification list, where it would outlive the email and be readable by anyone
    who later opened that session.
    """
    from app.core.config import settings

    link = f"{settings.APP_URL.rstrip('/')}/verify-email?token={token}"
    await _safe_notify(
        db,
        user_id=user.id,
        category=NotificationCategory.SECURITY,
        event_type="account.email_verification",
        title="Confirm your email address",
        body=(
            "Open this link to confirm this address for your Agoreum account. "
            f"It expires in 24 hours.\n\n{link}\n\n"
            "If you did not request this, you can ignore it. Nothing changes "
            "until the link is opened."
        ),
        action_url=link,
        channels=(NotificationChannel.EMAIL,),
        allow_unverified_email=True,
    )


# --- Order lifecycle --------------------------------------------------------


async def order_funded(db: AsyncSession, *, order: Order) -> None:
    """Money is committed on chain. The provider can start work.

    Goes to the provider rather than the buyer: the buyer just performed the
    action and is looking at the result, whereas the provider may not be at the
    site at all, and the delivery window starts now.
    """
    for user_id in await _provider_owner_ids(db, order=order):
        await _safe_notify(
            db,
            user_id=user_id,
            category=NotificationCategory.ORDER,
            event_type="order.funded",
            title=f"Order {order.reference} is funded and ready to start",
            body=(
                f"The buyer has funded escrow for order {order.reference}. "
                "Work can begin, and the delivery window has started."
            ),
            action_url=_order_url(order),
            related_order_id=order.id,
        )


async def order_released(db: AsyncSession, *, order: Order) -> None:
    """Funds released to the provider. Both sides need to know money moved."""
    recipients = [order.buyer_id, *await _provider_owner_ids(db, order=order)]
    for user_id in dict.fromkeys(recipients):
        is_buyer = user_id == order.buyer_id
        await _safe_notify(
            db,
            user_id=user_id,
            category=NotificationCategory.PAYMENT,
            event_type="order.released",
            title=f"Order {order.reference} has been paid out",
            body=(
                f"Escrow for order {order.reference} has been released to the "
                "provider."
                if is_buyer
                else f"Escrow for order {order.reference} has been released to you."
            ),
            action_url=_order_url(order),
            related_order_id=order.id,
        )


async def order_refunded(db: AsyncSession, *, order: Order) -> None:
    """Funds returned to the buyer."""
    recipients = [order.buyer_id, *await _provider_owner_ids(db, order=order)]
    for user_id in dict.fromkeys(recipients):
        is_buyer = user_id == order.buyer_id
        await _safe_notify(
            db,
            user_id=user_id,
            category=NotificationCategory.PAYMENT,
            event_type="order.refunded",
            title=f"Order {order.reference} has been refunded",
            body=(
                f"Escrow for order {order.reference} has been returned to you."
                if is_buyer
                else f"Escrow for order {order.reference} has been returned to "
                "the buyer."
            ),
            action_url=_order_url(order),
            related_order_id=order.id,
        )


async def order_disputed(
    db: AsyncSession, *, order: Order, raised_by_address: str | None
) -> None:
    """A dispute was raised on chain. The other side may not be looking.

    Driven by the chain event rather than the API's dispute-intent record,
    because the on-chain dispute is the authoritative one: it is what an arbiter
    can actually settle, and it can be raised straight from a wallet without
    touching this service at all.

    Only the counterparty is told. The person who raised it already knows, and
    mailing somebody about their own action is how a notification channel loses
    its meaning. `raisedBy` on the event is an address, so it is matched against
    the buyer's address; anyone else is the provider by elimination, since the
    contract only permits those two.
    """
    raiser = (raised_by_address or "").lower()
    buyer_address = (order.buyer.primary_address or "").lower() if order.buyer else ""
    raised_by_buyer = bool(raiser) and raiser == buyer_address

    provider_ids = await _provider_owner_ids(db, order=order)
    recipients = provider_ids if raised_by_buyer else [order.buyer_id]

    for user_id in dict.fromkeys(recipients):
        await _safe_notify(
            db,
            user_id=user_id,
            category=NotificationCategory.ORDER,
            event_type="order.disputed",
            title=f"A dispute was raised on order {order.reference}",
            body=(
                f"The other party has raised a dispute on order {order.reference}. "
                "An arbiter will review it. You can add context from the order page."
            ),
            action_url=_order_url(order),
            related_order_id=order.id,
        )


# --- Security ---------------------------------------------------------------


async def new_session_signin(
    db: AsyncSession,
    *,
    user: User,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    """A sign-in from a session this account has not used before.

    Categorised SECURITY, which `NON_SUPPRESSIBLE` means the recipient cannot
    turn off. That is deliberate: someone must always be able to learn that
    another person signed in as them, whatever their notification preferences
    say.
    """
    where = ip_address or "an unrecognised address"
    device = f" using {user_agent[:120]}" if user_agent else ""
    await _safe_notify(
        db,
        user_id=user.id,
        category=NotificationCategory.SECURITY,
        event_type="account.new_signin",
        title="New sign-in to your Agoreum account",
        body=(
            f"Your wallet was used to sign in from {where}{device}.\n\n"
            "If this was you, nothing further is needed. If it was not, "
            "disconnect the wallet and review your active sessions."
        ),
        action_url=f"{_settings_url()}/security",
    )


def _settings_url() -> str:
    from app.core.config import settings

    return f"{settings.APP_URL.rstrip('/')}/settings"
