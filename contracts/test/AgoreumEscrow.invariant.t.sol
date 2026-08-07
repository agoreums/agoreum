// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {StdInvariant} from "forge-std/StdInvariant.sol";
import {Test} from "forge-std/Test.sol";
import {console} from "forge-std/console.sol";

import {AgoreumEscrow} from "../src/AgoreumEscrow.sol";
import {MockUSDC} from "./mocks/Mocks.sol";

/// @notice Drives the escrow through random sequences of operations.
/// @dev The fuzzer calls these functions in arbitrary order with arbitrary
///      arguments. Calls that are not currently legal simply revert and are
///      skipped, so what survives is a realistic mix of valid and invalid
///      traffic, which is exactly the traffic a live contract sees.
contract EscrowHandler is Test {
    AgoreumEscrow public immutable escrow;
    MockUSDC public immutable usdc;
    address public immutable arbiter;

    bytes32[] public escrowIds;
    mapping(bytes32 => bool) public known;

    address[] public actors;

    // Ghost variables: an independent tally of what should have happened, kept
    // outside the contract so the invariant is not simply reading back the same
    // state it is trying to verify.
    uint256 public ghostTotalDeposited;
    uint256 public ghostTotalPaidOut;

    uint256 public createCalls;
    uint256 public releaseCalls;
    uint256 public refundCalls;
    uint256 public disputeCalls;
    uint256 public settleCalls;

    constructor(AgoreumEscrow escrow_, MockUSDC usdc_, address arbiter_) {
        escrow = escrow_;
        usdc = usdc_;
        arbiter = arbiter_;

        for (uint256 i = 0; i < 5; i++) {
            address actor = address(uint160(uint256(keccak256(abi.encode("actor", i)))));
            actors.push(actor);
            usdc.mint(actor, 1_000_000_000e6);
            vm.prank(actor);
            usdc.approve(address(escrow), type(uint256).max);
        }
    }

    function _actor(uint256 seed) internal view returns (address) {
        return actors[seed % actors.length];
    }

    function _existingId(uint256 seed) internal view returns (bytes32) {
        if (escrowIds.length == 0) return bytes32(0);
        return escrowIds[seed % escrowIds.length];
    }

    /// @dev Picks a caller for an escrow, weighted toward its real parties.
    ///      Purely random actors almost always fail the authorisation check, so
    ///      the fuzzer would rarely reach a terminal state and the invariants
    ///      would pass without ever exercising a payout. Roughly a quarter of
    ///      draws are still unrelated actors, keeping the unauthorised paths
    ///      under test.
    function _callerFor(bytes32 id, uint256 seed) internal view returns (address) {
        AgoreumEscrow.Escrow memory e = escrow.getEscrow(id);
        uint256 pick = seed % 4;
        if (pick == 0) return e.buyer;
        if (pick == 1) return e.provider;
        if (pick == 2) return seed % 2 == 0 ? e.buyer : e.provider;
        return _actor(seed);
    }

    function createEscrow(uint256 buyerSeed, uint256 providerSeed, uint256 amountSeed) external {
        address buyer = _actor(buyerSeed);
        address provider = _actor(providerSeed);
        if (buyer == provider) return;

        uint256 amount = bound(amountSeed, 1, 1_000_000e6);
        bytes32 id = keccak256(abi.encode(escrowIds.length, buyer, provider, amount));
        if (known[id]) return;

        vm.prank(buyer);
        try escrow.createEscrow(id, provider, address(usdc), amount, 1 days, 1 days) {
            escrowIds.push(id);
            known[id] = true;
            ghostTotalDeposited += amount;
            createCalls++;
        } catch {}
    }

    function release(uint256 idSeed, uint256 callerSeed) external {
        bytes32 id = _existingId(idSeed);
        if (id == bytes32(0)) return;

        uint256 before = _contractBalance();
        vm.prank(_callerFor(id, callerSeed));
        try escrow.release(id) {
            ghostTotalPaidOut += before - _contractBalance();
            releaseCalls++;
        } catch {}
    }

    function refund(uint256 idSeed, uint256 callerSeed) external {
        bytes32 id = _existingId(idSeed);
        if (id == bytes32(0)) return;

        uint256 before = _contractBalance();
        vm.prank(_callerFor(id, callerSeed));
        try escrow.refund(id) {
            ghostTotalPaidOut += before - _contractBalance();
            refundCalls++;
        } catch {}
    }

    function dispute(uint256 idSeed, uint256 callerSeed) external {
        bytes32 id = _existingId(idSeed);
        if (id == bytes32(0)) return;

        vm.prank(_callerFor(id, callerSeed));
        try escrow.dispute(id, "invariant") {
            disputeCalls++;
        } catch {}
    }

    function settleDispute(uint256 idSeed, uint256 providerSeed, uint256 buyerSeed) external {
        bytes32 id = _existingId(idSeed);
        if (id == bytes32(0)) return;

        AgoreumEscrow.Escrow memory e = escrow.getEscrow(id);
        uint256 providerShare = bound(providerSeed, 0, e.amount);
        uint256 buyerShare = bound(buyerSeed, 0, e.amount - providerShare);

        uint256 before = _contractBalance();
        vm.prank(arbiter);
        try escrow.settleDispute(id, providerShare, buyerShare) {
            ghostTotalPaidOut += before - _contractBalance();
            settleCalls++;
        } catch {}
    }

    /// @dev Time moving forward opens the unilateral paths, so the fuzzer must
    ///      be able to reach them.
    function warp(uint256 secondsSeed) external {
        vm.warp(block.timestamp + bound(secondsSeed, 1 hours, 30 days));
    }

    function escrowCount() external view returns (uint256) {
        return escrowIds.length;
    }

    function _contractBalance() internal view returns (uint256) {
        return usdc.balanceOf(address(escrow));
    }
}

