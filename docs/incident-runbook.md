# Contract incident runbook

What to do when something goes wrong with the deployed contracts. Every claim
here is backed by a test that runs in CI, cited by name, rather than by
reasoning about the code. Where a scenario has no test, that is stated.

Both contracts are **non-upgradeable**. There is no proxy, no `delegatecall`, and
no `selfdestruct`. Remediation is therefore always some combination of pause,
repoint, redeploy, and wait. Nothing can be patched in place.

## First, the two things that are always true

**No one can drain principal.** Neither contract has a sweep, withdraw, or
migrate function. `settleDispute` splits only between that escrow's own buyer and
provider, and `_assertSolvent` reverts any path where `released + refunded`
exceeds `amount`. Asserted continuously by the `contractIsSolvent`,
`noEscrowEverOverpays` and `valueIsConserved` invariants, the last of which uses
independent ghost accounting so it cannot agree with a bug in the contract's own
bookkeeping.

**Pausing never strands funds.** `pause()` blocks `createEscrow` and `dispute`
only. `release`, `refund` and `settleDispute` all keep working while paused, so a
pause stops new exposure without trapping anyone who already committed money.
This is deliberate, and it is the single most useful property during an incident:
pausing is close to free.

## Scenario: a bug is found in a deployed contract

1. **Pause immediately.** `pause()` from `GOVERNOR_ROLE`. This stops new escrows
   and new disputes. It does not stop settlement of what already exists.
2. **Decide whether existing escrows can safely run to completion.** They always
   *can* terminate: every funded escrow reaches Released, Refunded or Settled,
   and the buyer can always `refund()` once the delivery deadline passes. Whether
   they *should* depends on the bug.
3. **Deploy a corrected contract.** New address, new deploy block.
4. **Repoint the application**, setting `ESCROW_CONTRACT_ADDRESS` and
   `ESCROW_DEPLOY_BLOCK` to the new deployment and restarting. Indexer cursors
   are keyed on chain id *and* contract address, so the indexer rescans from the
   new deploy block rather than inheriting the old contract's height. This is
   already handled; no manual cursor surgery is needed.
5. **Let the old contract drain.** In-flight escrows on the abandoned contract
   cannot be migrated. There is no mechanism to move them and none can be added.
   They must be left to reach a terminal state, which they always can.

The gap worth naming: between steps 3 and 5 there are two live contracts, and the
old one is still settling. Support needs to be able to answer questions about
both.

## Scenario: USDC blacklists a participant

Real USDC on Base is an upgradeable proxy with an issuer-controlled blacklist.
All four cases below are covered by `test/AgoreumEscrow.fork.t.sol`, which runs
against the live token on a mainnet fork rather than a mock.

| Who is blacklisted | Effect | Remedy |
| --- | --- | --- |
| **Provider** | `release()` reverts. No governance action helps, because the failing leg is the provider's. | Buyer calls `refund()` after the delivery deadline and recovers the full principal. Covered by `test_buyerStillRecoversFromABlacklistedProvider`. |
| **Fee recipient** | `release()` reverts for **every** escrow, including ones funded long before. | Governor calls `setFeeConfig` with a new recipient. Stuck escrows settle immediately afterwards. Covered by `test_realBlacklistOnFeeRecipientIsRecoverableByRepointing`. |
| **Buyer** | `createEscrow` reverts. | Nothing to do. It fails at the door and strands nothing. |
| **Everyone (global pause)** | All transfers halt, so no escrow can settle. | Wait. Do not attempt a migration. Funds are immobile, not lost, and settlement resumes when the pause lifts. Covered by `test_usdcGlobalPauseFreezesSettlementUntilLifted`. |

The fee recipient case is the one to watch, because a single blacklisting of a
treasury address blocks settlement platform-wide until someone repoints it. It is
also the easiest to fix. Monitor it.

## Scenario: a governance key is compromised

Assume the attacker holds `DEFAULT_ADMIN_ROLE` and `GOVERNOR_ROLE`.

**What they can do:**

