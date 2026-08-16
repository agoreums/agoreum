# Ecosystem research, August 2026

Four parallel investigations run on 2026-08-16, at the start of the hardening and
expansion phase, to answer a question the repository cannot answer about itself:
what does a serious agent commerce platform on Base need that Agoreum does not
have.

Recorded here rather than acted on silently, because the findings change what
should be built and at least one of them raises a question that is the owner's
to answer rather than mine.

Every claim below carries a source in the original reports. Where the evidence is
a single study or a secondary source, that is said. Numbers from vendor marketing
are treated as marketing.

## The short version

The payment rails shipped. The economy did not.

Every layer Agoreum builds has now been shipped by somebody larger, and the total
economic activity across all of it is very small. The standards worth adopting
are mostly cheap. The one genuine structural advantage Agoreum holds is not the
marketplace, it is the evidence behind its reputation.

## What is actually adopted, and what only looks it

| Thing | Status | Read |
| --- | --- | --- |
| **MCP** | Genuinely adopted, by a wide margin | Tens of millions of monthly SDK downloads, shipped by OpenAI, Google, Microsoft, AWS, now under the Linux Foundation. This is where developer gravity is |
| **x402** | Real plumbing, unreal volume | Linux Foundation governance, 40 members including Visa, Stripe, Google, AWS. Independent analysis puts genuine daily commercial volume near $28,000, with roughly half of observed activity self-dealing or wash trading, and settlement volume down sharply over 2026 |
| **A2A** | Adopted in shape, not in use | v1.0 stable, 150+ organisations, but a survey of 22,341 hosts found 65 published agent cards and only 10 that pass validation. Providers publish the card as a discovery manifest and do not speak the protocol |
| **ERC-8004** | Registered, largely dead | 173,441 registrations; 3% to 15% expose a working endpoint. On Base, 15%, the best of the three chains studied |
| **Coinbase Spend Permissions** | Production, audited | Deployed on Base and Base Sepolia, three Spearbit audit rounds, on-chain per-period allowance enforcement with no arbitrary-call capability |
| **ERC-7715 / 7710** | Draft, moving | The primary RPC method was renamed. Not something to build a payment path on yet |
| **ERC-7702** | Live and dangerous | More than 97% of early mainnet delegations pointed at sweeper contracts. Agoreum must never prompt a user to sign one |

## The finding that matters most

Two independent investigations, arriving separately, landed on the same thing.

An empirical study of ERC-8004 across Ethereum, BSC and Base found that **98.7%
to 100% of reputation feedback records carry no proof of payment and no link to a
task**, that 59% to 91% of reviewers show coordinated behaviour, and that moving
an agent's score costs **$0.0027 on Base**.

Agoreum's reputation is computed only from orders that settled through escrow.
That constraint, which has been in place since before any of this was researched,
is a direct structural fix for the two failures that matter:

- **Groundedness.** Payment proof is a precondition rather than an attachment, so
  the figure that is at most 0.6% elsewhere is 100% here by construction.
- **Economic soundness.** The cost of manufacturing reputation moves from a
  fraction of a cent to the value of a real settled order, four to five orders of
  magnitude.

It does not fix everything, and saying so matters. **Commensurability** is
unsolved: settled orders give a defensible denominator, not a meaningful scale.
**Collusion** is unsolved: wash trading through escrow is possible and costs the
fee spread. And a separate study of 25 agents over 234 tasks found quality and
payment correlated at only **r=0.16** on harder tasks, which is the blunt version
of a point worth keeping: *settled does not mean good*. A reputation grounded
purely in settlement records faithfully that money changed hands and says nothing
about whether the work was worth it.

## The strategic question, which is the owner's

One investigation's recommendation was to stop building the venue and sell the
scorer: a settlement-grounded reputation oracle that other marketplaces consume,
rather than a marketplace competing with them for the same scarce buyers.

The argument for it is uncomfortable and evidence-backed:

- OKX shipped a near feature-for-feature match on 2026-06-30, non-custodial, with
  escrow, on-chain identity, unified reputation and a decentralised evaluator
  network, carrying exchange distribution.
- Virtuals Protocol shipped escrow with verification and an evaluation phase, and
  its protocol revenue fell 99.6%. It now pays a subsidy to attract sellers.
- Olas has genuine technical credibility, two audits, 11.1M agent-to-agent
  transactions, and **$89,000 of lifetime marketplace turnover**. A 2.5% fee on
  that is roughly $2,200, ever.
- Agent commerce transacts at roughly $0.50 average. Escrow costs two on-chain
  transactions and a dispute window, which is not rational below perhaps $10 to
  $100 an order. Above that, buyers want legal recourse and already have it.

The counterweight, stated as plainly: nobody is currently buying agent reputation
as a standalone product, so the demand for the oracle is *inferred from a
measured gap*, not observed. Swapping a product with no revenue for a product
with no customers is not obviously an improvement.

**This is not mine to decide.** It is recorded here with the evidence so it can
be decided rather than drifted into. What follows is chosen to be correct under
either answer.

## What is being built, and why it survives the question

Work selected because it is valuable whether Agoreum remains a venue or becomes
a scorer.

1. **A remote MCP server exposing the marketplace as tools.** One connector
   giving an agent the whole catalogue, rather than one integration per seller.
   This is where developers actually are, and it is also how any scorer would be
   consumed. Highest value per unit of work in the research.
2. **Signed settlement receipts on escrow release.** Makes a settled order
   independently verifiable by a third party. This is the venue's honesty
   feature and simultaneously the exact primitive the oracle strategy needs.
3. **A2A agent cards per published agent.** Near-free given the existing
   capability model, and conformance alone is differentiating when only ten
   publishers worldwide validate.
4. **The published OpenAPI contract**, shipped in this batch.

Deliberately deferred, with reasons: x402 on the escrow flow (architecturally
mismatched, since x402 is one synchronous round trip and escrow is asynchronous
with a dispute window), ERC-8004 reputation reads (importing a broken signal into
a working one), A2A protocol implementation (traffic that does not exist), AP2,
ACP, UCP, L402 and streaming payments.

## Two hard constraints this research adds

**The agent's own key must be the spender, never Agoreum.** If delegated spending
is ever built, a spend permission pays the spender. If Agoreum holds a spender
key on a user's behalf, the non-custodial claim is false regardless of intent.
This belongs in the code as an invariant with a test, not as a convention.

**Assume the agent is manipulated, not that the key is stolen.** Every
significant public agent-money loss in the last eighteen months came from an
agent being persuaded to authorise a legitimate-looking transaction, or from key
compromise. No public exploit of a session-key or spend-permission module was
found. The contracts are holding; the agents are not. Any limit Agoreum promises
must be enforced on chain, because that is the only layer that survives total
compromise of everything above it.

## A tool description is not a UI

One constraint that falls out of the MCP work and is worth stating separately.

Copy in a web interface is read by a person who can notice it is wrong. A tool
description is read by another agent, into its context, with no human in the
loop. Every payment-touching tool Agoreum exposes must state that settlement is
Base Sepolia testnet in the tool result itself, not only in documentation a human
might read. A misleading tool description is a fabrication delivered directly
into another system's reasoning, which is worse than a misleading page.
