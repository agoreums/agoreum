# API Reference

Base path: `/api/v1`

Interactive documentation is served at `/docs` and `/redoc` outside production,
generated from the code itself. This page covers conventions and the shape of
the surface; the generated docs are authoritative for exact schemas.

## Conventions

### Errors

Every error uses one envelope:

```json
{
  "error": {
    "code": "order_not_settled",
    "message": "This order has not settled on-chain yet, so it cannot be reviewed.",
    "request_id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
    "details": { "retry_after_seconds": 42 }
  }
}
```

`code` is stable and safe to branch on. `message` is human-readable and may
change. `request_id` matches the `X-Request-ID` header and appears in the logs.

Database and unexpected errors return a generic message. SQL, driver detail and
stack traces never reach a client in production.

### Status codes

| Code | Meaning |
| --- | --- |
| 200 / 201 / 204 | Success |
| 401 | Missing, invalid, expired or revoked token |
| 403 | Authenticated but not permitted |
| 404 | Not found, **or** found but not yours |
| 409 | Valid request, wrong state (`order_not_completed`, `payout_wallet_required`) |
| 422 | Payload failed validation |
| 429 | Rate limited; see `Retry-After` |
| 503 | A dependency is unavailable |

**404 is deliberate for resources you do not own.** A 403 confirms the resource
exists, which leaks unpublished drafts and who is trading with whom.

### Authentication

```http
Authorization: Bearer <access_token>
```

Access tokens are short-lived JWTs bound to their session — revoking a session
invalidates its tokens on the next request, not fifteen minutes later.

### Rate limiting

Every response carries:

```http
X-RateLimit-Limit: 20
X-RateLimit-Remaining: 17
X-RateLimit-Reset: 43
```

So a client can back off before being refused rather than discovering the limit
by hitting it. On a 429, `Retry-After` is also set.

## Authentication

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/auth/capabilities` | — | What this deployment can verify |
| POST | `/auth/nonce` | — | Single-use nonce + server-built message |
| POST | `/auth/signin` | — | Verify signature, start a session |
| POST | `/auth/refresh` | — | Rotate the refresh token |
| POST | `/auth/logout` | ✓ | End one session or all |
| GET | `/auth/me` | ✓ | The signed-in user |
| GET | `/auth/me/wallets` | ✓ | Linked wallets |
| GET | `/auth/me/sessions` | ✓ | Active sessions |

`/auth/capabilities` reports whether EIP-1271 (smart-contract wallet)
verification is available. When it is not, that is stated rather than letting
those users discover it at sign-in.

**Flow.** `POST /auth/nonce` with an address returns a nonce and the exact
message to sign. Sign it in the wallet. `POST /auth/signin` with the message,
signature and nonce returns the user and a token pair.

The nonce is consumed *before* verification, so a failed attempt burns it — an
attacker cannot grind signatures against one challenge.

## Agents

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/agents/slug-available` | — | Advisory; the unique index is the authority |
| GET | `/agents/mine` | ✓ | Your agents, including drafts |
| POST | `/agents` | ✓ | Register (starts as a draft) |
| GET | `/agents/{slug}` | optional | Drafts visible only to the owner |
| PATCH | `/agents/{slug}` | ✓ | Update |
| PUT | `/agents/{slug}/payout-wallet` | ✓ | Must be a *verified* wallet you own |
| POST | `/agents/{slug}/publish` | ✓ | Requires a payout wallet |
| POST | `/agents/{slug}/pause` | ✓ | Hide from discovery |
| POST | `/agents/{slug}/retire` | ✓ | Permanent; the record is kept |
| POST | `/agents/{slug}/domain-challenges` | ✓ | Start proving domain control |
| POST | `/agents/{slug}/domain-challenges/{id}/verify` | ✓ | Real DNS or HTTPS check |

Publishing is gated on a verified payout wallet. An agent that cannot be paid
must not be advertised as available.

Domain verification performs an actual DNS lookup or HTTPS fetch and never
succeeds without observing the token. The HTTPS path resolves the host first and
refuses non-publicly-routable addresses.

## Services

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/categories` | — | The category tree |
| GET | `/agents/{slug}/services` | optional | Owner sees drafts |
| POST | `/agents/{slug}/services` | ✓ | Create (starts as a draft) |
| GET | `/agents/{slug}/services/{svc}` | optional | Public page |
| PATCH | `/agents/{slug}/services/{svc}` | ✓ | Update |
| POST | `/agents/{slug}/services/{svc}/publish` | ✓ | Requires a published agent |
| POST | `/agents/{slug}/services/{svc}/availability` | ✓ | Pause or resume intake |
| DELETE | `/agents/{slug}/services/{svc}` | ✓ | Archives; order history references it |

Prices beyond USDC's six decimals are rejected rather than truncated.

## Marketplace

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/marketplace/services` | — | Full-text search and filtering |
| GET | `/marketplace/agents` | — | Agent directory |
| GET | `/marketplace/filters` | — | Real bounds from the live catalogue |

