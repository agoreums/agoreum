# apps/api — Agoreum Backend

FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async) · Alembic · PostgreSQL · Redis

## Running

```bash
# from the repository root
python -m venv .venv
./.venv/Scripts/python -m pip install -e "apps/api[dev]"

cd apps/api
alembic upgrade head              # apply migrations
python -m app.cli seed            # insert marketplace taxonomy (idempotent)
python -m app.cli check-db        # verify connectivity and current revision
uvicorn app.main:app --reload     # http://localhost:8000/docs

pytest                            # test suite
ruff check .                      # lint
```

Configuration is read from the repository-root `.env`, then from `apps/api/.env`
(gitignored, for local overrides). See `.env.example` for every variable.

## Structure

```text
app/
├── main.py              Application factory, middleware, lifespan
├── cli.py               Operator commands (seed, check-db)
├── api/v1.py            Router aggregation — the whole public surface
├── core/                config, logging, errors, middleware
├── db/
│   ├── base.py          Declarative base, constraint naming convention
│   ├── enums.py         Domain enums + pg_enum() binding helper
│   ├── types.py         EVM address / tx hash / exact-decimal money types
│   ├── search.py        Full-text search trigger definitions
│   ├── seed.py          Reference data (taxonomy only — never activity)
│   ├── session.py       Async engine and request-scoped sessions
│   └── models.py        Central model registry (import this to load all mappers)
└── modules/             Bounded modules, each owning its own models
    ├── health/          Liveness and readiness probes
    ├── users/           Users, wallets, sessions, SIWE nonces
    ├── agents/          Agents and domain-verification challenges
    ├── services/        Categories and the service catalogue
    ├── orders/          Orders, escrow, chain transactions, audit events
    ├── reputation/      Reviews and computed reputation snapshots
    └── notifications/   Notifications, deliveries, preferences
```

Modules are the seams along which this monolith could later be split. Cross-module
access goes through models and service functions, never by reaching into another
module's internals.

## Database

17 tables, 17 native enum types, 82 CHECK constraints, 27 foreign keys, 82 indexes.

Design rules the schema enforces at the database level, not merely by convention:

- **Money is exact.** All amounts are `NUMERIC(38,6)`, never float. `orders`
  requires `subtotal = unit_price × quantity` and `total = subtotal + fee`.
- **Escrow cannot overdraw.** `released_amount + refunded_amount <= amount`.
- **Reputation derives from real activity.** A review requires a completed order
  and is unique per order; `rating_sum <= review_count × 5`; a service cannot
  have more reviews than completed orders.
- **Nothing holds key material.** No private key, seed phrase, or password column
  exists anywhere. Sessions store only a SHA-256 hash of the refresh token.
- **Payouts require proof.** A wallet cannot be marked payout unless it is
  verified, and a partial unique index allows exactly one payout wallet per user.

A test asserts every foreign key declares an explicit `ON DELETE` rule, so the
consequence of deleting a parent row is always a decision, never a default.

### Migrations

```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade base     # fully reversible, including enum types
alembic check              # fails if models have drifted from migrations
```

Autogenerate does not drop PostgreSQL enum types, so `downgrade()` removes them
explicitly. Without that, a down/up cycle fails on `CREATE TYPE`.

### Full-text search

`services.search_vector` is maintained by a database trigger weighted
title (A) → summary/tags (B) → description (C). Keeping it in the database means
every write path stays correct, including migrations and manual repairs.

## Local development database

Docker Desktop's Linux engine cannot start on the current workstation (no WSL2
distribution installed), so local development runs a self-managed PostgreSQL 17
cluster instead. The Docker Compose configuration targets the Ubuntu droplet and
is unaffected by this. See `docs/development.md` for the setup commands.
