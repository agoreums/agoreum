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
| No manufactured activity | No giveaways, points programmes, airdrops, engagement campaigns or paid promotion, and no KOL or influencer arrangements. Reputation on the platform comes only from orders that settled on chain, and a community inflated by campaigns would contradict the one claim the product rests on |
| Not hiring until after the audit | Applications and partnership pitches of that shape are declined directly, with the reason, and without checking first. Settled on 2026-08-15 rather than decided per message |

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

## Current state

Maintained so a session starting cold can act from this section rather than
re-reading the repository. It records what is true now and what is in flight,
not the history, which is in the backlog and the git log. Anything here that has
gone stale is a defect in this file.

**Last updated:** 2026-08-15.

### Where things stand

| Area | State |
| --- | --- |
| Contracts | Escrow and subscriptions on Base Sepolia only. 140 tests, 0 skipped, including an invariant that deadlines never move. Fork suite runs in CI, 6 passed and 0 skipped, asserted rather than assumed. Nothing on mainnet |
| Backend and API | 701 tests, 701 passed, 0 skipped, and the same again on the second run against the same database, which CI enforces. API keys can write, gated per scope, see below |
| Frontend and web | Nine locales, each with its own canonical URL and social card |
| SDKs | Python, TypeScript and Go published at 0.2.0 on 2026-08-15, each verified from its registry rather than from the local build |
| Infrastructure | Droplet origin locked to Cloudflare ranges. Build cache bounded after the deploy verifies. Backups daily, restore and cutover both drilled |
| Local environment | Postgres, Redis and Anvil run as plain processes. `scripts/local-dev.ps1` brings them up, `-Status` says which are answering. Restored on 2026-08-15 after a cleanup removed the Docker Desktop that had been providing them. The GitHub CLI went in the same cleanup and has not been reinstalled: CI is queried through the REST API with the token from the env file, which needs no install and no separate login |
| Community | Support inbox answered to zero as of 2026-08-15. Discord readable and answered as of the same day |

### In flight

Nothing. Two pull requests merged to `main` on 2026-08-15, each with all
fourteen CI jobs green including Deploy and Fork tests:

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
