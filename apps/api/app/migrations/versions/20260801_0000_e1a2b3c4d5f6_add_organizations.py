"""add organizations and memberships

Creates the organization substrate and gives every existing user a personal
organization they solely own. Agents are not moved to organizations in this
revision; that ownership cutover is a separate, deliberate change.

Revision ID: e1a2b3c4d5f6
Revises: b7d1e0f92a34
Create Date: 2026-08-01 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.types  # noqa: F401

revision: str = "e1a2b3c4d5f6"
down_revision: str | None = "b7d1e0f92a34"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("slug", app.db.types.LowercaseString(length=64), nullable=False),
        sa.Column("name", sa.String(length=96), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("personal", "team", name="org_kind"),
            server_default="team",
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )
    op.create_table(
        "organization_memberships",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("member", "admin", "owner", name="org_role"),
            server_default="member",
            nullable=False,
        ),
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
            name=op.f("fk_organization_memberships_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_organization_memberships_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_memberships")),
        sa.UniqueConstraint("org_id", "user_id", name="uq_membership_org_user"),
    )
    op.create_index(
        "ix_org_memberships_user_id", "organization_memberships", ["user_id"], unique=False
    )
    op.create_index(
        "ix_org_memberships_org_id", "organization_memberships", ["org_id"], unique=False
    )

    # Backfill: every existing user gets a personal organization they solely own.
    # The org slug encodes the user id so the membership join below is exact.
    op.execute(
        """
        INSERT INTO organizations (id, slug, name, kind, created_at, updated_at)
        SELECT gen_random_uuid(),
               'u-' || replace(u.id::text, '-', ''),
               COALESCE(u.display_name, u.username, 'Personal'),
               'personal',
               now(), now()
        FROM users u
        """
    )
    op.execute(
        """
        INSERT INTO organization_memberships (id, org_id, user_id, role, created_at, updated_at)
        SELECT gen_random_uuid(), o.id, u.id, 'owner', now(), now()
        FROM users u
        JOIN organizations o ON o.slug = 'u-' || replace(u.id::text, '-', '')
        """
    )


def downgrade() -> None:
    op.drop_index("ix_org_memberships_org_id", table_name="organization_memberships")
    op.drop_index("ix_org_memberships_user_id", table_name="organization_memberships")
    op.drop_table("organization_memberships")
    op.drop_table("organizations")
    op.execute("DROP TYPE IF EXISTS org_role")
    op.execute("DROP TYPE IF EXISTS org_kind")
