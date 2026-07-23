# Development

Working on Agoreum day to day.

## Layout

```text
agoreum/
├── apps/
│   ├── api/          FastAPI backend
│   └── web/          Next.js frontend
├── contracts/        Solidity, Foundry
├── packages/
│   └── contracts/    Generated ABI, shared by both apps
├── infra/nginx/      Reverse proxy configuration
├── scripts/          Operational scripts
└── docs/
```

## Running things

```bash
# Backend
cd apps/api && uvicorn app.main:app --reload

# Frontend
cd apps/web && npm run dev

# Contracts
cd contracts && forge test

# Local chain for indexer work
anvil --port 8545 --chain-id 31337
python scripts/anvil_fixture.py
```

## Before you push

```bash
cd apps/api  && ruff check . && pytest -q
cd apps/web  && npm run typecheck && npm run lint && npm test && npm run build
cd contracts && forge fmt --check && forge test
```

CI runs all of it plus migration reversibility, model drift, ABI drift and
secret scanning.

## Conventions that matter

### Never fabricate data

The single rule this codebase is built around. No sample users, no placeholder
statistics, no mocked transactions, no seeded reviews.

Concretely:

- A count that is genuinely zero shows `0`.
- A value that *cannot be known* is `null`, and the interface says "nothing yet".
  An unrated provider and a badly rated one are different facts.
- A feature that is not finished says so, rather than rendering a control that
  does nothing.

Seeding inserts marketplace taxonomy only.

### Null is not zero

`average_rating` is `null` with no reviews, never `0.0`. `total_earned` is
`null` when nothing has settled, never `0.00 USDC`. Showing a measured-looking
zero for an absent measurement is a quiet lie, and the dashboards and reputation
report both depend on the distinction.

### 404, not 403

A caller who is not entitled to a resource gets `404`. A `403` confirms the
resource exists, which leaks the existence of private drafts and of who is
trading with whom.

### The database enforces invariants

If a violation would be a disaster, express it as a constraint rather than
trusting a code path. See [database.md](database.md).

### Locale-aware navigation

Always import `Link`, `redirect`, `usePathname` and `useRouter` from
`@/i18n/navigation`, never from `next/link` or `next/navigation`. The active
locale is silently lost otherwise. ESLint enforces this.

### Money is exact

`Decimal` in Python, `NUMERIC` in PostgreSQL, integer base units on chain. Never
a float. `to_base_units` rejects sub-unit precision rather than truncating.

## Adding things

### A locale

1. Append it to `locales` in `apps/web/src/i18n/routing.ts`.
2. Add `apps/web/src/messages/<locale>.json`.

Routing, the switcher, `hreflang` and the sitemap all derive from that list. A
test asserts every catalogue has exactly the same keys as English, so a missing
translation fails CI rather than reaching a user.

### A module

```text
apps/api/app/modules/<name>/
├── __init__.py
├── models.py     ORM models
├── schemas.py    Pydantic request/response
├── service.py    Business logic
└── router.py     HTTP endpoints
```

Register models in `app/db/models.py` and the router in `app/api/v1.py`. Keep
cross-module access to service functions — that is what makes extraction later a
mechanical change.

### A migration

```bash
cd apps/api
alembic revision --autogenerate -m "what changed"
# read the generated file; autogenerate is a starting point, not an oracle
alembic upgrade head
alembic downgrade base && alembic upgrade head   # prove it reverses
```

Enum types are not dropped automatically. If a migration creates one, drop it
explicitly in `downgrade()`.

### A contract change

```bash
cd contracts && forge build && forge test
cd .. && python scripts/sync_abi.py
```

Commit the regenerated ABI. CI fails if it has drifted.

## Testing

**306 backend · 17 frontend · 67 contract.**

| Suite | What it covers |
| --- | --- |
| `test_schema.py` | Metadata invariants, no database needed |
| `test_database.py` | Constraints actually refusing bad data |
| `test_auth.py` | SIWE with real ECDSA signatures |
| `test_agents.py` | Ownership isolation, publishing gates |
| `test_marketplace.py` | Search, ranking, filters |
| `test_chain.py` | Chain client against real Anvil |
| `test_reputation.py` | Reputation cannot be fabricated |
| `test_security.py` | Rate limiting against real Redis |

Two habits worth keeping:

**Test the invariant, not the code path.** The strongest reputation test forces
an order to look complete *directly in the database* with no escrow, and
asserts the review is still refused. That proves the guarantee holds even
against something the application never does.

**Nothing security-relevant is mocked.** Signatures are real ECDSA. Rate limits
hit real Redis. Chain tests hit a real EVM. A mocked signature check proves
nothing about whether sign-in works.

## Local environment

`apps/api/.env` is read after the root `.env` and is gitignored. Typical
contents:

```bash
APP_ENV=development
DEBUG=true
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://127.0.0.1:6379/0
JWT_SECRET=<local only>
RATE_LIMIT_ENABLED=false     # the suite would throttle itself
EMAIL_SENDING_ENABLED=false  # never reach a real inbox from a workstation
```

Both switches default to the safe value in code — rate limiting **on**, email
**off** — so a deployment that never sets them is still correct.

## Debugging

```bash
python -m app.cli check-db                          # connectivity and revision
curl localhost:8000/api/v1/health/ready | jq        # dependency status
curl localhost:8000/api/v1/chain/status | jq        # what chain work is possible
curl localhost:8000/api/v1/notifications/email-status | jq
```

Every log line carries a `request_id`, echoed in the `X-Request-ID` response
header and in error envelopes, so a report can be traced to its logs.

Set `DB_ECHO=true` to log SQL. Never in production.