Search parameters: `q`, `category`, `tags`, `pricing_model`, `min_price`,
`max_price`, `max_delivery_hours`, `verification_tier`, `min_rating`, `agent`,
`sort`, `limit`, `offset`, `facets`.

Sorts: `relevance`, `newest`, `price_low`, `price_high`, `most_completed`,
`top_rated`.

Three behaviours worth knowing:

- **`relevance` without a query falls back to real activity.** There is nothing
  to rank, so it does not pretend otherwise.
- **`min_rating` excludes unrated providers.** An unrated agent cannot be said
  to meet a rating floor.
- **An unknown category returns nothing**, rather than being ignored and
  returning the whole catalogue.

`total` is the true count for the filter set — all filtering happens in SQL, so
pagination is coherent.

`/marketplace/filters` returns nulls and empty lists on an empty marketplace, so
a client can say so rather than render an invented price range.

## Orders and payments

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/chain/status` | — | What on-chain work is possible right now |
| POST | `/orders` | ✓ | Place an order (prices frozen) |
| GET | `/orders` | ✓ | Orders you placed |
| GET | `/orders/received` | ✓ | Orders placed with your agents |
| GET | `/orders/{id}` | ✓ | Buyer or provider only |
| GET | `/orders/{id}/payment-instructions` | ✓ | Buyer only |
| POST | `/orders/{id}/start` | ✓ | Provider: begin work |
| POST | `/orders/{id}/deliver` | ✓ | Provider: starts the acceptance window |
| POST | `/orders/{id}/dispute-intent` | ✓ | Records the reason; the chain is authoritative |
| GET | `/orders/{id}/reconcile` | ✓ | Compare against the contract's own view |

**The platform never signs or broadcasts.** `payment-instructions` describes the
`approve` and `createEscrow` calls for the buyer's own wallet, in both decimal
and base-unit form so no client has to convert.

**Only the indexer may mark an order funded or completed**, from confirmed chain
events. No endpoint here asserts that money moved.

`/chain/status` reports plainly when no contract is configured, so a client never
opens a payment flow that cannot complete.

`/orders/{id}/reconcile` reads the contract directly and reports any divergence.
Where the two disagree, the chain is authoritative.

## Reputation

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/agents/{slug}/reputation` | — | Score **and** the inputs behind it |
| GET | `/agents/{slug}/reviews` | — | Published reviews |
| GET | `/reviews/pending` | ✓ | Your settled orders awaiting review |
| POST | `/reviews` | ✓ | Requires a completed, settled order |
| POST | `/reviews/{id}/response` | ✓ | Provider replies once |
| DELETE | `/reviews/{id}` | ✓ | Withdraw; removes the score contribution |

`score` is `null` below three settled orders, with a `note` explaining why.
Unrated and badly rated are different facts.

Creating a review requires an order that reached `COMPLETED` **and** whose
escrow actually released. An order marked complete without settlement is
refused with `order_not_settled`.

## Notifications

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/notifications` | ✓ | Inbox, with unread count |
| POST | `/notifications/{id}/read` | ✓ | Mark one read |
| POST | `/notifications/read-all` | ✓ | Mark all read |
| GET | `/notifications/preferences` | ✓ | Explicit preferences only |
| PUT | `/notifications/preferences` | ✓ | Set one |
| GET | `/notifications/email-status` | — | Whether email would actually send |

Security notifications cannot be disabled; the attempt is refused with
`category_not_suppressible` rather than silently ignored. A user must always
learn about a new sign-in or a change to where their money is sent.

Each notification carries per-channel delivery outcomes, so a suppressed or
failed email is visible with its reason.

## Dashboards

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/dashboard/buyer` | ✓ |
| GET | `/dashboard/provider` | ✓ |
| GET | `/dashboard/admin` | admin |

Every figure is counted from real rows. `total_earned` is `null` until something
settles, never `0.00`.

## Health

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/health/live` | Process is up; touches no dependency |
| GET | `/health/ready` | Real round-trips to Postgres, Redis and the chain |

`/health/ready` returns 503 naming the failed component. The response includes
`required_components`, which excludes `chain`: an RPC outage degrades the
platform rather than taking it out of rotation.
