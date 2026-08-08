"""record a dispute decision before it is executed

The order already carried dispute_resolution, dispute_resolved_at and
dispute_resolved_by, but nothing recorded the figure that was decided or why.
Without those, an on-chain settlement has nothing to be compared against, so a
settlement that differs from the decision is merely surprising rather than
detectable.

Only the provider's share is stored. The contract derives the buyer's as
amount - providerAmount and treats its own buyerAmount argument as a bounds check,
so a second column here would be a source of truth the chain ignores.

Revision ID: f8b0d2e4a6c7
Revises: e7a9c1d3f5b6
Create Date: 2026-08-08 21:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8b0d2e4a6c7"
down_revision: str | None = "e7a9c1d3f5b6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # 38,6 is TokenAmount, the same type every other amount on this table uses.
    # USDC has six decimals, so a split cannot round differently from the price it
    # divides.
    op.add_column(
        "orders",
        sa.Column("dispute_provider_amount", sa.Numeric(38, 6), nullable=True),
    )
    op.add_column("orders", sa.Column("dispute_reasoning", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "dispute_reasoning")
    op.drop_column("orders", "dispute_provider_amount")
