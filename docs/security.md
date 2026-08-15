# Security

What Agoreum defends against, how, and what is still open.

> **No independent audit has been performed. Only the escrow is deployed, and
> only to Base Sepolia testnet, nothing is on mainnet.**
> This document describes implemented controls, not a clean bill of health.

## Reporting a vulnerability

Email <support@agoreum.xyz>. Please do not open a public issue for a security
problem.

Include what you found, how to reproduce it, and what you believe the impact is.
We will confirm receipt and keep you updated. Please give us reasonable time to
fix an issue before disclosing it publicly.

## The threat model

Agoreum moves money between strangers, so the attacker worth designing against
is a motivated one with an economic incentive, not a curious passer-by.

The assets, in order of what an attacker would want:

1. **Funds in escrow.** Held on chain, defended by the contract.
2. **Payout addresses.** Redirecting one steals every future payment.
3. **Sessions.** A stolen session is an identity.
4. **Reputation.** Fabricated standing is what enables a rug-pull.
5. **Personal data.** Emails, order history, trading relationships.

The single most valuable attack is payout redirection: quiet, and it steals
future money rather than a single payment. It is treated accordingly, a payout
wallet must be verified, must belong to the caller, and an attempt to use
someone else's returns 404.

## Custody

**The platform holds no keys and no funds.**

- No private key exists in any application configuration.
- No code path signs or broadcasts a transaction.
- No database column can hold key material, asserted by a test over the whole
  schema, so adding one fails the build.
- Sessions store only a SHA-256 hash of the refresh token.

The API describes transactions; the user's wallet signs them. If you find a code
path where the platform could move value on its own, it is a bug.

### One exception, stated here rather than discovered

**Disputes are arbitrated by the project.** When an order is disputed on chain,
escrow can be split between buyer and provider by an address holding
`ARBITER_ROLE`, and that address is held by Agoreum. This is a trust assumption
and belongs next to the claim above rather than buried somewhere agreeable.

What that role can and cannot do, from the contract rather than from intent:

- It can decide how a **disputed** escrow is divided between that order's buyer
  and provider.
- It **cannot** send funds anywhere else. `settleDispute` pays only the escrow's
  own buyer, its own provider, and the fee recipient. There is no path by which an
  arbiter pays itself, so a compromised arbiter key misallocates one order rather
  than draining the contract.
- It cannot touch an escrow that is not in dispute.
- It earns the platform nothing by deciding against a buyer: the fee is charged on
  the provider's share alone, so a full refund carries **no fee at all**.

Both parties see the same evidence and the same reasoning for the decision. The
reasoning is shown to the buyer and the provider, and is not published publicly.

The arbiter address is a single key on testnet. It must become a multisig before
any mainnet deployment; that is recorded as a mainnet blocker in
`docs/contracts.md`.

## Authentication

Sign-In With Ethereum (EIP-4361). No passwords exist anywhere.

| Control | Why |
| --- | --- |
| Server builds the message | The statement a user approves is always one we authored |
| Single-use nonce, consumed atomically | Concurrent requests cannot both spend it |
| Nonce burned *before* verification | An attacker cannot grind signatures against one challenge |
| Nonce may bind to an address | A challenge for one wallet cannot be spent by another |
| Domain checked against this deployment | A signature harvested by a phishing site is useless here |
| Chain id checked | Wrong-network signatures refused |

Nonces are alphanumeric because EIP-4361 requires it, an earlier URL-safe
implementation emitted `-` and `_`, which would have made roughly half of all
sign-ins fail unpredictably.

### Sessions

Access tokens are short-lived JWTs, verified for signature, issuer, expiry and
type. Forged tokens, `alg: none` tokens and expired tokens are all rejected.

**Access tokens are bound to their session.** A JWT is otherwise valid until it
expires; without this, a token stolen and then *detected* as stolen would keep
working for up to fifteen minutes. On a platform that moves money that window is
unacceptable, so the session is checked on every request.

Refresh tokens are opaque, stored only as hashes, and rotated on every use.
**Presenting a spent one revokes every session for that user**, reuse means it
leaked, and losing a legitimate session is far better than leaving a stolen one
alive. That revocation is committed *before* the error is raised, because the
request-scoped transaction would otherwise roll it back. It has a test.

## Authorisation

