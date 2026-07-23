"""Deploy AgoreumEscrow + a mock USDC to a local Anvil node and run a lifecycle.

Produces real EVM logs so the chain client, ABI decoder and indexer can be tested
against genuine chain output rather than hand-written fixtures. A mocked chain
would prove nothing about whether the platform can read the one it settles on.

Prerequisites:

    anvil --port 8545 --chain-id 31337

Then:

    python scripts/anvil_fixture.py

Writes ``apps/api/tests/anvil_fixture.json``, which the chain tests read. They
skip cleanly when it is absent, so the suite still runs without a local node.

The signing key below is Anvil's first well-known development account, published
in Foundry's own documentation. It controls nothing outside this local node and
is not a credential.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = REPO_ROOT / "contracts"
FIXTURE_OUT = REPO_ROOT / "apps" / "api" / "tests" / "anvil_fixture.json"

# Foundry is often already on PATH; FOUNDRY_BIN overrides for a local install.
FOUNDRY_BIN = os.environ.get("FOUNDRY_BIN", "")

RPC = os.environ.get("ANVIL_RPC", "http://127.0.0.1:8545")

# Anvil's first development account. Public, deterministic, worthless.
DEV_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
BUYER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
PROVIDER = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"

# A bytes32 escrow id in the same shape the backend derives from an order UUID.
ESCROW_ID = "0x000000000000000000000000000000000123456789abcdef0123456789abcdef"

AMOUNT_BASE_UNITS = "25500000"  # 25.50 USDC
FEE_BPS = "250"
DELIVERY_WINDOW = "86400"
AUTO_RELEASE_WINDOW = "86400"


def _tool(name: str) -> str:
    return str(Path(FOUNDRY_BIN) / f"{name}.exe") if FOUNDRY_BIN else name


def run(args: list[str], *, json_out: bool = False):
    env = dict(os.environ)
    if FOUNDRY_BIN:
        env["PATH"] = FOUNDRY_BIN + os.pathsep + env.get("PATH", "")

    result = subprocess.run(
        args, cwd=CONTRACTS, capture_output=True, text=True, env=env
    )
    if result.returncode != 0:
        print("COMMAND FAILED:", " ".join(args[:3]))
        print(result.stderr[-1500:])
        sys.exit(1)

    out = result.stdout.strip()
    if not json_out:
        return out

    # forge and cast prepend warnings and pretty-print JSON across lines, so
    # decode from the first brace rather than scanning line by line.
    start = out.find("{")
    if start == -1:
        print("no JSON in output:", out[-800:])
        sys.exit(1)
    return json.JSONDecoder().raw_decode(out[start:])[0]


def main() -> int:
    forge, cast = _tool("forge"), _tool("cast")

    print("=== deploying MockUSDC ===")
    usdc = run(
        [forge, "create", "test/mocks/Mocks.sol:MockUSDC", "--rpc-url", RPC,
         "--private-key", DEV_KEY, "--broadcast", "--json"],
        json_out=True,
    )["deployedTo"]
    print("USDC   =", usdc)

    print("=== deploying AgoreumEscrow ===")
    # admin = arbiter = feeRecipient = buyer, which is a local-fixture
    # simplification only. A real deployment separates these roles.
    escrow = run(
        [forge, "create", "src/AgoreumEscrow.sol:AgoreumEscrow", "--rpc-url", RPC,
         "--private-key", DEV_KEY, "--broadcast", "--json",
         "--constructor-args", BUYER, BUYER, BUYER, FEE_BPS],
        json_out=True,
    )["deployedTo"]
    print("ESCROW =", escrow)

    print("=== mint + approve ===")
    run([cast, "send", usdc, "mint(address,uint256)", BUYER, "1000000000",
         "--rpc-url", RPC, "--private-key", DEV_KEY])
    run([cast, "send", usdc, "approve(address,uint256)", escrow, "1000000000",
         "--rpc-url", RPC, "--private-key", DEV_KEY])

    print("=== createEscrow (25.50 USDC) ===")
    create = run(
        [cast, "send", escrow,
         "createEscrow(bytes32,address,address,uint256,uint64,uint64)",
         ESCROW_ID, PROVIDER, usdc, AMOUNT_BASE_UNITS,
         DELIVERY_WINDOW, AUTO_RELEASE_WINDOW,
         "--rpc-url", RPC, "--private-key", DEV_KEY, "--json"],
        json_out=True,
    )
    print("createTx  =", create["transactionHash"])

    print("=== release ===")
    release = run(
        [cast, "send", escrow, "release(bytes32)", ESCROW_ID,
         "--rpc-url", RPC, "--private-key", DEV_KEY, "--json"],
        json_out=True,
    )
    print("releaseTx =", release["transactionHash"])

    balance = run(
        [cast, "call", usdc, "balanceOf(address)(uint256)", PROVIDER, "--rpc-url", RPC]
    )
    print("provider balance =", balance, "(expect 24862500 = 25.50 less 2.5%)")

    FIXTURE_OUT.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_OUT.write_text(
        json.dumps(
            {
                "rpc": RPC,
                "usdc": usdc,
                "escrow": escrow,
                "escrowId": ESCROW_ID,
                "createTx": create["transactionHash"],
                "releaseTx": release["transactionHash"],
                "buyer": BUYER,
                "provider": PROVIDER,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("wrote", FIXTURE_OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
