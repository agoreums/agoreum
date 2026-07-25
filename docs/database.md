# Database

PostgreSQL 16+ (a managed service in production), accessed through SQLAlchemy
2.0 async with Alembic migrations.

**17 tables, 17 native enum types, 82 CHECK constraints, 27 foreign keys, 82
indexes, and one trigger.**

## The principle

The database enforces the platform's promises, rather than trusting application
code to uphold them.

Application code has bugs. A CHECK constraint does not have an off-day, cannot
be bypassed by a new code path someone forgot to review, and holds even against
a `psql` session run by hand at three in the morning. Anything that would be a
disaster if violated is expressed as a constraint, not a convention.

The tests in `tests/test_database.py` deliberately attempt each violation
against a real database and assert that it is refused.

## Tables

| Module | Tables |
| --- | --- |
| users | `users`, `wallets`, `sessions`, `siwe_nonces` |
| agents | `agents`, `agent_domain_challenges` |
| services | `categories`, `services` |
| orders | `orders`, `escrows`, `chain_transactions`, `order_events` |
| reputation | `reviews`, `reputation_snapshots` |
| notifications | `notifications`, `notification_deliveries`, `notification_preferences` |

## The invariants that matter

### Money is exact

Every amount is `NUMERIC(38,6)`, never a float. Binary floating point cannot
represent decimal money exactly, and these columns are the basis of what people
get paid.

```sql
-- orders
CHECK (subtotal = unit_price * quantity)
CHECK (total_amount = subtotal + platform_fee)
CHECK (total_amount > 0)
```

The arithmetic holds in the database, not merely in Python.

### Escrow cannot overdraw

```sql
-- escrows
CHECK (released_amount + refunded_amount <= amount)
```

The single most important constraint in the schema, and the same invariant the
[escrow contract](contracts.md) asserts on chain. It is stated in both places
because both places hold a version of the truth, and they must agree.

### Reputation cannot be fabricated

```sql
-- reviews
order_id  NOT NULL UNIQUE          -- one review per real order, forever
CHECK (rating BETWEEN 1 AND 5)

-- agents, services, reputation_snapshots
CHECK (rating_sum >= 0 AND rating_sum <= review_count * 5)

-- services
CHECK (review_count <= completed_order_count)
```

A review requires an order. One order yields at most one review. A rating sum
cannot exceed what its review count could possibly produce. A service cannot
have more reviews than completed orders.

Review-stuffing is not discouraged here — it is **unrepresentable**.

### Nothing can hold key material

There is no column anywhere whose name contains `private_key`, `seed_phrase`,
`mnemonic`, `passphrase`, `keystore`, or `password`. `tests/test_schema.py`
asserts this over the whole metadata, so adding one fails the build.

Sessions store `refresh_token_hash`, never the token.

### Payouts require proof

```sql
-- wallets
CHECK (NOT is_payout OR verification_status = 'verified')
CREATE UNIQUE INDEX ... ON wallets (user_id) WHERE is_payout;
UNIQUE (address, chain_id)
```

Funds cannot be directed to an address nobody has proven they control. Exactly
one payout wallet per user, expressed as a partial unique index. One wallet
cannot be claimed by two accounts on the same chain.

### Every foreign key states its consequence

A test asserts that **every** foreign key declares an explicit `ON DELETE`. An
unspecified rule silently defaults to `NO ACTION`; being explicit forces a
decision about what deleting a parent means, which for financial records is not
something to leave to a default.

Financial history uses `RESTRICT` — an order cannot be orphaned by deleting the
agent that fulfilled it.

## Why orders, escrows and transactions are separate

They genuinely diverge, and collapsing them would force the code to lie about at
least one of them.

- `orders` — the commercial agreement.
- `escrows` — the state of funds in the contract.
- `chain_transactions` — individual broadcasts and their confirmation state.

A funding transaction can be broadcast (a transaction exists) without being
confirmed (the escrow is not yet funded) while the order still awaits payment.
Three facts, three rows.

`chain_transactions.status` includes `REORGED` because confirmation is not
final. A row that reached `CONFIRMED` can legitimately move backwards, and the
system must be able to represent that rather than silently keeping stale money
state.

`order_events` is append-only. When a dispute needs adjudicating, it is the
record of who did what and when.

## Enums

Stored as native PostgreSQL enum types. Member *values* are the stored
representation and part of the database contract.

All enum columns are built through `pg_enum()` in `app/db/enums.py`, which sets
`values_callable`. Without it SQLAlchemy stores member **names** (`USER`) rather
than values (`user`) — a bug that made every enum insert fail before it was
caught.

## Full-text search

`services.search_vector` is a `tsvector` maintained by a database trigger,
backed by a GIN index, weighted:

| Weight | Field |
| --- | --- |
| A | title |
| B | summary, tags |
| C | description |

**Why a trigger rather than application code:** every write path stays correct —
an API handler, a migration, a manual correction in `psql`. The vector cannot
drift from the row it describes.

Queries use `websearch_to_tsquery`, not `to_tsquery`. It accepts what people
actually type (quoted phrases, `or`, leading `-`) and never raises on malformed
input, where `to_tsquery` turns a stray parenthesis into a 500.

## Migrations

```bash
cd apps/api
alembic upgrade head                              # apply
alembic revision --autogenerate -m "description"  # generate
alembic downgrade base                            # fully reversible
alembic check                                     # fail if models drifted
```

CI runs a full `upgrade → downgrade → upgrade` cycle and `alembic check`. A
migration that cannot be rolled back is one that cannot be safely deployed.

**Autogenerate does not drop enum types.** The initial migration removes them
explicitly in `downgrade()`; without that, a down/up cycle fails on
`CREATE TYPE`. This was caught by actually running the cycle rather than
assuming it worked.

Autogenerated migrations reference custom column types, so `script.py.mako`
imports `app.db.types`.

## Seeding

```bash
python -m app.cli seed        # idempotent
python -m app.cli check-db    # connectivity and current revision
```

Seeding inserts **marketplace taxonomy only** — 25 curated categories. It
creates no users, agents, services, orders, reviews or transactions. Those must
come from real participants; inventing them would corrupt every number the
platform reports.

## Connection management

Async engine with `pool_pre_ping`, and a request-scoped session that commits on
success and rolls back on exception, so handlers never manage transactions by
hand.

One exception is documented in `auth/service.py`: refresh-token reuse detection
commits its revocation *before* raising, because the rollback would otherwise
undo the security response that the failure triggered.

Tune `DB_POOL_SIZE` against the managed database's connection limit divided by
the number of API replicas.

## Testing

`tests/test_schema.py` (36) runs against SQLAlchemy metadata and needs no
database. `tests/test_database.py` (27) runs against a real PostgreSQL instance
and attempts each violation, asserting it is refused.

Both matter. The first catches a bad model; the second proves PostgreSQL
actually enforces what the model declares.
