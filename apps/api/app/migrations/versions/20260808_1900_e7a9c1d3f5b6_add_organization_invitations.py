"""add organization invitations

Membership was granted directly: an owner named an address and that account was in
the organization, having never agreed to it. Membership decides who is notified
about an organization's orders and whose name is attached to it, so it is not
something one party should be able to impose on another.

Resolved invitations are kept rather than deleted, so there is a record of who
invited whom and what came of it. The partial unique index allows exactly one open
invitation per person per organization while permitting a fresh one after a
decline.

Revision ID: e7a9c1d3f5b6
Revises: d6f8b0c2e4a5
Create Date: 2026-08-08 19:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7a9c1d3f5b6"
down_revision: str | None = "d6f8b0c2e4a5"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization_invitations",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("invited_by_id", sa.UUID(), nullable=True),
        # Reuses the existing enum type rather than creating a second one, so a
        # role added later cannot mean different things in different tables.
        sa.Column(
            "role",
            sa.Enum(name="org_role", create_type=False),
            nullable=False,
            server_default="member",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_organization_invitations_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_organization_invitations_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_id"],
            ["users.id"],
            name=op.f("fk_organization_invitations_invited_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_invitations")),
        # An answered invitation must record both halves of the answer, or
        # neither. A responded_at with a null accepted is not a state that means
        # anything.
        sa.CheckConstraint(
            "(responded_at IS NULL) = (accepted IS NULL)",
            name=op.f("ck_organization_invitations_response_is_complete"),
        ),
    )
    op.create_index(
        "uq_org_invitation_pending",
        "organization_invitations",
        ["org_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("responded_at IS NULL"),
    )
    op.create_index(
        "ix_org_invitations_user_id", "organization_invitations", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_org_invitations_user_id", table_name="organization_invitations")
    op.drop_index("uq_org_invitation_pending", table_name="organization_invitations")
    op.drop_table("organization_invitations")
