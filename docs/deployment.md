# Deployment

How Agoreum runs in production, at the level a contributor needs. This describes
the deployment *model*, not a specific provider, host, or region, the stack is
containerised and runs anywhere Docker does.

> **Chain state is testnet only.** The escrow contract is deployed to Base Sepolia
> and nothing is on mainnet. Any mainnet action is gated on an explicit decision,
> a real audit, and separated key-holding addresses, see [contracts.md](contracts.md).

## Topology

| Component | Role |
| --- | --- |
| API + web + indexer | Application containers, built from this repo |
| PostgreSQL | A managed database service, kept out of the compose file so backups and failover are handled by the provider |
| Redis | A container on the internal network; disposable, nothing here needs to survive a restart |
| Reverse proxy (Nginx) | TLS termination, per-IP limits, routing; a container |
| Edge (CDN/WAF) | DNS, TLS, caching, and a web application firewall in front of the origin |
| Chain access | An EVM RPC provider, read-only |

**PostgreSQL is deliberately not in the production compose file.** Backups,
point-in-time recovery, and failover belong to a managed service rather than to a
container whose host could be rebuilt out from under the data.

## Before the first deploy

- [ ] A Linux host with Docker and the Compose plugin, reachable only over SSH keys (password auth disabled)
- [ ] A managed PostgreSQL database, with the host allowed through its firewall over a private network
- [ ] DNS pointed at the host through the CDN/edge, proxy enabled
- [ ] Edge SSL mode set to **Full (strict)**
- [ ] An origin TLS certificate installed at `infra/nginx/certs/`
- [ ] `.env` present on the host with production values (never in the image, never in git)
- [ ] Escrow contract deployed and `ESCROW_CONTRACT_ADDRESS` set
- [ ] `JWT_SECRET` generated fresh, never reused from any other environment

## Host preparation

Install Docker and the Compose plugin, then open only what is needed. Everything
but SSH, HTTP, and HTTPS stays closed:

```bash
# firewall: allow SSH + HTTP + HTTPS only
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

Postgres and Redis are never exposed: Redis lives on the internal Docker network
and is not published, and the managed database is reached over its private
endpoint. Consider restricting 80/443 to the [CDN's IP ranges](https://www.cloudflare.com/ips/)
so the origin cannot be reached directly, bypassing the WAF.

## Environment

`.env` on the host, never in the image and never in git:

```bash
APP_ENV=production
DEBUG=false

DATABASE_URL=postgresql+asyncpg://user:pass@private-host:PORT/agoreum?ssl=require
DATABASE_URL_SYNC=postgresql+psycopg://user:pass@private-host:PORT/agoreum?sslmode=require

JWT_SECRET=<48+ random bytes, unique to production>
SIWE_DOMAIN=agoreum.xyz
APP_URL=https://agoreum.xyz
CORS_ALLOWED_ORIGINS=https://agoreum.xyz,https://www.agoreum.xyz

CHAIN_ID=<target chain id>
ALCHEMY_BASE_URL_SEPOLIA=<full endpoint>
ESCROW_CONTRACT_ADDRESS=<deployed address>

RESEND_API_KEY=<key>
EMAIL_SENDING_ENABLED=true     # the only place this should ever be true