/// @notice Invariants that must hold after every possible sequence of calls.
contract AgoreumEscrowInvariantTest is StdInvariant, Test {
    AgoreumEscrow internal escrow;
    MockUSDC internal usdc;
    EscrowHandler internal handler;

    address internal admin = makeAddr("admin");
    address internal arbiter = makeAddr("arbiter");
    address internal feeRecipient = makeAddr("feeRecipient");

    function setUp() public {
        escrow = new AgoreumEscrow(admin, arbiter, feeRecipient, 250);
        usdc = new MockUSDC();
        handler = new EscrowHandler(escrow, usdc, arbiter);

        // Only the handler drives the system, so every call is a plausible one.
        targetContract(address(handler));
    }

    /// @notice No escrow can ever have paid out more than it took in.
    /// @dev The contract's central promise, checked across every escrow after
    ///      every random sequence.
    function invariant_noEscrowEverOverpays() public view {
        uint256 count = handler.escrowCount();
        for (uint256 i = 0; i < count; i++) {
            bytes32 id = handler.escrowIds(i);
            AgoreumEscrow.Escrow memory e = escrow.getEscrow(id);
            assertLe(e.released + e.refunded, e.amount, "released + refunded exceeded the deposit");
        }
    }

    /// @notice The contract always holds at least what it still owes.
    /// @dev If this fails, some escrow is unpayable, the funds backing it are
    ///      already gone. This is the property that would catch a drain.
    function invariant_contractIsSolvent() public view {
        uint256 outstanding;
        uint256 count = handler.escrowCount();
        for (uint256 i = 0; i < count; i++) {
            bytes32 id = handler.escrowIds(i);
            AgoreumEscrow.Escrow memory e = escrow.getEscrow(id);
            outstanding += e.amount - e.released - e.refunded;
        }

        assertGe(usdc.balanceOf(address(escrow)), outstanding, "contract holds less than it owes");
    }

    /// @notice Deposits in equals payouts out plus what is still held.
    /// @dev Value is neither created nor destroyed by any sequence of calls.
    function invariant_valueIsConserved() public view {
        assertEq(
            handler.ghostTotalDeposited(),
            handler.ghostTotalPaidOut() + usdc.balanceOf(address(escrow)),
            "value was created or destroyed"
        );
    }

    /// @notice A terminal escrow holds nothing back.
    /// @dev Every completed engagement must have fully distributed its funds;
    ///      money must never be left stranded in a finished escrow.
    function invariant_terminalEscrowsAreFullyDistributed() public view {
        uint256 count = handler.escrowCount();
        for (uint256 i = 0; i < count; i++) {
            bytes32 id = handler.escrowIds(i);
            AgoreumEscrow.Escrow memory e = escrow.getEscrow(id);

            if (
                e.status == AgoreumEscrow.Status.Released
                    || e.status == AgoreumEscrow.Status.Refunded
                    || e.status == AgoreumEscrow.Status.Settled
            ) {
                assertEq(e.released + e.refunded, e.amount, "terminal escrow left funds stranded");
            }
        }
    }

    /// @notice A funded or disputed escrow has distributed nothing yet.
    function invariant_activeEscrowsHavePaidNothing() public view {
        uint256 count = handler.escrowCount();
        for (uint256 i = 0; i < count; i++) {
            bytes32 id = handler.escrowIds(i);
            AgoreumEscrow.Escrow memory e = escrow.getEscrow(id);

            if (
                e.status == AgoreumEscrow.Status.Funded || e.status == AgoreumEscrow.Status.Disputed
            ) {
                assertEq(e.released, 0, "active escrow already released funds");
                assertEq(e.refunded, 0, "active escrow already refunded funds");
            }
        }
    }

    /// @notice Reports how much of the state space the run actually explored.
    /// @dev An invariant suite that never reaches the interesting states passes
    ///      vacuously. This makes the coverage visible rather than assumed.
    function invariant_callSummary() public view {
        console.log("escrows created :", handler.createCalls());
        console.log("releases        :", handler.releaseCalls());
        console.log("refunds         :", handler.refundCalls());
        console.log("disputes        :", handler.disputeCalls());
        console.log("settlements     :", handler.settleCalls());
    }
}
