"""freeze delivery and auto release windows on the order

The order already froze its price so a later edit could not change what an
existing order was owed. It did not freeze the two windows that decide *when*
money moves, and those were read from the live service every time payment
instructions were built.

So a provider could edit the service after an order existed and move that order's
deadlines. Shortening `auto_release_hours` is the dangerous direction: it shrinks
the window a buyer has to raise a dispute before escrow releases to the provider.

Nullable, and existing rows are backfilled from their service rather than left
empty, so history reflects the terms those orders were actually placed under. The
read path falls back to the service when the column is null, which keeps any row
this backfill cannot resolve working exactly as before.

Revision ID: d6f8b0c2e4a5
Revises: c5e7a9b1d3f4
Create Date: 2026-08-08 18:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6f8b0c2e4a5"
down_revision: str | None = "c5e7a9b1d3f4"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders", sa.Column("delivery_time_hours", sa.Integer(), nullable=True)
    )
    op.add_column(
        "orders", sa.Column("auto_release_hours", sa.Integer(), nullable=True)
    )
    op.execute(
        """
        UPDATE orders o
           SET delivery_time_hours = s.delivery_time_hours,
               auto_release_hours = s.auto_release_hours
          FROM services s
         WHERE s.id = o.service_id
        """
    )


def downgrade() -> None:
    op.drop_column("orders", "auto_release_hours")
    op.drop_column("orders", "delivery_time_hours")
