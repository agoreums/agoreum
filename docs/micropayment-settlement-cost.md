# What a settlement actually costs on Base

Measured 2026-08-16 against a Base mainnet fork, to decide whether the proposed
payment-channel primitive is worth building at all.

The proposal was that an agent opens one bounded commitment and many small calls
settle against it, so that per-call on-chain cost stops dominating a $0.50 job.
That is a good instinct, and it rests on an empirical premise: **a channel is
only worth building if settling each call directly on chain genuinely cannot be
cheap enough.** Nobody had measured that. So it was measured before any design
work, and the measurement decides the outcome.

The harness is `contracts/test/MicropaymentGas.fork.t.sol`. It runs against real
USDC on a Base mainnet fork, prices ETH from Chainlink's feed on Base rather than
from a number typed into a test, and skips visibly rather than passing quietly
when no RPC is configured.

## The numbers

Base mainnet block 50039552. L2 base fee 0.005 gwei. ETH/USD 1878.80 from
Chainlink. Gas figures include the 21,000 intrinsic cost a standalone
transaction pays before executing an opcode.

| Operation | L2 gas | L1 data fee (wei) | Total cost |
|---|---|---|---|
| USDC transfer, repeat payee | 26,880 | 394,849,872 | **$0.000253** |
| USDC transfer, new payee | 66,577 | 394,849,872 | $0.000626 |
| `createEscrow` + fund | 215,421 | 446,193,780 | $0.002024 |
| `release` | 129,983 | 394,849,872 | $0.001221 |
| Escrow round trip | 345,404 | 841,043,652 | $0.003245 |

A new payee costs more than a repeat one because their balance slot moves from
zero to non-zero. That is the honest figure for a first-time counterparty and it
is still under a tenth of a cent.

## Is that a quiet moment?

One block is not a distribution, so the base fee was sampled across a year.

| Window | Median | p99 | Max |
|---|---|---|---|
| now, 1025 blocks | 0.00500 gwei | 0.00500 | 0.00500 |
| 1 day ago | 0.00500 | 0.00500 | 0.00501 |
| 7 days ago | 0.00500 | 0.00500 | 0.00504 |
| 30 days ago | 0.00500 | 0.00500 | 0.00500 |
| 90 days ago | 0.00500 | 0.00500 | 0.00500 |
| 180 days ago | 0.01267 | 0.01415 | 0.01422 |
| 365 days ago | 0.00037 | 0.00045 | 0.00045 |

Base has sat on a 0.005 gwei floor for at least 90 days. The worst congestion
anywhere in the sampled year is 0.0142 gwei, under 3x current. A hypothetical
100x spike, never observed, would still put a direct transfer at about 2.5 cents.

## A prior of mine that the measurement corrected

Going in, the stated expectation was that the L1 data-availability fee would
dominate on an OP-stack chain, and that a measurement capturing only `gasleft()`
would understate true cost badly, most of all for the small simple transactions a
channel is meant to optimise.

That is wrong at current prices. The L1 term is 394,849,872 wei against an L2
execution fee of 134,400,000,000 wei for a warm transfer: under 0.3% of the
total. Post-Ecotone blob data availability collapsed it. The instinct to measure
both was still correct, because the conclusion depended on it and the direction
of the error would have falsely justified building a channel.

## The result

**Direct on-chain settlement on Base is already cheap enough. The channel is not
justified, and should not be built.**

At the roughly $0.50 average agent transaction recorded in
[ecosystem-research.md](ecosystem-research.md), a direct USDC transfer is about
0.05% overhead. Even at a $0.01 call it is 2.5%, and it stays under a cent
through every congestion level Base has seen in a year. There is no cost problem
here for a channel to solve.

Building one anyway would add a new fund-moving primitive, a new custody surface,
a new dispute surface and a new class of adversarial behaviour, in exchange for
saving a quarter of a thousandth of a dollar. That is a bad trade, and the fact
that the idea was appealing is not a reason to route around the measurement.

## What the measurement did find

Escrow costs 13x a direct transfer, but the gap that matters is not the gas. It
is that escrow needs two transactions, a delivery window and dispute machinery.
For a $0.50 call the mismatch is the *shape* of the workflow, not its price, and
a channel would not have fixed that either.

If serving small-value calls becomes a priority, the cheaper and far safer answer
is a direct-settle path: settle on delivery in a single transfer, with no escrow
lifecycle, for amounts below a threshold where a dispute window is not rational
anyway. That reuses a primitive that already exists instead of introducing one.

Like every other settlement rail, it would not feed reputation. Reputation is
computed only from settled escrow orders, permanently, regardless of what else
gets built. That rule is what makes the structural advantage recorded in
[ecosystem-research.md](ecosystem-research.md) worth anything, and a cheap
high-frequency rail is precisely the thing that would otherwise make
manufacturing a score cheap.
