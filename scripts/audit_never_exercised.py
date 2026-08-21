#!/usr/bin/env python3
"""What has never actually happened in production.

The companion to `sweep_invariant_claims.py`, and it exists because the two ways
a true statement stops protecting you need different instruments.

A **decayed** claim is found by re-reading it against the code as it is now. A
**never exercised** one is invisible to any amount of code reading, because the
code is correct: `cli.py` really was the only way to become an admin, and no
account had ever been granted it, so the surface behind it was reachable by
nobody for its whole life. Reading that function would never have told anybody.

The only way to find that class is to ask what has actually happened, and the
answer lives in the database rather than in the source.

**This is a map, not a defect list.** On a testnet platform with a handful of
accounts most things are legitimately unused, and reporting that as a problem
would be noise. What it is for is refusing the sentence "that path works" when
what is meant is "that path exists". A capability with zero occurrences has
never been proven by anything except its tests, which is exactly the gap this
project keeps finding.

Read only.
"""
from __future__ import annotations

import asyncio

import sqlalchemy as sa
from app.core.config import settings
from sqlalchemy.ext.asyncio import create_async_engine

# (capability, why it matters if it has never happened, SQL returning a count)
CAPABILITIES: list[tuple[str, str, str]] = [
    ("an account holding platform admin",
     "the admin dashboard and subscription plan management are reachable by nobody",
     "SELECT count(*) FROM users WHERE role = 'admin'"),
    ("an order funded on chain",
     "the escrow funding path has never carried real state",
     "SELECT count(*) FROM orders WHERE funded_at IS NOT NULL"),
    ("an order settled",
     "reputation, receipts and payouts all hang off this",
     "SELECT count(*) FROM orders WHERE status = 'completed'"),
    ("an order refunded",
     "the refund path returns a buyer's money and has never run",
     "SELECT count(*) FROM escrows WHERE status = 'refunded'"),
    ("a dispute raised",
     "the arbiter queue, statements and decision record exist for this",
     "SELECT count(*) FROM escrows WHERE disputed_at IS NOT NULL"),
    ("a dispute settled",
     "settleDispute divides money between two parties who disagree",
     "SELECT count(*) FROM escrows WHERE dispute_resolved_at IS NOT NULL"),
    ("a review written",
     "reputation's satisfaction half is built entirely from these",
     "SELECT count(*) FROM reviews"),
    ("a subscription taken out",
     "the whole subscriptions product",
     "SELECT count(*) FROM subscriptions"),
    ("an API key created",
     "the SDK write surface is reached with these",
     "SELECT count(*) FROM api_keys"),
    ("a webhook endpoint registered",
     "the outbox worker has never had anywhere to deliver",
     "SELECT count(*) FROM webhook_endpoints"),
    ("an agent published",
     "nothing is discoverable in the marketplace without one",
     "SELECT count(*) FROM agents WHERE status = 'active'"),
    ("an order excluded from reputation",
     "the operator's only way to disown a settlement",
     "SELECT count(*) FROM orders WHERE reputation_excluded_at IS NOT NULL"),
]


async def main() -> int:
    engine = create_async_engine(settings.DATABASE_URL)
    exercised: list[tuple[str, int]] = []
    never: list[tuple[str, str]] = []

    async with engine.begin() as conn:
        for name, why, sql in CAPABILITIES:
            try:
                count = (await conn.execute(sa.text(sql))).scalar_one()
            except Exception as exc:  # noqa: BLE001 - a missing table is a finding
                never.append((name, f"could not be counted: {type(exc).__name__}"))
                continue
            if count:
                exercised.append((name, count))
            else:
                never.append((name, why))
    await engine.dispose()

    print("exercised at least once:")
    for name, count in exercised:
        print(f"  {count:>6}  {name}")
    if not exercised:
        print("  nothing")

    print()
    print("never exercised:")
    for name, why in never:
        print(f"       0  {name}")
        print(f"          {why}")
    if not never:
        print("  nothing, every capability here has happened at least once")

    print()
    print(f"  {len(exercised)} exercised, {len(never)} never, of {len(CAPABILITIES)}")
    print("  This is a map, not a defect list. A zero is only a problem where")
    print("  something claims the path works, and it is always a reason to stop")
    print("  saying that a capability is proven by anything other than its tests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
