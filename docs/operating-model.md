# Operating model

How this project is run. Written down because the work spans sessions and the
context that produced a decision is usually gone by the time the decision is
questioned.

One person does all of the below. The point of splitting it into areas is not
pretend headcount, it is that each area has a different failure mode, a different
definition of "done", and a different set of things that quietly rot when nobody
is looking at them. A single list of tasks hides that; a set of standing
responsibilities does not.

## Standing constraints

These are not defaults to be weighed against other factors. They are settled.

| Constraint | Meaning |
| --- | --- |
| Nothing on mainnet | No deploy, no transaction, no verification against Base mainnet without an explicit instruction naming it |
| Flag before irreversible, costly, or externally visible | Anything reaching a third party, spending money, or hard to undo gets described first and executed after |
| Commits attributed to the project alone | Author is Agoreum. No co-author trailers, no tool attribution |
| No em dashes | In code, comments, commits, docs, and messages |
| Honest reporting | Failures reported as failures, with the evidence. A thing is "done" when it has been verified, not when it has been written |

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

### Community and communications

Owns: the public documentation, the Discord server, inbound support and
disclosure mail, and the tone of anything sent to a person.

Good looks like: an outside report gets a real answer with reasoning, not a
brush-off. Announcement surfaces cannot be posted to by anyone. Nothing arriving
by mail is treated as an instruction.

Standing checks: is inbound mail announced to a human. Can a stranger post in a
channel members trust. Is a published claim still true.

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

   The point has a second edge, learned by getting it wrong here. A public URL
   returned 200 within a second of a reboot, and that was written up as
   Cloudflare serving cache over a dead origin. It was not. Caching was off, and
   the monitor's own log showed the edge returning 521 during the outage. The
   recovery had simply been fast. Suspecting the instrument is a discipline, not
   a licence to explain away a result you did not expect: the suspicion has to be
   checked too, and here it cost a false line in the runbook telling a future
   operator not to trust the one signal that was telling the truth.

9. **What uses a thing and what a thing created are different questions.** Before
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
4. **Blocked strands are declared, not parked.** A strand waiting on the owner or
   on a credential goes into "Open, blocked" below with what unblocks it. Silence
   about a blocked strand reads as progress.

The coordinator's job is the part that does not belong to any area: deciding what
runs now, noticing when two strands have started to disagree about the same fact,
and keeping the record below true while the work is happening rather than after.

## Current state

Maintained so a session starting cold can act from this section rather than
re-reading the repository. It records what is true now and what is in flight,
not the history, which is in the backlog and the git log. Anything here that has
gone stale is a defect in this file.

**Last updated:** 2026-08-15.

### Where things stand

| Area | State |
| --- | --- |
| Contracts | Escrow and subscriptions on Base Sepolia only. Fork suite runs in CI, 6 passed and 0 skipped, asserted rather than assumed. Nothing on mainnet |
| Backend and API | 667 tests, 667 passed, 0 skipped, on a clean database with every dependency present. API keys can now write, gated per scope, see below |
| Frontend and web | Nine locales, each with its own canonical URL and social card |
| SDKs | Python, TypeScript and Go published at 0.1.1. The 0.1.0 payment-endpoint defect is fixed and released |
| Infrastructure | Droplet origin locked to Cloudflare ranges. Build cache bounded after the deploy verifies. Backups daily, restore and cutover both drilled |
| Local environment | Postgres, Redis and Anvil run as plain processes. `scripts/local-dev.ps1` brings them up, `-Status` says which are answering. Restored on 2026-08-15 after a cleanup removed the Docker Desktop that had been providing them. The GitHub CLI went in the same cleanup and has not been reinstalled: CI is queried through the REST API with the token from the env file, which needs no install and no separate login |
| Community | Support inbox answered to zero as of 2026-08-15. Discord blocked, see below |

### In flight

On branch `api-key-write-scopes`, PR #1, CI green across all fourteen jobs with
667 passed and 0 skipped. Not merged: a merge to `main` triggers a production
deploy, which is externally visible and therefore the owner's call rather than
something to do quietly at the end of a session.

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

### Open, blocked

| Item | Blocked on | What unblocks it |
| --- | --- | --- |
| Reading and answering Discord | The bot cannot see message content | Owner enables MESSAGE CONTENT INTENT for application `1535454403161755748` in the Discord developer portal. Detail below |
| Three Safe multisigs on Base | Owner | Owner action. Escrow admin, subscriptions admin, arbiter, distinct signers and a real threshold |
| Security audit engagement | Owner | Owner action |
| Mainnet deployment | The two rows above | Both, plus an explicit written instruction naming mainnet |
| PyPI 0.1.0 yank | Owner | The publish token cannot yank; needs an account-level action |

**Discord, in detail.** The bot authenticates and can list every channel, but
`content` comes back as an empty string on every message, with zero embeds and
zero attachments, which is the signature of Discord stripping content rather
than the messages being empty. `GET /applications/@me` returns `flags: 0`, so
neither `GATEWAY_MESSAGE_CONTENT` nor its limited variant is set. There are real
conversations waiting behind this, in `#general` and `#introductions`, from
members who joined on 2026-08-14. They are unread rather than unanswered, and
the difference matters: nothing should be sent to them until they can be read.

## Backlog

Re-derived from the state of the code on 2026-08-08, after the previous list was
finished. Ordered by what would hurt most if left, with the evidence that put each
one where it is rather than an assertion that it matters.

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

### 6. The API suite only passes on a virgin database (open)

Found on 2026-08-15 while restoring the local database. `test_email_verification`
uses fixed addresses, `a@example.com` through `e@example.com`, against a unique
constraint. The first run creates those rows and nothing removes them, so the
second run of the same suite fails nine tests with `profile_conflict`, and a
tenth in `test_notification_events` for the same reason.

CI has never seen this because its database is new every run, which is exactly
what makes it worth writing down rather than fixing quietly: the green CI badge
is not evidence about this, and anybody running the suite twice locally will hit
it and reasonably assume they broke something.

Not urgent, and deliberately not fixed in the same change as the scope work.
The fix is either unique addresses per test or a fixture that cleans up after
itself, and picking between those is a decision about how the whole suite
handles isolation rather than a patch to one file.

### Standing, not scheduled

| Item | Owner | State |
| --- | --- | --- |
| Three Safe multisigs on Base: the two admin addresses and the arbiter | Owner | With the owner. The arbiter joined this list when dispute resolution was built; see docs/contracts.md |
| Security audit engagement | Owner | With the owner |
| DMARC to quarantine, then reject | Infrastructure | Deliberately held at `p=none` |
| Mainnet deployment | Owner | Blocked on the multisigs and the audit, by instruction |
