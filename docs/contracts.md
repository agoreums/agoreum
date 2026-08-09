# Smart Contracts

Solidity 0.8.36, built with Foundry on OpenZeppelin 5.1.0. Target network: Base.

> **Status: deployed to Base Sepolia testnet, verified, and proven end to end
> with real testnet USDC. Not on mainnet. No audit has been performed.**
>
> The testnet address and deploy block are in [deployment.md](deployment.md).
> Everything below is tested locally and exercised once on a live testnet. It has
> not handled real money.

## AgoreumEscrow

One contract. It holds ERC-20 payment for a single engagement between a buyer
and a provider, and releases it only under defined settlement conditions.

### Design rules, in priority order

**1. It can never pay out more than it took in.**

```solidity
function _assertSolvent(Escrow storage escrow) private view {
    assert(escrow.released + escrow.refunded <= escrow.amount);
}
```

Asserted on every path that moves money, after the state write and before the
transfer. An accounting bug therefore reverts rather than becoming a loss. This
is the same invariant [the database](database.md) enforces, restated where it is
actually authoritative.

**2. State is written before value moves.**

Checks-effects-interactions throughout, plus `ReentrancyGuard`. Correct ordering
alone already prevents reentrancy; the guard is defence in depth, because escrow
balances warrant both.

**3. Money is never trapped.**

Every funded escrow always has a terminal path available:

- If the provider never delivers, the buyer reclaims after the delivery
  deadline, without needing anyone's cooperation, including the platform's.
- If the buyer disappears, the provider is paid after the auto-release deadline
  by a **permissionless** call. Anyone can trigger it.

**4. The platform is not a custodian.**

The operator can resolve disputes and set the fee for *future* escrows. It has
no function that moves funds to itself beyond the fee frozen at creation, and
cannot reprice an escrow that already exists. `MAX_FEE_BPS` is 10% in immutable
code, so no operator, including a compromised one, can set a confiscatory
rate.

### Lifecycle

```text
                 createEscrow
                      │
                      ▼
                   Funded ──────── release ───────▶ Released
                    │  │            (buyer, or anyone
                    │  │             after auto-release)
                    │  │
                    │  └────────── refund ────────▶ Refunded
                    │               (provider, or buyer
                    │                after deadline)
                    ▼
                 Disputed ──── settleDispute ─────▶ Settled
                (either party)      (arbiter)
```

Raising a dispute closes the auto-release path. That is the point: an unresolved
disagreement must not resolve itself in the provider's favour purely through the
passage of time.

### Pausing

`pause()` blocks **new escrows only**. `release`, `refund` and `settleDispute`
keep working while paused.

A pause that could strand committed funds would be a custody risk, not a safety
mechanism. Once money is in the contract it must always be able to reach a
terminal state, whatever the platform's operational status.

### Unsupported tokens

Fee-on-transfer and rebasing tokens are rejected at funding:

```solidity
uint256 received = erc20.balanceOf(address(this)) - balanceBefore;
if (received != amount) revert UnsupportedToken(amount, received);
```

The contract measures what actually arrived rather than trusting the requested
figure. Supporting such tokens silently would make the accounting invariant
unprovable, the contract would promise more than it holds.

### Roles

| Role | Can | Should be |
| --- | --- | --- |
| `DEFAULT_ADMIN_ROLE` | Grant and revoke roles | Multisig |
| `GOVERNOR_ROLE` | Set fees, pause | Multisig |
| `ARBITER_ROLE` | Resolve disputes | Separate operational key |

The arbiter is deliberately separate. It is used frequently, so it is the most
exposed key; if it also held governance, compromising the dispute-handling key
would hand over the contract.

## Testing

**138 tests passing, 6 skipped.** The suites include fuzzing at 2000 runs,
invariants at 512 sequences of depth 64, and six fork tests against the real
USDC contract on Base rather than a mock. Those six are the skips: they need a
Base RPC URL configured, and are the only tests that do. Coverage percentages are not quoted here: they were
last measured at an earlier revision and are not re-measured on every change, so
a number in this file would be a claim nobody is checking.

The uncovered branches are defensive checks that the other invariants make
unreachable, they are kept because "unreachable" is a property of today's
code, not a guarantee about tomorrow's.

```bash
cd contracts
forge test                                          # everything
forge test --no-match-path "test/*.invariant.t.sol" # fast
forge coverage --ir-minimum
FOUNDRY_PROFILE=deep forge test                     # 50k fuzz, 2k invariant runs
```

The suite is built around the ways money is actually lost, not the happy path.

### Adversarial cases

- **Reentrancy**, a hook-bearing token that calls back into `release`, into
  `refund`, and *cross-function* (`refund` from inside `release`); plus a
  contract recipient that re-enters on receipt. Each test asserts the reentrancy
  actually fired, so it cannot pass by the vector never triggering.
- **Double spend**, double release, double refund, double settlement,
  refund-after-release, release-after-refund, and **the same settlement
  submitted twice** (a normal operational retry, which must be inert rather than
  paying twice).
- **Arithmetic boundaries**, 1 base unit where the fee rounds to zero, 399
  units where it truncates, and `type(uint128).max`.
- **Silent token failure**, a token returning `false` must revert the whole
  release, not record a payout that never happened.

### Property tests