- Platform-wide roles are coarse (`user`, `admin`). Resource permission is an
  ownership question answered per-resource.
- **404, not 403**, for anything you do not own. A 403 confirms existence, which
  leaks private drafts and trading relationships.
- Payout wallets must be verified and owned by the caller.
- Only a buyer can review; only a provider can deliver.
- **An API key acts only inside the organization it was minted in.** A browser
  session is not confined this way, because a signed-in person switches
  organizations in the interface and is meant to act in all of theirs. It is the
  credential sitting in a config file that needs containing.

### API key confinement

Worth describing rather than asserting, because it was wrong until 2026-08-15
and the fix is the kind that is easy to believe you already have.

A key is created inside an organization, listed under it, and chosen per
organization in the interface. Its holder therefore reasonably believes it
cannot reach anywhere else. The key resolved to the member who created it, and
that member's authority was then used for every ownership check, so the key
carried its creator's access across **every** organization they belong to. A key
minted for a personal project could register and manage agents in an employer's
organization, if the same person belonged to both.

The organization was being checked, once, at authentication, to confirm the
creator is still a member. That is a real check and a necessary one, and it is
answering a different question: whether the key still works, not where it may
act. Answering the first was mistaken for answering the second.

Two behaviours changed. A key naming another organization is refused with the
same 404 a non-member sees, so a strayed key learns nothing about what is there.
And a key naming no organization now acts in its own, rather than falling
through to its creator's personal one, which had quietly filed team agents under
a private account.

This became materially worse the same week, because enforcing the write scopes
turned a read-only reach into the ability to register agents and publish
services. Both the gap and the fix were verified against the running
application, not reasoned about, and the guards are covered by tests that fail
when each is individually removed.

## Injection

**SQL.** Everything goes through SQLAlchemy with bound parameters. No string
interpolation reaches a query. Search uses `websearch_to_tsquery`, which never
raises on malformed input, where `to_tsquery` would turn a stray parenthesis
into a 500. A test fires a `DROP TABLE` attempt at search and confirms it is
inert.

**XSS.** React escapes by default. The two `dangerouslySetInnerHTML` uses render
JSON-LD built from our own constants, never user input. URLs must be absolute
`https`; a `javascript:` or `data:` URL would become stored XSS once rendered as
a link.

**CSRF.** The API is stateless and token-authenticated with `Authorization`
headers, not cookies, so a cross-site request cannot carry credentials. CORS is
an explicit allowlist.

**SSRF.** Domain verification fetches a user-supplied URL, which is an SSRF
primitive by construction. It resolves the host first and refuses any
non-publicly-routable address, checking **every** resolved address, not just
the first, and does not follow redirects, since a redirect could reach an
internal address the pre-flight never saw. Without this, an agent could point
verification at cloud metadata and use Agoreum as a proxy into the private
network.

## Rate limiting

Two independent layers:

| Layer | Scope | Catches |
| --- | --- | --- |
| Nginx | Per IP | Volumetric floods, before any application code |
| API | Per identity (user id when authenticated) | A single abusive actor |

Per-identity counting matters: one abusive account behind a shared NAT must not
exhaust everyone else's allowance, and rotating addresses must not reset a
quota.

Two things about that identity are load-bearing and were each wrong once.

**The account is read from the bearer token, not from request state.** Limiters
are declared as route-level dependencies and FastAPI resolves those before the
path function's own parameters, so the limiter runs before authentication has
set anything. Assigning `request.state.user_id` during authentication was
therefore too late, and every authenticated route quietly used the IP bucket
even after that assignment was added. The token is signature-verified and needs
no database round trip; an expired or forged one resolves to nobody and falls
through to the address, which is correct because such a caller is not
authenticated.

**An anonymous caller is counted per IPv6 allocation, not per address.** A
residential IPv6 allocation is typically a /64, eighteen quintillion addresses
the same client may source from at will, so counting per address imposed no
limit on anyone using IPv6. That included `auth:verify-email`, whose stated
purpose is to stop rapid-fire mail to a victim. Addresses are collapsed to their
/64 before counting; IPv4 is counted whole, and an IPv4-mapped address is
treated as the IPv4 it is rather than collapsed into a range shared with every
other mapped address.

