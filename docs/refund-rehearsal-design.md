# The refund rehearsal

**Status: run 2026-08-22, both branches, against production on Base Sepolia.**
The design below was written first and is left exactly as it was, so the
predictions can be read against what happened. Results are at the end.

**Outcome: 36 of 36 predictions agree.** Both predicted defects were real, one
was found before a transaction was ever sent, and two of the checks were wrong
in ways worth keeping on the record.

The design was written before the exercise so the predictions could be wrong in
public. The dispute rehearsal proved the value of that: three of its four
findings were in code nobody had reason to doubt, and the write-up is what made
the difference between finding them and explaining them away.

Refund is the last money-moving path that has never executed in production. The
audit of never-exercised capabilities has said so since it was written, and the
indexer's own comment now says the refund event would have crash-looped the
indexer for exactly the reason a settlement did, because both were latent from
the day the line was written. That fix has never run against a real
`EscrowRefunded`.

## What the contract actually does

`refund(bytes32 escrowId)` returns the **entire** amount to the buyer and takes
no fee. There is no partial refund. Two callers are authorised, and they are
authorised for different reasons:

* **The provider, at any time.** Declining the work. No deadline applies.
* **The buyer, once `deliveryDeadline` has passed.** Reclaiming when nothing was
  delivered.

`refund` is deliberately not gated on `whenNotPaused`, unlike `createEscrow` and
`dispute`. A paused contract must still let people take their own money out.

There is no race between the buyer's refund window and the provider's
auto-release, which is worth stating because the shape of the code invites the
suspicion. `createEscrow` sets `autoReleaseAt = deliveryDeadline +
autoReleaseWindow`, so the provider's unilateral claim opens strictly after the
buyer's unilateral reclaim, never at the same instant. Checked rather than
assumed.

## The two branches, and why both get run

One order per branch, because they are different authorisation paths in the
contract even though they emit the same event.

**Order R1, the provider declines.** Funded, then `refund` called from the
provider wallet before any deadline. Available immediately.

**Order R2, the buyer reclaims.** A service with a one hour delivery window,
which is the contract's `MIN_WINDOW`. After the deadline the buyer calls
`refund` and the money comes back without the provider's cooperation or the
platform's.

R2 is the one that matters. It is the guarantee that makes escrow worth using at
all: a provider who disappears cannot keep the money. Everything else the
platform says about trust rests on that being true in practice and not only in
Solidity.

## Predicted consequences, written in advance

### On chain

* `escrow.refunded` equals the full amount, status becomes `Refunded`.
* `_assertSolvent` holds trivially, `0 + amount <= amount`.
* **No fee.** `feesCollected` must not move and the fee recipient's balance must
  not change. Checked explicitly, because "no fee is taken on a refund" is a
  published claim about the platform's incentives and has never been observed.
* The buyer's USDC balance returns to its pre-funding value, less gas.
* `EscrowRefunded(escrowId, buyer, amount, refundedBy)` with `refundedBy` being
  the provider for R1 and the buyer for R2.

### In the database

* A `chain_transactions` row of type `escrow_refund` carrying the full amount.
* `escrow.status` refunded, `refunded_amount` equal to the amount, `refunded_at`
  set, `released_amount` still zero, `fee_amount` still zero.
* `order.status` refunded and `order.cancelled_at` set.
* Three check constraints are in the path and all three should hold:
  `payouts_cannot_exceed_deposit`, `released_at_matches_status`, and
  `funded_states_require_funded_at`. The dispute rehearsal crash-looped the
  indexer on a constraint nobody had thought about, so these are named in
  advance rather than checked afterwards.

**Two predicted defects.** Stated now so that finding them is a confirmation and
not finding them is a correction:

1. **The ledger row will say the buyer paid themselves.** `from_address` is
   `event.args.get("buyer") or ...` and `to_address` is `_recipient`, which for
   a refund falls through to the same `buyer`, because the event names no
   provider. Both ends of the transfer will be the buyer's address. Nothing
   reads these columns today, which is precisely why it has survived.
