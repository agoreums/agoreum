# Operating model

How this project is run. Written down because the work spans sessions and the
context that produced a decision is usually gone by the time the decision is
questioned.

One person does all of the below. The point of splitting it into areas is not
pretend headcount, it is that each area has a different failure mode, a different
definition of "done", and a different set of things that quietly rot when nobody
is looking at them. A single list of tasks hides that; a set of standing
responsibilities does not.

## Start of session: read this before doing anything

The recurring failure across this build has not been bad work. It has been
starting work without reading what is already true, then asking for access that
already exists or reporting something as missing when it is not.

Two concrete instances, both in one session. I grepped `.env` for
`GITHUB_TOKEN|GH_TOKEN|GITHUB_PAT`, found nothing, reported that no GitHub
credential existed, and skipped opening a pull request. The token is on line 22
under a different name. Minutes earlier the same mistake with DigitalOcean. In
both cases the file was right there and I searched it for names I had invented
instead of reading it.

So: **read `.env` top to bottom, as a file, before concluding anything about
access.** Never grep it for a guessed name. If something seems missing, that
belief is far more likely to be wrong than the file is to be empty.

### What access actually exists

`.env` at the repository root is the single source of truth for every credential
this project has, and it is gitignored. It currently carries working credentials
for GitHub (fine-grained, including releases and tags), DigitalOcean, Cloudflare
(DNS and R2), Alchemy, Basescan, Resend, Telegram, Discord, Reown, Umami, PyPI
and npm, plus the chain deployment roles and the receipt signing key. Read it for
the names.

Facts about this machine that have cost time before:

- The `gh` CLI is **not installed**. Use the GitHub REST API with the
  fine-grained token. Creating and merging pull requests both work that way.
- The droplet is reachable directly:
  `ssh -i ~/.ssh/agoreum_droplet root@209.97.186.80`, repository at
  `/root/agoreum`, production `.env` beside it. That key gives a real shell.
- The key CI uses is a **different** key and is force-command locked to `deploy`,
  so it cannot set secrets or run arbitrary commands. Production environment
  changes go over the direct shell above, not through CI.
- Containers are named `agoreum-<service>-1`, not `agoreum-<service>`.
- Local Postgres runs on port 55432, not 5432. Foundry lives in
  `C:\Users\Agoreum\foundry`, not on `PATH`.
- CI runs on push to `main` **and on every pull request against it**. Corrected
  on 2026-08-16, having read here for days as "there is no pull-request trigger,
  so a green tick on a branch does not exist and merging is what actually tests
  and deploys". `ci.yml` has carried `pull_request: branches: [main]`
  throughout. Only `Deploy`, `Notify` and `Fork tests` skip on a pull request,
  so eleven jobs really do report on a branch before anything is merged.

  This one cost something rather than being a tidy-up. Believing no branch
  signal existed, a previous session recorded PR #30 below as verified and ready
  to merge while its `Contracts` job was failing, and it had never once been
  green. Two separate causes were sitting in a log nobody opened, because this
  file said the log did not exist.

  **A note claiming a signal is unavailable is the most expensive kind of
  stale**, because every other kind of stale note gets corrected by somebody
  going to look, and this kind is specifically an instruction not to.

### Then read the running record

`## Running record` immediately below is the state of the project as of the last
batch of work. It is the part written for a cold start: what is true now, what
each strand did last, what is open, and what was decided and why. Everything
after it is durable doctrine and the archive of findings, which is worth reading
but does not change week to week.

### And update it before you stop

The record is only worth reading if it is true, and a rule to keep it true is
worth nothing on its own. This project has spent a month proving that a stated
invariant with no check under it drifts, in the SDK version constants, in the
scope catalogue, in two documents quoting test counts maintained by hand.

So: **before reporting a batch of work or moving to the next one, update the
running record in the same commit as the work.** Not afterwards, not at the end
of a session, because the moment the work feels finished is exactly the moment
the record stops feeling urgent.

`scripts/check_state_record.py` enforces it. If a commit changes code and the
record's `Last updated` line is older than that commit, CI fails and names the
commits that landed without the record moving. That check exists because
"remember to update the document" is the same class of instruction as every
other one that rotted, and the fix for those was never a stronger reminder.

**Forgetting something already established is a failure to read this file, not
an ordinary cost of working across sessions.** Claiming access is missing when
it sits in `.env` is the same failure. Both are treated as defects with a root
cause, and the root cause is never "should have tried harder".

## Running record

**Last updated:** 2026-08-22, after `9f79868`.

Written so that a session starting cold, whether that is a fresh instance or the
same one resuming, can act from this section rather than reconstruct it.

### Where the project is right now

Testnet only, on Base Sepolia, in the hardening and expansion phase set on
2026-08-16. The platform is live at `agoreum.xyz` and usable end to end:
identities, published services, orders, on-chain escrow, disputes with an
arbiter path, native USDC subscriptions, three published SDKs, a remote MCP
server, a published OpenAPI contract, and signed settlement receipts. Nine
locales. Nothing is deployed to mainnet and nothing may be without an explicit
instruction naming it.

The single structural advantage, and the thing every decision defends: reputation
is computed only from orders that settled through escrow, against an ERC-8004
landscape where between 98.7% and 100% of on-chain reputation records carry no
proof of payment at all.

### Live production facts

Verified against the running artifact rather than the repository, on the date
shown. Anything here that cannot be re-derived from production is a defect in
this section.

| Fact | Value | How it was checked |
| --- | --- | --- |
| Origin | Droplet `209.97.186.80`, repo at `/root/agoreum`, locked to Cloudflare ranges | SSH, direct shell |
| Containers | `agoreum-<service>-1`, ten of them, all up | `docker ps` |
| API health | database, Redis and chain all ok, chain ~1.5s behind head | `/api/v1/health/ready` inside the container |
| Workers | subscription indexer, webhooks, emails, all heartbeating within 3s | `/api/v1/health/workers` |
| Receipts | **signing live and proven end to end**, kid `rVl3VOYAtNY4LW0J` | a real settled order's receipt verified against the published key, then its transaction confirmed on chain |
| Settled orders in production | One, `AGO-TMMR2TWH`, self-dealt by construction. It **does** count toward its agent's reputation, because the platform cannot see the relationship. Agent paused and unlisted | the exercise below |
| Escrow contract | `0x13c90ba1441bD02d55801Cb2F8bDA3515020A16D` on Base Sepolia, 8,741 bytes | `eth_getCode` |
| Chain funds | admin/arbiter address holds ~0.287 ETH and ~496 USDC on Base Sepolia | `eth_getBalance`, `balanceOf` |
| SDKs | Python, TypeScript, Go all at 0.2.0 | verified from the registries, not the local build |
| Suites | API 744+ passing with 0 skipped, asserted; contracts 142 with 0 skipped; fork suite runs in CI | CI |

### What each strand did last, and what is next

| Strand | Last action | Next |
| --- | --- | --- |
| Security | Found the platform's central claim rested on one untested branch, and made it structural. Verified receipts sign in production against the deployed artifact | Continue the sweep for the "looks covered, never exercised" shape; it has produced a real finding every time |
| Backend and API | Found `build()`, the function that issues a receipt, had no test at all, and that the one test named for the settlement refusal passed a random uuid and never reached it. Eleven tests added, four mutations | Prove the receipt path over a real settled order rather than a fake session |
| Contracts | Fixed the two failures that had kept `Contracts` red on every open branch, and corrected a gas measurement that read nothing back from a transfer that can return false | Settlement cost measurement is recorded; no open work |
| Frontend and web | Built `/verify`, where anyone can check a receipt in their own browser without an account and without trusting us. Mark sizing corrected at its two definitions; social cards name Base Sepolia | Continue raising the interface to the standard set for this phase |
| Infrastructure | Recovered production from a silent indexer outage caused by a half-rotated credential, and closed the class with a consistency check wired into the deploy | Decide whether the monitor should retain logs across a container recreate, since the fix destroyed the evidence of whether it paged |
| Product and growth | Discord read in full, nothing unanswered; the only recent messages are members talking to each other, and posting into that would be manufactured activity | Keep inbound answered as a standing responsibility |

### Open threads

| Item | State | What it needs |
| --- | --- | --- |
| ~~Apply the exclusion to `AGO-TMMR2TWH`~~ | **Closed 2026-08-21** | Excluded, recomputed through the new admin endpoint, and confirmed in production: the agent publishes zero settled orders and zero volume |
| The arm's-length filter does nothing for personal organizations | Open, understood | It keys on membership, and a personal organization has one member and cannot gain another. Covered for team organizations and for orders created outside `create_order`; not covered otherwise |
| Cross-language verifier conformance beyond the browser | Open | The API and the browser are now pinned to identical canonical bytes by tests on both sides. The three published SDKs do not verify receipts at all yet, and adding it would make the canonical form a contract with four implementations rather than two |
| Reputation is not Sybil resistant across unrelated accounts | Accepted, documented | Nothing. No reasonable check catches it, and the honest claim is economic rather than absolute |
| `NEXT_PUBLIC_BASE_RPC_URL` is a dead build arg | Open, cosmetic | Nothing in `apps/web/src` reads it; remove or wire it |
| Chain health is not in `required_components` | Deliberate, now asserted at deploy | `/health/ready` says `ok` while the chain is down. Making it required would drop the API out of service on any RPC blip. The monitor covers it, so the gap is that the top-level status word cannot answer "is the product working" |
| Monitor logs do not survive a recreate | Open | Recreating the container during an incident destroyed the evidence of whether it had paged |
| Nothing watched the clock until 2026-08-21 | Closed | The monitor now compares against a `Date` header. Worth asking what else is trusted without ever being measured |
| A dispute has never been raised or settled in production | Open, next exercise | The contract half is proven; the operational half has never carried a real case. Design it before running it, as with the settlement exercise |
| Who holds platform admin | Blocked, deliberately | Owner decision, expected alongside the multisig conversation. Not to be granted before then. See the standing constraint |
| ~~A divergence could be reported but never closed~~ | **Closed 2026-08-22** | `reconcile` named the first real divergence and nothing could act on it. Repair added, admin gated, copying only what the contract holds and refusing to paper over a structural one |
| Three Safe multisigs on Base | Blocked | Owner action |
| Security audit engagement | Blocked | Owner action |
| Mainnet deployment | Blocked | Both rows above, plus an explicit written instruction naming mainnet |
| PyPI 0.1.0 yank | Blocked | Account-level action the publish token cannot perform |

### What has never happened in production, 2026-08-21

`scripts/audit_never_exercised.py` is the instrument for the second class in the
taxonomy above. A decayed claim is found by re-reading it against the code. A
never exercised one is invisible to code reading, because the code is correct,
so the only way to find it is to ask what has actually happened.

First run against production, 5 of 12 capabilities exercised:

| Exercised | Never exercised |
| --- | --- |
| an order funded on chain (1) | an account holding platform admin |
| an order settled (1) | an order refunded |
| a subscription taken out (2) | a dispute raised |
| an API key created (3) | a dispute settled |
| an order excluded from reputation (1) | a review written |
| | a webhook endpoint registered |
| | an agent published |

**A map, not a defect list.** On a testnet platform with six accounts most of
these are legitimately unused, and calling that a problem would be noise. What
it is for is refusing the sentence "that path works" when what is meant is "that
path exists".

**The one that matters most is disputes.** Neither raising nor settling one has
ever happened in production. That is the operational half of the single
situation this product exists to handle: money held between two parties who
disagree. The contract half is thoroughly proven, with the fork suite and the
invariants, and the operational half, meaning the arbiter queue, the statements
from both sides and the recorded decision, has never carried a real case. It was
ranked first in the backlog when it was built, and building it is not the same
as running it.

The refund path is second for the same reason: it returns a buyer's money and
has never executed against production.

**"An agent published" reading zero is correct rather than alarming**, and is a
good example of why this needs a reader. The verification agent from the
settlement exercise was paused deliberately, so the marketplace holds no active
agent, which is the intended state.

**Next exercise, designed before it is run.** A dispute rehearsal on Base
Sepolia, following the settlement exercise's pattern: written up first, run
against production, and with its reputation consequences worked out in advance
rather than discovered afterwards. The settlement exercise taught that the
interesting part is not whether the happy path works but what the exercise does
to the numbers the platform publishes. Not started in this batch, because it
writes real rows and deserves a fresh start rather than the end of a long one.

### Sweep worklist, and what has been checked

Kept here so the next session works the remaining candidates instead of
re-checking these. 89 found, 5 worked. **Two were real, three were sound**, and
the three are recorded because a sweep that only ever reports problems is not
measuring anything.

| Claim | Where | Verdict |
| --- | --- | --- |
| "the fast read path and the authoritative computation cannot drift apart" | `reputation/service.py` | **False.** True of the agent, never true of the service. Fixed |
| "the only way an account becomes an admin" | `cli.py` | **True and insufficient.** Verified as the only assignment, and nobody had ever used it, so the surface was reachable by nobody |
| "kept in sync with payout_wallet_id by the service layer" | `agents/models.py` | Sound, and stronger than stated. One write path, wallet addresses immutable, `RESTRICT` on the key, and a database constraint forces a payout wallet to be verified |
| "it never raises, so a webhook problem cannot fail the action" | `notifications/service.py` | Sound. `dispatch` swallows everything, and the whole path sits inside `_safe_notify`, which wraps a savepoint around it. All seven event helpers route through it and the only direct call is inside the wrapper |
| "a validator can nudge block.timestamp by seconds, which cannot move a decision" | `AgoreumEscrow.sol` | Sound, and the premise is enforced rather than assumed: `MIN_WINDOW = 1 hours`, checked at creation for both windows |
| "it cannot reach the limiter: limiters are route-level dependencies" | `api/deps.py` | Sound. The guard enumerates limiters rather than hardcoding a count, so it survives new ones being added, and refuses to pass when it finds none |

