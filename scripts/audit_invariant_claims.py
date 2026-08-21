"""Check claims the code makes about itself against the real database.

Each of these is asserted somewhere in a comment or docstring. A comment is not
a check, and on 2026-08-21 one that had been true when written turned out to
have been false for as long as a second code path existed. So they are measured
here rather than believed.

Read only. Nothing is written.
"""
import asyncio

import sqlalchemy as sa
from app.core.config import settings
from sqlalchemy.ext.asyncio import create_async_engine

CHECKS = [
    (
        "agents.payout_address matches the wallet it points at",
        "models.py: 'Kept in sync with payout_wallet_id by the service layer'",
        """
        SELECT count(*) FROM agents a
        JOIN wallets w ON w.id = a.payout_wallet_id
        WHERE a.payout_address IS DISTINCT FROM w.address
        """,
    ),
    (
        "no agent has an address without the wallet, or the reverse",
        "the two columns are written together in one place",
        """
        SELECT count(*) FROM agents
        WHERE (payout_wallet_id IS NULL) <> (payout_address IS NULL)
        """,
    ),
    (
        "every payout wallet is verified",
        "users/models.py: NOT is_payout OR verification_status = 'verified'",
        """
        SELECT count(*) FROM wallets
        WHERE is_payout AND verification_status <> 'verified'
        """,
    ),
    (
        "service review counters match their published reviews",
        "reputation/service.py: derived so they cannot drift",
        """
        SELECT count(*) FROM services s
        LEFT JOIN (
            SELECT service_id, count(*) AS n, coalesce(sum(rating), 0) AS total
            FROM reviews WHERE status = 'published' GROUP BY service_id
        ) r ON r.service_id = s.id
        WHERE s.review_count IS DISTINCT FROM coalesce(r.n, 0)
           OR s.rating_sum IS DISTINCT FROM coalesce(r.total, 0)
        """,
    ),
    (
        "no review outnumbers its service's completed orders",
        "services check constraint reviews_cannot_exceed_completed_orders",
        "SELECT count(*) FROM services WHERE review_count > completed_order_count",
    ),
    (
        "no escrow paid out more than it took in",
        "escrows check constraint payouts_cannot_exceed_deposit",
        """
        SELECT count(*) FROM escrows
        WHERE released_amount + refunded_amount > amount
        """,
    ),
    (
        "every completed order records when it completed",
        "orders check constraint completed_at_matches_status",
        """
        SELECT count(*) FROM orders
        WHERE (status = 'completed') <> (completed_at IS NOT NULL)
        """,
    ),
    (
        "every reputation exclusion carries a reason",
        "orders check constraint reputation_exclusion_has_a_reason",
        """
        SELECT count(*) FROM orders
        WHERE (reputation_excluded_at IS NULL) <> (reputation_exclusion_reason IS NULL)
        """,
    ),
]


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    failures = 0
    async with engine.begin() as conn:
        for title, claim, sql in CHECKS:
            rows = (await conn.execute(sa.text(sql))).scalar_one()
            mark = "ok  " if rows == 0 else "FAIL"
            if rows:
                failures += 1
            print(f"  [{mark}] {title}")
            print(f"         claim: {claim}")
            if rows:
                print(f"         violating rows: {rows}")

        totals = (await conn.execute(sa.text(
            "SELECT (SELECT count(*) FROM agents), (SELECT count(*) FROM orders),"
            " (SELECT count(*) FROM services), (SELECT count(*) FROM reviews),"
            " (SELECT count(*) FROM escrows)"
        ))).one()
    await engine.dispose()

    print(f"\n  rows present: agents={totals[0]} orders={totals[1]} "
          f"services={totals[2]} reviews={totals[3]} escrows={totals[4]}")
    print(f"  claims checked: {len(CHECKS)}, violated: {failures}")
    # A pass on a nearly empty database is not evidence of anything. Said
    # loudly, because "8 of 8 claims hold" reads like a result and would be a
    # false one against three rows. The first run of this, against production
    # on 2026-08-21, passed every check with one agent, one order, no reviews.
    smallest = min(totals)
    if smallest < 20:
        print()
        print(f"  WARNING: the smallest table here has {smallest} rows.")
        print("  Most of these checks are satisfied vacuously at this size,")
        print("  so this run is close to no evidence at all. Treat a pass as")
        print("  meaningful only against a populated database.")


asyncio.run(main())
