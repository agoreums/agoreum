# Contract incident runbook

What to do when something goes wrong with the deployed contracts. Every claim
here is backed by a test that runs in CI, cited by name, rather than by
reasoning about the code. Where a scenario has no test, that is stated.

Both contracts are **non-upgradeable**. There is no proxy, no `delegatecall`, and
no `selfdestruct`. Remediation is therefore always some combination of pause,
repoint, redeploy, and wait. Nothing can be patched in place.

## First, the two things that are always true

**No one can drain principal.** Neither contract has a sweep, withdraw, or
migrate function. `settleDispute` splits only between that escrow's own buyer and
provider, and `_assertSolvent` reverts any path where `released + refunded`
exceeds `amount`. Asserted continuously by the `contractIsSolvent`,
`noEscrowEverOverpays` and `valueIsConserved` invariants, the last of which uses
independent ghost accounting so it cannot agree with a bug in the contract's own
bookkeeping.

**Pausing never strands funds.** `pause()` blocks `createEscrow` and `dispute`
only. `release`, `refund` and `settleDispute` all keep working while paused, so a
pause stops new exposure without trapping anyone who already committed money.
This is deliberate, and it is the single most useful property during an incident:
pausing is close to free.

## Scenario: a bug is found in a deployed contract

1. **Pause immediately.** `pause()` from `GOVERNOR_ROLE`. This stops new escrows
   and new disputes. It does not stop settlement of what already exists.
2. **Decide whether existing escrows can safely run to completion.** They always
   *can* terminate: every funded escrow reaches Released, Refunded or Settled,
   and the buyer can always `refund()` once the delivery deadline passes. Whether
   they *should* depends on the bug.
3. **Deploy a corrected contract.** New address, new deploy block.
4. **Repoint the application**, setting `ESCROW_CONTRACT_ADDRESS` and
   `ESCROW_DEPLOY_BLOCK` to the new deployment and restarting. Indexer cursors
   are keyed on chain id *and* contract address, so the indexer rescans from the
   new deploy block rather than inheriting the old contract's height. This is
   already handled; no manual cursor surgery is needed.
5. **Let the old contract drain.** In-flight escrows on the abandoned contract
   cannot be migrated. There is no mechanism to move them and none can be added.
   They must be left to reach a terminal state, which they always can.

The gap worth naming: between steps 3 and 5 there are two live contracts, and the
old one is still settling. Support needs to be able to answer questions about
both.

## Scenario: USDC blacklists a participant

Real USDC on Base is an upgradeable proxy with an issuer-controlled blacklist.
All four cases below are covered by `test/AgoreumEscrow.fork.t.sol`, which runs
against the live token on a mainnet fork rather than a mock.

Those tests **run in CI on every push to main**, so the remedies in this table
are executed rather than reasoned about. That was not true until 2026-08-14:
they skip themselves without an RPC URL, so they had only ever run when somebody
remembered to run them locally, and this page was citing them as its evidence
throughout. The CI job asserts six passed and zero skipped, because a suite that
skips itself still exits zero.

| Who is blacklisted | Effect | Remedy |
| --- | --- | --- |
| **Provider** | `release()` reverts. No governance action helps, because the failing leg is the provider's. | Buyer calls `refund()` after the delivery deadline and recovers the full principal. Covered by `test_buyerStillRecoversFromABlacklistedProvider`. |
| **Fee recipient** | `release()` reverts for **every** escrow, including ones funded long before. | Governor calls `setFeeConfig` with a new recipient. Stuck escrows settle immediately afterwards. Covered by `test_realBlacklistOnFeeRecipientIsRecoverableByRepointing`. |
| **Buyer** | `createEscrow` reverts. | Nothing to do. It fails at the door and strands nothing. |
| **Everyone (global pause)** | All transfers halt, so no escrow can settle. | Wait. Do not attempt a migration. Funds are immobile, not lost, and settlement resumes when the pause lifts. Covered by `test_usdcGlobalPauseFreezesSettlementUntilLifted`. |