**The pattern in the two that failed** is worth stating separately from the
claims themselves. Neither was a lie and neither was careless. One was true when
written and decayed when a second path appeared. The other was true the whole
time and described a door nobody had opened. **True and sufficient are different
properties**, and only the first is what a reader checks when they write the
sentence.

### A second admin authority nobody held, 2026-08-21

The sweep's second finding, and the same defect as the first in a different
costume.

**There are two administrative authorities here and they are granted in
completely different ways.** `is_platform_admin` compares an account's address
to `ESCROW_ADMIN_ADDRESS`, so it is granted by configuration and gates `/admin`.
`require_admin` reads `user.role`, granted only by an operator running the CLI
on the host, and gates the admin dashboard and subscription plan management.

Both are reasonable. Both fail closed when unset, which is correct. Neither said
anything when it did.

`ESCROW_ADMIN_ADDRESS` was unset in production for the whole life of the admin
surface, found earlier this session. Checking the other half now: **no account
in production holds `UserRole.ADMIN`.** All six users are `user`, so the admin
dashboard and subscription plan management have been reachable by nobody,
including the owner, since they were built. One plan exists, created outside the
API.

The claim in `cli.py` that it is "the only way an account becomes an admin" is
true, and verified: `user.role` is assigned in exactly one place. The trap is not
that the claim is false, it is that being the only path is worth nothing if
nobody has walked it, and nothing was ever going to mention that.

**Not granted, and the reason matters.** The account matching
`ESCROW_ADMIN_ADDRESS` is the obvious candidate and I hold its private key.
Granting it platform admin would be escalating my own privileges, whatever the
intent, so it is the owner's call and is flagged rather than done.

**What is done** is that startup now warns when either authority is reachable by
nobody, naming the surface and how to grant it. A warning rather than a refusal,
because a deployment may legitimately not have granted these yet and refusing to
start would turn a dormant surface into an outage. The failure being fixed is
silence, not permissiveness.

Writing the test found a real flaw in the first version. It queried the database
first and returned early when that failed, so a database hiccup silently
suppressed the address warning, which needs no database at all. Two independent
conditions must be able to fail independently. Three mutations each caught:
removing either warning, and narrowing the exception so a database failure
escapes and breaks startup.

### Sweeping for claims that were true once, 2026-08-21

Made deliberate after the service counter defect, because that one is the
sharpest instance of the month's pattern and the least likely to be found by
accident. The false confidence did not come from a missing test. It came from a
**true statement that stopped being true**, checked against one code path,
while a second path quietly started touching the same data.

This is the inverse of the hedged-language sweep already recorded here. That one
looked for uncertainty: "not tested", "worth confirming", "we assume". A hedge
invites a check. A confident claim closes the question, and goes on closing it
long after the code underneath has moved.

`scripts/sweep_invariant_claims.py` lists them: 89 across 281 files, grouped by
the phrase that makes them a claim. The highest-yield shapes are the ones a
second code path can invalidate: "kept in sync", "cannot drift", "the only
thing", "nothing else reads", "one source of truth". It produces a worklist and
never a verdict, which is the only honest output for something a person has to
go and check.

**What the first pass found.** The highest-stakes claim was
`agents.payout_address` being "kept in sync with payout_wallet_id by the service
layer": a denormalised field that decides where money goes. It holds, and it
holds more strongly than the comment says. One code path writes both together,
no path mutates a wallet address after creation, the foreign key is `RESTRICT`
so a referenced wallet cannot be deleted, and a database constraint already
forces any payout wallet to be verified. The comment credits the service layer
for something the schema enforces.

**Standing, not a pass.** The remaining candidates are worked the same way,
a few at a time, and the sweep is re-run when the code has moved. Two of the
first three produced real findings, which is a high enough yield that treating
it as a one-time exercise would be leaving evidence on the table.

**What the audit did not prove, which matters more than what it did.**
`scripts/audit_invariant_claims.py` checks eight of these against a real
database. Run against production it passed all eight, and that is close to
worthless: production holds one agent, one order and no reviews, so most of the
checks are satisfied vacuously. The local database has 200 users and zero
agents, because the tests that create them roll back.

So the script now refuses to let a pass read as a result. Below twenty rows in
the smallest table it prints a warning saying the run is close to no evidence at
all. The instrument is worth having for when there is data to measure; today it
measures almost nothing, and saying "8 of 8 claims hold" without that caveat
would be exactly the kind of confident sentence this sweep exists to catch.

### The marketplace rating disagreed with the reputation, 2026-08-21

Found by asking, after the snapshot fix, what else caches a figure the filtered
computation is supposed to govern.

`recompute` refreshes the cached counters on the agent row, and its docstring
says that is so the fast read path and the authoritative computation cannot
drift apart. **That was true of the agent and had never been true of the
service.** `Service.review_count` and `Service.rating_sum` were incremented when
a review was written and decremented when one was withdrawn, and nothing ever
reconciled them against the filtered computation.

`Service.average_rating` derives from those counters and is published in the
marketplace listing, the service detail and search results. So excluding an
order from reputation dropped its review from the agent's figures and left it in
the rating a buyer actually browses. The reputation system disowned the review
and the shop window kept showing it.

Demonstrated before it was fixed: with one settled, reviewed order excluded,
`gather_inputs` reported zero reviews while the service still reported one at
five stars.

The counters are now derived from the rows under the same filter rather than
adjusted in place. An incremental counter is only ever as correct as every path
that touches it, and the reason this was wrong is that a path appeared which
nobody thought to teach about counters. Three mutations, each caught: removing
the refresh, dropping the filter so excluded reviews return, and zeroing every
service, which is the control that would otherwise have deleted every real
rating on the platform while passing the first test perfectly.

**A docstring asserting an invariant is not the invariant.** This one said the
two could not drift apart, was written by somebody who had checked the agent,
and was half wrong for as long as it existed.

### The exclusion was recorded and invisible, 2026-08-21

Found by using the feature against production rather than by any test, which is
the point.

Excluding `AGO-TMMR2TWH` returned 200, wrote the timestamp and reason, and
correctly refused a repeat with `already_excluded`. The agent's public
reputation kept showing the excluded order.

**The endpoint does not compute anything.** `/agents/{slug}/reputation` serves a
stored `ReputationSnapshot` and computes one only when none exists. Excluding an
order changes what a fresh computation would produce and changes nothing anybody
can see.

**Four tests passed throughout, because all four asked a question the endpoint
does not ask.** Every one asserted `gather_inputs`, the internal computation.
Not one asserted the number a visitor reads. That is the same shape as the
`accepted_chain_ids` assertion that was true in both branches: coverage that is
real, careful, mutation tested, and pointed slightly to one side of the thing
that matters.

**The broader half was worse.** Nothing recomputed a snapshot when an order
settled. Only review activity did. So an agent's published figures were fixed at
whichever read happened first and then refreshed only if somebody wrote a
review: settle a second, third and tenth order and keep publishing the numbers
from the first. That inverts the single claim this platform makes, which is that
reputation follows settled trade.

Both closed. The indexer recomputes when an order reaches a terminal state,
swallowing failures because a stale score is a wrong number while a stalled
indexer is orders that never leave pending. The exclusion recomputes without
swallowing, because an operator told the exclusion succeeded while the number
stays wrong is worse than an error.

**And the fix did not reach the case that prompted it**, which is worth its own
line. The exclusion of `AGO-TMMR2TWH` was recorded *before* recompute-on-exclusion
shipped. The write was durable, a repeat was correctly refused as
`already_excluded`, and the published figure stayed wrong with nothing able to
correct it: every future exclusion was covered and the one already made was not.
Deploying a fix and watching the number not move is the only reason that was
noticed.

So `POST /admin/agents/{slug}/recompute-reputation` exists now. It is a repair
tool for a published number that has stopped following the data, and it is safe
by construction rather than by care: `recompute` derives every figure from
orders and reviews and takes no argument that could carry a score, so the only
reachable outcome is the published number matching the rows. A test asserts
exactly that, by recomputing an agent with no settled trade and requiring it to
produce none.

Two tests now assert the published figure rather than the internal one, and the
mutation that removes the recompute fails the exclusion test with the exact
production symptom.

**The lesson, stated for the next time.** Ask what the user reads, not what the
function returns. Every finding in this class has been a test that was correct
about something adjacent to the thing that mattered.
### Production-only code was never executed by any test, 2026-08-21

Found by pulling the same thread as the logging blind spot, deliberately rather
than by accident: what else is configured more quietly in tests than in
production.

`APP_ENV` is `test` in CI and `development` locally, so every branch guarded by
`settings.is_production` was dead code as far as the suite was concerned. Three
of them are security controls.

- **The sign-in chain policy.** Outside production the verifier also accepts
  Base mainnet and Base Sepolia so the flow can be exercised; in production it
  accepts exactly the configured chain. The only test asserted `CHAIN_ID in
  accepted_chain_ids()`, which is true in both branches and could never have
  caught the narrowing being lost. A deployment that kept the permissive set
  would accept a signature produced for a different chain, which is the entire
  reason the chain id is inside the signed message.
- **Strict-Transport-Security**, added only in production and only at
  construction time.
- **TrustedHostMiddleware**, installed only in production. It fails loudly in
  one direction: a hostname missing from the allowed set answers 400 for
  everything reaching it. The internal names are the dangerous ones, because
  the container healthcheck arrives as `127.0.0.1` and the web container calls
  the API as `api`, so dropping either takes production down while every test
  stays green.

None of this needed a deployment to test. `create_app()` and the middleware are
built at call time, so flipping the setting and constructing them executes the
real branch. Eight tests, and three mutations each caught by the test that
claims to cover it: dropping the narrowing, dropping HSTS, and commenting out
one internal hostname.

Each control was then checked against the live site rather than only in a test.
Production serves `max-age=63072000; includeSubDomains; preload`, answers 403 to
a forged `Host` header, and reports `accepted_chain_ids: [84532]`, exactly one
chain.

**Two controls were checked and found genuinely sound**, which is worth saying
because a hunt that only ever reports problems is not measuring anything.
`RATE_LIMIT_ENABLED` is false in CI, but `tests/test_security.py` forces it on
through a fixture, requires Redis, and asserts real 429s, and the whole-suite
skip assertion means it cannot quietly stop running.

### The droplet clock was three days behind, 2026-08-21

Found because the running-record guard failed CI, which is the only reason it
was found at all.

Every date I wrote during this batch came from the droplet, which reported
2026-08-18 while GitHub, this workstation and the real world were on 2026-08-21.
NTP corrected it part way through the session. Nothing anywhere reported the
skew; the guard simply refused a record dated before the commits it was meant to
describe, and chasing that disagreement is what surfaced it.

**Why this matters more here than on most servers.** Every deadline this product
enforces is a timestamp comparison against that clock: the funding window that
freezes a price, the delivery window, the auto-release deadline after which
anybody may release an escrow, and the dispute window a buyer relies on. A clock
that jumps forward expires all of them at once. A permissionless auto-release
firing early pays a provider before the buyer has had their window to dispute,
which is exactly the property `invariant_deadlinesNeverMove` exists to protect,
defeated from outside the contract entirely.

**Blast radius was nil, and only by luck.** Production holds one order, already
completed and released by hand, with no live auto-release or funding deadline.
Checked rather than assumed.

**Now watched.** The monitor compares its own clock against the `Date` header of
a response it already fetches, so the check costs no extra request and needs no
time service of its own. Tolerance is half an hour, generous on purpose, because
this is looking for a clock wrong by days rather than drifting by seconds and an
alert that fires on ordinary NTP correction is one people learn to ignore. It
returns "unknown" rather than "fine" when it cannot read the header, which is
the difference between a check that abstains and one that lies. Verified against
the real skew of about three seconds, against a simulated three-day skew which
alerts, and against a network failure which abstains.

**The general shape.** A wrong clock is not a wrong answer, it is every
time-dependent answer being wrong at once, quietly, while every component
reports healthy. Worth asking of anything else the system trusts without
measuring: not "is it configured", but "when did anything last check it".

### The Alchemy rotation, 2026-08-21

A rotated key, updated in one of the three places it lived, took the production
indexer down silently. Worth writing up in full because every layer that should
have caught it had a reason not to.

**What happened.** `ALCHEMY_API_KEY` was rotated and updated.
`ALCHEMY_BASE_URL_MAINNET` and `ALCHEMY_BASE_URL_SEPOLIA` embed the same key
inside a URL and were not. The old key was revoked, so both URLs 401ed. The
indexer raised `ChainUnavailableError` on every poll. Orders would have stopped
being funded or settled.

**Why nothing was obviously wrong.** `/health/ready` returned `status: ok` with
`chain: down`, because only database and Redis are required components. That is
a defensible choice, since making the chain required would take the API out of
service on any RPC blip, but it means the top-level status word cannot be used
to answer "is the product working".