2. **`refunded_amount` is written from the database's own `amount`, not from the
   event's.** The event carries the authoritative figure and the handler ignores
   it. This is the same shape as the settlement defect: the chain states a number
   and the code writes a different one it happens to believe. Today the two agree,
   so nothing is visibly wrong, and if `amount` ever diverged a refund would
   silently copy the divergence forward instead of correcting it.

### In reputation, which is where the real consequence is

* `completed_orders` does not move. It requires `COMPLETED` and
  `released_amount > 0`, and a refund has neither.
* `total_volume` does not move. It sums `released_amount`, which is zero.
* `disputed_orders` and `disputes_lost` do not move. Nothing was disputed.
* **`cancelled_orders` increases by one per refund**, because the query counts
  `status IN (cancelled, refunded)`.

**And that cannot be excluded away.** The exclusion flag is applied only through
`counts_toward_reputation`, which is applied only to the figures that could
flatter an agent. `cancelled_orders` is deliberately outside it. So the rehearsal
will leave two cancellations on the rehearsal agent's permanent record, and no
operator action can remove them.

That is the correct outcome and it is not going to be worked around. Two orders
really did end with the money going back, and an operator who could delete that
would have exactly the power the one-directional exclusion exists to deny. The
settled order and the dispute could have their positive contribution removed
because a positive from self-dealing is a lie. A refund is not a positive, so
there is nothing to remove, and the honest record is the one that keeps it.

Stating it in advance because it is the part that will be tempting to undo once
it is visible.

* No published score changes either way. `compute_score` returns `None` below
  three completed orders, and this agent has none.

### Receipts

A refunded escrow **is** a settled escrow for receipt purposes: `REFUNDED` is in
`SETTLED_ESCROW_STATUSES`. So a refund produces a signed receipt attesting that
the money went back, which is a genuinely useful document for a buyer and has
never once been generated.

Predicted payload: `settlement.status` refunded, `released_amount` "0.000000",
`refunded_amount` the full figure, `fee_amount` "0.000000", and
`transaction_hash` pointing at the refund transaction rather than the funding
one. The public verification page must accept it, and the signature must verify
in the browser against bytes produced by the API. Both are checked against the
deployed site, not locally.

### Notifications

`order.refunded.buyer` and `order.refunded.provider` fire to both sides. All nine
locales carry both keys, checked. This is the first time either has been sent.

### Analytics

`refunded_orders` and `refunded_value` move for the first time.

## The finding that came out of designing this, before running anything

**Neither refund branch is reachable from the product.**

The web application makes exactly two kinds of on-chain write: `approve` plus
`createEscrow` to fund an order, and `subscribe`. There is no release button, no
refund button, and no dispute button. The API tells a buyer precisely how to put
money in, with contract address, selector, calldata, amounts and deadline, and
offers nothing at all for taking it out. `payment_instructions` exists;
there is no equivalent for `release`, `refund`, or `dispute`.

So a real buyer whose provider vanished has a contract that protects them and a
product that does not tell them so. Recovering their money means finding the
contract address, reading the ABI, and building the transaction themselves. Most
people cannot, and the ones who can should not have to.

The rehearsal has to construct both transactions by hand. That difficulty is not
an inconvenience in the exercise. It **is** the finding, and it is the strongest
argument for running these rehearsals at all: reading the Solidity tells you the
buyer is protected, and only trying to use the protection tells you they cannot
reach it.

Fixing that is a separate piece of work and it is the obvious next one. This
document records it at the point it was found rather than after.

## What would make this rehearsal a failure

Not "a defect was found". Defects are the expected yield. The failure modes are:

* Running it and reporting a pass without checking the fee recipient balance, the
  receipt signature against the deployed page, and reconcile after the fact.
  Every one of those has caught something before.
* Quietly removing the two cancellations afterwards because the record looks
  worse with them.
* Concluding "the refund path works" when what was proven is "the refund path
  works when driven by someone who can write web3 code".

## What happened

Two orders, both on Base Sepolia against production, 2026-08-22.

| | Order | Refunded by | Result |
|---|---|---|---|
| R1 | `AGO-RPBSNQXC` | the provider, declining | full amount returned, no fee |
| R2 | `AGO-XNE2SADX` | the buyer, after the deadline | full amount returned, no fee |

