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

## Working loop

Pick the highest item on the backlog that is not blocked. Build it with tests
asserting the property, not the implementation. Run CI. Verify in production where
production is where it lives. Report what was done, what was found, and what is
still not true. Update the backlog. Repeat without waiting to be asked.

Anything discovered mid-task that is broken but out of scope gets written to the
backlog rather than silently fixed or silently ignored.

## Backlog

Ordered by judgement, revised as things are learned. Kept here so it survives the
session that created it.

| Priority | Item | Area | State |
| --- | --- | --- | --- |
| 1 | Service versioning: orders now freeze delivery and auto release windows alongside price. A full version history for services, so buyers can see what changed since they ordered, is still open | Backend | Partly done: terms frozen, history not built |
| 2 | Usage analytics depth: creator view now carries a revenue series, a previous-period comparison, and in-flight versus disputed versus refunded exposure. A buyer view exists. Organization-wide and platform-wide views are still open | Backend | Partly done |
| 3 | Organization accounts refinement: invitations require the invitee to accept, both sides have an interface, and role changes and ownership transfer already guard against orphaning an org | Done |
| 4 | Developer documentation: three SDKs ship with no worked examples or quickstart per language | Community | Thin |
| 5 | Notification locale: captured on every notification and never read, so all mail is English while the site ships nine locales | Backend | Known gap |
| 6 | DMARC to quarantine, then reject, once aggregate reports look clean | Infrastructure | Waiting on report volume |
| 7 | Two Safe multisigs on Base for the admin addresses | Owner | With the owner |
| 8 | Security audit engagement | Owner | With the owner |