The monitor does iterate the components and would have flagged it. Whether it
actually paged is **unknown**, and unknown because recreating the container
during the fix destroyed its logs. Recorded as unknown rather than assumed
either way.

**The fix, and the class.** Production env corrected, all eight containers
checked for the dead value rather than the four that were obviously affected,
and two were still carrying it. Then `scripts/check_env_consistency.py`, which
requires every place a credential appears to agree, wired into the deploy before
migrations so a wrong configuration is refused rather than noticed later.

**That guard was wrong on its first deploy, in an instructive way.** It assumed
the standalone variable always exists and failed when it found no pair to
compare. Production carries only the URL, so the very first deploy after it
shipped was refused on a perfectly good environment. Two lessons, and the second
matters more.

A check must not confuse "nothing to compare" with "misconfigured": one
occurrence cannot disagree with itself, and that is a pass. It now fails only
when none of the named variables exist at all, which is what a rename looks
like.

And the guard could never have caught the actual incident where it happened.
Consistency only exists between two occurrences, and production has one, so the
protection it offers lives on the workstation rather than on the server that
went down. **What would have caught it is a liveness check, not a consistency
check.** The deploy now asserts the chain is genuinely reachable rather than
reading the overall status word, which stays `ok` while the chain is down
because the chain is deliberately not a required component. Verified against the
exact JSON production served during the outage, where the old check read `ok`
and passed.

**A second outage, self-inflicted, during the fix.** Recreating the containers
by hand gave them new IPs, and nginx resolves upstreams at load time, so the
site 502ed until nginx was reloaded. `deploy.sh` documents exactly this and does
the reload; working outside it meant not getting it. The lesson is narrow: use
the deploy path, or repeat its steps deliberately.

### The admin surface had never been reachable, 2026-08-21

Production carried no `ESCROW_ADMIN_ADDRESS`, so `is_platform_admin` returned
false for every account and every `_require_admin` endpoint answered 403 to
everybody, for the whole life of the surface. The gate failing closed was
correct. Nobody had ever checked that it opened.

**A claim I made about this was wrong and is corrected here.** I first reported
that the dispute queue was among the unreachable endpoints. It was not: the
queue is gated on the arbiter, which production did have configured, and the two
authorities are deliberately separate so that running the platform does not
confer the power to decide who gets the money. I found this by writing a test
asserting an admin could open the queue, which failed with `not_arbiter`. The
code was right and the test was wrong.

What was actually unreachable: email suppressions, and the new reputation
exclusion endpoint.

The tests around this surface asserted who *may* use it and that the routes
exist in the schema. None called one, which is how both this and the logging
defect below got through.

### Every logger.info call was invisible to the test suite, 2026-08-21

The most useful finding of the batch, and it was found by a mutation surviving.

The exclusion endpoint raised `TypeError` in production on its own logging call,
because it passed context as bare keyword arguments where this project's adapter
wants `extra=`. After fixing it, restoring the bug as a mutation left the suite
completely green, including a new end-to-end test that drives the endpoint over
HTTP and reaches that exact line.

**The cause is systemic.** pytest ran at the default WARNING level.
`Logger.info` checks `isEnabledFor` before touching its arguments, so at WARNING
every info call in the codebase returns before doing anything. A malformed one
executes nothing, raises nothing, and looks tested. That covered all 106 logging
calls in the project, not one.

Fixed with `log_level = "INFO"` in the pytest configuration, after which the
mutation fails with the exact production error. The full suite still passes, 738
tests, and an AST audit of all 106 calls found no other offender.

The shape is worth keeping: **a test environment configured more quietly than
production does not test production.** The same question is worth asking of
anything else the suite turns down or off.

### The settlement exercise, run 2026-08-16

**Done, and the receipt path is proven end to end for the first time.** Order
`AGO-TMMR2TWH` on Base Sepolia: escrow funded, delivered, released, indexed, and
a signed receipt issued over real database rows rather than a fake session.

Verified the way somebody who trusts nothing would, with no credential except a
public RPC endpoint:

- the key was fetched from the public URL, and its kid matches the one the
  receipt names
- the canonical form was rebuilt from the sentence the key document publishes
  rather than imported from our code, so the check does not inherit our
  assumptions
- the signature verifies, and altering the released amount breaks it
- the named transaction `0x340f7bfc...` at block 45568344 succeeded, went to the
  escrow contract the receipt names, and emitted `EscrowReleased` for exactly
  the escrow id derived from the order

That last step is the one that matters. The signature only proves Agoreum made a
claim. Following the transaction is what proves the claim is true, and until
this run nothing had ever done it against real data.

**The self-dealing half did not work as planned, and that is the most useful
thing the exercise produced.** The intention was to add the buyer to the
provider's organization so the arm's-length filter would exclude the order. The
API refused: `personal_org_immutable`, a personal organization cannot have its
team changed. Correct behaviour, and it exposes a limit in the fix shipped hours
earlier that the tests could not have shown.

**The filter is narrower than it was described as being.** It keys on
organization membership. An agent in a *personal* organization has exactly one
member and can never gain another, so for those agents the filter reduces to
precisely the condition `create_order` already enforces: buyer is the owner. It
adds real defence for team organizations, and for orders arriving by any route
that does not pass through `create_order`, and it adds nothing else for the
default case. The claim that it defends against "the buyer joining the
provider's organization later" is true only where such joining is possible,
which is not personal organizations.

That was written in the same batch as the fix and before anything exercised it.
Being wrong in a document about the thing just built is the ordinary case rather
than the surprising one, which is the argument for exercises like this.

**What the exercise therefore left in production.** One settled order that the
platform cannot tell was self-dealt, because the two accounts share nothing it
can see: different wallets, different users, no common organization. That is
exactly the Sybil case the fix explicitly does not cover, now demonstrated
rather than theorised.

Exposure measured rather than assumed: the agent is paused, holds no services,
and appears in neither the marketplace agent nor service listings, which both
return zero items. Its page and reputation resolve at a direct URL to a reader
who knows the slug, showing one completed order, 1.025 USDC of volume and no
score, since three settled orders are needed before a score is published.

**Open, and the honest resolution.** Reputation should be excludable for an
order known to be non-arm's-length even where the platform cannot infer it. The
safe shape is a flag that can only ever remove a contribution, never add one, so
the mechanism cannot become a way to manufacture standing. Recorded in the open
threads rather than improvised at the end of a batch.

**The listing was withdrawn immediately.** The verification service was, briefly,
the only item in the public marketplace, which is the closest thing to fake
marketplace data this exercise could produce. Service archived, agent paused,
catalogue back to zero items. The order and escrow stay, because they are real
and the receipt points at them, which is also why archiving is not deletion.

### Why it was not simply "go and run it"

Authorised on 2026-08-16 as a low cost, reversible testnet action, which it is.
Preparing it surfaced something that changes the shape of the task, recorded
here because the next session will otherwise re-derive it.

Driving a real order to settlement in production means one person controlling
both sides. That is self-dealing, and until this was found, a settled self-dealt
order counted toward the provider's reputation in full. So the exercise as
originally imagined would have manufactured exactly the wash-traded reputation
this platform exists to be structurally free of, in the production database, as
its first settled order.

The fix landed first, and it changes what is possible. Reputation now excludes
orders whose buyer belongs to the provider agent's organization, at computation
time rather than only at order creation. So an exercise where the two accounts
share an organization produces a genuine settled escrow, a genuine receipt over
real rows, and no reputation at all, which is the correct outcome on every axis.

The remaining wrinkle is ordering. `create_order` refuses a buyer who is already
a member, so the membership has to be established after the order exists rather
than before. That is not a workaround: the trade genuinely was between related
parties, and the record ends up saying so.

Kept because the reasoning is what made the run safe, and because the next
person to propose an end-to-end exercise on any new rail will face the same
question: what does driving both sides of a real transaction do to the numbers
this platform publishes.

### Decisions taken, and why

Recorded here when the reasoning would not survive being rediscovered. The
durable ones are in `## Standing constraints`; the archive of findings is in
`## Backlog`.

- **Reputation is escrow only, permanently.** Any cheap high-frequency
  settlement rail is, read adversarially, a machine for manufacturing settled
  volume at gas prices. Wiring one into reputation would sell the only
  differentiator for the price of gas. Decoupling costs nothing.
- **A payment channel is not being built yet.** The premise was that settling
  each call on chain is too expensive, and nobody had measured it. It is now
  measured against a real fork rather than assumed, in
  `docs/micropayment-settlement-cost.md`.
- **The record gets a check, not a reminder.** See the section above.

### Session log

Terse, most recent first. One line per batch, enough to know what happened
without reading the commits.

- **2026-08-21.** An Alchemy key rotation took the production indexer down and
  nothing said so. Fixed, then closed the class with a check. Found the admin
  surface had never been reachable in production, corrected a claim I made about
  which endpoints that affected, and found that the entire test suite ran at
  WARNING so every `logger.info` call in the project was never executed by any
  test. Relicensed to Apache 2.0. Gave the landing field depth and motion that
  describes settlement.
- **2026-08-16, latest+2.** Built the public receipt verification page at
  `/verify`, which checks a pasted receipt in the reader's own browser and
  reports attribution and chain evidence as two separate findings rather than
  one tick. Building it found that the canonical form was under-specified:
  Python escaped non-ASCII and JavaScript does not, so a verifier following the
  published sentence would have computed a different digest on any receipt
  carrying an accent. Fixed on both sides and pinned to identical literals.
- **2026-08-16, latest+1.** Built the reputation exclusion as a one-way
  mechanism enforced by a database trigger rather than by the service layer, so
  a future endpoint, a script, a migration or a psql prompt all meet it equally.
  Proven by dropping the trigger and watching both one-way tests fail.
- **2026-08-16, latest.** Ran the settlement exercise. Receipt path proven end
  to end for the first time: a real settled order's receipt verified against the
  published key, then its transaction confirmed on chain by following the hash.
  The exercise also disproved part of what had been written about the
  arm's-length filter hours earlier, which is the argument for running it.
- **2026-08-16, later.** Found that the only thing preventing self-dealt
  reputation was one untested branch of `create_order`, and that reputation
  itself re-established nothing. Fixed structurally at computation time, filter
  applied to every figure that could flatter an agent and deliberately not to
  the ones that count against it. Made the running record enforceable rather
  than aspirational, and the guard for that was itself wrong when written and
  caught by mutation. Fixed the Cloudflare browser integrity check refusing the
  well-known documents to a plain client, scoped to that path, with the rule in
  the repository rather than a console.
- **2026-08-16.** Confirmed receipts sign live in production and closed the loop
  from outside: a production signature verified against the key fetched from the
  public URL by a client that reimplemented the canonical rules from the
  published instructions rather than importing ours. Merged #30, #31 and #32.
  Found and fixed two Contracts failures that had never been green, a gas
  measurement that could report a plausible number for a transfer that did
  nothing, an operating model note asserting CI had no branch signal, and a
  receipts feature whose issuing function had no test. Measured a Cloudflare
  403 against one common client on the well-known documents.

## Standing constraints

These are not defaults to be weighed against other factors. They are settled.

| Constraint | Meaning |
| --- | --- |
| Nothing on mainnet | No deploy, no transaction, no verification against Base mainnet without an explicit instruction naming it |
| Flag before irreversible, costly, or externally visible | Anything reaching a third party, spending money, or hard to undo gets described first and executed after |
| Commits attributed to the project alone | Author is Agoreum. No co-author trailers, no tool attribution |
| No em dashes | In code, comments, commits, docs, and messages |
| Honest reporting | Failures reported as failures, with the evidence. A thing is "done" when it has been verified, not when it has been written |
| No manufactured activity | No giveaways, points programmes, airdrops, engagement campaigns or paid promotion, and no KOL or influencer arrangements. Reputation on the platform comes only from orders that settled on chain, and a community inflated by campaigns would contradict the one claim the product rests on |
| Not hiring until after the audit | Applications and partnership pitches of that shape are declined directly, with the reason, and without checking first. Settled on 2026-08-15 rather than decided per message |
| Reputation is escrow only, and arm's length | Reputation is computed only from orders that settled through escrow, and only where the buyer is not a member of the provider agent's organization. No other settlement rail may ever feed it, whatever gets built later. Escrow-only settled 2026-08-16; the arm's-length half added the same day, after finding a settled payment from yourself to yourself counted in full |
| Admin access is granted deliberately, never by default | No account holds platform admin and none is to be granted until a real decision is made about who holds it, expected alongside the multisig conversation for the contract roles. Both authorities stay unreachable and the startup warning stays, so the gap is visible rather than silent. Settled 2026-08-21. The path existing, and one signer being available, is not a reason to walk it |
| No unreleased work in public | Upcoming features, internal roadmap and research stay in this repository. Discord, the website and the documentation only ever show what has shipped |

**Why reputation is escrow only, since it will look like an arbitrary
restriction the first time a cheaper rail exists.** The one structural advantage
this project has over the rest of the ecosystem is that its score cannot exist
without a settled payment behind it, against an ERC-8004 landscape where between
98.7% and 100% of on-chain reputation records carry no proof of payment at all.
Any cheap high-frequency settlement rail is, read adversarially, a machine for
manufacturing settled volume at gas prices. That is not hypothetical: it is the
wash trading already visible in x402's published numbers. Wiring such a rail into
reputation would sell the only differentiator for the price of gas. Decoupling
costs nothing and removes the entire class, so an attacker who self-deals a
million calls buys nothing.

