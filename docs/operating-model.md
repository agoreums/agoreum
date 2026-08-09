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

## Working loop

Pick the highest item on the backlog that is not blocked. Build it with tests
asserting the property, not the implementation. Run CI. Verify in production where
production is where it lives. Report what was done, what was found, and what is
still not true. Update the backlog. Repeat without waiting to be asked.

Anything discovered mid-task that is broken but out of scope gets written to the
backlog rather than silently fixed or silently ignored.

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

### 2. The money path is the least tested large module (partly done)

Both now have test files covering their arithmetic and their rules: what a buyer is
charged, how a figure is rounded to the settlement token, and what a service is
allowed to say about its own price.

What is still uncovered is the state machine. The transitions between funded, in
progress, delivered and completed, and what each one refuses, are exercised only by
three indexer tests about applying chain events.

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

### Standing, not scheduled

| Item | Owner | State |
| --- | --- | --- |
| Three Safe multisigs on Base: the two admin addresses and the arbiter | Owner | With the owner. The arbiter joined this list when dispute resolution was built; see docs/contracts.md |
| Security audit engagement | Owner | With the owner |
| DMARC to quarantine, then reject | Infrastructure | Deliberately held at `p=none` |
| Mainnet deployment | Owner | Blocked on the multisigs and the audit, by instruction |