- Raise the fee up to `MAX_FEE_BPS`, a hard-coded 1000 bps (10%) ceiling that
  nobody can exceed. Verified by `test_feeCannotBeRaisedAboveTheHardCeiling`.
- Redirect the fee stream, including on escrows that are already funded, because
  `feeRecipient` is read from live storage at payout time. The fee **rate** is
  frozen per escrow at creation, so already-funded work cannot be repriced:
  `test_raisingTheFeeDoesNotRepriceExistingEscrows`.
- Grant themselves `ARBITER_ROLE` and settle any escrow that a party has already
  disputed: `test_adminCanGrantItselfArbiterAfterDeployment`.
- Pause new escrows, denying service.

**What they cannot do:**

- Move principal to an arbitrary address. There is no such function.
- Raise a dispute themselves, so they cannot reach `settleDispute` on a healthy
  escrow unilaterally. One of the two parties must dispute first:
  `test_governorCannotDisputeOnBehalfOfAParty`.
- Exceed the 10% fee ceiling.

**Response:** if a second admin holder exists, revoke the compromised account's
roles immediately. If the compromised key is the *only* admin, the contract
cannot be recovered: deploy fresh and repoint. This is why admin should be a
multisig, and why the deploy script now refuses a mainnet deploy whose admin has
no code.

## Scenario: governance is lost entirely

Renouncing `DEFAULT_ADMIN_ROLE` without first granting it to a successor leaves
the contract permanently ungovernable. Nobody can pause, change the fee, or grant
any role, ever. Covered by
`test_renouncingAdminWithoutASuccessorIsIrreversible`.

Escrows still settle normally, which is the saving grace, but the contract can
never be paused again and the fee recipient can never be repointed, so a later
blacklist of that recipient would be unrecoverable.

**The handover order therefore matters: grant to the new admin, verify with
`hasRole`, and only then renounce.** Covered end to end by
`test_fullHandoverToMultisigLeavesTheOldAdminPowerless`.

## What is watched

`scripts/monitor.py` alerts on the escrow's governance events, so a hostile or
mistaken change is visible without waiting for somebody to complain:

| Event | Alert |
| --- | --- |
| `FeeConfigUpdated` | fee config changed |
| `TreasuryUpdated` | TREASURY REDIRECTED |
| `RoleGranted` | ROLE GRANTED |
| `RoleRevoked` | role revoked |
| `Paused` / `Unpaused` | contract paused, contract unpaused |
| `EscrowSettled` | DISPUTE SETTLED |

Every topic is the keccak of the declaration in `contracts/src`, precomputed so
the monitor keeps its standard-library-only promise. A wrong topic fails silently,
the alert simply never fires, which is worse than having no alert because it looks
like coverage; they are regenerated and checked against the source when an event
signature changes.

`EscrowSettled` alerts on every settlement rather than only an unexpected one.
Settlements are rare, each divides somebody's money by a decision, and one nobody
expected is the exact shape of a compromised arbiter key.

An earlier version of this page said under "what is not covered" that governance
events were unmonitored and that this should be fixed before mainnet. That has been
untrue since the monitor gained those topics. A runbook is read during an incident
by somebody deciding what to trust, so understating its own coverage is the wrong
kind of wrong.

## What is not covered

Stated plainly so nobody assumes otherwise:

- **No timelock.** Every governance action is immediate. There is no delay in
  which to notice and react to a hostile `setFeeConfig` or `setTreasury`.
- **Separation of duties is enforced at deploy time only.** `DEFAULT_ADMIN` can
  grant itself `ARBITER_ROLE` afterwards, so separation is an operational
  commitment the contract does not maintain for you.
- **The arbiter is a single key on testnet.** It cannot steal, since
  `settleDispute` pays only the escrow's own buyer and provider, but it decides
  how a disputed escrow is divided and there is no timelock and no appeal. Making
  it a multisig is a recorded mainnet blocker in `docs/contracts.md`.
- **The subscriptions contract has one untested live-only revert:** if `treasury`
  equals the subscriber, `subscribe()` reverts with `UnsupportedToken`, because
  the balance-delta guard sees no net change on a self-transfer. Moot with a
  separated treasury, which mainnet enforces, but worth knowing.