## Decision rights

**Done without asking:** writing and refactoring code, tests, migrations that
have a working downgrade, documentation, dependency updates, configuration in the
repository, non-destructive investigation of production, and reversible fixes to
things that are demonstrably broken.

**Described first, then done on the word:** anything that sends mail to a real
person, spends money, touches mainnet, rotates or revokes a credential, deletes
data, changes DNS, or alters something the public can see. Also any change whose
blast radius I cannot state confidently.

**Never done:** working around a permission that was refused, or presenting an
assumption as a verified fact.

## Phase: hardening and expansion

Set on 2026-08-16. One to two months of serious hardening and expansion on
testnet, with mainnet as the outcome of that period rather than an event inside
it. The standard for the end of it: when the owner says deploy to mainnet and
connect the hardware signer, **there is nothing left to find**.

That phrasing sets the bar deliberately high, and it changes what counts as
finished. A thing is not done because it works; it is done when the way it could
fail has been looked for and either closed or written down. The weeks before this
phase found nine defects of the same family, every one of them in code that
worked and was believed correct, so the assumption that anything unexamined is
fine has already been tested and failed.

It also rules out spending the phase re-reading what exists. Auditing is the
floor. The work is new capability across the whole stack, and the sections below
are organised so the six strands can run at once rather than in a queue.

## Areas of responsibility

### Security

Owns: the threat model, authentication, secrets, dependency and supply chain
posture, disclosure handling, and the security posture of everything the other
areas produce.

Good looks like: every trust boundary has something enforcing it, and the
enforcement is tested by asserting the negative case. Every secret has exactly one
source of truth. Untrusted input is treated as hostile at the point it enters, not
somewhere downstream.

Standing checks: is anything user-controlled reaching a place that implies we
wrote it. Does any credential have more scope than its job needs. Is the
disclosure address monitored and answered.

### Backend and API

Owns: `apps/api`, the data model, migrations, background workers, and the
contract the SDKs depend on.

Good looks like: the request path does only what the request needs, with anything
slow or third-party moved to a worker. State transitions are driven by the chain
rather than by optimism. Every migration applies, reverses, and reapplies.

Standing checks: does a failure here corrupt the caller's transaction. Is a queue
draining. Does an endpoint's rate limit match how a real person uses it, in both
directions.

### Frontend and web

Owns: `apps/web`, the nine locales, accessibility, performance, and the fact that
a feature is not delivered until a person can actually reach it.

Good looks like: every API capability has a path through the interface, in every
locale, and the interface reports what actually happened rather than what was
intended.

Standing checks: does every link in an outbound message resolve. Does the
interface distinguish "we tried and it failed" from "we did nothing". Is a new
string translated everywhere, since a missing key is a render error.

### Contracts

Owns: `contracts`, the escrow and subscription logic, the test and invariant
suites, deploy scripts, and verification on the explorer.

Good looks like: money cannot be lost or locked by any sequence a participant can
force. Governance actions are constrained and observable. Behaviour is proven
against a fork of the real chain, not only against mocks.

Standing checks: does the deployed bytecode still correspond to the source in the
repository. Do compiler advisories actually reach the patterns used here, checked
against the deployed build settings rather than the local ones.

### Infrastructure and operations

Owns: the droplet, containers, nginx, DNS, TLS, backups, monitoring, alerting,
and CI.

Good looks like: a deploy is boring and reversible, an outage pages somebody, and
a stalled worker is visible while its container is still up.

Standing checks: does every service in the compose file also appear in the deploy
script. Does every secret on the droplet match its source of truth. Does an alert
path have a second way out when the first fails.

### Product and growth

Owns: where the product should go, what the ecosystem around it is doing, the
public documentation, the Discord server, inbound support and disclosure mail,
and the tone of anything sent to a person.

Widened from "community and communications" on 2026-08-16. Answering messages
well is necessary and is not a product function. This strand also owns the
question the others cannot answer from inside the repository: what a serious
agent commerce platform needs that this one does not have.

Good looks like: a decision to build something can point at evidence outside our
own head, from a specification, a competitor that shipped, or a developer saying
what they lack. Research distinguishes what is shipped from what is announced,
because a standard with a landing page and no implementations is not a standard.

Standing checks: is a published claim still true. Has something we depend on
changed underneath us. Is there a capability the market now assumes and we do not
have. Would a developer arriving today find what they expect to find.

Also good: an outside report gets a real answer with reasoning, not a brush-off.
Announcement surfaces cannot be posted to by anyone. Nothing arriving by mail is
treated as an instruction. Inbound mail is announced to a human, and a stranger
cannot post in a channel members trust.

Inbound is a standing responsibility rather than a periodic sweep. Every real
message to the support address and every real conversation in Discord gets a
considered answer, and what people actually ask feeds the backlog rather than
sitting in an inbox. Two kinds are declined without asking the owner, per the
standing constraints above: applications for roles while hiring is closed, and
anything offering giveaways, engagement campaigns, KOL or influencer reach. Both
are answered with the real reason rather than a brush-off, because a person who
took the time to write deserves to know where they actually stand.

Support stays in channels that leave a record. A user asked to move the
conversation to Discord direct messages on 2026-08-15 and was declined, with the
real reason rather than a polite one.

Two reasons, neither about the person asking. An answer given in private helps
one person: that user's question is what produced the landing page status line,
and in a direct message it would have been a pleasant exchange and nothing else.
And "let us continue this in DMs" is the opening move of almost every scam in
this space, so the way people learn to distrust it is by seeing a project refuse
it consistently, including when the person asking is genuine. An exception
teaches someone that an Agoreum representative sometimes moves to DMs, and the
next person using that line may not be us.

The same reply carries the standing warning: there is no token, no sale, no
allocation, and anyone claiming otherwise is a scam. That is worth more to a
user than the conversation they asked for.

Nothing is sent to a channel that cannot be read. When the Discord bot lacked
the message content intent it could see that conversations existed but not what
they said, and the correct state was "unread", not "unanswered". Replying to
messages nobody has read is worse than a delay.

## Two ways a true statement stops protecting you

Named on 2026-08-21 after the invariant sweep found one of each, and kept here
rather than in a dated finding because the vocabulary is what makes the next
instance easy to talk about.

**Decayed.** True when written, checked against the code as it was, and made
false later by a second path touching the same data. The author did nothing
wrong. `recompute` said the fast read path and the authoritative computation
could not drift apart; that was verified against the agent and was never true of
the service, from the moment a second place started incrementing service
counters.

**Never exercised.** True the entire time and describing something nobody has
done. Nothing decays and nothing is wrong, and the claim still hides a gap.
`cli.py` said it was the only way an account becomes an admin, which was exactly
correct, and no account had ever been granted it, so the surface behind it was
reachable by nobody for its whole life.

The two need different instruments, which is why separating them matters.
Decayed claims are found by re-reading a claim against the code that exists now,
which is what `scripts/sweep_invariant_claims.py` produces a worklist for. Never
exercised claims are invisible to any amount of code reading, because the code
is correct: they are found only by asking whether anybody has ever taken the
path, and answering that against real data.

**True and sufficient are different properties.** When a sentence asserts a
guarantee, only the first is usually checked, because it is the only one that
feels like the author's responsibility.

## Verification standard

Earned by getting each of these wrong at least once.

1. **A local pass is not evidence for anything involving configuration.** This
   machine has credentials and a state that a fresh deployment does not. CI is
   more honest than local, and still not authoritative: a migration once passed
   apply, reverse, reapply and `alembic check` in CI and was refused outright by
   the production database, because the two environments do not run identical
   installed versions. Treat each environment as evidence about itself only.
2. **A test that skips is not a test that passes.** A suite reporting hundreds of
   skips is reporting that it did not check.

   Acted on rather than repeated: as of 2026-08-14 the API suite runs in CI with
   **zero** skips, 649 of 649, and the contract fork suite runs there too. Both
   needed something CI did not have, a local chain node and a mainnet RPC URL,
   and both had been skipping in silence while documents cited them as evidence.
   Where a suite can skip itself, the job now asserts it did not, because a
   skipped test still exits zero and that is indistinguishable from success in
   every summary anybody reads.

   Revisited on 2026-08-15 and found half-done, which is worth more than the
   original fix. The assertion covered `test_chain.py` alone, so every other
   skippable test in the suite was still unwatched: the guard was written while
   looking at the tests that had just been caught skipping, and inherited their
   scope. It now covers the whole suite and prints each skip with its reason.

   The same look found the check partly aimed at nothing. It grepped for
   `^SKIPPED` or `[0-9]+ skipped`, and under `-q` this pytest prints no final
   counts line at all, so the second pattern could never match and "N passed"
   could not be read back out of any log, in CI or locally. The step no longer
   passes `-q`. Both halves were then mutation tested: with every dependency up
   the guard is silent, and with Redis stopped it fails and names the seven
   tests that skipped and why.
3. **Verify the deployed artifact, not the repository.** Read the running
   container's configuration and the explorer's verification metadata.
4. **Follow the whole path a person takes.** An endpoint that works and a link
   that 404s is a broken feature.
5. **Two sources of truth for a secret is zero.** Sync, then confirm from the
   consuming side.
6. **When a claim is convenient, check it harder.** Most of the real defects here
   were found by testing something already believed to be true.
7. **The item as written is rarely the real problem.** Standing doctrine rather
   than an observation. Service versioning turned out to be unfrozen dispute
   windows. Organization refinement turned out to be a consent bug. Writing tests
   for the order state machine found an auto release hole in a fix already
   declared complete. A restore drill found a dual URL trap that would have
   migrated production during an incident. Preparing a testnet exercise found the
   configured arbiter held no on-chain role. Every one surfaced by going to look
   rather than by reasoning about it, so budget for the looking, and expect the
   thing you find to be adjacent to the thing you went in for.

8. **A measurement measures the instrument too.** The first load test put the API
   at 67 requests per second. The real figure was 333: four fifths of the
   apparent load was one endpoint in the test's own mix making an outbound RPC
   call on every request. The instrument was measuring itself. That first number
   was not merely imprecise, it pointed at entirely the wrong problem, and acting
   on it would have meant tuning workers that were never the constraint. Before
   reporting a number, account for what the act of measuring contributed to it.
   The corollary is that a surprising result is more often a broken measurement
   than a broken system, and it is worth ruling that out first. A colour-contrast
   check in the same batch parsed the wrong CSS block and would have reported a
   clean palette it had never read.

   A third instance, 2026-08-15, caught before it was reported rather than
   after. A script waiting on CI took the first workflow run matching a commit
   on a branch, and every commit here has at least two: our own CI, and GitHub's
   built-in Pages build. The script reported "success" with jobs named build,
   deploy and report-build-status, which are not the names of any job in
   `ci.yml`. The real CI run for that commit was still in progress. Nothing was
   wrong except which instrument was being read, and the jobs not matching any
   known job name is what gave it away. A watcher now filters on the workflow
   file rather than the commit alone.

   It happened a fourth time the same day, in the fixed watcher, for a different
   reason. The shell step capturing the merge commit failed, so the watcher was
   handed an empty string, and `startswith("")` matches every run. It
   confidently reported a *previous* commit's green deploy as this one's, with
   all fourteen jobs green, which is exactly what the real answer would look
   like. The tell was the run id being one already seen earlier in the session.

   Two lessons rather than one. A prefix match needs a minimum length before it
   means anything, and it now refuses a sha shorter than seven characters. And a
   value read from a step that can fail must be checked before it is used,
   because an empty filter does not look like an error, it looks like a match.

   The point has a second edge, learned by getting it wrong here. A public URL
   returned 200 within a second of a reboot, and that was written up as
   Cloudflare serving cache over a dead origin. It was not. Caching was off, and
   the monitor's own log showed the edge returning 521 during the outage. The
   recovery had simply been fast. Suspecting the instrument is a discipline, not
   a licence to explain away a result you did not expect: the suspicion has to be
   checked too, and here it cost a false line in the runbook telling a future
   operator not to trust the one signal that was telling the truth.

9. **A pipeline's reported success can come from the wrong command entirely.**
   A category of its own after three instances in one day, all the same shape
   and all nearly reported as results.

   `pytest ... | tail -4; echo $?` prints `tail`'s status, which is always zero.
   `tsc --noEmit | tail -2` did the same while TypeScript was reporting two real
   errors in a file just written. A watcher matched every workflow run because
   the sha it filtered on was an empty string, and `startswith("")` is true of
   everything. In each case a real failure wore the exact appearance of success:
   not a suspicious result to be double-checked, but the specific result that
   was wanted.

   The common root is that the thing reporting is not the thing being asked
   about. `set -o pipefail` covers the pipeline case and is easy to forget under
   time pressure, which is how it was forgotten three times.

   So it is a tool rather than a resolution. `scripts/run-checked.sh` runs a
   command unpiped, sends its output to a file, prints the tail, and exits with
   that command's status, which the calling shell cannot overwrite. It also says
   so explicitly when a command produced no output at all, because "ran and
   printed nothing" and "never ran" are otherwise identical on screen.

   The general form, worth carrying beyond shell: **before believing a result,
   name which process produced it.** An empty filter, a swallowed status and a
   silently dropped mutation are the same mistake wearing different clothes.

