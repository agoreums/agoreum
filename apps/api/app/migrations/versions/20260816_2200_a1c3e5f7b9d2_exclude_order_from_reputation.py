"""allow an order to be excluded from reputation, permanently and one way only

Some settled orders are real payments that should not become standing. The one
that forced this is the settlement exercise of 2026-08-16: a genuine escrow,
funded, released and receipted on Base Sepolia, with one person holding both
wallets. The platform cannot infer that. The two accounts share no organization,
no wallet and no visible relationship, which is exactly the case the arm's length
filter is documented as not covering.

So the operator needs to be able to say "this one does not count", and that
ability is dangerous in precisely one direction. A flag that can be set and
cleared is a mechanism for handing out standing: exclude a rival's orders, or
exclude your own during a bad month and restore them after. The requirement is
therefore not "an exclusion flag" but "an exclusion that cannot be reversed".

**Enforced by the database rather than by the application.** Every defect worth
recording this month had the same shape: a guarantee living in one branch of one
function, correct there, and absent from every other route to the same table. A
trigger is below all of them. A future endpoint, an admin script, a migration, a
backfill, or somebody at a psql prompt all hit it equally, and none of them can
be written in a way that does not.

Three things the trigger refuses:

1. clearing an exclusion once set
2. changing the timestamp of an existing exclusion, which would otherwise let
   somebody rewrite when a decision was taken
3. changing the reason after the fact, for the same reason

Setting one on an order that has none is allowed, and is the only permitted
transition. Nothing here deletes or alters the order, the escrow or the receipt:
the settlement genuinely happened, the receipt still points at it, and the
exclusion is a statement about reputation alone.

Revision ID: a1c3e5f7b9d2
Revises: f8b0d2e4a6c7
Create Date: 2026-08-16 22:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c3e5f7b9d2"
down_revision: str | None = "f8b0d2e4a6c7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION agoreum_reputation_exclusion_is_one_way()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.reputation_excluded_at IS NOT NULL THEN
        IF NEW.reputation_excluded_at IS NULL THEN
            RAISE EXCEPTION
                'reputation exclusion cannot be lifted (order %)', OLD.id
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.reputation_excluded_at <> OLD.reputation_excluded_at THEN
            RAISE EXCEPTION
                'reputation exclusion timestamp cannot be rewritten (order %)', OLD.id
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.reputation_exclusion_reason IS DISTINCT FROM OLD.reputation_exclusion_reason THEN
            RAISE EXCEPTION
                'reputation exclusion reason cannot be rewritten (order %)', OLD.id
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("reputation_excluded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("reputation_exclusion_reason", sa.Text(), nullable=True),
    )

    # An exclusion with no reason is an exclusion nobody can audit later, and the
    # whole point of the record is that somebody can ask why afterwards.
    # The bare name, not the final one. The metadata naming convention is
    # `ck_%(table_name)s_%(constraint_name)s`, so passing the already-prefixed
    # name produced `ck_orders_ck_orders_...` in the database while the model
    # declared `ck_orders_...`, and the two disagreed forever after. Caught by
    # `alembic check` in CI against a fresh database, which is the environment
    # that has no history to hide the difference.
    op.create_check_constraint(
        "reputation_exclusion_has_a_reason",
        "orders",
        "(reputation_excluded_at IS NULL) = (reputation_exclusion_reason IS NULL)",
    )

    op.execute(TRIGGER_FUNCTION)
    op.execute(
        "CREATE TRIGGER agoreum_reputation_exclusion_is_one_way"
        " BEFORE UPDATE ON orders"
        " FOR EACH ROW"
        " EXECUTE FUNCTION agoreum_reputation_exclusion_is_one_way();"
    )

    # Reputation reads filter on this column for every agent it scores, and the
    # excluded set is expected to stay tiny, so a partial index keeps that filter
    # from growing a sequential scan as the table does.
    op.create_index(
        "ix_orders_reputation_excluded",
        "orders",
        ["provider_agent_id"],
        postgresql_where=sa.text("reputation_excluded_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_orders_reputation_excluded", table_name="orders")
    op.execute("DROP TRIGGER IF EXISTS agoreum_reputation_exclusion_is_one_way ON orders;")
    op.execute("DROP FUNCTION IF EXISTS agoreum_reputation_exclusion_is_one_way();")
    # The bare name here too. An earlier version of this comment claimed
    # drop_constraint takes the name the database actually uses; running the
    # downgrade proved otherwise, since alembic expands the same convention on
    # the way down and the drop failed looking for ck_orders_ck_orders_...
    op.drop_constraint("reputation_exclusion_has_a_reason", "orders", type_="check")
    op.drop_column("orders", "reputation_exclusion_reason")
    op.drop_column("orders", "reputation_excluded_at")