The fee recipient case is the one to watch, because a single blacklisting of a
treasury address blocks settlement platform-wide until someone repoints it. It is
also the easiest to fix. Monitor it.

## Scenario: a governance key is compromised

Assume the attacker holds `DEFAULT_ADMIN_ROLE` and `GOVERNOR_ROLE`.

**What they can do:**

- Raise the fee up to `MAX_FEE_BPS`, a hard-coded 1000 bps (10%) ceiling that
  nobody can exceed. Verified by `test_feeCannotBeRaisedAboveTheHardCeiling`.
- Redirect the fee stream, including on escrows that are already funded, because
  `feeRecipient` is read from live storage at payout time. The fee **rate** is
  frozen per escrow at creation, so already-funded work cannot be repriced:
  `test_raisingTheFeeDoesNotRepriceExistingEscrows`.
- Grant themselves `ARBITER_ROLE` and settle any escrow that a party has already
  disputed: `test_adminCanGrantItselfArbiterAfterDeployment`.
- Pause new escrows, denying service.

**What they cannot do:**

- Move principal to an arbitrary address. There is no such function.
- Raise a dispute themselves, so they cannot reach `settleDispute` on a healthy
  escrow unilaterally. One of the two parties must dispute first:
  `test_governorCannotDisputeOnBehalfOfAParty`.
- Exceed the 10% fee ceiling.

**Response:** if a second admin holder exists, revoke the compromised account's
roles immediately. If the compromised key is the *only* admin, the contract
cannot be recovered: deploy fresh and repoint. This is why admin should be a
multisig, and why the deploy script now refuses a mainnet deploy whose admin has
no code.

## Scenario: governance is lost entirely

Renouncing `DEFAULT_ADMIN_ROLE` without first granting it to a successor leaves
the contract permanently ungovernable. Nobody can pause, change the fee, or grant
any role, ever. Covered by
`test_renouncingAdminWithoutASuccessorIsIrreversible`.

Escrows still settle normally, which is the saving grace, but the contract can
never be paused again and the fee recipient can never be repointed, so a later
blacklist of that recipient would be unrecoverable.

**The handover order therefore matters: grant to the new admin, verify with
`hasRole`, and only then renounce.** Covered end to end by
`test_fullHandoverToMultisigLeavesTheOldAdminPowerless`.

## Scenario: the database is lost or corrupted

Tested on 2026-08-08, not theoretical. The figures below are from that drill.

DigitalOcean restores by **forking**: it builds a new cluster from a backup at a
point in time and leaves the running one untouched. There is no in-place restore
to get wrong, and the original stays available throughout, so the decision to cut
over is separate from the decision to restore.

### The procedure

1. List backups and choose one.

   ```
   GET /v2/databases/{cluster_id}/backups
   ```

   The list is **not ordered**. Take the maximum `created_at` rather than the
   first element; reading the first cost me a false alarm about backups having
   stopped a week earlier.

2. Fork it.

   ```
   POST /v2/databases
   {"name": "...", "engine": "pg", "version": "18", "region": "lon1",
    "size": "db-s-1vcpu-1gb", "num_nodes": 1,
    "backup_restore": {"database_name": "agoreum-db",
                       "backup_created_at": "<chosen backup>"}}
   ```

   It returns immediately with status `forking`. Poll `GET /v2/databases/{id}`
   until `online`.

3. Connect to the right database. The connection URI points at `defaultdb`; the
   application's data is in `agoreum`, and `umami` comes across as well. Swap the
   database name in the URI or the first query fails with "relation
   alembic_version does not exist", which looks like a failed restore and is not.

4. Verify with TLS properly, not by disabling it. The cluster presents
   DigitalOcean's own CA, so fetch it and verify against it:

   ```
   GET /v2/databases/{id}/ca        # base64 in .ca.certificate
   ```

   A drill that turns verification off proves the shortcut works, not the
   procedure.