10. **What uses a thing and what a thing created are different questions.** Before
   removing anything, ask both. A GitHub token was replaced, and every operation
   that reads it was verified against the replacement first: pushing, editing
   workflow files, reading run status and logs, setting Actions secrets. All of
   it passed, the old token was declared safe to revoke, and revoking it broke
   production deploys.

   The droplet pulls over SSH with a key that had been added to the account, and
   GitHub removes account SSH keys that were created using a token when that
   token is revoked. Nothing *used* the old token to deploy. The old token had
   *created* the credential that did. The check answered "what reads this" and
   the question that mattered was "what exists because of this".

   The shape generalises past credentials. Anything that provisions leaves
   descendants that hold no reference back to their parent, so a search for
   references finds nothing and reports safety. Ask what a thing brought into
   existence, and prefer the narrower successor when re-creating it: the key is
   now a read-only deploy key on the one repository, which no future revocation
   can reach.

   A second instance, 2026-08-15, worth recording because it combines this point
   with point 2 and was self-inflicted. A workstation cleanup removed apps that
   were not part of the project, and Docker Desktop looked like one: no source
   file references it, nothing in `apps/` imports it, and the project deploys to
   a droplet that runs its own. What it *created* was the local Postgres on port
   55432 that the test suite connects to. Removing it did not fail anything
   loudly. The suite kept exiting 0, because the fixtures skip when no database
   is reachable, so a suite that had been running 649 tests silently became a
   suite running none, reporting success either way.

   This is exactly the failure point 2 exists to catch, arriving through the
   door point 9 describes, and it survived a full suite run and a green exit
   code before being noticed. The lesson is narrower than "be careful": the
   question to ask before removing a tool is not only what references it, and
   not only what it created, but **what silently degrades rather than fails when
   it is gone.** A dependency that has a fallback path is more dangerous to
   remove than one that does not, because the fallback hides the removal.

   The failure was legible for the right reason, which is the one consolation
   worth recording. Every test passed and only the deploy job failed, so nothing
   pointed at the code. A pipeline that fails in the shape of the actual fault is
   worth more than one that simply goes red.

## Working loop

Pick the highest item on the backlog that is not blocked. Build it with tests
asserting the property, not the implementation. Run CI. Verify in production where
production is where it lives. Report what was done, what was found, and what is
still not true. Update the backlog. Repeat without waiting to be asked.

Anything discovered mid-task that is broken but out of scope gets written to the
backlog rather than silently fixed or silently ignored.

### Running the areas in parallel

The areas above were being worked one at a time, which is not how they actually
interact. Most items touch several: a scope change is a Security decision, a
Backend change, a Frontend copy change and a Community answer, and doing those in
sequence means three of the four sit idle while the fourth blocks.

They now run concurrently, with one coordinator. The rules that make that safe:

1. **Parallelise on waiting, not on ambition.** The reason to start a second
   strand is that the first is blocked on something slow that is already moving:
   a suite running, a download, CI, a deploy. Starting a strand because there is
   more to do produces half-finished work in several places.
2. **One strand owns a file.** Two strands editing the same module is a merge
   conflict with extra steps. Strands are separated by area, and where they must
   touch the same file, they are serialised deliberately.
3. **A strand reports its own evidence.** The coordinator does not summarise a
   strand as done because it was started. Each strand ends with a command and its
   output, or with a plain statement that it is unfinished and why.

   A mutation counts as evidence only once it is shown to have changed
   behaviour. Three times on 2026-08-15 a mutation was applied, the suite stayed
   green, and the mutation was the broken thing: an annotation FastAPI silently
   dropped, twice, and a replacement string matching nothing so the file was
   never edited. A green run after a mutation that did not land looks exactly
   like a guard that correctly had nothing to say.
4. **Blocked strands are declared, not parked.** A strand waiting on the owner or
   on a credential goes into "Open, blocked" below with what unblocks it. Silence
   about a blocked strand reads as progress.

The coordinator's job is the part that does not belong to any area: deciding what
runs now, noticing when two strands have started to disagree about the same fact,
and keeping the record below true while the work is happening rather than after.

### Dependencies between strands, and who wins

Extended on 2026-08-16, when the six areas became six named strands expected to
run at once rather than a list to work through.

Most conflicts between them are not really conflicts, they are one strand being
asked to accept a cost that belongs to another. These are settled in advance so
they are not re-argued each time:

| Tension | Resolution |
| --- | --- |
| Security wants a narrower credential; Backend wants fewer moving parts | Security wins. Every scope widening this project has shipped was later found to have been wider than the check under it |
| Product wants a capability; Contracts says the guarantee is not provable | Contracts wins, and the capability ships off chain or not at all. A promise the chain does not enforce is a promise the platform is personally liable for |
| Frontend wants an endpoint shaped for one screen; Backend wants a general contract | Backend wins on shape, Frontend wins on whether it is enough. An endpoint nobody can build a screen from is not general, it is unfinished |
| Infrastructure wants a change frozen; anyone wants to ship | Infrastructure wins during an incident and loses otherwise. A deploy freeze with no incident behind it is a habit, not a control |
| Any strand wants to skip a guard "just this once" | Nobody wins. The guard is either wrong and gets fixed, or right and gets obeyed |

Sequencing rule when strands genuinely block each other: **the strand whose
output the others cannot proceed without runs first, even if it is not the most
interesting.** Contracts before Backend before SDK before Frontend, because each
of those consumes the previous one's surface and reworking a shipped surface is
more expensive than waiting for it.

Research is the exception and runs ahead of everything, because it is the only
strand whose output changes what the others should build rather than how.

## Roadmap and delivery history

Superseded as the place to start. `## Running record` near the top of this file
is what a cold session reads; this section is the roadmap and the archive of
what has already been delivered.

It used to be called "Current state" and carried its own `Last updated` line,
which is how `scripts/check_state_record.py` came to have a real defect on the
day it was written. The check searched the file for the first `Last updated`
line, and with two of them it would happily read this one while the running
record's line was missing entirely, reporting the record current when nothing
was maintaining it. Found by mutation testing the guard rather than by trusting
it, which is the only reason it is not still there. There is now exactly one
such line, and the check refuses to run if that stops being true.

### Roadmap, from evidence rather than instinct

Set 2026-08-16 from four parallel investigations, written up in
[ecosystem-research.md](ecosystem-research.md). Ordered by value per unit of
work, and chosen so that every item is worth building whether Agoreum stays a
marketplace or becomes a reputation oracle, which is an open question recorded in
that document for the owner.

1. **A remote MCP server exposing the marketplace as tools.** Shipped
   2026-08-16. One connector giving an agent the whole catalogue instead of one
   integration per seller. MCP is where developer gravity actually is, by
   roughly two orders of magnitude over the alternatives. Seven tools at
   `/api/v1/mcp`, scoped by the existing API keys, with RFC 9728 metadata at the
   origin root.
2. **Signed settlement receipts on escrow release.** Makes a settled order
   independently verifiable by a third party. The venue's honesty feature and
   the oracle's core primitive at the same time.
3. **A2A agent cards per published agent.** Near-free given the capability model
   already in the database, and only ten publishers worldwide currently pass
   validation.
4. **The published OpenAPI contract.** Shipped in this batch.

Deferred with reasons rather than forgotten: x402 on the escrow flow is
architecturally mismatched, one synchronous round trip against an asynchronous
flow with a dispute window; ERC-8004 reputation reads would import a measurably
broken signal into a working one; A2A protocol implementation serves traffic
that does not exist.

Two constraints the research adds, both of which belong in code before any
delegated spending is built:

- **The agent's own key is the spender, never Agoreum.** A spend permission pays
  the spender, so holding one on a user's behalf makes the non-custodial claim
  false whatever the intent.
- **A tool description is not a UI.** Interface copy is read by a person who can
  notice it is wrong. A tool description goes into another agent's context with
  no human in the loop, so every payment-touching tool must state Base Sepolia in
  the result itself.

### Where things stand

| Area | State |
| --- | --- |
| Contracts | Escrow and subscriptions on Base Sepolia only. 142 tests, 0 skipped, including an invariant that deadlines never move and coverage measured at 99% of escrow lines. Fork suite runs in CI, 6 passed and 0 skipped, asserted rather than assumed. Nothing on mainnet |
| Backend and API | 744 tests, 744 passed, 0 skipped, and the same again on the second run against the same database, which CI enforces. API keys can write, gated per scope, see below |
| Frontend and web | Nine locales, each with its own canonical URL and social card |
| SDKs | Python, TypeScript and Go published at 0.2.0 on 2026-08-15, each verified from its registry rather than from the local build |
| Infrastructure | Droplet origin locked to Cloudflare ranges. Build cache bounded after the deploy verifies. Backups daily, restore and cutover both drilled |
| Local environment | Postgres, Redis and Anvil run as plain processes. `scripts/local-dev.ps1` brings them up, `-Status` says which are answering. Restored on 2026-08-15 after a cleanup removed the Docker Desktop that had been providing them. The GitHub CLI went in the same cleanup and has not been reinstalled: CI is queried through the REST API with the token from the env file, which needs no install and no separate login |
| Community | Support inbox answered to zero as of 2026-08-15. Discord readable and answered as of the same day |

### In flight

**Receipts are signing live in production, confirmed 2026-08-16.** The owner
added `RECEIPT_SIGNING_KEY` to the droplet and restarted the API. Verified from
the deployed artifact rather than from the deploy going green: inside the
running container `_signing_key()` returns a key, the key document carries a JWK
with kid `rVl3VOYAtNY4LW0J`, and a signature produced by that process verifies
against the published public key while a tampered copy of the same payload is
rejected. The value on the droplet hashes identically to the one in the local
`.env`, so the two sources of truth for it agree.

Two things were *not* proven, and saying which is the point of writing this
down. No settled escrow exists in production, so `build()` has never run over a
real order there and the database half of the path is unexercised; what was
exercised is the signing tail on a synthetic payload, in the deployed process,
with the deployed key. And the public URL still returns the web application's
404 HTML, because the routing that fixes it is in PR #30 and has not landed, so
a receipt is signed but not yet independently checkable by an outsider, which is
the entire reason receipts exist.

**PR #30 was recorded here as ready to merge and was red.** Its `Contracts` job
had never passed, for two reasons that had nothing to do with the change's
substance: `forge fmt --check` wanted four statements unwrapped to the
configured width of 100, and `forge lint` refuses warnings under
`deny_warnings`, of which the file carried three. Both are fixed on the branch
now and `Contracts` is green.

One of the three lint warnings was worth more than compliance. The gas
measurement timed a bare `usdc.transfer` and read nothing back. USDC returns
false instead of reverting, so a transfer that silently did nothing would still
have produced a plausible gas figure, and that figure is what the payment
channel decision rests on. The return value is now bound inside the timed window
and asserted outside it, so the number is unchanged and a failed settlement can
no longer look like a cheap one.

The branch also now fails the deploy if the receipts key document stops carrying
a key, asserted through the public URL so one check covers both a missing key
and a document answered by the web app. Exercised in both directions against
production before being committed.

**One finding left open deliberately.** `RECEIPT_SIGNING_KEY` appears three
times in the droplet's `.env`, on consecutive lines. All three values are byte
identical and the container resolves the correct one, so nothing is wrong today.
It is worth fixing anyway, because a rotation that edits one line leaves two
stale copies and dotenv's last-wins rule would silently keep serving an old key.
Deduplicating it was refused by the local permission gate, and per the standing
rule a refused permission is not worked around, so it is recorded here rather
than done. The same sweep found no other duplicated key in that file.

Merged 2026-08-16:

