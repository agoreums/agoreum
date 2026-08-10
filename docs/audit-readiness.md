# Audit readiness

Written for an auditor rather than for us. It says what the system is, where the
money is, what is trusted, and what we already know is wrong. The intent is that
nobody spends billable hours rediscovering things we could have written down.

**Scope.** Two contracts, `contracts/src/AgoreumEscrow.sol` (444 lines) and
`contracts/src/AgoreumSubscriptions.sol` (278 lines). Solidity 0.8.36, OpenZeppelin
`AccessControl`, `Pausable`, `ReentrancyGuard`, `SafeERC20`. Settlement asset is
USDC on Base. Deployed on Base Sepolia only; nothing is on mainnet.

**Not in scope but worth knowing.** The API and web app are off-chain conveniences.
They never hold keys and never sign: every state-changing transaction is sent by a
user's own wallet. If you find an off-chain path that can move value, that is a
finding, because it should not exist.

## Start here

The four questions we would ask first, with our answers, so you can disprove them
rather than derive them:

1. **Can value leave an escrow other than to its own buyer, its own provider, or
   the fee recipient?** We believe no. Every payout is `_payOut` and the
   destination is read from the escrow struct or from `feeRecipient`.
2. **Can any privileged role take user funds?** We believe no. The admin can
   repoint the fee recipient and grant roles, the arbiter can divide a disputed
   escrow between its two parties, and neither can name itself as a destination
   for an escrow it is not party to.
3. **Can a subscription exist without a payment?** We believe no. `expiresAt`
   moves only in `subscribe`, which reverts unless the treasury balance actually
   increased by the full price.
4. **Can the accounting drift from the token balance?** We believe no.
   `_assertSolvent` is called before every escrow payout, and the subscription
   contract never holds a balance at all.

## Fund-moving paths

Every path by which a token moves, and what stands in front of it. This is the
table we would want if we were auditing.

### AgoreumEscrow

| Path | Who may call | Guards | Destination |
| --- | --- | --- | --- |
| `createEscrow` | anyone, as buyer | `whenNotPaused`, `nonReentrant`, id unused, provider and token non-zero, provider is not the buyer, windows within bounds, balance delta must equal `amount` | into the contract |
| `release` | the buyer, or anyone once `autoReleaseAt` has passed | `nonReentrant`, status must be `Funded`, effects written before any transfer, `_assertSolvent` | provider and fee recipient |
| `refund` | the provider at any time, or the buyer once the delivery deadline passed | `nonReentrant`, status must be `Funded`, effects before transfer, `_assertSolvent` | buyer only, no fee taken |
| `dispute` | buyer or provider | `whenNotPaused`, status must be `Funded` | nothing moves; the escrow freezes |
| `settleDispute` | `ARBITER_ROLE` | `nonReentrant`, status must be `Disputed`, `providerAmount + buyerAmount` bounded by `amount`, effects before transfers, `_assertSolvent` | that escrow's provider, that escrow's buyer, fee recipient |

Three properties of `settleDispute` that matter and are easy to miss:

- **The arbiter cannot pay itself.** Destinations come from the escrow struct.
  A compromised arbiter key misallocates one escrow between its two parties; it
  cannot drain the contract.
- **Only one number is really decided.** The contract computes
  `buyerTotal = amount - providerAmount` and uses its `buyerAmount` argument
  purely as a bounds check. Passing `(60, 30)` against a 100 escrow does **not**
  revert and pays the buyer 40. Our API derives the second figure rather than
  accepting it, so a recorded decision cannot differ from what is paid. We would
  welcome a view on whether the parameter should exist at all.
- **The fee falls on the provider's share alone.** A full refund carries no fee,
  so the platform earns nothing by deciding against a buyer.

### AgoreumSubscriptions

| Path | Who may call | Guards | Destination |
| --- | --- | --- | --- |
| `subscribe` | anyone | `whenNotPaused`, `nonReentrant`, plan exists and is active, `price <= maxPrice`, treasury balance must increase by exactly `price` | treasury, in one hop |
| `cancel` | the subscriber | must have a subscription, not already cancelled | nothing moves |
| `setTreasury` | `GOVERNOR_ROLE` | non-zero | changes future destinations only |

The contract never holds a balance. `contractHoldsNothing(token)` exposes that as
a checkable fact rather than a claim.

## Trust model

| Role | Held by | Can | Cannot |
| --- | --- | --- | --- |
| `DEFAULT_ADMIN_ROLE` | platform | grant and revoke every role, including granting itself `ARBITER_ROLE` | move funds directly |
| `GOVERNOR_ROLE` | platform | set fee bps up to `MAX_FEE_BPS`, repoint the fee recipient, pause new escrows, define subscription plans, repoint the treasury | touch an existing escrow's amounts or destinations |
| `ARBITER_ROLE` | platform | divide a **disputed** escrow between that escrow's own two parties | touch a non-disputed escrow, or send anywhere else |
| buyer | user | fund, release, refund after the delivery deadline, dispute | take the provider's share |
| provider | user | refund the buyer, dispute | release to itself |

**The platform is trusted for arbitration.** That is a real trust assumption and
is disclosed in `docs/security.md` next to the non-custody claim rather than
buried.

**Existing escrows are immune to governance.** `feeBps` is copied into each escrow
at creation, so a later fee change cannot alter an escrow already funded. Worth
verifying independently; it is the property most likely to be quietly broken by a
future change.

## Invariants

Stated as properties, with where each is enforced and where it is tested.