7 properties × 2,000 runs = **14,000 randomised cases**, asserting that release
never overpays, refunds are always whole, settlements never exceed the deposit,
and rounding always favours the provider over the platform.

### Invariants

6 stateful invariants × 512 sequences × 64 calls = **32,768 calls per
invariant**, checked after every step:

| Invariant | Meaning |
| --- | --- |
| `noEscrowEverOverpays` | `released + refunded <= amount`, always |
| `contractIsSolvent` | The contract holds at least what it owes |
| `valueIsConserved` | Deposits in = payouts out + held |
| `terminalEscrowsAreFullyDistributed` | A finished escrow strands nothing |
| `activeEscrowsHavePaidNothing` | A live escrow has paid nothing out |
| `callSummary` | Reports which states the run reached |

`valueIsConserved` uses independent ghost accounting rather than reading back
the contract's own state, so it cannot agree with a bug.

`callSummary` exists because an invariant suite that never reaches a payout
passes vacuously. It exposed exactly that: the first handler almost never
reached terminal states because random callers failed authorisation, so caller
selection is now weighted toward the real parties while keeping ~25%
unauthorised traffic.

## Deployment

`script/DeployEscrow.s.sol` **refuses to deploy to Base mainnet** unless the
deploy is deliberately authorised:

```solidity
if (chainId == BASE_MAINNET) {
    if (!_mainnetDeploymentAllowed()) revert MainnetDeploymentNotAuthorized(chainId);
    // then: admin, arbiter and feeRecipient must be pairwise distinct
}
```

`_mainnetDeploymentAllowed()` reads `ALLOW_MAINNET_DEPLOY` from the environment.
This is an environment flag, not a compile-time guard. Earlier revisions of this
document claimed the latter and quoted an unconditional revert; that has been
untrue since the opt-in landed, and the difference is not cosmetic. It is the
difference between "a mainnet deploy requires a reviewed code change" and "a
mainnet deploy requires one variable typed at a prompt".

Both guards are tested, including that mainnet is refused by default and that
collapsed roles are rejected even when the opt-in is set.

### Mainnet blockers

Deliberate gates, not a wishlist. Every one is owner-held and none is satisfied by
code alone.

| Blocker | Why |
| --- | --- |
| `ESCROW_ADMIN_ADDRESS` is a Safe multisig | A single admin key can grant itself any role, including arbiter |
| `SUBSCRIPTIONS_ADMIN_ADDRESS` is a Safe multisig | Same, and it can redirect the treasury |
| `ESCROW_ARBITER_ADDRESS` is a Safe multisig | It decides how disputed escrow is split between two parties. A single key means one compromised key decides other people's money, and settlements are immediate with no timelock and no appeal |
| The fee recipient is a **different address** too | The deploy script enforces all three being pairwise distinct on mainnet, and does not on a test network. On the deployed testnet contract all three are the same address, which is how that latitude actually gets used |
| The arbiter and the admin are **different addresses** | Not theoretical. On the deployed testnet contract they are the same address: `hasRole(ARBITER_ROLE, ...)` returns true for the deployer, which also holds `DEFAULT_ADMIN_ROLE`, while the address named in configuration held no role at all. One key that can both grant itself roles and divide disputed escrow is the collapse the incident runbook warns about, and it happened by default rather than by decision. Found by running a dispute end to end and watching the fee land somewhere other than the configured address |
| A security audit has been performed | No third party has reviewed this code |

The arbiter blocker was added when dispute resolution was built. It is the same
gate as the other two roles and is not a lesser one: the admin keys can take a role
they should not have, and the arbiter key can move money that is already in
dispute.

```bash
cd contracts
forge script script/DeployEscrow.s.sol --rpc-url base_sepolia --broadcast --verify
```

Required environment: `ESCROW_ADMIN_ADDRESS`, `ESCROW_ARBITER_ADDRESS`,
`ESCROW_FEE_RECIPIENT`, `DEPLOYER_PRIVATE_KEY`, `BASESCAN_API_KEY`, optionally
`ESCROW_FEE_BPS` (default 250 = 2.5%).

The script verifies the deployed state matches what was intended rather than
assuming the constructor did what the arguments implied.

**After deploying, set `ESCROW_CONTRACT_ADDRESS` in the environment.** That is
the only wiring step: the address is configuration everywhere, and a test
asserts nothing hardcodes it.

### Before mainnet

- [ ] Testnet deployment with real transactions settling
- [ ] Three genuinely separate role addresses
- [ ] Admin and fee recipient behind a multisig
- [ ] An independent audit
- [ ] `MAX_FEE_BPS` and window bounds reviewed against real usage

## ABI

Generated for both the backend and frontend from one artefact:

```bash
forge build --root contracts
python scripts/sync_abi.py
```

Writes `packages/contracts/AgoreumEscrow.abi.json` (read by the backend at
runtime) and `apps/web/src/lib/escrow-abi.ts` (a typed subset). CI fails if they
have drifted, so a contract change cannot leave one side decoding a shape the
other no longer emits.

## Local testing against a real EVM

```bash
anvil --port 8545 --chain-id 31337
python scripts/anvil_fixture.py
```

Deploys the escrow and a mock USDC, then runs a full create → release cycle,
producing real logs for the chain client and indexer tests. They skip cleanly
when it is not running.

A mocked chain would prove nothing about whether the platform can read the one
it settles on.
