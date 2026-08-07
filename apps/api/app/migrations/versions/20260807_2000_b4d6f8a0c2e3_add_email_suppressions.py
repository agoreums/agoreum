"""add email suppressions

Addresses the platform must stop mailing, because they hard bounced or their
owner marked a message as spam.

Sending to a known-bad address is the clearest signal a provider has of a sender
who is not paying attention, and the reputation damage lands on every later
message, including the security notices that most need to arrive. A complaint is
also a person saying they do not want this, which is reason enough on its own.

Keyed on the address rather than the user: the same address can belong to
different accounts over time, and it is the mailbox that bounced.

Revision ID: b4d6f8a0c2e3
Revises: a3c5e7f9b1d2
Create Date: 2026-08-07 20:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.types  # noqa: F401

revision: str = "b4d6f8a0c2e3"
down_revision: str | None = "a3c5e7f9b1d2"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_suppressions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", app.db.types.LowercaseString(length=320), nullable=False),
        # Free text rather than an enum: this records what a third party told us,
        # and a provider adding a category should not need a migration to write
        # it down.
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_suppressions")),
        # One row per address. A second bounce for an address already suppressed
        # is not new information.
        sa.UniqueConstraint("email", name=op.f("uq_email_suppressions_email")),
    )
    op.create_index(
        "ix_email_suppressions_created_at",
        "email_suppressions",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_suppressions_created_at", table_name="email_suppressions"
    )
    op.drop_table("email_suppressions")
