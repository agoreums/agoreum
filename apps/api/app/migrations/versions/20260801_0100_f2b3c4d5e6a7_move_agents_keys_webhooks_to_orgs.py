"""move agents, api keys, and webhooks to organization ownership

The ownership cutover. Each agent, api key, and webhook endpoint moves from a
single user to an organization. Existing rows backfill to the owner's personal
organization, which the previous revision created with slug 'u-' plus the user id
hex, so the mapping is exact. The down-migration restores single-user ownership
from each org's owner membership.

Revision ID: f2b3c4d5e6a7
Revises: e1a2b3c4d5f6
Create Date: 2026-08-01 01:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db.types  # noqa: F401

revision: str = "f2b3c4d5e6a7"
down_revision: str | None = "e1a2b3c4d5f6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # --- agents: owner_id (user) -> org_id (organization) ---------------------
    op.add_column("agents", sa.Column("org_id", sa.UUID(), nullable=True))
    op.execute(
        """
        UPDATE agents a SET org_id = o.id
        FROM organizations o
        WHERE o.slug = 'u-' || replace(a.owner_id::text, '-', '')
        """
    )
    op.alter_column("agents", "org_id", nullable=False)
    op.create_index("ix_agents_org_id", "agents", ["org_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_agents_org_id_organizations"),
        "agents",
        "organizations",
        ["org_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_index("ix_agents_owner_id", table_name="agents")
    op.drop_constraint(op.f("fk_agents_owner_id_users"), "agents", type_="foreignkey")
    op.drop_column("agents", "owner_id")

    # --- api_keys: user_id -> org_id + created_by_user_id ---------------------
    op.add_column("api_keys", sa.Column("org_id", sa.UUID(), nullable=True))
    op.add_column("api_keys", sa.Column("created_by_user_id", sa.UUID(), nullable=True))
    op.execute(
        """
        UPDATE api_keys k SET org_id = o.id, created_by_user_id = k.user_id
        FROM organizations o
        WHERE o.slug = 'u-' || replace(k.user_id::text, '-', '')
        """
    )
    op.alter_column("api_keys", "org_id", nullable=False)
    op.create_index("ix_api_keys_org_id", "api_keys", ["org_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_api_keys_org_id_organizations"),
        "api_keys",
        "organizations",
        ["org_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_api_keys_created_by_user_id_users"),
        "api_keys",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_constraint(op.f("fk_api_keys_user_id_users"), "api_keys", type_="foreignkey")
    op.drop_column("api_keys", "user_id")

    # --- webhook_endpoints: user_id -> org_id + created_by_user_id ------------
    op.add_column("webhook_endpoints", sa.Column("org_id", sa.UUID(), nullable=True))
    op.add_column(
        "webhook_endpoints", sa.Column("created_by_user_id", sa.UUID(), nullable=True)
    )
    op.execute(
        """
        UPDATE webhook_endpoints w SET org_id = o.id, created_by_user_id = w.user_id
        FROM organizations o
        WHERE o.slug = 'u-' || replace(w.user_id::text, '-', '')
        """
    )
    op.alter_column("webhook_endpoints", "org_id", nullable=False)
    op.create_index("ix_webhook_endpoints_org_id", "webhook_endpoints", ["org_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_webhook_endpoints_org_id_organizations"),
        "webhook_endpoints",
        "organizations",
        ["org_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_webhook_endpoints_created_by_user_id_users"),
        "webhook_endpoints",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_index("ix_webhook_endpoints_user_id", table_name="webhook_endpoints")
    op.drop_constraint(
        op.f("fk_webhook_endpoints_user_id_users"), "webhook_endpoints", type_="foreignkey"
    )
    op.drop_column("webhook_endpoints", "user_id")


def _restore_user_column(table: str, ondelete: str) -> None:
    """Re-add a user_id column and backfill it from each org's owner membership."""
    op.add_column(table, sa.Column("user_id", sa.UUID(), nullable=True))
    # `table` is one of a fixed set of literals passed by this module, never user
    # input, so the interpolation is safe.
    backfill = f"UPDATE {table} t SET user_id = (SELECT m.user_id FROM organization_memberships m WHERE m.org_id = t.org_id AND m.role = 'owner' ORDER BY m.created_at LIMIT 1)"  # noqa: S608
    op.execute(backfill)
    op.alter_column(table, "user_id", nullable=False)
    op.create_index(f"ix_{table}_user_id", table, ["user_id"], unique=False)
    op.create_foreign_key(
        op.f(f"fk_{table}_user_id_users"), table, "users", ["user_id"], ["id"], ondelete=ondelete
    )


def downgrade() -> None:
    # webhook_endpoints
    op.drop_constraint(
        op.f("fk_webhook_endpoints_created_by_user_id_users"),
        "webhook_endpoints",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_webhook_endpoints_org_id_organizations"), "webhook_endpoints", type_="foreignkey"
    )
    op.drop_index("ix_webhook_endpoints_org_id", table_name="webhook_endpoints")
    op.drop_column("webhook_endpoints", "created_by_user_id")
    _restore_user_column("webhook_endpoints", "CASCADE")
    op.drop_column("webhook_endpoints", "org_id")

    # api_keys
    op.drop_constraint(
        op.f("fk_api_keys_created_by_user_id_users"), "api_keys", type_="foreignkey"
    )
    op.drop_constraint(op.f("fk_api_keys_org_id_organizations"), "api_keys", type_="foreignkey")
    op.drop_index("ix_api_keys_org_id", table_name="api_keys")
    op.drop_column("api_keys", "created_by_user_id")
    _restore_user_column("api_keys", "CASCADE")
    op.drop_column("api_keys", "org_id")

    # agents
    op.drop_constraint(op.f("fk_agents_org_id_organizations"), "agents", type_="foreignkey")
    op.drop_index("ix_agents_org_id", table_name="agents")
    op.add_column("agents", sa.Column("owner_id", sa.UUID(), nullable=True))
    op.execute(
        """
        UPDATE agents a SET owner_id = (
            SELECT m.user_id FROM organization_memberships m
            WHERE m.org_id = a.org_id AND m.role = 'owner'
            ORDER BY m.created_at LIMIT 1
        )
        """
    )
    op.alter_column("agents", "owner_id", nullable=False)
    op.create_index("ix_agents_owner_id", "agents", ["owner_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_agents_owner_id_users"), "agents", "users", ["owner_id"], ["id"], ondelete="RESTRICT"
    )
    op.drop_column("agents", "org_id")