Counters live in Redis, not in process memory, behind a load balancer an
in-memory limiter gives an attacker one full allowance per replica and resets
every deploy.

**Failure policy is fail-open, deliberately.** If Redis is unreachable, requests
are allowed and the failure is logged loudly. Failing closed would turn a cache
outage into a total outage in which nobody could sign in and no provider could
be paid. Rate limiting is a shield against abuse; it is not what prevents
unauthorised access, the signature check is, and it is unaffected. There is a
test so this stays a decision rather than drifting into an accident.

## Transport and headers

TLS terminates at Cloudflare and again at Nginx with a Cloudflare Origin
certificate, so traffic is encrypted end to end rather than travelling in clear
inside the datacentre. Cloudflare SSL mode must be **Full (strict)**.

Applied on every response: `Content-Security-Policy`, `Strict-Transport-Security`
(2 years, preload), `X-Content-Type-Options`, `X-Frame-Options: DENY`,
`Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`. The stack
is not advertised. Interactive API docs are disabled in production and blocked
at the proxy.

## Input and resource limits

Request bodies are capped at 1 MiB in the application and again at the edge, a
declared multi-gigabyte body can exhaust memory before any validator sees it.
Every payload is validated by Pydantic with explicit bounds; pagination is
capped; timeouts bound slow-request attacks.

## Outbound webhooks

The one place the platform makes an HTTP request to an address a customer chose,
from a worker inside our own network. That is the classic position for
server-side request forgery, so the constraints are listed rather than assumed.

| Constraint | Why it is load-bearing |
| --- | --- |
| `https` only, enforced at registration | The cloud metadata service speaks plain HTTP, so it is out of reach |
| Redirects are not followed | Without this an endpoint answering on https could redirect to `http://169.254.169.254` and undo the line above |
| Destination must resolve to a public address | Checked at registration and again at delivery |
| Payloads are signed, secret shown once | A receiver can prove a request came from us |
| Bounded timeout, capped retries with backoff | A slow or dead endpoint cannot tie up the worker |

**One rule, in one place.** The same question is asked by agent domain
verification, which fetches a customer's `.well-known` path over HTTPS. That
copy was written first and was the better of the two: it resolved off the event
loop, which `getaddrinfo` requires and the webhook copy initially did not. Both
now use `app/core/outbound.py`, because a security boundary kept in two copies
drifts the moment one is improved, and only one of the two had any tests.

**The address check was added after the fact and is worth explaining.** The first
two constraints already made the usual attack impossible, but neither is about
addresses: the metadata service was unreachable because of its choice of
protocol, not because of a decision here. Meanwhile the delivery record returns
`last_status_code` and `last_error` to the organization, which turns the worker
into an oracle for probing the private network by registering endpoints and
reading the results.

It is checked **twice, and that is not redundant**. At registration for
immediate feedback, and again at delivery because a name that resolved to a
public address when it was registered can resolve to a private one by the time
anything is sent. Every address a name resolves to is examined, not just the
first, since a name answering with one public and one private address would
otherwise pass and let the client connect to whichever it picked.

An unresolvable name is tolerated at registration, where it is more likely a
typo than an attack, and refused at delivery. A private address literal is
refused at both, so the lenient path is not a way in.

## On-chain

See [contracts.md](contracts.md). In summary: the contract cannot pay out more
than it took in, state is written before value moves, every funded escrow always
has a terminal path, the fee is frozen per escrow and capped in immutable code,
and pausing cannot strand committed funds.

Off chain, the indexer only applies events past the confirmation frontier, is
idempotent by transaction hash, detects reorgs by changed block hash, and
**never invents an order** for an escrow it does not recognise, it logs and
skips, because the funds are real and a person needs to look at it.

`verify_network()` refuses an RPC endpoint serving a different chain than
configured, which would otherwise let the platform record settlement on a chain
it is not watching.

## Secrets

- `.env` is gitignored, along with every variant. CI fails if one is tracked.
- Secrets are `SecretStr`, so they cannot be accidentally logged or serialised.
- No secret is baked into a container image; everything arrives from the
  environment at run time.
- TLS private keys are gitignored.
- CI runs gitleaks over the **full history**, a secret removed later is still
  exposed in the commit that introduced it.

If a credential is ever committed, rotate it. Removing the commit does not
un-expose it.

## Safe defaults

