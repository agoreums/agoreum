# contracts, Agoreum Smart Contracts

Solidity 0.8.36 · Foundry · OpenZeppelin 5.1.0 · target: Base

## AgoreumEscrow

Holds ERC-20 payment for a single engagement between a buyer and a provider, and
releases it only under defined settlement conditions.

### Design rules, in order of importance

1. **The contract can never pay out more than it took in.** Every escrow tracks
   `amount`, `released` and `refunded`, and every function that moves money
   asserts `released + refunded <= amount` after the state write and before the
   transfer. This is the same invariant the database enforces, restated where it
   is actually authoritative.
2. **State is written before value moves.** Checks-effects-interactions
   throughout, plus a reentrancy guard. The guard is defence in depth, correct
   ordering already prevents reentrancy, because escrow balances warrant both.
3. **Money is never trapped.** Every funded escrow always has a terminal path
   available. If a provider never delivers, the buyer reclaims after the
   deadline without needing anyone's cooperation, including the platform's. If a
   buyer disappears, the provider is paid after the auto-release deadline by a
   permissionless call.
4. **The platform is not a custodian.** The operator can resolve disputes and set
   the fee for *future* escrows, but has no function that moves funds to itself
   beyond the fee frozen at creation, and cannot reprice an existing escrow. The
   fee is capped at 10% in immutable code.

Pausing blocks new escrows only. `release`, `refund` and `settleDispute` keep
working while paused, because a pause that could strand committed funds would be
a custody risk rather than a safety mechanism.

Fee-on-transfer and rebasing tokens are rejected at funding: the contract
measures what actually arrived and reverts if it differs from what was sent.
Supporting them silently would make the accounting invariant unprovable.

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

## Testing

```bash
forge test                 # full suite
forge test --no-match-path "test/*.invariant.t.sol"   # fast: skip invariants
forge coverage --ir-minimum
FOUNDRY_PROFILE=deep forge test   # 50k fuzz runs, 2k invariant runs
```

**67 tests**, covering 97.5% of lines and 100% of functions in the escrow.

Beyond the happy path, the suite specifically exercises the ways money is lost:

- **Reentrancy**, a hook-bearing token that calls back into `release`, `refund`,
  and cross-function (`refund` from inside `release`); a contract recipient that
  re-enters on receipt.
- **Double spend**, double release, double refund, double settlement,
  refund-after-release, release-after-refund, and the same settlement transaction
  submitted twice (a normal operational retry, which must be inert).
- **Arithmetic boundaries**, 1 base unit where the fee rounds to zero, amounts
  where the fee truncates, and `type(uint128).max`.
- **Token misbehaviour**, a token that silently returns `false` must revert the
  whole release rather than record a payout that never happened.
- **Authorisation**, fuzzed over arbitrary caller addresses.

### Property and invariant testing

7 property tests at 2,000 runs each (14,000 randomised cases) assert that
release never overpays, refunds are always whole, settlements never exceed the
deposit, and rounding always favours the provider over the platform.

6 stateful invariants run 512 sequences of 64 random calls each, **32,768 calls
per invariant**, asserting after every step that no escrow overpays, the
contract holds at least what it owes, value is conserved end to end, terminal
escrows strand nothing, and active escrows have paid nothing.

A `callSummary` invariant prints how much of the state space each run actually
reached, so the suite cannot pass vacuously without that being visible.

## Deployment

`script/DeployEscrow.s.sol` **refuses to deploy to Base mainnet.** That is a
compile-time guard, not a flag: mainnet deployment is an explicit human decision
to be taken after reviewing testnet results, and removing the guard is itself a
reviewable change.

```bash
forge script script/DeployEscrow.s.sol \
  --rpc-url base_sepolia --broadcast --verify
```

Required environment: `ESCROW_ADMIN_ADDRESS`, `ESCROW_ARBITER_ADDRESS`,
`ESCROW_FEE_RECIPIENT`, optionally `ESCROW_FEE_BPS` (default 250 = 2.5%).

The admin and arbiter are deliberately separate roles: whoever resolves disputes
should not also be able to change the fee or pause the contract.

## Status

Not yet deployed to any network. No audit has been performed.
