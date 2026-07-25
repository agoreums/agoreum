// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {StdInvariant} from "forge-std/StdInvariant.sol";
import {Test} from "forge-std/Test.sol";

import {AgoreumSubscriptions} from "../src/AgoreumSubscriptions.sol";
import {MockUSDC} from "./mocks/Mocks.sol";

/// @notice Drives the subscription contract through random sequences of calls.
/// @dev Illegal calls simply revert and are skipped, so the surviving traffic is
///      a realistic mix. The ghost tally is kept independently of the contract so
///      the invariants are not merely reading back the state they verify.
contract SubscriptionsHandler is Test {
    AgoreumSubscriptions public immutable subs;
    MockUSDC public immutable usdc;
    address public immutable treasury;
    address public immutable admin;

    uint256[] public planIds;
    address[] public actors;

    uint256 public ghostTotalPaid;

    constructor(AgoreumSubscriptions subs_, MockUSDC usdc_, address treasury_, address admin_) {
        subs = subs_;
        usdc = usdc_;
        treasury = treasury_;
        admin = admin_;

        // A few plans of varying price and period.
        for (uint256 i = 0; i < 3; i++) {
            uint256 id = i + 1;
            planIds.push(id);
            vm.prank(admin);
            subs.createPlan(id, address(usdc), (i + 1) * 5e6, uint64((i + 1) * 30 days));
        }

        for (uint256 i = 0; i < 5; i++) {
            address actor = address(uint160(uint256(keccak256(abi.encode("sub-actor", i)))));
            actors.push(actor);
            usdc.mint(actor, 1_000_000_000e6);
            vm.prank(actor);
            usdc.approve(address(subs), type(uint256).max);
        }
    }

    function _actor(uint256 seed) internal view returns (address) {
        return actors[seed % actors.length];
    }

    function _plan(uint256 seed) internal view returns (uint256) {
        return planIds[seed % planIds.length];
    }

    function subscribe(uint256 actorSeed, uint256 planSeed) external {
        address actor = _actor(actorSeed);
        uint256 planId = _plan(planSeed);
        uint256 price = subs.getPlan(planId).price;
        vm.prank(actor);
        try subs.subscribe(planId, type(uint256).max) {
            ghostTotalPaid += price;
        } catch {}
    }

    function cancel(uint256 actorSeed, uint256 planSeed) external {
        vm.prank(_actor(actorSeed));
        try subs.cancel(_plan(planSeed)) {} catch {}
    }

    function reprice(uint256 planSeed, uint256 price) external {
        price = bound(price, 1, 1_000e6);
        uint256 planId = _plan(planSeed);
        uint64 period = subs.getPlan(planId).period;
        vm.prank(admin);
        try subs.updatePlan(planId, price, period, true) {} catch {}
    }

    function warp(uint256 secondsForward) external {
        secondsForward = bound(secondsForward, 1, 40 days);
        vm.warp(block.timestamp + secondsForward);
    }
}

contract AgoreumSubscriptionsInvariantTest is StdInvariant, Test {
    AgoreumSubscriptions internal subs;
    MockUSDC internal usdc;
    SubscriptionsHandler internal handler;

    address internal admin = makeAddr("admin");
    address internal treasury = makeAddr("treasury");

    function setUp() public {
        usdc = new MockUSDC();
        subs = new AgoreumSubscriptions(admin, treasury);
        handler = new SubscriptionsHandler(subs, usdc, treasury, admin);
        targetContract(address(handler));
    }

    /// @notice The contract must never hold a single unit of the token. Every
    ///         payment passes straight to the treasury; if this ever fails, the
    ///         contract has become a custodian, which it must never be.
    function invariant_contractIsNonCustodial() public view {
        assertEq(usdc.balanceOf(address(subs)), 0, "contract holds funds");
        assertTrue(subs.contractHoldsNothing(address(usdc)));
    }

    /// @notice Everything paid reached the treasury, and the contract's own tally
    ///         of routed revenue agrees with both the treasury balance and the
    ///         independent ghost total.
    function invariant_allRevenueReachedTreasury() public view {
        assertEq(usdc.balanceOf(treasury), handler.ghostTotalPaid(), "treasury vs ghost");
        assertEq(subs.revenueRouted(address(usdc)), handler.ghostTotalPaid(), "routed vs ghost");
    }
}