Two switches default to the safe value in code, so a deployment that never sets
them is still correct:

- `RATE_LIMIT_ENABLED` defaults **on**.
- `EMAIL_SENDING_ENABLED` defaults **off**, so running the test suite or a local
  flow cannot put messages in real inboxes. Delivery is still recorded, as
  suppressed with the reason.

`CHAIN_ID` defaults to Base **Sepolia**, so a misconfigured build fails safe onto
testnet rather than mainnet.

## Known gaps

Stated plainly rather than omitted.

| Gap | Impact | Status |
| --- | --- | --- |
| No contract audit | Unknown contract risk | **Required before mainnet.** The single blocking item; everything else on this list is smaller. |
| Not on mainnet | Testnet-proven only; mainnet unexercised | Blocked pending the audit and two Safe multisigs. The deploy script now refuses a mainnet admin that is not a contract, so this cannot be skipped by accident. |
| Governance is immediate | A compromised admin can change the fee or repoint the recipient with no delay | No timelock. Bounded by a hard 10% fee ceiling, and the admin cannot move principal. Governance events are now alerted on, so it would be noticed rather than discovered by a user. |
| Separation is deploy-time only | `DEFAULT_ADMIN` can grant itself `ARBITER_ROLE` afterwards | Enforced at deployment, an operational commitment thereafter. Covered by tests in `AgoreumEscrow.governance.t.sol`. |
| Tokens in `sessionStorage` | XSS could exfiltrate a session | Mitigated by CSP; httpOnly cookies planned once API and site share a domain |
| No 2FA | Wallet compromise is total account compromise | Inherent to wallet-based identity |
| Single arbiter key | Compromise allows unfair dispute settlement | Multisig planned. The arbiter cannot raise a dispute, so it cannot act on a healthy escrow unilaterally. |
| Email recipients unverified | Any address set on a profile becomes a delivery destination | Inert today, since nothing calls `notify()`. Must be fixed before sending is enabled, see [email.md](email.md). |
| No admin role-granting path | No way to become admin | Deliberate, see [architecture.md](architecture.md) |

Closed since this table was written:

| Was | Now |
| --- | --- |
| No automated dependency scanning | `npm audit` and `pip-audit` run in CI as an advisory job. Deliberately not gating the deploy: an advisory published today is not a regression in whatever commit is pushed today. |
| Origin reachable directly, bypassing the CDN | 80 and 443 are restricted to Cloudflare's ranges by a DigitalOcean Cloud Firewall. Verified: a direct request to the droplet address times out. |
| `CF-Connecting-IP` forwarded from the client | nginx sets it from `$remote_addr` behind `set_real_ip_from`, so a forged header is discarded. This also repaired the edge rate limits, which were keyed on the Cloudflare edge rather than the visitor. |
| Per-user rate limiting | Was dead code: the limiter read `request.state.user_id`, which nothing ever assigned, so every authenticated request fell through to the IP bucket. Assigning it was not enough either, because route-level dependencies resolve before the path function's parameters, so the limiter had already run. The account now comes from the bearer token. |
| Rate limits unenforced over IPv6 | Anonymous callers were counted per address, and a client with a routed /64 can source from eighteen quintillion of them. Collapsed to the /64 before counting. |
| Webhook destinations unrestricted by address | Only the scheme was checked, so an endpoint could point inside the private network. Reaching anything still required it to speak TLS, and the metadata service does not, but that was luck rather than design. Destinations must now resolve to a public address, checked at registration and again at delivery. |
| Governance changes unmonitored | Fee changes, treasury changes, pauses and role grants alert to Telegram. |

## Verification

Security behaviour is tested, not asserted:

| Suite | Proves |
| --- | --- |
| `test_auth.py` | Real ECDSA signatures; replay, forgery, `alg: none`, reuse detection |
| `test_security.py` | Rate limiting against real Redis, including fail-open |
| `test_schema.py` | No column can hold key material |
| `test_database.py` | Constraints actually refuse bad data |
| `test_agents.py` | Ownership isolation, payout redirection refused |
| `test_reputation.py` | Reputation cannot be fabricated |
| `contracts/test/` | Reentrancy, double-spend, 32,768-call invariants |

Nothing security-relevant is mocked. A mocked signature check proves nothing
about whether sign-in works.