5. Check what came back: `select version_num from alembic_version`, the table
   count, and row counts per table. Compare against production **as of the backup
   time**, not as of now.

6. Destroy the fork when finished. It bills by the hour and holds a second copy
   of user data.

   ```
   DELETE /v2/databases/{id}
   ```

### What the drill found

The restore is sound. Differences against live production were all explained by
the ten hours of activity between the backup and the check:

| | Production, at check time | Restored, from a 15:21Z backup |
| --- | --- | --- |
| alembic head | `f8b0d2e4a6c7` | `c5e7a9b1d3f4` |
| tables | 31 | 30 |
| rows | 274 | 189 |

The restored head is older because three migrations were deployed after that
backup, and `organization_invitations` is the missing table for the same reason.
Row counts are lower by exactly the sessions, notifications and nonces created
since. A restore that matched production exactly would have meant the backup was
not a point in time at all.

### Recovery objectives, measured

- **RPO, worst case about 24 hours.** Backups are automated daily, around 15:21
  UTC, with eight retained. Anything after the last one is gone. That is the
  number to argue with if it is unacceptable, and it is a cost decision rather
  than a technical one.
- **Provisioning takes about 3.5 minutes.** Measured on the second drill by
  polling: 213 seconds from the fork request to `online`, for this cluster size
  and a database of this size. The first drill did not measure it.
- **A full restore and cutover rehearsal took 422 seconds end to end**, fork
  request to fork destroyed, including migrating the restored cluster and
  verifying the application against it.

## Scenario: cutting the application over to a restored database

Rehearsed on 2026-08-09 with a separate API instance, production untouched
throughout. This is the second half of recovery; restoring the data is the first.

### Two things that will bite

**`DATABASE_URL` is not the only database setting.** The application reads
`DATABASE_URL`, and **alembic reads `DATABASE_URL_SYNC`**. Overriding only the
first gives an instance whose queries go to the restored cluster while its
migrations go to production.

The rehearsal did exactly that by accident and it looked fine: `alembic current`
reported `f8b0d2e4a6c7 (head)` while the application's own query on the same
container reported `organization_invitations` missing. The two were talking to
different clusters. Running `alembic upgrade head` at that point would have
migrated **production** during an incident. Set both, and confirm they name the
same host before running anything.

**A restored instance reports healthy while its schema is behind.** The readiness
probe checks that the database answers, not that it matches the code. The
rehearsed instance returned `{"status":"ok"}` with a schema three migrations old,
against which any request touching the newer tables fails. Health is not a schema
check; run `alembic current` and compare it to `alembic heads` yourself.

### The procedure

1. Restore, as in the scenario above, and note the new host.
2. Build both URLs against the restored cluster, matching the shapes production
   uses:
   - `DATABASE_URL`: `postgresql+asyncpg://.../agoreum?ssl=require`
   - `DATABASE_URL_SYNC`: `postgresql+psycopg://.../agoreum?sslmode=require`
   The connection URI DigitalOcean returns names `defaultdb`; change it.
3. Start one instance against it before touching the live one:

   ```
   docker run -d --name agoreum-api-cutover --network agoreum_internal      --env-file /root/agoreum/.env      -e DATABASE_URL='<async url>' -e DATABASE_URL_SYNC='<sync url>'      -e REDIS_URL=redis://redis:6379/1      agoreum-api
   ```

   A separate Redis database index keeps its cache and rate limit counters out of
   the live one's.

4. Bring the schema up: `alembic upgrade head`, then confirm `alembic current`
   equals `alembic heads`.
5. Verify it serves: `curl http://127.0.0.1:8000/api/v1/health/ready` from inside
   the container, and query a table the newest migration created.
6. Only then change the live service, and remove the rehearsal instance.

### What the rehearsal proved

The application came up against a restored database and served correctly:
readiness ok with database, redis and chain all healthy, 31 tables and the
expected four users after migrating from `c5e7a9b1d3f4` to `f8b0d2e4a6c7`, with
the three intervening migrations applying cleanly to restored data.