| Invariant | Enforced | Tested |
| --- | --- | --- |
| Contract token balance is at least the sum of unsettled escrow amounts | `_assertSolvent` before every payout | `AgoreumEscrow.invariant.t.sol` |
| An escrow's terminal state is final | status checks at the head of every mutator | `AgoreumEscrow.t.sol`, and the fuzz suite |
| `released + refunded <= amount` for every escrow | arithmetic in each payout path | invariant suite |
| Fee never exceeds `MAX_FEE_BPS` | `setFeeConfig` bound | `AgoreumEscrow.governance.t.sol` |
| The subscription contract holds no token balance | payment goes straight to the treasury | `AgoreumSubscriptions.invariant.t.sol` |
| Coverage moves forward only on payment | `subscribe` is the only writer of `expiresAt` | subscription invariant suite |

## Known limitations, stated rather than found

We would rather you spend the time elsewhere.

- **No timelock on governance.** `setFeeConfig`, `setTreasury` and role changes
  take effect immediately. There is no window in which to notice a hostile change.
  Monitoring alerts on all of them, which is detection rather than prevention.
- **Separation of duties is enforced at deploy time only.** `DEFAULT_ADMIN` can
  grant itself `ARBITER_ROLE` afterwards. On the current testnet deployment the
  admin, arbiter and fee recipient are in fact **the same address**, which is what
  that latitude looks like when used. Mainnet deployment is blocked on three
  distinct Safe multisigs.
- **Settlement is final.** No appeal, no reversal, no timelock.
- **A forwarding treasury breaks subscriptions.** `subscribe` measures the
  treasury's balance delta, so a treasury that immediately forwards tokens on
  receipt would show no gain and the payment would revert with
  `UnsupportedToken`. The treasury must be a plain holding address. The same
  mechanism means a subscriber who is also the treasury cannot subscribe, since a
  self-transfer nets to zero.
- **Fee-on-transfer and rebasing tokens are unsupported by construction**, in both
  contracts, by the same balance-delta check. This is deliberate.
- **`block.timestamp` is used for deadlines.** Windows are hours to days; a
  validator can move the clock by seconds.
- **Auto-release is permissionless once due.** Anyone may call `release` after
  `autoReleaseAt`. That is intended, so a provider is not dependent on the buyer
  showing up, but it is worth confirming the deadline cannot be brought forward.

## Security-relevant defects found and fixed during the build

Auditors ask for this history because the shape of past mistakes predicts where
the next ones are. Every item below was found by us, before any external review.

| Defect | Why it mattered | Fixed |
| --- | --- | --- |
| Arbiter could shorten the buyer's dispute window after an order was placed, by editing the service, because `auto_release_at` was computed from the live service at delivery time | Cut the window in which a buyer could dispute before escrow auto-released to the provider | Terms frozen on the order at purchase; `58ae8fb` |
| The same freeze applied in one of two code paths only | The fix was reported complete while the dangerous path was untouched | `58ae8fb` |
| Order terms were frozen for price but not for delivery and auto-release windows | Provider could move deadlines under an existing order | `13ca540` |
| Organization membership could be granted without the member's consent | Membership decides notification targeting and public association | Invitations; `d27581c` |
| Configured arbiter address held no on-chain role | The API would authorise a decision the chain would refuse | `eabdaaf` |
| Configured fee recipient was not the contract's fee recipient | Fee verification pointed at an address that never receives fees | `a902b3f` |
| Notification failure poisoned the caller's database session | A failed notification aborted the sign-in or indexer work that triggered it, producing a 503 for every returning account | Savepoint; `3942112` |
| Unauthenticated webhook could suppress any email address | Suppression is a denial-of-service primitive: silently stop somebody receiving security notices | Svix signature verification; `64cc12b` |
| Sign-in security notice echoed an attacker-controlled `User-Agent` as prose | Text chosen by an intruder appeared as our own words in the one message warning about that intruder | Quoted, truncated, disclaimed; `8e1b0ab` |
| Monitoring change never reached the running process | An added governance alert was committed, deployed and documented while the process ran older code; a real settlement passed unannounced | Bind-mount redeploy; `d92b97b` |

## Does the deployed code match this repository

Checked on 2026-08-10 rather than assumed, because it is the first thing worth
knowing and the easiest to take on trust.

| Contract | Base Sepolia address | Runtime bytecode vs a build of this repo |
| --- | --- | --- |
| `AgoreumEscrow` | `0x13c90ba1441bD02d55801Cb2F8bDA3515020A16D` | **byte-identical**, sha256 `6e954a979c23746c…` |
| `AgoreumSubscriptions` | `0x509D50f826067452447cB24449A34B497e010017` | **byte-identical** |

Reproduce it with `forge build`, then compare `deployedBytecode.object` from
`out/<name>.sol/<name>.json` against `eth_getCode` at the address above. There is
no metadata trailer to account for: `foundry.toml` sets `bytecode_hash = "none"`
and `cbor_metadata = false`, so the compared bytes are all executable code.

Two things an auditor should know before reading the explorer:

- **The escrow's verified source on Basescan is older than this repository.** It
  was verified at deployment, when the pragma was 0.8.28; the repo has since
  moved to 0.8.36 (`49588c6`) and gained natspec. The runtime bytecode is
  nevertheless identical, which is checkable above, so the difference is
  comments and a compiler bump that changed no codegen for this contract. Read
  the repository for the source and treat the explorer as confirmation of the
  address, not of the text.
- **`AgoreumSubscriptions` is not verified on the explorer at all.** Its source
  is in this repository and its bytecode matches, but nothing can be read from
  Basescan.

## How to run what we run

```bash
cd contracts
forge test                 # 138 pass, 6 skip without a fork URL
forge test --match-path 'test/*invariant*'
forge coverage
```

Fork tests skip unless a Base RPC URL is configured. `forge test --gas-report`
gives the gas profile we work against.
