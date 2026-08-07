"""allow a suppressed email delivery to have no destination

A delivery row records what happened to one notification on one channel,
including the messages that deliberately went nowhere. The email channel is
suppressed when the recipient has no address at all, has not proven the one they
gave, or is on the bounce list, and in the first of those there is no destination
to record.

The old constraint required one regardless, so the insert failed and the error
propagated out of the notification code into whatever caused it. Sign-in returned
503 for every returning account without an email address.

The guarantee worth keeping is the one about mail that actually left: anything not
suppressed still has to say where it went.

Revision ID: c5e7a9b1d3f4
Revises: b4d6f8a0c2e3
Create Date: 2026-08-07 21:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c5e7a9b1d3f4"
down_revision: str | None = "b4d6f8a0c2e3"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

TABLE = "notification_deliveries"
NAME = "ck_notification_deliveries_email_requires_destination"


def upgrade() -> None:
    op.drop_constraint(NAME, TABLE, type_="check")
    op.create_check_constraint(
        "email_requires_destination",
        TABLE,
        "channel <> 'email' OR destination IS NOT NULL OR status = 'suppressed'",
    )


def downgrade() -> None:
    # Rows the old constraint forbids have to go before it can be restored, or
    # the downgrade fails on existing data. They are records of mail that was
    # never sent, so nothing is lost that could be recovered by keeping them.
    op.execute(
        f"DELETE FROM {TABLE} "  # noqa: S608 - table name is a literal above
        "WHERE channel = 'email' AND destination IS NULL"
    )
    op.drop_constraint(NAME, TABLE, type_="check")
    op.create_check_constraint(
        "email_requires_destination",
        TABLE,
        "channel <> 'email' OR destination IS NOT NULL",
    )