RATE_LIMIT_ENABLED=true
```

```bash
chmod 600 .env
```

`CHAIN_ID` alone selects the RPC endpoint, USDC address, and block explorer.
Setting it without also setting the matching RPC endpoint leaves the chain
unreachable, which readiness reports rather than hiding.

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
but excluded from the verdict, an RPC outage should degrade the platform, not
take the site out of rotation over a third party.

## Continuous deployment

A merge to `main` runs CI; when every check passes, the deploy job builds the
images on the host, runs `alembic upgrade head`, recreates the services, reloads
the proxy so it re-resolves the new containers, and verifies the public site
serves before reporting success. If the site does not come back, the job fails
loudly rather than leaving a half-deployed stack looking green.

The runner reaches the host through a deploy key scoped to exactly that action,
not a general-purpose credential, giving a CI runner access to production is a
real security decision and is kept deliberately narrow.

### Rolling back

```bash
git checkout <previous-tag>
docker compose -f docker-compose.prod.yml up -d --build
```

If the release included a migration, roll that back **first**, while the old code
is still running:

```bash
docker compose -f docker-compose.prod.yml exec api alembic downgrade -1
```

CI verifies every migration reverses, so this path is tested rather than hoped
for. Migrations must be backwards compatible with the running version, add
columns before using them, drop them a release later, because there is a brief
window during a deploy where both the old and new code may serve.

## TLS

TLS terminates twice: at the CDN edge, and again at Nginx using an origin
certificate. Traffic between the two is encrypted rather than travelling in the
clear. Set the edge SSL mode to **Full (strict)**; anything less lets the edge
accept an invalid origin certificate, defeating the point. See
[infra/nginx/README.md](../infra/nginx/README.md).

## Contract deployment

### Current testnet deployment

| | |
| --- | --- |
| Network | Base Sepolia (chain 84532) |
| Address | [`0x13c90ba1441bD02d55801Cb2F8bDA3515020A16D`](https://sepolia.basescan.org/address/0x13c90ba1441bd02d55801cb2f8bda3515020a16d) (verified) |
| Deploy block | 44531775 |
| Roles | admin, arbiter, and fee recipient all set to the deployer, **testnet only** |
| Fee | 250 bps (2.5%), cap 1000 bps |

Mainnet must use three genuinely separate addresses, with admin and fee recipient
behind a multisig. The single-key arrangement here exists only because a testnet
has nothing at stake.

### Procedure

See [contracts.md](contracts.md). Two rules:

1. **Testnet first.** Base Sepolia, with real transactions settling, before
   mainnet is discussed.
2. **The deploy script refuses mainnet** as a compile-time guard. Removing it is
   a reviewable code change, not a flag.

After deploying, set two values from the deployment receipt and restart:

```bash
ESCROW_CONTRACT_ADDRESS=<deployed address>
ESCROW_DEPLOY_BLOCK=<block the deployment landed in>
```

The address is configuration everywhere, so nothing else needs changing. The
deploy block is what the indexer starts from the first time it runs against this
contract, there is nothing to find before it, and without it the only safe
default is genesis, which is not a viable scan on a live chain.

## Running the indexer

**Nothing is marked funded or completed until the indexer runs.** It is a separate
process, not part of the API, and runs as its own long-lived service:

```bash
python -m app.cli index-chain --follow --interval 15
```

Two reasons it is separate rather than a background task inside the API: indexing
must not stop while the API is being redeployed, and two API replicas would
otherwise both index the same range concurrently.

Concurrency is nonetheless safe, events are keyed by `(tx_hash, log_index)`, so a
duplicate scan applies nothing twice, but doing it by accident wastes an RPC
allowance.

Position is stored in `indexer_cursors`, keyed by chain id **and** contract
address. Redeploying the contract therefore starts a fresh scan from
`ESCROW_DEPLOY_BLOCK` rather than inheriting the old contract's height and
silently skipping the new one's first events, funding included.

Each run resumes `REORG_DEPTH` (64) blocks behind the stored position. Blocks
already covered may have been reorganised since; re-applying an event costs
nothing, missing one is permanent.

Two sibling workers run the same single-instance shape and for the same reasons:

```bash
python -m app.cli index-subscriptions --follow --interval 15
python -m app.cli deliver-webhooks --follow --interval 5
```

`index-subscriptions` trails the subscription contract and is the only thing that
activates a subscription, judged by its own cursor exactly like the escrow indexer.
`deliver-webhooks` drains the outbox, signing and posting due deliveries and
retrying failures; it makes no outbound call until `WEBHOOK_DELIVERY_ENABLED` is
set, marking due deliveries suppressed until then so the queue cannot grow
unbounded. Having no chain cursor to trail, it records a Redis heartbeat each pass,
which is the signal `/health/workers` reads. Both are covered by that probe.

## Observability

```bash
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f nginx
```

Both emit single-line JSON. Logs rotate per container, so a noisy failure cannot
fill the disk. Every request carries a `request_id`, echoed in `X-Request-ID` and
in error envelopes; the proxy logs the same field, so a user's report traces end
to end.

Worth alerting on:

| Signal | Meaning |
| --- | --- |
| `/health/ready` non-200 | A required dependency is down |
| `rate_limit_unavailable` | Redis is unreachable; limits are failing open |
| `reorg_detected` | A chain reorganisation touched a recorded transaction |
| `orphan_escrow_event` | On-chain escrow with no matching order, funds need a human |
| `order_chain_divergence` | Database disagrees with the chain |
| `email_send_failed` | Notifications are not arriving |
| `chain_scan_complete` **absent** | The indexer has stopped; paid orders are not being credited |

`orphan_escrow_event` and `order_chain_divergence` are the two that involve
someone's money. Treat them as pages, not tickets.

The indexer is the one to alert on by **absence** rather than by an error line. It
emits `chain_scan_complete` on every pass; if that stops appearing, buyers are
funding escrows and nothing is marking their orders paid. A silent indexer looks
exactly like a quiet marketplace.

A small monitor container turns those signals into pages without a hosted service.
It polls the public site end to end, `/health/ready`, `/health/indexer` and
`/health/workers` on a fixed interval, and messages a chat bot when the state
changes: once when a problem starts and once when it clears, rather than every
interval in between. A short run of consecutive failures is required before it
pages, so a routine recreate that briefly returns 502 does not wake anyone, and a
daily heartbeat confirms the monitor itself is alive. The two worker probes are
what make a stalled subscription indexer or a stuck webhook loop page on their own,
rather than being noticed later. It stays silent until a chat id is configured, so
it is safe to run before alerting is wired.

## Backups

The managed database handles automated backups and point-in-time recovery. Verify
the retention window matches what you would need, and **restore into a scratch
database occasionally**, an unverified backup is a hypothesis. Redis holds only
cache and rate-limit counters; losing it costs a cold cache.

A nightly logical dump runs alongside the provider snapshots as a second, portable
layer: a `pg_dump` in custom format, rotated on a short retention, with credentials
read at runtime and never written to the command line or a log. Provider snapshots
are tied to the provider; a logical dump restores anywhere Postgres runs, which is
what you want on the day the provider itself is the problem.

Prove the restore, do not assume it. The drill is to load the latest dump into a
throwaway Postgres container and compare row counts per table against production.
A dump that has never been restored is a hypothesis; a restore whose row counts
match is the evidence. Rehearsing it also means the steps are familiar the one time
they are run under real pressure.

## Resources

Each container sets an explicit memory limit. On a modest host an unbounded
container can push the others into the OOM killer, and the process that dies is
whichever allocated last rather than the one at fault, so the limits are stated in
`docker-compose.prod.yml` rather than left to chance.

Two uvicorn workers per API container matches a two-core host; more would contend
for the same cores while multiplying the database connection pool. When one host
stops being enough, the first move is separating web and API behind a load
balancer; the module boundaries make splitting the API itself possible after that.