Production was verified untouched afterwards: same head, same row count.

## What is watched

`scripts/monitor.py` alerts on the escrow's governance events, so a hostile or
mistaken change is visible without waiting for somebody to complain:

| Event | Alert |
| --- | --- |
| `FeeConfigUpdated` | fee config changed |
| `TreasuryUpdated` | TREASURY REDIRECTED |
| `RoleGranted` | ROLE GRANTED |
| `RoleRevoked` | role revoked |
| `Paused` / `Unpaused` | contract paused, contract unpaused |
| `EscrowSettled` | DISPUTE SETTLED |

Every topic is the keccak of the declaration in `contracts/src`, precomputed so
the monitor keeps its standard-library-only promise. A wrong topic fails silently,
the alert simply never fires, which is worse than having no alert because it looks
like coverage; they are regenerated and checked against the source when an event
signature changes.

`EscrowSettled` alerts on every settlement rather than only an unexpected one.
Settlements are rare, each divides somebody's money by a decision, and one nobody
expected is the exact shape of a compromised arbiter key.

An earlier version of this page said under "what is not covered" that governance
events were unmonitored and that this should be fixed before mainnet. That has been
untrue since the monitor gained those topics. A runbook is read during an incident
by somebody deciding what to trust, so understating its own coverage is the wrong
kind of wrong.

### Watched from outside the droplet

Three things watch from outside the droplet and report to the same Telegram
channel, so an operator has one place to look rather than four.

| What | Watches | Alerts |
| --- | --- | --- |
| `infra/uptime-worker` on Cloudflare cron | the public site and the API, **every minute** | after two consecutive failures, and again on recovery |
| `.github/workflows/uptime.yml` | the same two targets, every half hour, best effort | after three spaced attempts fail, and again on recovery |
| `.github/workflows/ci.yml` (`Notify` job) | every CI job on a push to main | naming the jobs that failed, and again when main returns to green |

**Two uptime checks is deliberate.** They run on different providers and share
no infrastructure with each other or with the droplet, so a fault in either
scheduler still leaves the site watched. Cloudflare is the primary because it
actually runs every minute. GitHub is the backup because it does not: measured,
its first scheduled run took about a hundred minutes to appear and it has fired
sparsely since. That is documented GitHub behaviour for high-frequency crons,
not a misconfiguration, and it is the reason the primary moved.

Both stay silent while healthy, and both check that their own credentials
resolve before deciding they have nothing to say. Without that, a workflow whose
secrets had stopped working would look exactly like a quiet, healthy one.

The uptime check asserts the API returns live JSON with `status: ok`, not merely
that a page loads. Edge caching is off today, so a 200 does mean the origin
answered, but if that is ever turned on a page check alone would silently become
a test of Cloudflare's cache. JSON that a static cache cannot fake is the guard
against that.

**Limits, stated so nobody assumes otherwise.** Detection is about two minutes,
being two consecutive one-minute checks, not instant. Neither check can report
that Cloudflare itself is unreachable in a way that also takes down the Worker,
though the GitHub check covers that case from a different provider, which is
half the reason it is kept. GitHub additionally disables scheduled workflows in
a repository with no activity for sixty days.

**When reading Worker state, pass `--remote`.** Without it `wrangler kv key get`
reads local storage and reports `Value not found` for a key that exists, which
looks exactly like a Worker that is not running. That cost time during setup:
the cron was firing correctly the whole while and the reading tool was wrong.

## Scenario: the deploy fails with "Permission denied (publickey)"

Happened on 2026-08-10, immediately after a GitHub personal access token was
revoked, and the connection is not obvious.

The droplet pulls over SSH, using `~/.ssh/gh_deploy`. That key had been added to
the **account**, and GitHub removes account SSH keys that were created using a
token when that token is revoked. So revoking a token that nothing appeared to
depend on removed the credential the deploy depended on. Every test passed and
only the deploy job failed, which is the correct shape for this: nothing was
wrong with the code.

