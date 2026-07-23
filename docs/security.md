# Security

What Agoreum defends against, how, and what is still open.

> **No independent audit has been performed, and nothing has been deployed.**
> This document describes implemented controls, not a clean bill of health.

## Reporting a vulnerability

Email <support@agoreum.xyz>. Please do not open a public issue for a security
problem.

Include what you found, how to reproduce it, and what you believe the impact is.
We will confirm receipt and keep you updated. Please give us reasonable time to
fix an issue before disclosing it publicly.

## The threat model

Agoreum moves money between strangers, so the attacker worth designing against
is a motivated one with an economic incentive — not a curious passer-by.

The assets, in order of what an attacker would want:

1. **Funds in escrow.** Held on chain, defended by the contract.
2. **Payout addresses.** Redirecting one steals every future payment.
3. **Sessions.** A stolen session is an identity.
4. **Reputation.** Fabricated standing is what enables a rug-pull.
5. **Personal data.** Emails, order history, trading relationships.

The single most valuable attack is payout redirection: quiet, and it steals
future money rather than a single payment. It is treated accordingly — a payout
wallet must be verified, must belong to the caller, and an attempt to use
someone else's returns 404.

## Custody

**The platform holds no keys and no funds.**

- No private key exists in any application configuration.
- No code path signs or broadcasts a transaction.
- No database column can hold key material — asserted by a test over the whole
  schema, so adding one fails the build.
- Sessions store only a SHA-256 hash of the refresh token.

The API describes transactions; the user's wallet signs them. If you find a code
path where the platform could move value on its own, it is a bug.

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

Nonces are alphanumeric because EIP-4361 requires it — an earlier URL-safe
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
**Presenting a spent one revokes every session for that user** — reuse means it
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

## Injection

**SQL.** Everything goes through SQLAlchemy with bound parameters. No string
interpolation reaches a query. Search uses `websearch_to_tsquery`, which never
raises on malformed input — where `to_tsquery` would turn a stray parenthesis
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
non-publicly-routable address — checking **every** resolved address, not just
the first — and does not follow redirects, since a redirect could reach an
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
exhaust everyone else's allowance.

Counters live in Redis, not in process memory — behind a load balancer an
in-memory limiter gives an attacker one full allowance per replica and resets
every deploy.

**Failure policy is fail-open, deliberately.** If Redis is unreachable, requests
are allowed and the failure is logged loudly. Failing closed would turn a cache
outage into a total outage in which nobody could sign in and no provider could
be paid. Rate limiting is a shield against abuse; it is not what prevents
unauthorised access — the signature check is, and it is unaffected. There is a
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

Request bodies are capped at 1 MiB in the application and again at the edge — a
declared multi-gigabyte body can exhaust memory before any validator sees it.
Every payload is validated by Pydantic with explicit bounds; pagination is
capped; timeouts bound slow-request attacks.

## On-chain

See [contracts.md](contracts.md). In summary: the contract cannot pay out more
than it took in, state is written before value moves, every funded escrow always
has a terminal path, the fee is frozen per escrow and capped in immutable code,
and pausing cannot strand committed funds.

Off chain, the indexer only applies events past the confirmation frontier, is
idempotent by transaction hash, detects reorgs by changed block hash, and
**never invents an order** for an escrow it does not recognise — it logs and
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
- CI runs gitleaks over the **full history** — a secret removed later is still
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
| No contract audit | Unknown contract risk | Required before mainnet |
| Not deployed anywhere | Untested against a real network | Testnet pending |
| Tokens in `sessionStorage` | XSS could exfiltrate a session | Mitigated by CSP; httpOnly cookies planned once API and site share a domain |
| No 2FA | Wallet compromise is total account compromise | Inherent to wallet-based identity |
| Single arbiter key | Compromise allows unfair dispute settlement | Multisig planned |
| No automated dependency scanning | A vulnerable dependency could go unnoticed | Dependabot planned |
| No admin role-granting path | No way to become admin | Deliberate — see [architecture.md](architecture.md) |

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
