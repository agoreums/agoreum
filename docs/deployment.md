# Deployment

Running Agoreum in production.

> **Nothing has been deployed yet.** These are the intended procedures. Treat
> the first run of each as the first time it has been exercised.

## Target

| Component | Choice | Why |
| --- | --- | --- |
| Host | DigitalOcean droplet, Ubuntu 24.04, 4 GB, 2 vCPU, 120 GB | Sized for early traffic |
| Database | DigitalOcean managed PostgreSQL | A droplet rebuild cannot take the data with it |
| Cache | Redis in a container | Disposable; nothing here needs to survive a restart |
| Edge | Cloudflare | DNS, WAF, CDN, TLS |
| Proxy | Nginx in a container | TLS again, per-IP limits, routing |
| Chain | Base via Alchemy | Read-only |

**Postgres is deliberately not in the production compose file.** Backups,
point-in-time recovery and failover are somebody's full-time job, and that
somebody should not be us at this stage.

## Before the first deploy

- [ ] Droplet provisioned, SSH key access only, password auth disabled
- [ ] Managed PostgreSQL created, droplet added to its trusted sources
- [ ] Cloudflare DNS pointed at the droplet, proxy enabled
- [ ] Cloudflare SSL mode set to **Full (strict)**
- [ ] Cloudflare Origin certificate installed at `infra/nginx/certs/`
- [ ] `.env` present on the droplet with production values
- [ ] Escrow contract deployed and `ESCROW_CONTRACT_ADDRESS` set
- [ ] `JWT_SECRET` generated fresh — never reused from any other environment

## Host preparation

```bash
adduser --disabled-password --gecos "" agoreum
usermod -aG sudo,docker agoreum

apt update && apt upgrade -y
apt install -y docker.io docker-compose-plugin

ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

Only 22, 80 and 443 are open. Postgres and Redis are never exposed: Redis lives
on the internal Docker network and is not published, and the managed database is
reached over its private endpoint.

Consider restricting 80/443 to [Cloudflare's IP ranges](https://www.cloudflare.com/ips/)
so the origin cannot be reached directly, bypassing the WAF.

## Environment

`.env` on the droplet, never in the image and never in git:

```bash
APP_ENV=production
DEBUG=false

DATABASE_URL=postgresql+asyncpg://user:pass@private-host:25060/agoreum?ssl=require
DATABASE_URL_SYNC=postgresql+psycopg://user:pass@private-host:25060/agoreum?sslmode=require

JWT_SECRET=<48+ random bytes, unique to production>
SIWE_DOMAIN=agoreum.xyz
APP_URL=https://agoreum.xyz
CORS_ALLOWED_ORIGINS=https://agoreum.xyz,https://www.agoreum.xyz

CHAIN_ID=8453
ALCHEMY_BASE_URL_MAINNET=<full endpoint>
ESCROW_CONTRACT_ADDRESS=<deployed address>

RESEND_API_KEY=<key>
EMAIL_SENDING_ENABLED=true     # the only place this should ever be true

RATE_LIMIT_ENABLED=true
```

```bash
chmod 600 .env
```

`CHAIN_ID` alone selects the RPC endpoint, USDC address and block explorer.
Setting it to `8453` without also setting `ALCHEMY_BASE_URL_MAINNET` leaves the
chain unreachable, which readiness reports rather than hiding.

## Deploy

```bash
git clone --recurse-submodules https://github.com/agoreums/agoreum.git
cd agoreum
# place .env and infra/nginx/certs/ here

docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
docker compose -f docker-compose.prod.yml exec api python -m app.cli seed
```

Verify:

```bash
curl -s https://agoreum.xyz/api/v1/health/ready | jq
curl -s https://agoreum.xyz/api/v1/chain/status | jq
docker compose -f docker-compose.prod.yml ps
```

Readiness returns 503 if Postgres or Redis is unreachable. The chain is reported
but excluded from the verdict — an RPC outage should degrade the platform, not
take the site out of rotation over a third party.

## Updating

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

Compose replaces containers one service at a time and each has a healthcheck, so
Nginx keeps routing to the old container until the new one is healthy. There is
a brief window where both may serve; migrations must therefore be backwards
compatible with the running version — add columns before using them, drop them
a release later.

### Rolling back

```bash
git checkout <previous-tag>
docker compose -f docker-compose.prod.yml up -d --build
```

If the release included a migration, roll that back **first**, while the old
code is still running:

```bash
docker compose -f docker-compose.prod.yml exec api alembic downgrade -1
```

CI verifies every migration reverses, so this path is tested rather than hoped
for.

## TLS

TLS terminates twice: at Cloudflare's edge, and again at Nginx using a
Cloudflare Origin certificate. Traffic between the two is encrypted rather than
travelling in clear inside the datacentre.

Set Cloudflare SSL mode to **Full (strict)**. Anything less lets the edge accept
an invalid origin certificate, defeating the point.

Origin certificates last 15 years, so there is no renewal automation — and no
renewal cron quietly failing either. See [infra/nginx/README.md](../infra/nginx/README.md).

## Contract deployment

See [contracts.md](contracts.md). Two rules:

1. **Testnet first.** Base Sepolia, with real transactions settling, before
   mainnet is discussed.
2. **The deploy script refuses mainnet** as a compile-time guard. Removing it is
   a reviewable code change, not a flag.

After deploying, set `ESCROW_CONTRACT_ADDRESS` and restart the API. That is the
only wiring step — the address is configuration everywhere.

## Observability

```bash
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f nginx
```

Both emit single-line JSON. Logs rotate at 10 MB × 3 files per container, so a
noisy failure cannot fill 120 GB.

Every request carries a `request_id`, echoed in `X-Request-ID` and in error
envelopes. Nginx logs the same field, so a user's report traces end to end.

Worth alerting on:

| Signal | Meaning |
| --- | --- |
| `/health/ready` non-200 | A required dependency is down |
| `rate_limit_unavailable` | Redis is unreachable; limits are failing open |
| `reorg_detected` | A chain reorganisation touched a recorded transaction |
| `orphan_escrow_event` | On-chain escrow with no matching order — funds need a human |
| `order_chain_divergence` | Database disagrees with the chain |
| `email_send_failed` | Notifications are not arriving |

`orphan_escrow_event` and `order_chain_divergence` are the two that involve
someone's money. Treat them as pages, not tickets.

## Backups

The managed database handles automated backups and point-in-time recovery.
Verify the retention window matches what you would need, and **restore into a
scratch database occasionally** — an unverified backup is a hypothesis.

Redis holds only cache and rate-limit counters. Losing it costs a cold cache.

## Sizing

4 GB across: API 1 GB, web 768 MB, Redis 640 MB, Nginx 256 MB, ~1.3 GB for the
host. Limits are explicit because on a small box an unbounded container pushes
the others into the OOM killer, and the process that dies is whichever allocated
last rather than the one at fault.

Two uvicorn workers for two vCPUs. More would contend for the same cores while
multiplying the database connection pool.

When this stops being enough, the first move is separating web and API onto
different droplets behind a load balancer. The module boundaries make splitting
the API itself possible after that, but that is a later problem.

## What is not automated

CI builds and validates images but **does not deploy**. Deployment is a
deliberate action.

Adding continuous deployment means giving a CI runner SSH access to production.
That is a real security decision — a compromised action, or a malicious
dependency in the build, would reach the host. It should be taken explicitly,
with a deploy key scoped to exactly that, not inherited by default.
