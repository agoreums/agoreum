"""Regenerate the shared contract ABI artefacts from the compiled output.

Run after any change to the contracts:

    forge build --root contracts
    python scripts/sync_abi.py

Writes two files from one source of truth:

* ``packages/contracts/AgoreumEscrow.abi.json`` — the full ABI, read by the
  backend at runtime.
* ``apps/web/src/lib/escrow-abi.ts`` — a typed subset for the frontend.

Keeping both generated means a contract change cannot leave one side of the
platform decoding a shape the other no longer emits.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = REPO_ROOT / "contracts" / "out" / "AgoreumEscrow.sol" / "AgoreumEscrow.json"
ABI_JSON = REPO_ROOT / "packages" / "contracts" / "AgoreumEscrow.abi.json"
ABI_TS = REPO_ROOT / "apps" / "web" / "src" / "lib" / "escrow-abi.ts"

# The entry points the interface actually calls. Every custom error is kept
# regardless, so a revert can be reported with its real reason.
FRONTEND_FUNCTIONS = {
    "createEscrow", "release", "refund", "dispute", "getEscrow", "statusOf",
    "outstanding", "autoReleaseAvailable", "refundAvailable", "feeBps",
}
FRONTEND_EVENTS = {
    "EscrowCreated", "EscrowReleased", "EscrowRefunded", "EscrowDisputed",
    "EscrowSettled",
}

TS_HEADER = """/**
 * AgoreumEscrow ABI.
 *
 * Generated from `packages/contracts/AgoreumEscrow.abi.json`, which is produced
 * by `forge build`. Backend and frontend consume the same artefact, so a
 * contract change cannot leave one side decoding a stale shape.
 *
 * Trimmed to the entry points the interface actually calls, plus every custom
 * error so a revert can be reported with its real reason rather than "failed".
 *
 * Do not edit by hand — run `python scripts/sync_abi.py`.
 */
const escrowAbi = """


def main() -> int:
    if not ARTIFACT.exists():
        print(f"No compiled artefact at {ARTIFACT}. Run `forge build` first.")
        return 1

    abi = json.loads(ARTIFACT.read_text(encoding="utf-8"))["abi"]

    ABI_JSON.parent.mkdir(parents=True, exist_ok=True)
    ABI_JSON.write_text(json.dumps(abi, indent=2) + "\n", encoding="utf-8")

    trimmed = [
        entry
        for entry in abi
        if (entry["type"] == "function" and entry.get("name") in FRONTEND_FUNCTIONS)
        or (entry["type"] == "event" and entry.get("name") in FRONTEND_EVENTS)
        or entry["type"] == "error"
    ]

    ABI_TS.parent.mkdir(parents=True, exist_ok=True)
    ABI_TS.write_text(
        TS_HEADER + json.dumps(trimmed, indent=2) + " as const;\n\nexport default escrowAbi;\n",
        encoding="utf-8",
    )

    print(f"{ABI_JSON.relative_to(REPO_ROOT)}: {len(abi)} entries")
    print(f"{ABI_TS.relative_to(REPO_ROOT)}: {len(trimmed)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
