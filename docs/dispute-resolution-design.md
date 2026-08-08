# Dispute resolution: proposed design

**Status: proposal, not built.** Written for a decision, because how a dispute is
decided and who decides it is a trust question rather than a technical one.

## What already exists

Worth separating from what is being proposed, because most of the machinery is
there and unused.

`AgoreumEscrow.settleDispute(escrowId, providerAmount, buyerAmount)` is
implemented, tested, and gated on `ARBITER_ROLE`. The escrow must be in `Disputed`.
The order table already carries `disputed_at`, `dispute_reason`,
`dispute_resolution` (`released_to_provider`, `refunded_to_buyer`, `split`),
`dispute_resolved_at`, and `dispute_resolved_by`. `POST /orders/{id}/dispute-intent`
records a reason.

What is missing is everything between raising a dispute and settling it.

## Three properties of the contract that shape the design

**The arbiter cannot steal.** `settleDispute` pays only the escrow's own `provider`
and `buyer` addresses, plus the fee recipient. There is no path by which an arbiter
sends funds to itself. A compromised arbiter key can misallocate between the two
parties to that order; it cannot drain the contract. That is a meaningfully smaller
blast radius than "the arbiter controls the money" and should be said plainly to
users rather than left implied.

**A full refund costs the buyer nothing.** The fee is `providerAmount * feeBps`, so
a dispute resolved entirely in the buyer's favour takes no platform fee at all. The
platform earns nothing from refusing a refund, which is the right incentive and
worth publishing.

**Only one number is actually decided.** The contract computes
`buyerTotal = amount - providerAmount` and uses the `buyerAmount` argument solely as
a bounds check. Passing `(60, 30)` against a 100 escrow does not revert and pays the
buyer 40, not 30. So the recorded decision and the on-chain effect can diverge
silently.

The proposal is therefore that the arbiter names **one** figure, the provider's
share, and the system derives the buyer's. Any request supplying an inconsistent
pair is refused rather than normalised, so a mistake is an error rather than a
quiet difference between what was decided and what happened.

## Who arbitrates

Today `ARBITER_ROLE` is a single address, `ESCROW_ARBITER_ADDRESS`, held by the
project. Three honest options:

1. **The project arbitrates, disclosed.** Simple, available now, and a trust
   assumption users are entitled to know about.
2. **An independent panel.** Better, and not credible before there is anyone
   independent to appoint.
3. **Automated defaults with human escalation.** Deadlines decide the easy cases,
   a person decides the rest.

**Recommendation: 1 now, structured so it can become 2 without changing the flow**,
plus the deadline-driven parts of 3 where they are unambiguous. The role is an
address, so moving it later to a Safe or to a third party is a role grant, not a
redesign.

Two conditions attached to that recommendation:

- The arbiter address should be a **Safe multisig**, not a single key, for the same
  reason the admin addresses are. That adds a third Safe to the two already on your
  list.
- `docs/security.md` and the public terms should state who arbitrates, in the same
  place they state that the platform is non-custodial. A disclosed trust assumption
  is a different thing from a discovered one.

## The process

Deliberately short. A dispute is money not moving for somebody who is usually owed
it, and a process that takes three weeks is a punishment regardless of its outcome.

1. **Raised.** A party raises the dispute from their own wallet, on chain, as
   today. The indexer sees `EscrowDisputed` and moves the order to `DISPUTED`.
2. **Statements, 5 days.** Both parties are invited to state their case. Each sees
   the other's statement as it arrives.
3. **Decision.** The arbiter records a provider share and written reasoning, both
   stored before anything is executed.
4. **Execution.** `settleDispute` is called with the recorded figure. The indexer
   confirms `EscrowSettled` and the order becomes terminal.
5. **Notification.** Both parties are told at each of steps 1, 2 (when the other
   side responds), 3, and 4.

If a party does not respond within the window, the decision is made on what is
available and the record says so. Silence should not stall somebody else's money
indefinitely.

## What informs a split

The proposal is that the arbiter sees exactly what both parties see, and nothing
else: the order's terms as frozen at purchase, its event timeline including
delivery submissions and timestamps, and the two statements.

**No file uploads in the first version.** Attachments mean storage, malware
scanning, and a channel for sending a stranger a file. Statements are text, and
parties can link to anything already public. This is a real limitation and should
be stated to users rather than discovered by them; if evidence turns out to be the
binding constraint in practice, that is the moment to build uploads properly.

## What each party sees

Symmetric, on purpose. A decision made on evidence one side never saw is not
defensible, whoever made it.

| Stage | Buyer | Provider |
| --- | --- | --- |
| Raised | who raised it, the reason, the response deadline | the same |
| Statements | both statements as they are submitted | the same |
| Decided | the split, the reasoning, who decided | the same |
| Settled | the transaction, and the amounts actually paid | the same |

The reasoning is shown to both parties, not kept internal. An arbiter who cannot
explain a split to the party who lost is an arbiter who should not have made it.

## Safeguards

- **The decision is recorded before it is executed**, so an on-chain settlement can
  always be compared against the reasoning that was supposed to produce it.
- **One figure, derived, never two typed**, per the contract behaviour above.
- **`EscrowSettled` should be alerted on**, alongside the governance events the
  monitor already watches. A settlement nobody expected is exactly the shape of a
  compromised arbiter key.
- **A dispute an arbiter is party to must be refused by the system**, not left to
  their judgement.

## What this does not solve

Stated so nobody assumes otherwise:

- The arbiter is the platform. Users trust a person to be fair. Everything above
  constrains and documents that trust; none of it removes it.
- There is no appeal. A settlement is final on chain and cannot be reversed.
- There is no timelock on `settleDispute`, so a compromised arbiter key acts
  immediately, bounded only by the fact that it can misallocate rather than steal.

## Open questions for the owner

1. Is the project arbitrating, disclosed, acceptable as the starting position?
2. Five days for statements, or a different window?
3. Should the arbiter's reasoning be public on the order, as proposed, or visible
   only to the two parties?
4. Should the arbiter address become a third Safe multisig before this goes live?
