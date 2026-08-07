# Solidity compiler bug warnings

Basescan shows a list of known compiler bugs on any contract verified with an
affected solc version. The list is attached to the **version**, not to the
contract: it is the contents of solc's own `bugs_by_version.json` for whichever
compiler the verification metadata names. Seeing it does not mean any of those
bugs reaches the code, and it will keep appearing on the currently deployed
contract for as long as that deployment exists.

This page records the analysis so it does not need repeating. It was prompted by
an external report to `support@agoreum.xyz` on 2026-08-07 naming the three bugs
below, which was a reasonable thing to report and worth answering properly.

## What is deployed

`AgoreumEscrow` at `0x13c90ba1441bD02d55801Cb2F8bDA3515020A16D`, verified on
**Base Sepolia**. Nothing is deployed or verified at that address on Base
mainnet.

Build settings, read from the verification metadata rather than from the current
repository config, because the repository has moved on since the deploy:

| Setting | Deployed value |
| --- | --- |
| compiler | `v0.8.28+commit.7893614a` |
| `viaIR` | **false** |
| optimizer | enabled, 10000 runs |
| evmVersion | cancun |

The repository is now on **0.8.36**, which solc's bug list records as having no
known bugs, and which is at or past the fix version for all three below. Any
redeploy from current HEAD is unaffected regardless of the analysis here.

## The three bugs, and why none of them apply

All three are exactly the set solc lists for 0.8.28, so their presence tells us
nothing beyond the version number.

### TransientStorageClearingHelperCollision (high)

Introduced 0.8.28, fixed 0.8.34. Conditions: **`viaIR: true` and
`evmVersion >= cancun`**.

Our evm version is cancun, so the second condition holds and this is the one
worth taking seriously. The first does not: the deployed contract was compiled
through the legacy evmasm pipeline, `viaIR: false`, confirmed in the verification
metadata above. The bug is in a Yul helper emitted only by the IR code generator,
which never ran.

Severity is about what happens when a bug applies, not how likely it is to apply.
High severity with an unmet condition is still not applicable.

### UnsoundSpillInMutualRecursion (medium)

Introduced 0.7.2, fixed 0.8.36. Condition: **`viaIR: true`**.

Same reason: the stack-too-deep evader that mishandles recursive call chains
exists only in the IR pipeline. It additionally requires mutually recursive
functions, and neither contract contains any recursion at all.

### LostStorageArrayWriteOnSlotOverflow (low)

Introduced 0.1.0, fixed 0.8.32. **No compiler-setting condition**, so it affects
both pipelines and cannot be dismissed on `viaIR` alone.

It requires a storage variable that extends past the last slot of storage and
wraps around to slot zero, which breaks the assumption that a container's last
slot has its highest address. In practice that needs an enormous fixed-size
storage array or a hand-placed storage layout.

Neither contract has a storage array of any kind. Full layouts, from
`forge inspect`, including inherited storage:

| Slot | `AgoreumEscrow` | `AgoreumSubscriptions` |
| --- | --- | --- |
| 0 | `_roles` mapping | `_roles` mapping |
| 1 | `_paused` bool | `_paused` bool |
| 2 | `_status` uint256 | `_status` uint256 |
| 3 | `_escrows` mapping | `_plans` mapping |
| 4 | `feeRecipient` address | `_subs` nested mapping |
| 5 | `feeBps` uint256 | `treasury` address |
| 6 | `feesCollected` mapping | `revenueRouted` mapping |

Seven slots each, all of them mappings or single values. There is no `delete`, no
`.push`, no `.pop`, no `assembly`, and no `sstore` anywhere in either source
file. Mappings are unaffected: they are addressed by hash rather than iterated
against absolute slot bounds, which is the thing this bug breaks.

## Conclusion

None of the three applies. No fix, no recompilation, and no redeploy is required
on their account.

If the contracts are redeployed for an unrelated reason they will build with
0.8.36 and the warnings will not appear on the new verification. That produces
different bytecode from what is deployed today, so the new address needs
verifying on Basescan afresh; it is not a byte-identical rebuild and should not
be described as one.

## Reproducing this check

```
curl -O https://raw.githubusercontent.com/ethereum/solidity/develop/docs/bugs_by_version.json
curl -O https://raw.githubusercontent.com/ethereum/solidity/develop/docs/bugs.json
forge inspect AgoreumEscrow storageLayout
```

The authoritative source for which bugs affect a version, and under which
conditions, is those two files in the solidity repository. Basescan is only
rendering them.