The fix, which is also the hardening, is that the same public key is now a
**read-only deploy key on the repository** rather than a key on the account.
That is narrower in every direction: it reaches one repository, it cannot push,
and no token revocation can sweep it away.

To confirm which kind of key is in use, run this on the droplet:

```
ssh -T git@github.com
```

`Hi agoreums/agoreum!` is a repository deploy key, which is what you want.
`Hi agoreums!` is an account key, which is the fragile arrangement.

The general lesson is worth more than the fix: **revoking a credential can
remove other credentials that were created with it.** Before revoking, ask what
that credential was used to create, not just what uses it now.

## Scenario: the host reboots or the stack is recreated

Drilled on production rather than reasoned about, on 2026-08-09.

A reboot was issued, and then, separately, the whole stack was taken down with
`docker compose down` (removing every container and the internal network) and
brought back with `up -d`. Nothing was touched by hand in either case.

| Event | Time to full service |
| --- | --- |
| Droplet reboot | SSH at 16s, all ten containers running at 30s, verified healthy at 45s |
| Full stack recreate from cold | 43s from `up -d` returning to everything healthy |

Both returned unattended. What was checked afterwards was not just "the
containers are running", which proves little, but that the things that fail
silently were actually working: both indexers resumed from their cursors in
Postgres and were back to a five block lag, and the webhooks worker was writing
its heartbeat again within seconds.

Two facts worth keeping in mind:

- **Redis holds nothing that needs to survive.** It has no persistence
  configured, deliberately. Everything in it is a rate-limit counter, a worker
  heartbeat or a cache entry, all with expiry, so a cold start loses nothing
  that matters. If anything durable is ever put in Redis, that changes and this
  note is the place it will be missed.
- **The public URL is a truthful signal, and this was checked rather than
  assumed.** The first write-up of this drill claimed Cloudflare had served a
  cached page while the origin was down, inferred from a 200 arriving very soon
  after the reboot. That was wrong. `always_online` is off, HTML returns
  `cf-cache-status: DYNAMIC` so it is not cached at the edge, and the monitor's
  own log from the stack recreate records the public URL returning **HTTP 521**,
  Cloudflare's "web server is down", rather than a stale page. The fast 200 was
  simply a fast recovery. This matters because it is what makes an external
  uptime check on the public URL meaningful at all.
- **A 521 means the origin, not Cloudflare.** When distinguishing an origin
  failure from an edge problem, check the origin directly with
  `curl -k -H "Host: agoreum.xyz" https://localhost/en` on the droplet. A 521 at
  the edge with a healthy origin points at the Cloudflare firewall allowlist, not
  the application.

## What is not covered

Stated plainly so nobody assumes otherwise:

- **A host-level outage is detected in about two minutes, not instantly.**
  Nothing inside the host can page anybody about the host being gone: the
  monitor went down with it during the drill and sent nothing. That is covered
  from outside by the Cloudflare cron Worker, which checks every minute and
  alerts on the second consecutive failure, with the GitHub workflow behind it.
  Two minutes is the deliberate cost of not paging on every one-minute blip.

- **No timelock.** Every governance action is immediate. There is no delay in
  which to notice and react to a hostile `setFeeConfig` or `setTreasury`.
- **Separation of duties is enforced at deploy time only.** `DEFAULT_ADMIN` can
  grant itself `ARBITER_ROLE` afterwards, so separation is an operational
  commitment the contract does not maintain for you.
- **The arbiter is a single key on testnet.** It cannot steal, since
  `settleDispute` pays only the escrow's own buyer and provider, but it decides
  how a disputed escrow is divided and there is no timelock and no appeal. Making
  it a multisig is a recorded mainnet blocker in `docs/contracts.md`.
- **The subscriptions contract has one untested live-only revert:** if `treasury`
  equals the subscriber, `subscribe()` reverts with `UnsupportedToken`, because
  the balance-delta guard sees no net change on a self-transfer. Moot with a
  separated treasury, which mainnet enforces, but worth knowing.
