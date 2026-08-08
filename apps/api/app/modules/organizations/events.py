"""Organization events worth telling somebody about.

Same rule as the notification events module it mirrors: nothing here may raise
into its caller. An invitation that is recorded but whose notification failed is
recoverable, since the invitee sees it in their list either way. An invitation
that failed to record because the notification did is not.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.enums import NotificationCategory
from app.modules.notifications import events as notification_events
from app.modules.organizations.models import Organization, OrganizationInvitation
from app.modules.users.models import User

logger = get_logger(__name__)


async def organization_invitation_sent(
    db: AsyncSession,
    *,
    org: Organization,
    invitation: OrganizationInvitation,
    invitee: User,
) -> None:
    """Tell somebody they have been invited to join an organization.

    Categorised ORDER rather than SECURITY, so it respects the recipient's
    channel preferences. It is an offer, not a warning, and a person who has
    turned off organization mail should not be forced to receive it.

    The organization's name is attacker-controlled in the sense that anyone can
    create an organization and name it, then invite a stranger. It is placed in
    the body as quoted data rather than woven into a sentence that reads as our
    own words, for the same reason the sign-in notice quotes a user agent.
    """
    from app.core.config import settings

    name = " ".join((org.name or "").split())[:80] or org.slug

    await notification_events._safe_notify(
        db,
        user_id=invitee.id,
        category=NotificationCategory.ORDER,
        event_type="organization.invitation",
        message_key="organization.invitation",
        message_params={"role": invitation.role.value, "name": name},
        action_url=f"{settings.APP_URL.rstrip('/')}/settings/organizations",
    )
