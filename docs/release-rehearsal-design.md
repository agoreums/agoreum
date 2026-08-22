# The release rehearsal: design

**Status: designed, not yet run.** Written before the exercise so the
predictions can be wrong in public, as with the dispute and refund rehearsals.

## A correction first

I said release had never run in production. That was wrong, and the chain says
so plainly: `EscrowReleased` has been emitted **five** times, four in July and
one on 2026-08-16, and every one of them was released by the buyer accepting the
work.

What has never run is the branch that matters:

```solidity
bool autoReleaseDue = block.timestamp >= escrow.autoReleaseAt;
if (msg.sender != escrow.buyer && !autoReleaseDue) revert NotAuthorized(msg.sender);
```

**After `autoReleaseAt`, anyone at all may release.** Not the buyer, not the
provider, not the platform. Anyone. That is the strongest untested claim left,
and it is deliberate: a provider must not depend on the buyer, or on us,
remaining available in order to be paid. Five releases, all by the buyer, prove
nothing about it.

## Why this branch is the one worth the trouble

Refund answers "the buyer cannot be robbed by a provider who vanishes". This
answers the mirror question: **can a provider be robbed by a buyer who vanishes,
or by us?**

If the permissionless path works, the answer is no, and it is no without
trusting anybody. If it does not, then every provider on this platform is
relying on the buyer's goodwill or ours, and the escrow is worth much less than
it claims.

## What runs

Two orders, funded together, both windows at the contract's `MIN_WINDOW` of one
hour so `autoReleaseAt` lands at roughly two hours after funding.

**Order L1, the provider claims.** After `autoReleaseAt`, the provider calls
`release`. This is the realistic case: a buyer who never accepted and never
disputed, and a provider who wants paying.

**Order L2, a stranger claims.** After `autoReleaseAt`, a wallet that is neither
buyer nor provider nor the platform calls `release`, from a fresh account funded
with nothing but gas. If this succeeds and the provider is paid, the
permissionless claim is real. Nothing else tests it.

L2 is the point of the exercise. L1 is the path a real provider would take.

## Predicted consequences, written in advance

### On chain

* `escrow.released` becomes the **whole** amount, not the provider's share.
* The provider receives `amount - fee`, and `feeRecipient` receives `fee`.
* **A fee is taken for the first time in any of these rehearsals.** 250 bps of
  1.025000 is 0.025625. `feesCollected` must increase by exactly that per order.
  Checked against `feesCollected`, not against balances: the fee recipient and
  the buyer are the same address on this deployment, so a balance comparison
  cannot distinguish a fee taken from a fee not taken. That lesson cost a real
  check in the refund rehearsal and is not being relearned.
* `EscrowReleased(escrowId, provider, providerAmount, feeAmount, releasedBy)`
  with `releasedBy` being the provider for L1 and the stranger for L2.
* `release` is not gated on `whenNotPaused`, exactly like `refund`. A pause must
  not strand a provider's earnings any more than a buyer's deposit.

### In the database

* `escrow.status` released, `released_at` set, `fee_amount` from the event.
* `order.status` completed, `completed_at` set.
* The constraint `released_at_matches_status` requires
  `(status = 'released') = (released_at IS NOT NULL)`. Both are set together, so
  it holds; named in advance because a dispute settlement crash-looped the
  indexer on a constraint nobody had thought about.

**One predicted defect**, the same shape as the two already found:

`escrow.released_amount = escrow.amount` takes the figure from the record rather
than from the event. The event carries `providerAmount` and `feeAmount`, whose
sum **is** the chain's gross, so an authoritative number is available and
ignored. Today the two agree and nothing is visibly wrong. If `amount` had ever
drifted, a release would carry the drift forward and `reconcile` would keep
reporting a divergence that nothing closed.

This is the third occurrence of one pattern: settlement wrote the net where the
chain held the gross, refund read the database instead of the event, and release
does the same. The fix belongs in all three or none.

### In reputation, and this one is different

Every rehearsal so far produced nothing positive: a refund credits no volume, a
dispute credits no completion. **A release does.** These orders will satisfy
`OrderStatus.COMPLETED`, `released_amount > 0`, and `arms_length`, because the
buyer and the provider share no organisation that the platform can see.

So unless they are excluded, this rehearsal **manufactures two completed orders
and 2.05 USDC of volume out of my own money moving between my own wallets.**
That is precisely the fake activity every standing rule forbids, and it would be
produced by the system working correctly rather than by any bug.

They will be excluded through the admin endpoint immediately after settling,
exactly as `AGO-TMMR2TWH` was, and the published figures checked afterwards
rather than assumed. Stated here, before running, so the obligation exists in
writing before the temptation does.

The dispute and the refund left marks that could not be removed and were left
alone. This one leaves a mark that **must** be removed, and the asymmetry is the
whole design: exclusion only ever subtracts.

### Receipts

The first release receipts. `settlement.status` released, `released_amount` the
whole escrow, `refunded_amount` zero, and `fee_amount` non-zero **for the first
time in any receipt ever issued.** Every receipt so far has carried a zero fee,
so the field has never been observed with a real value in it.

### Settlement options

Before `autoReleaseAt`, the provider should see `release` unavailable with the
moment it opens. After, available. That transition, on a real escrow, is the
endpoint's own claim about the permissionless window being tested against the
contract rather than against its docstring.

## What would make this a failure

* Reporting the fee as correct without reading `feesCollected` before and after.
* Letting the two completed orders stand in the published reputation because the
  number looks better with them.
* Concluding "auto-release works" from L1 alone. L1 is released by the provider,
  who is a party to the escrow; it says nothing about permissionlessness. Only
  L2 does.
