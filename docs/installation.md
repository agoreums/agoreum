# Installation

Getting Agoreum running locally.

## Requirements

| Tool | Version | Needed for |
| --- | --- | --- |
| Python | 3.12+ | Backend |
| Node.js | 20+ (22 recommended) | Frontend |
| PostgreSQL | 16+ | Database |
| Redis | 5+ | Cache, rate limiting |
| Foundry | 1.7+ | Contracts (optional) |
| Docker | 24+ | Containers (optional) |

Redis 5 works: the client pins RESP2 and disables the `CLIENT SETINFO`
handshake, neither of which older servers implement.

## Quickest path: Docker

```bash
git clone https://github.com/agoreums/agoreum.git
cd agoreum
cp .env.example .env    # fill in what you have; most is optional locally
docker compose up -d --build
```

Brings up Postgres, Redis, the API and the web app. Then:

```bash
docker compose exec api alembic upgrade head
docker compose exec api python -m app.cli seed
```

- Web — <http://localhost:3000>
- API docs — <http://localhost:8000/docs>

Ports bind to `127.0.0.1` only. Binding `0.0.0.0` on a laptop exposes a
development database to every network it joins.

## Manual setup

### 1. Clone with submodules

```bash
git clone --recurse-submodules https://github.com/agoreums/agoreum.git
cd agoreum
```

Already cloned without them:

```bash
git submodule update --init --recursive
```

Contract dependencies (forge-std, OpenZeppelin) are pinned submodules.

### 2. Backend

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e "apps/api[dev]"
```

### 3. Database and Redis

Either use the containers:

```bash
docker compose up -d postgres redis
```

Or point at your own instances via `DATABASE_URL` and `REDIS_URL`.

### 4. Configure

```bash
cp .env.example .env
```

The minimum for a working local stack:

```bash
DATABASE_URL=postgresql+asyncpg://agoreum:password@localhost:5432/agoreum
DATABASE_URL_SYNC=postgresql+psycopg://agoreum:password@localhost:5432/agoreum
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=<any 32+ character string for local use>
SIWE_DOMAIN=localhost:3000
APP_URL=http://localhost:3000
```

Generate a secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Everything else is optional. Without an Alchemy endpoint, chain reads are
unavailable and the API reports that plainly. Without an escrow address,
payment surfaces say ordering is unavailable rather than offering a button that
cannot work.

**Local overrides** can go in `apps/api/.env`, which is read after the root
`.env` and is gitignored. Useful for keeping development settings out of a file
that also holds production credentials.

### 5. Migrate and seed

```bash
cd apps/api
alembic upgrade head
python -m app.cli seed
python -m app.cli check-db     # verify connectivity and revision
```

### 6. Frontend

```bash
cd apps/web
npm ci
npm run dev
```

### 7. Contracts (optional)

```bash
curl -L https://foundry.paradigm.xyz | bash && foundryup
cd contracts && forge build && forge test
```

## Verify

```bash
curl http://localhost:8000/api/v1/health/ready
```

Expect `database` and `redis` reporting `ok`, and `chain` reporting `degraded`
if no RPC endpoint is configured — which is correct, and is why `chain` is
excluded from the readiness verdict.

```bash
cd apps/api && pytest -q      # 319 tests
cd apps/web  && npm test      # 17 tests
cd contracts && forge test    # 73 tests
```

Chain tests skip unless the Anvil fixture is running. That is expected.

## Known environment issues

**Windows + Python 3.14.** Starlette's threaded `TestClient` can crash on
teardown. The suite uses httpx's ASGI transport instead, so this does not
affect it.

**Docker Desktop needs WSL2.** Without a WSL distribution installed the Linux
engine never starts. Install one, or run Postgres and Redis natively.

**Port 5432 in use.** Another PostgreSQL is already running. Either use it, or
run yours on a different port and set `DATABASE_URL` accordingly.

## Next

- [development.md](development.md) — workflow and conventions
- [architecture.md](architecture.md) — how it fits together
- [deployment.md](deployment.md) — production
