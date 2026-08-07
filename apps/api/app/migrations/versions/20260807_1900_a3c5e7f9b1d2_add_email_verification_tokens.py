"""add email verification tokens

Proving control of an email address before the platform will send anything to it.

Until now `email_verified_at` existed on users but was only ever written as NULL:
there was no flow that could set it to a timestamp, so every address on every
profile was unverified and indistinguishable from a verified one. Nothing sends
mail yet, so nothing was exploitable, but the moment sending is enabled an
unverified address is an open relay: one account could set a stranger's address
and have the platform mail them, carrying this domain's sending reputation.

Only the SHA-256 of each token is stored, matching how refresh tokens are already
held in this schema. A leaked backup should not hand out working verification
links.

The issued-for address is recorded on the row rather than read from the user at
confirmation time. A token proves control of the address it was sent to, so if
the profile address changes between issue and confirmation the old token must not
silently verify the new one.

Revision ID: a3c5e7f9b1d2
Revises: f2b3c4d5e6a7
Create Date: 2026-08-07 19:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.types  # noqa: F401

revision: str = "a3c5e7f9b1d2"
down_revision: str | None = "f2b3c4d5e6a7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_verification_tokens",
        # gen_random_uuid() comes from UUIDPrimaryKeyMixin, and omitting it here
        # is what `alembic check` caught: the table would have been created
        # without a default, so every insert would have had to supply an id.
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        # 320 is the maximum length of an email address per RFC 3696: 64 for the
        # local part, 255 for the domain, plus the @.
        sa.Column("email", app.db.types.LowercaseString(length=320), nullable=False),
        # Hex SHA-256, so exactly 64 characters. Unique because a collision would
        # mean two tokens confirming each other's addresses.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Deleting a user takes their pending tokens with them. A token outliving
        # the account it belongs to can only ever be a loose end.
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_email_verification_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_verification_tokens")),
        sa.UniqueConstraint(
            "token_hash", name=op.f("uq_email_verification_tokens_token_hash")
        ),
    )
    op.create_index(
        "ix_email_verification_tokens_user_id",
        "email_verification_tokens",
        ["user_id"],
        unique=False,
    )
    # Supports the periodic purge of expired rows, which would otherwise scan the
    # whole table as it grows.
    op.create_index(
        "ix_email_verification_tokens_expires_at",
        "email_verification_tokens",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_verification_tokens_expires_at",
        table_name="email_verification_tokens",
    )
    op.drop_index(
        "ix_email_verification_tokens_user_id",
        table_name="email_verification_tokens",
    )
    op.drop_table("email_verification_tokens")