- `b43f87e` (PR #4 in this arc), signed settlement receipts. All fourteen CI jobs
  green including Deploy. Production serves the key document with kid
  `rVl3VOYAtNY4LW0J`, confirmed by querying the API container directly. The
  public URL for it is broken until PR #30 lands, which is how the routing bug
  was found.

Earlier pull requests merged to `main` on 2026-08-15, each with all fourteen CI
jobs green including Deploy and Fork tests:

- `5b4a7ce` (PR #1), the write scopes, the whole-suite skip assertion, and
  `scripts/local-dev.ps1`. Confirmed live in production.
- `366c245` (PR #2), test isolation, the second suite run against the same
  database, and the scope documentation check.
- `d8ea6e6` (PR #4), the SDK write surface, the method-and-path contract check,
  the SDK version parity check, and the database connect timeout. The new
  provider walkthrough is live at `/docs/sdks`, checked in three locales.
- `baf8fe6` (PR #8), API key organization confinement. Deployed and production
  confirmed healthy afterwards.
- `a0771bf` (PR #10), API key rate limit bucketing. Deployed, production healthy
  and still serving `x-ratelimit-*`.
- `4718650` (PR #12), the route-level limiter assertion and two corrected
  comments. Deployed, production healthy.
- `3820c39` (PR #14), the deadline invariant, the subscriptions self-transfer
  test, and the corrected security register row. Contracts 140 passed, 0
  skipped, and the fork suite ran on merge.
- `d9e7d1d` (PR #16), the landing page testnet status line. Verified live in
  English, German, Japanese, Arabic and Chinese, following redirects, which is
  the check the first attempt at this got wrong.
- `5c94b1e` (PR #24), the published OpenAPI contract and the ecosystem
  research. Verified live: 63 paths, 120 component schemas, ten public tags, and
  no admin or organization paths, so the scoping holds in production and not
  only in the test.
- `b9c79f7` (PR #22), the subscriptions unpause tests, measured coverage, and
  the removal of two stale test counts from the auditor-facing docs. All
  fourteen jobs green including the fork suite.
- `17b667b` (PR #20), per-identity limits on the two dispute endpoints. Verified
  in production with a control: both now advertise `x-ratelimit-limit: 10`, and
  `orders/{id}/start`, recorded as deliberately unlimited, still sends no such
  header. The control is the half worth having, since it checks the exemption
  list against production rather than only the fix.
- `2ee8808` (PR #18), the emails worker heartbeat and monitoring. Verified end
  to end in production rather than by the deploy going green: the endpoint now
  reports `emails_worker` with a heartbeat one second old, which proves the
  worker writes the key and the endpoint reads the same one.

**What was not verified in production, and why.** Bucket separation needs two
real keys, which means minting credentials against live data for a change that
is pure logic with no configuration dependency. The evidence is the unit level
with three mutations plus a green deploy of identical code, and that is stated
here rather than left to look like a production check that happened.

**Who was exposed.** Nobody outside their own account. The gap let a key reach
organizations its creator already belonged to, so it was a containment failure
rather than a cross-tenant one: no key could ever reach an organization its
creator could not. Combined with testnet only, no real funds, and a handful of
accounts, there is no one to notify. Recorded because "we decided there was
nothing to disclose" is a claim that should be written down with its reasoning,
not left implied.

The production check on the first is worth recording because it needed no
credentials. A fake API key only proves authentication, not scope. Instead,
`POST /api/v1/orders`
now returns the principal path's message, "Provide an API key (X-API-Key) or
sign in", identical to an endpoint that was already scoped, while `/auth/me`,
which was deliberately left on `CurrentUser`, still returns "Authentication is
required". The contrast between an endpoint that changed and one that did not is
what identifies the running build.

**API key write scopes.** `orders:write`, `agents:write` and `services:write`
existed in the catalogue, were offered when minting a key, and were enforced by
nothing: every write endpoint took `CurrentUser`, which is session-only and
refuses a key outright. A key holding every scope the product offers got 401 on
every write, so the SDK could read and never act.

Now wired through `AgentsWrite`, `ServicesWrite` and `OrdersWrite` in
`apps/api/app/api/deps.py`, covering 6 order, 7 agent and 5 service handlers.
Each is granted only by naming it at mint time. Nothing is implied by a read
scope and nothing is bundled. The key-minting UI marks write scopes and warns,
in all nine locales, that a leaked key holding one can act as its owner, while
being explicit that it still cannot move funds because every on-chain payment
needs a wallet signature.

Verified the way the gap was found, by driving the published SDK against the
real app through ASGI: a key holding `orders:read` is refused with 403 and
`insufficient_scope`, a key granted `orders:write` reaches the handler and gets
the handler's own 404 for an unknown service, and that same key is still refused
on agents and services. Then mutation tested: downgrading `create_order` back to
`OrdersRead` turns the refusal test red, so the guard is doing the work rather
than the test passing for an unrelated reason.

One thing the 403 buys that is easy to undervalue. The old failure was a 401,
which tells a developer their key is wrong, so they go and check the key. It is
not wrong. Hours can go into checking a correct credential. `insufficient_scope`
with the missing scope named points at the actual fix.

### 19. Subscriptions could be stopped but never proven startable (done)

Found by preparing for the audit rather than waiting for it. The engagement is
the owner's to move; the artefacts an auditor reads are mine, and an auditor's
time is expensive enough that the difference is worth spending.

Coverage had never been measured. Measured now: escrow 99.19% of lines and 100%
of functions, subscriptions 97.14% and 92.86%. The number worth acting on was
not the percentage but what it excluded. Thirteen of fourteen functions covered,
and the missing one was `unpause`.

`pause` was tested five ways. `unpause` was never called by any test in this
repository, while the escrow tests both. The asymmetry is the tell: somebody
proved the stop and not the restart.

It matters because pause is an incident tool. The moment it is used is the
moment the restart has to work, and until now the restart was the one governance
action never executed outside production. A contract that can be stopped and not
started is stopped permanently.

Covered two ways, that it restores selling and that it remains governor only,
asserted by selling again rather than by reading the `paused()` flag, because
the flag flipping is not the property anybody cares about. Both fail if
`unpause` is made a no-op or loses its role gate.

**Two documents were also telling an auditor the wrong numbers.** Both quoted
"144 tests, 138 passing with 6 skipped", written days earlier and wrong by the
time anybody read it, because a count maintained by hand drifts every time a
test is added and nothing notices.

Corrected by removing the totals rather than updating them. The figure that
matters is not how many tests exist but that none skip, which CI asserts on
every run, and `forge test` prints the current count for anyone who wants it. A
number nobody checks is worse than no number, because it looks like evidence.

### 18. Two dispute endpoints had no per-identity limit (done)

Found by sweeping the sub-shape that produced item 17: a set that looks
complete. The set this time is my own doing, the write endpoints made reachable
by API key a few days earlier.

Of 52 write routes, 11 carried a per-identity limit. Most of the rest are fine
and the reason is worth stating rather than assuming: nginx already limits every
request per address, and most write routes are state changes on a resource the
caller already owns, creating no new rows, with the number of those resources
already bounded by the create limits.

Two were not fine. `dispute-intent` and `dispute-statements` each append a row
to the order's timeline on every call, with no cap. That timeline is the record
an arbiter reads to decide who gets the money, so flooding it is not storage
abuse, it degrades the process the escrow depends on, and it does so against the
other party rather than against us.

They sat directly under a comment in the bucket table reading "writes that
create durable records", which is precisely what they are. The category was
named and the members were not checked against it.

**Nginx is why this was a gap and not a hole.** Every request was already
limited to 30 per second per address. The per-identity layer exists because an
address is something a caller can change, which that module documents at length,
and both endpoints became reachable by API key when the write scopes shipped.

Fixed with two buckets at 10 per five minutes, generous because disputes are
rare and deliberate and a party writing several accounts of what happened is
normal.

The durable half is `WRITE_ENDPOINT_LIMITS`: every write-scoped endpoint maps to
its bucket, or to None with the reason a limit is not needed. Three tests, and
three mutations each fail on their own: removing a limiter, pointing one at an
unconfigured bucket, and deleting a bucket's configuration while leaving the
limiter attached. A new write endpoint now forces a decision instead of relying
on somebody noticing.

### 17. A worker ran in production with nothing watching it (done)

Found by doing the infrastructure role's standing check, which had gone
unattended while the week went into backend and security work. Production is
healthy on every component, verified rather than assumed: database, Redis and
chain all ok, both indexers six blocks behind head, webhooks worker heartbeat
three seconds old.

The gap was next to that. Production runs four workers besides the monitor.
`/health/workers` reported two, and the monitor alerted on three. The one
watched by nothing was the emails worker, which sends sign-in alerts and
verification links.

Its silence is the hardest to notice from outside, because nobody reports mail
they were never expecting. A wedged loop would have looked exactly like a quiet
week, and sending is live: sign-in notices are being delivered today.

The same fingerprint as the key bugs, in a third subsystem. The webhooks worker
had the pattern, correct and load-bearing, one service over, writing a heartbeat
each pass precisely so a stalled loop is visible while the container is up. The
emails worker had a `while True` and nothing else. The endpoint reporting two
workers made the set look complete.

Fixed by generalising rather than copying: heartbeat keys now live in a map
keyed by worker name, and one `check_worker` covers any of them, so adding a
worker means adding an entry rather than remembering to write a new function.
The worker writes its heartbeat after the pass rather than before, so it means
"a pass completed" and not "a pass started".

Six tests. Four mutations, two of which initially survived and are the more
useful half:

Excluding the emails worker from the overall status still passed, because every
worker check calls the same `create_client` and the shared fake made one
worker's health depend on another's. The 503 being asserted was coming from the
webhooks worker. The fake now answers per key, so the test isolates what it
claims to.

Replacing the shared key constant with a local of the same name still passed,
because the test grepped for the token rather than the import. It now requires
the import, so a writer that stops using the reader's key fails.

Both were the test being weaker than it looked while reporting success, which is
the same category as the pipeline exit codes: the check ran, and it was not
checking the thing named on it.

### 16. The landing page implied its status rather than stating it (done)

Raised by a prospective user on 2026-08-15, who asked why the site did not give
enough detail about the testnet phase. Approved by the owner and shipped.

Checked before agreeing, and the criticism is fair in substance but not in the
way it was phrased. The landing page does carry a "Testnet first" card, and the
docs and security pages are explicit. What it does not carry is a statement of
*current status*. "Testnet first" describes a practice, a way of working, and a
visitor can reasonably read it as "we test carefully" rather than "everything
here is testnet only and the USDC has no value". Those are different sentences
and only one answers the question people arrive with.

Shipped: a status line as the first element in the hero, before the kicker and
the headline, in all nine locales. It names the network, says the USDC is test
currency with no real value, says nothing is deployed to mainnet, and links to
the security page.

Deliberately not animated. The rest of the hero is staged to sequence reading,
and a disclosure that fades in after the headline is one the fastest readers
miss, which defeats the point of putting it first.

Asserted rather than left in place by habit, since a disclosure held there only
by nobody having refactored the hero is exactly the shape this project has spent
the week finding. Three mutations each fail it: a locale losing the block, a
locale watered down to a vague phrase, and the line moved below the headline.

**A measurement error worth recording**, because it nearly turned this into the
wrong fix. The first check fetched the landing page without following the
redirect, got an empty shell, and reported zero mentions of testnet. That would
have meant telling a user their criticism was entirely correct and changing the
page on a false premise. Following the redirect shows four mentions. The site
was fine; the fetch was not.

### 20. nginx had been serving a week-old configuration (done)

The MCP discovery document returned the web application's 404 page in
production while serving correctly everywhere else. The cause was not routing
and not Cloudflare.

**Docker bind-mounts a single file by inode, not by path.** `git pull` replaces
these files rather than editing them in place, so the container kept serving the
copy it started with. `up -d nginx` saw an unchanged service definition and did
nothing. `nginx -s reload` re-read the same stale inode and succeeded, so the
deploy's recreate fallback, which only fires when reload *fails*, never fired.

Measured rather than reasoned: the config on disk and the config inside the
running container had different checksums, and the container had been created on
2026-08-09. **Every nginx configuration change for a week had silently not taken
effect**, including routing and rate limiting. Nothing failed. Every deploy went
green.

The narrowing is worth keeping, because two plausible causes were ruled out
before touching either. All `/.well-known/` paths returned Next.js 404s, and the
API's own 404s are JSON, so the request was reaching the origin and being routed
to the web app. That eliminated Cloudflare interception, which was the more
attractive hypothesis, without opening a dashboard. What remained was the origin,
and the origin's config was checkable directly.

Fixed in two places. Production was recreated, and following the challenge now
resolves to the metadata document. `scripts/deploy.sh` compares each mounted
config against its copy inside the container, recreates only when they differ so
an ordinary deploy keeps its zero-downtime reload, and then **asserts** they
match, failing the deploy rather than reporting success while serving
yesterday's routing.

**The general shape.** A reload is not a guarantee that what reloaded is what
you wrote. This is the same family as everything else found this month: a
mechanism that names the right thing, succeeds, and does not do the job. The
difference here is that the success signal was the deploy itself.

### Open, blocked

| Item | Blocked on | What unblocks it |
| --- | --- | --- |
| PyPI 0.1.0 yank | Owner | The publish token cannot yank; needs an account-level action |
| Three Safe multisigs on Base | Owner | Owner action. Escrow admin, subscriptions admin, arbiter, distinct signers and a real threshold |
| Security audit engagement | Owner | Owner action |
| Mainnet deployment | The two rows above | Both, plus an explicit written instruction naming mainnet |

**Discord, resolved.** The bot had authenticated and could list every channel,
but `content` came back empty on every message with zero embeds and zero
attachments, which is the signature of Discord stripping content rather than the
messages being empty, and `GET /applications/@me` returned `flags: 0`. The owner
enabled the message content intent on 2026-08-15; flags are now `565248` and
content reads. The waiting conversations were answered the same day: a direct
question in `#introductions` about who runs the project, and the first real
exchange between members in `#general`, which was answered with what the project
is and is not, including that there is no token, sale, airdrop or points
programme and that anything claiming otherwise is a scam.

## Backlog

Re-derived from the state of the code on 2026-08-08, after the previous list was
finished. Ordered by what would hurt most if left, with the evidence that put each
one where it is rather than an assertion that it matters.

Items 1 to 12 are done. **Re-derived again on 2026-08-15**, and the method is
worth recording because it worked better than reading code looking for problems:
the documentation was searched for claims it made about itself and could not
support. Two turned up immediately, both on the money path, both phrased as
things somebody meant to check.

`docs/audit-readiness.md` said permissionless auto-release was deliberate "but it
is worth confirming the deadline cannot be brought forward", and
`docs/incident-runbook.md` listed "one untested live-only revert". Both are now
asserted, items 13 and 14 below. That is the same fingerprint as the API key
bugs, one layer up: a document naming the right concern is not a check.

**The sweep that produced them, worth repeating:** grep the docs for hedged
language, `not tested`, `untested`, `worth confirming`, `should be`, `we assume`,
`known limitation`. Every hit is either a real check nobody wrote, or a decision
that should be stated without the hedge. Both outcomes are worth having.

### 21. The function that issues a receipt had no test (done)

Found on 2026-08-16, hours after signing went live in production, by asking what
covers the feature that had just shipped rather than by anything failing.

Ten tests existed and every one of them was about the key or the signing
primitives: that no key is invented at startup, that the key is not a chain key,
that an Ed25519 key cannot sign an Ethereum transaction, that a signature
verifies, that tampering breaks it, that the canonical form is order
independent. All worth having. None of them called `build()`.

So on the day the product's newest claim went live, the function that decides
whether a receipt exists at all, and what goes in it, had never been executed by
any test in either direction.

**The one test that looked like coverage was named for a different check.**
`test_the_endpoint_refuses_an_order_that_has_not_settled` passes a random uuid,
so `require_visible_order` answers 404 and `build()` is never reached. It has
never once exercised the settlement refusal in its name. Renamed to what it
actually asserts, which is worth keeping: a stranger must not learn whether an
order exists by asking for its receipt.

This is the same asymmetry as item 19 in the subscriptions contract, where
`pause` was tested five ways and `unpause` was never called, found a day apart
in unrelated code. The pattern is that somebody proves the refusal and not the
thing being refused, because the refusal is the case they were worried about.

Eleven tests now cover the issuing path: that a settled escrow produces a signed
receipt, that it carries every coordinate a verifier needs, that the signature
covers the settlement figures rather than merely some payload, that a refund
settles as well as a release, that a merely funded escrow is refused with
`not_settled`, that an escrow with no settling transaction still issues with a
null hash rather than refusing, that the network is named and testnet marked,
and that with no key configured the receipt is unsigned rather than faked, which
is precisely the state production was in until today.

Four mutations, each caught by the test that claims to cover it: disabling
signing, counting a funded escrow as settled, pointing at the first transaction
instead of the settling one, and dropping a figure from the signed payload. Two
of the four initially did not land at all, because this working copy is CRLF and
the replacement strings were not, and the harness reported that rather than
reporting a pass. That guard is the reason the result means anything.

### 23. Reputation could be manufactured by paying yourself (done)

Found on 2026-08-16 while preparing the settlement exercise, by asking what
would happen to reputation if one person controlled both sides of a real order.
That is not an idle question: it is what the exercise requires.

The answer was that it counted, in full.

**What existed.** `create_order` refuses a buyer who is a member of the provider
agent's organization, with code `self_dealing`. The escrow contract separately
refuses `provider == msg.sender`, so one address cannot be both sides on chain.
Both correct, and together they were the entire defence.

**What was missing, in two ways.** The API guard had **no test anywhere**. Not
one, and it is not mentioned in any document either, so nothing would have
noticed it regressing. And reputation re-established nothing: `gather_inputs`
counted settled orders, volume, delivery times and reviews with no reference to
who the buyer was.

That arrangement fails quietly. A creation-time check answers "may this order be
created" and reputation asks "did money move". Nobody asks "were these parties
at arm's length" at the moment a score is computed, so the guarantee lives in
one branch of one function and anything arriving by another route inherits none
of it: an admin action, a backfill, an import, a future endpoint, or simply the
buyer joining the provider's organization after placing the order, which the
creation check cannot see because it has already run. That last case needs no
mistake by anybody at all.

**Why it is the most serious thing found this month.** Every other finding was
about a mechanism not doing its job. This one was about the single claim the
product is built on. The argument for this platform over the ERC-8004 landscape
is that a score cannot exist without a settled payment behind it, against
records where between 98.7% and 100% carry no proof of payment. A settled
payment from yourself to yourself satisfies that sentence perfectly and means
nothing, so the claim was true in letter and hollow where it mattered.

**Narrower than first described**, corrected the same day by running the
settlement exercise against it. The filter keys on organization membership, and
a personal organization has exactly one member and is forbidden from gaining
another, so for agents owned personally it reduces to the condition
`create_order` already enforces. It is real defence for team organizations and
for orders arriving by any route that skips `create_order`, and nothing beyond
that. The original write-up claimed it covered a buyer joining the organization
later, which cannot happen where joining is impossible.

**Fixed structurally rather than procedurally.** `arms_length()` in the
reputation service excludes orders whose buyer belongs to the rated agent's
organization, applied to every figure that could flatter an agent: settled
order count, volume, delivery metrics and published reviews. Reviews are joined
back to their order for this, since a review is only creatable by the buyer of a
settled order and would otherwise carry a self-written five stars as a
customer's opinion.

**Deliberately asymmetric**, which is the part worth keeping. Cancellations,
disputes and disputes lost are *not* filtered. Filtering those too would let an
agent dispute its own orders from inside its own organization and launder a real
dispute history into a clean one. Leaving them makes the guarantee directional:
self-dealing can never improve a score in any combination, without anybody
having to enumerate what somebody might try.

**What this does not buy**, stated so nobody later assumes more than it does. It
is not Sybil resistance. Two unrelated accounts controlled by one person still
pass, and no reasonable check catches that. What survives is the honest version
of the claim: manufacturing reputation here costs real money at real fee rates
on real settled volume, rather than fractions of a cent with no payment at all,
and where the platform can see the parties are one interest it does not count.

Four mutations, each caught by the test that claims to cover it: removing the
filter, making it always true, making it always false, which is the control that
proves it is not silently deleting genuine reputation, and removing the
`self_dealing` refusal from `create_order`.

### 22. Cloudflare refuses the key document to one common client (done)

Measured on 2026-08-16 while verifying a production signature the way an
outsider would. `GET /.well-known/agoreum-receipts.json` returns 403 to the
default `Python-urllib` user agent and 200 to everything else tried:
python-requests, curl, Go-http-client, node-fetch, axios, a browser, and our own
`agoreum-python/0.2.0`.

Not specific to receipts. The same client gets 403 on
`/.well-known/oauth-protected-resource` too, so it is a blanket edge rule
against that user agent rather than anything about this document.

Worth fixing anyway, and the reason is the design rather than the severity. The
intended reader of that document is software belonging to somebody with no
account here, and the most dependency-free way to write that verifier in Python
is the standard library, which is exactly the client that is refused. A verifier
that gets 403 does not conclude "I should set a user agent", it concludes the
receipt cannot be checked.

Left open rather than fixed, because it needs a Cloudflare rule change and edge
configuration is externally visible. The proposal is a bot-protection skip
scoped to `/.well-known/*` only: those documents are public, unauthenticated,
420 bytes, and already rate limited by nginx, so exempting them costs nothing
that bot protection was buying.

### 1. Dispute resolution has no ending (done)

`AgoreumEscrow.settleDispute(escrowId, providerAmount, buyerAmount)` exists and
requires `ARBITER_ROLE`. The API has exactly one dispute endpoint, which records an
intent, and the authoritative dispute is raised on chain by a party's own wallet.
There is nothing between those two facts: no queue of open disputes, no path for an
arbiter to act, and no record of why a split was chosen.

Built and reachable: statements from both parties, a recorded decision with
reasoning, settlement instructions for the arbiter's own wallet, an arbiter queue
at `/arbiter`, and a dispute panel on the order for both parties. The design and
the decisions behind it are in `docs/dispute-resolution-design.md`.

What follows is why it was ranked first. A buyer could raise a dispute and the
money stopped there. Escrow is the platform's entire promise, and the one
situation where the platform itself has to act was the situation it could not.

Not a contract change: the on-chain half works and is tested. What is missing is
the operational half around it.

### 2. The money path is the least tested large module (done)

Both now have test files covering their arithmetic and their rules: what a buyer is
charged, how a figure is rounded to the settlement token, and what a service is
allowed to say about its own price.

The state machine is now covered too: what starting, delivering and disputing
each refuse, that no transition reopens a terminal order, and that the
auto-release window is the one frozen at purchase.

Writing those tests is what found the funding deadline was decorative.
`expire_unfunded_orders` existed, was correct, and had no caller anywhere in the
codebase, so no order had ever expired. There was even a partial index on
`funding_deadline` where `status = 'pending_payment'`, built to make a sweep
efficient that never ran. Nothing enforced the deadline at funding time either,
so the price an order freezes at purchase stayed payable indefinitely: a buyer
could hold an order open, wait for the provider to raise their price, and still
pay the old one. Closed by refusing payment instructions past the deadline and
by running the sweep from the indexer loop, which is the process that knows the
chain is current.

Worth stating plainly against a week of evidence: every real defect found recently
was in code that had tests, and was caught because a test or a gate existed to
catch it. The largest module handling money has neither.

### 3. No administrative surface (done)

Built. `/admin/disputes`, `/admin/email-suppressions` and a way to lift one, each
gated on an address the chain recognises. What follows is why it was ranked here.
There is no way to work a dispute queue, lift an email suppression, or look at an
account to answer a support message, other than opening a database session against
production. Every operational action so far in this project has been a hand-written
script run through `docker exec`, which is fine for one person and does not survive
a second.

Blocks item 1 in practice, which is why it is next to it.

### 4. A backup that has never been restored (done)

Daily automated backups exist and are current: eight retained, the most recent
today. That was verified rather than assumed.

Drilled on 2026-08-08 against the real backup, verified, and torn down. The
procedure is in `docs/incident-runbook.md` with measured figures.

Cutover was rehearsed separately on 2026-08-09 and is written up too, so both
halves are proven rather than only the first. It found that overriding
DATABASE_URL alone leaves alembic pointed at production, which during an incident
would migrate the live database while the application served a restored copy.

Two things remain open by choice. RPO is about 24 hours, since backups are daily,
accepted as a cost tradeoff at current scale. The database is a single node, so a
node failure is an outage rather than a failover.

### 5. Documentation that has drifted from the code (done)

Corrected. The runbook now has a "What is watched" section listing every alerted
event, and the stale claim is gone. It had stated under "What is not covered" that
governance events were unmonitored and should be fixed before mainnet. They are
monitored: `scripts/monitor.py` watches `FeeConfigUpdated`, `TreasuryUpdated`,
role grants and revocations, and pause and unpause, and the monitor is running in
production with both an RPC URL and the escrow address configured.

Small to fix and listed because of what it is rather than its size. A runbook is
read in an incident, by someone deciding what to trust, and one that understates
its own coverage is the wrong kind of wrong.

### 6. The API suite only passed on a virgin database (done)

Found on 2026-08-15 while restoring the local database. `test_email_verification`
used fixed addresses, `a@example.com` through `h@example.com`, against a unique
constraint. The first run created those rows and nothing removed them, so the
second run of the same suite failed nine tests with `profile_conflict`, and a
tenth in `test_notification_events` for the same reason.

Fixed with unique addresses per test rather than a cleanup fixture, because that
is already how these files solve the identical problem for identities: `Wallet`
has always created a fresh keypair per test rather than deleting the old one.
Cleanup has to run to be correct and does not run when a test fails partway,
which is precisely when leftovers matter. Twenty three literals across the two
files became generated addresses, each carrying a label so a failure message
still says which address it means.

Verified by running the whole suite twice against the same database: 667 passed
both times. Then mutation tested, because two green runs on their own do not
show which change caused them. Putting one literal back makes run one pass and
run two fail, and restoring it makes both pass again.

CI could never have caught this. Its database is new every run, so it was
structurally incapable of seeing a test that only passes the first time, and the
green badge was not evidence either way. The Backend job now runs the suite a
second time against the same database, which is the only thing that asserts the
property, for about a minute.

The general shape is worth keeping: **a check that is re-created clean before
every use cannot detect anything that accumulates.** Freshness is usually a
virtue in a test environment and is exactly what blinded this one.

### 7. The public API docs duplicated the scope catalogue (done)

Found while checking whether shipping the write scopes had made any published
claim untrue. The docs page at `/docs/api` hardcodes the seven scopes and their
descriptions as a literal array, while the key-minting UI fetches
`/api-keys/scopes` and renders whatever the API returns. The second cannot
drift. The first can, and nothing compared them.

The copies happened to agree, which is the least reassuring possible state: the
same shape as three published SDKs calling an endpoint this API had never
served, agreeing with each other and with nothing authoritative.

Worse than cosmetic, because this page is what a developer reads to decide which
scopes to request. A scope listed but not real means keys minted for something
that will never work. A scope real but not listed means people granting more
than they needed because the narrower option looked absent. Both are
authorisation decisions taken from a stale page.

Now compared in `test_sdk_contract.py`, names and descriptions both, since a
description that quietly narrowed would understate what a leaked key can do.
Mutation tested twice: a drifted description and a scope that does not exist are
each caught, and the test refuses to pass when it parses nothing.

### 8. The SDKs could not use the scopes they asked for (done)

Enforcing the three write scopes made 18 endpoints reachable by API key. The
published clients exposed exactly one of them, `place`. So a developer could
read the scope catalogue, see "Create, update, and change the status of your
agents", grant `agents:write`, and find no method for it. The product's headline
claim, that an agent registers a verified identity and publishes services, could
not be done through the client built for agents.

Fifteen of the eighteen are covered now, across Python, TypeScript and Go, with
the sync and async Python clients kept identical. Three are deliberately absent
and say why in `SDK_WRITE_COVERAGE`: settling a dispute needs `ARBITER_ROLE` on
chain, which no ordinary integrator's key can have, and the two identity
challenge verifications are the last third of a flow whose middle is a human
serving a file from a domain or a GitHub account.

The gap was a judgement call. Its invisibility was not: nothing stated which
write endpoints the clients covered, so the answer took reading three SDKs
against a router by hand. A test now makes the app and that table agree, so a
new write endpoint cannot land without someone deciding what the clients do
about it.

**Two defects found by building it**, both only visible against the real API:

`agents.list()` called `GET /agents` in all three clients. The API serves
`POST /agents` and `GET /agents/mine`, so listing your own agents returned 405
in every published SDK. This is the second shipped instance of the original
defect shape, and the existing guard missed it because it compared paths and not
methods: `/agents` is a real path, just not for that verb. One near miss is a
bug; the same shape twice is a guard aimed slightly short. It now compares the
pair, and says which verb *is* served when it fails.

The TypeScript and Go version constants said `0.1.0` while both shipped as
`0.1.1`. That string goes out in the User-Agent, so the one moment it earns its
keep, asking which version a broken call came from, both would have answered
wrongly. The comment above the TypeScript constant said "kept in sync with
package.json" and nothing kept it in sync, which is the same shape as the docs
page and the scope catalogue: a stated invariant with no check under it. All
three are now compared.

### 8a. Releasing 0.2.0 (done)

Published on 2026-08-15 to PyPI, npm and the Go proxy, built from a clean tree
at `57435b9` with all four version strings agreeing.

Verified from the registries rather than the local build, which is the only
version of this check worth doing: the artifact that reaches a user is the one
the registry serves, and a local pass says nothing about what was uploaded.

- **PyPI**: installed `agoreum==0.2.0` into a fresh virtualenv, confirmed it
  loaded from site-packages, then swapped the editable install in the API's
  environment for the published one and ran the integration suite against the
  real app over ASGI. Ten passed, including the whole provider loop. The
  published artifact drives the API, not just a copy of the source that does.
- **npm**: installed `@agoreum/sdk@0.2.0` into an empty project and imported it
  as both ESM and CommonJS.
- **Go**: fetched `v0.2.0` from `proxy.golang.org` and compiled a program
  against the proxy's cached copy that references all fourteen new methods, so
  the signatures are checked by the compiler rather than by grep.

The User-Agent was checked separately, because it is the defect this release
fixes rather than a side effect of it. All three now send their true version:
`agoreum-python/0.2.0`, `agoreum-typescript/0.2.0`, `agoreum-go/0.2.0`.

The three package READMEs documented only the read surface plus `place`, so the
headline new capability was undocumented on the pages PyPI and npm render. All
three now carry the provider walkthrough, and each example was checked against
the **published** package rather than the source: the Go snippet compiled
against the proxy copy, the TypeScript snippet type-checked with `--strict`
against the installed types, and the Python calls bound to the real signatures.
A documentation example that does not compile is a defect with a slower fuse
than a broken method, because the reader assumes they mistyped it.

Those README updates are in the repository but **not** on the package pages,
which are frozen to whatever shipped with 0.2.0. They will appear with the next
release; publishing a version purely for prose was not worth another
irreversible tag.

Two probes failed and both were the probe. Reading `@agoreum/sdk/package.json`
is blocked by the package's own `exports`, which is correct packaging, and the
Python check first sent a `/me` payload without an `id`. Neither was a fault in
what was published, and both are worth noting only because a failing probe reads
exactly like a failing package until you look.

### 13. The auto-release deadline was assumed immutable, not asserted (done)

`docs/audit-readiness.md` listed permissionless auto-release as deliberate and
added that it was "worth confirming the deadline cannot be brought forward".
Nobody had. That property is what makes the permissionless path safe: anyone may
call `release` once `autoReleaseAt` has passed, so an actor who could move that
timestamp earlier could pay a provider before the buyer's window to dispute had
run. Nothing about the release path would look wrong. The deadline would simply
have arrived early.

It holds, and by construction: both deadlines are written once inside the struct
literal at funding and no function reassigns either, and the windows are bounded
by `MIN_WINDOW` and `MAX_WINDOW` so the additions cannot overflow into a small
value under checked arithmetic.

`invariant_deadlinesNeverMove` compares every escrow against values recorded at
creation in handler state, outside the contract, so it cannot read the
contract's own storage back and agree with itself. It held over 32,768 calls
including warps, disputes, settlements, releases and refunds. Making `dispute`
rewrite `autoReleaseAt` fails it, reporting the deadline having moved earlier,
which is the direction that costs a buyer their dispute window.

Existing tests covered behaviour *at* the deadline, which is a different
question and is why this went unnoticed: `test_strangerCannotReleaseBefore...`
and `test_anyoneCanReleaseAfter...` both hold a fixed deadline and vary the
clock. Nothing varied the deadline.

### 14. A documented revert had never been executed (done)

`docs/incident-runbook.md` described "one untested live-only revert": with
`treasury` equal to the subscriber, `subscribe()` reverts because the
balance-delta guard sees no net change on a self-transfer. Accurate, and nobody
had run it.

Now tested, including that no subscription is left behind, since a revert that
still granted a period is the failure worth catching. Weakening the guard to
accept a zero delta turns the revert into a free subscription and fails the test.

Worth doing despite being moot on mainnet, where the treasury is separated. The
revert comes from a guard about token behaviour, not about identity, so a future
change to how payment is measured could quietly turn it from a refusal into a
free subscription, and the runbook would still describe it as a revert.

### 15. The security document was wrong about its own premise (done)

The same sweep found a third, and this one was a live inaccuracy in a public
document rather than a missing test.

`docs/security.md` listed unverified email recipients as a risk and dismissed it
as "inert today, since nothing calls `notify()`", adding that it "must be fixed
before sending is enabled". Every part of that was wrong by the time it was
read. `notify()` is called from three modules. And the risk is not inert for the
reason given; it is genuinely mitigated for a better one, by a verification check
at delivery time that the document did not mention.

Wrong in both directions at once, which is the interesting part. Reassuring on
the premise, since a reader would conclude no code path reaches this. Pessimistic
on the control, since a reader would conclude the protection is still to be
built. Either way somebody deciding how much to trust the system was reading
something false.

The row now states the three conditions that must all hold before anything is
sent, that the single caller permitted to skip the last is the verification
message itself via an explicit argument, and that refusals are recorded rather
than dropped.

**The lesson is about how risk registers rot.** A mitigation written as "inert
because nothing calls it" is a statement about the *rest of the codebase*, which
changes without anybody revisiting the register. A mitigation written as "refused
by this check" is a statement about a specific control, and stays true or fails a
test. Prefer the second, and treat the first as a note that expires.

### 12. The assumption under both key bugs was never asserted (done)

After the same fingerprint appeared twice in one day, the next step was to stop
finding instances and go after what they rest on.

Both defects depended on one unwritten fact: every rate limiter is attached as a
route-level dependency, so FastAPI resolves it before the path function's own
parameters. That ordering is why `client_identity` reads credentials from the
headers rather than from request state, and why two separate attempts to publish
the caller onto `request.state.user_id` achieved nothing. Nothing anywhere
asserted it. Attach one limiter as a path parameter and the ordering inverts,
sessions behave identically, and API keys silently move from a per-key quota to
a per-account one, merging the quotas of every key an account holds.

Now asserted: 13 limiters, all route-level.

**Two comments corrected, including one I wrote the day before.** The API key
path said the assignment served "logging, auditing, error context". Nothing
reads it. That comment was written while fixing the previous false comment on
the same line, which is how quickly this happens even with the pattern in mind.
Both now say plainly that nothing reads it and why it is kept.

**The guard needed guarding, three times over.** Worth recording in full because
each failure looked like success.

The first mutation moved a real limiter onto a path parameter and the suite
stayed green. The mutation was broken, not the guard: that router uses lazy
annotations and never imports `Annotated`, so the annotation did not resolve and
FastAPI dropped the parameter entirely, leaving a route with no limiter at all.
A mutation that silently does nothing is indistinguishable from a guard with
nothing to complain about.

The second attempt moved the check into a purpose-built application, and hit the
same cause inside the test file, which also uses lazy annotations. That one was
caught only because the probe asserted its own setup had worked before drawing a
conclusion. Without that line it would have passed while testing nothing.

The third was the worst. The self-test carried its own copy of the detection
logic, so blinding the real detector left it green: it proved that *a* detector
like this works, not that *the* detector does. Both now call one function, and
blinding it fails both tests.

**The rule this leaves.** A test that proves a guard works must exercise the
same code the guard uses, and a mutation must be shown to have changed
behaviour before its result means anything. Otherwise the verification inherits
the exact weakness it exists to rule out.

### 11. API key traffic was rate limited by address, not by key (done)

Found by hunting the shape of item 10 rather than filing it: a check that names
the right thing while answering a different question. The obvious place to look
next was the other control that decides what a credential can do at volume.

`client_identity` reads the account from `request.state.user_id`, and failing
that decodes a bearer JWT. An API key arrives as `X-API-Key`, or as
`Authorization: Bearer ak_...` which is not a JWT and fails to decode. Either
way key traffic landed in the IP bucket. Two unrelated customers calling from
one cloud provider's address shared a quota, and moving address reset a key's
quota, both of which that module documents as impossible.

It looked handled, which is the whole point. `get_principal` sets
`request.state.user_id` for key traffic under a comment saying keys are counted
by account, so anyone checking found an answer. It was wrong for exactly the
ordering reason documented at length a few lines above the code it was wrong in:
limiters are route-level dependencies, resolved before a path function's own
parameters, so the limiter had already run.

**Twice now in one day, and the pattern is worth stating.** A comment asserting
an outcome is not evidence of the outcome, and it is worse than no comment,
because it terminates the search. Both defects were found by asking what a line
*decides* rather than what it *mentions*, and both had a correct, load-bearing
version of the same idea sitting nearby, which is what made the wrong one look
finished.

Counted per key rather than per account: resolving the account needs a database
round trip, and costing nothing is a design property of that path. Per key is
also the better unit, since one runaway integration cannot consume the quota of
its owner's other keys. The bound is the 25 active keys an organization may
hold. The token is hashed before it becomes a bucket name, so a live credential
never reaches a Redis key, a log line, or an error message.

Eight tests, and three separate mutations each fail on their own: removing the
key bucket, bucketing by the raw secret, and reading only one of the two headers
a key may arrive in.

### 10. An API key was not confined to its organization (done)

Found by asking the security question that follows from the previous batch
rather than waiting for it to surface: enforcing the write scopes made 18
endpoints reachable by a credential that previously could not reach them at all,
so what does the authorization layer *underneath* the scope check actually
enforce.

It enforced the caller's membership of the resource's organization, and nothing
about the key's own. A key is minted inside an organization, listed under it,
and chosen per organization in the interface, so its holder reasonably believes
it is confined there. It was not. The key resolved to its creator, and that
person's authority was used for every ownership check, so the key reached every
organization they belong to.

The organization *was* being checked, once, at authentication, to confirm the
creator is still a member. That is a real and necessary check answering a
different question: whether the key still works, not where it may act. Answering
the first was mistaken for answering the second, which is why nothing looked
missing.

Demonstrated before it was fixed: a key minted in a personal organization
created an agent in a separate team organization and got a 201. Then fixed, then
demonstrated again in the other direction.

A second, quieter half surfaced while fixing the first. A key naming no
organization fell through to the creator's *personal* organization, so a team
key filed new agents under a private account. Nothing failed and nothing warned.
The agent was simply in the wrong place, owned by a person rather than a team.

Sessions are deliberately not confined. A signed-in person switches
organizations in the interface and is meant to act in all of theirs; it is the
credential living in a config file that needs containing. Asserted rather than
assumed, with a test that a session still acts in both.

Four tests, and each of the three guards was removed individually to confirm it
is what fails: removing the agent confinement, letting a key name any
organization, and restoring the personal-organization fallback each turn the
suite red on their own.

**The general point worth keeping.** A check that mentions the right noun is not
the same as a check that answers the right question. `key.org_id` appeared in
the authentication path, so a reader looking for "is the organization enforced"
found something and stopped. Searching for whether a concept is *referenced*
will keep finding these; the question has to be what the reference decides.

### 9. A five second database timeout was skipping tests (done)

The test fixtures connected with `timeout=5`, to "fail fast when nothing is
listening". On a loaded workstation a full run takes about eleven minutes rather
than CI's sixty five seconds, and that timeout produced an error in one run and
a **silently skipped test** in the next.

The stated reason did not survive being measured. With nothing listening on
loopback the connection is refused in about two seconds whatever the timeout,
tested at both 5 and 30. The short value never made the no-database case fast;
the refusal did. It only ever bit when a database was present and slow, which is
the one case it should not have failed.

Raised to 30 seconds across eighteen test files. Worth recording as more than a
tuning change: a setting justified by a plausible story nobody had measured was
quietly reducing how many tests ran, which is the failure this project treats as
most serious.

### Standing, not scheduled

| Item | Owner | State |
| --- | --- | --- |
| Three Safe multisigs on Base: the two admin addresses and the arbiter | Owner | With the owner. The arbiter joined this list when dispute resolution was built; see docs/contracts.md |
| Security audit engagement | Owner | With the owner |
| DMARC to quarantine, then reject | Infrastructure | Deliberately held at `p=none` |
| Mainnet deployment | Owner | Blocked on the multisigs and the audit, by instruction |