Every prediction above was checked, 36 in total, and all 36 agree. The indexer
took both events without incident, which is the first time the `_recipient` fix
has run against a real `EscrowRefunded` rather than against a test.

### The guarantee that matters actually holds

R2 is the one worth stating plainly. A buyer funded an escrow, the provider
delivered nothing, the delivery deadline passed, and the buyer took the whole
amount back **without the provider's cooperation and without the platform's**.
No fee was taken. `reconcile` reports the database and the chain in agreement.

That is the claim the whole product rests on, and until this it had never been
true of anything except a test.

The contract's guard was exercised in both directions, one of them by accident.
An earlier attempt called `refund` before the deadline, because a stale RPC read
returned a deadline of zero and the script believed it. The contract refused it
with `DeadlineNotReached(1787364250, 1787360664)`. An unplanned mutation test of
the exact guard the branch depends on, run against production, and it held.

### The no fee claim, and the check that would have proved nothing

"No fee is taken on a refund" is published, because it says the platform earns
nothing from refusing a buyer their money back. The obvious check is whether the
fee recipient's balance moved.

**That check was worthless here and would have passed regardless.** On this
deployment the fee recipient is the same address as the buyer, so a fee taken on
a refund and a refund paid in full are indistinguishable by that balance: the
money lands in the same wallet either way.

`feesCollected(token)` is an independent accumulator that the refund path never
touches, so it can actually be wrong. It read 453750 before and after both
refunds. That is evidence; the balance comparison was not.

Worth keeping as a general shape. A check that cannot fail is not a weak check,
it is a false one, and it is most tempting exactly where the configuration
happens to make two things equal.

### Both predicted defects were real

**The ledger row named the buyer at both ends.** Confirmed against the ABI's
real event shapes and fixed. A refund now records the provider returning money
to the buyer, which is the direction that gives the row its meaning. It is not
observable through any endpoint, because neither address is exposed, which is
exactly why it survived from the day the line was written.

**The refunded figure came from the database rather than the chain.** Fixed to
read the event, and to correct `escrow.amount` when the two disagree rather than
writing a refund that would breach `payouts_cannot_exceed_deposit` and crash-loop
the indexer, which is how the first settled dispute took chain projection down.

Both fixes are mutation tested: reverting either one, and reverting the
correction separately, fails the suite.

### The receipt

The first refund receipts ever issued. Both are signed, both say `refunded` with
`released_amount` zero and `fee_amount` zero, and both point at the refund
transaction rather than the funding one.

Verified as a stranger would: fetched the published key from
`/.well-known/agoreum-receipts.json`, rebuilt the canonical bytes, and checked
the signature. It verifies. A copy with the refunded amount altered to 999 is
rejected, which is what makes the first result mean anything.

### Two checks of mine that were wrong

Recorded because a verification script that is wrong is worse than none.

**A check compared two fields that do not exist and reported CONFIRMED.**
`from_address` and `to_address` are not exposed by the transaction schema, so
both read as absent, the comparison found them equal, and the script announced
that the predicted defect was confirmed. It was agreeing with itself. The
prediction was true, and that run was not what established it.

**A check called the receipt endpoint with no credentials** and read the 401 as
"a refunded order has no receipt". The endpoint is deliberately scoped to a
party of the order. The check was wrong, not the product.

Both are the same failure the sweep exists to find, committed inside the
instrument built to find it.

### One thing that could not be checked from here

`order.cancelled_at` was predicted to be set on a refund. The order schema does
not expose it, so the API returns nothing for it either way and asserting on it
would test the schema rather than the indexer. Separately: the column is written
by the indexer and read by nothing at all, along with `cancellation_reason`.

### What it cost and what it bought

Two test orders, 2.05 USDC returned in full, two real defects in a path that had
never executed, and one confirmed guarantee that the product's whole trust
argument depends on. Plus the product gap below, which was worth the exercise on
its own and was found before any money moved.

The two refunds count permanently against the rehearsal agent as cancellations,
exactly as the design said they would, and they have not been removed.
