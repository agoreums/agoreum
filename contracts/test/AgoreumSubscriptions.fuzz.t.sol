// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";

import {AgoreumSubscriptions} from "../src/AgoreumSubscriptions.sol";
import {MockUSDC} from "./mocks/Mocks.sol";

/// @notice Property tests over randomised prices, periods, and timings.
contract AgoreumSubscriptionsFuzzTest is Test {
    AgoreumSubscriptions internal subs;
    MockUSDC internal usdc;

    address internal admin = makeAddr("admin");
    address internal treasury = makeAddr("treasury");
    address internal alice = makeAddr("alice");

    function setUp() public {
        usdc = new MockUSDC();
        subs = new AgoreumSubscriptions(admin, treasury);
        usdc.mint(alice, type(uint128).max);
        vm.prank(alice);
        usdc.approve(address(subs), type(uint256).max);
    }

    function testFuzz_subscribeActivatesForExactlyOnePeriod(uint256 price, uint64 period) public {
        price = bound(price, 1, 1_000_000e6);
        period = uint64(bound(period, subs.MIN_PERIOD(), subs.MAX_PERIOD()));

        vm.prank(admin);
        subs.createPlan(1, address(usdc), price, period);

        uint256 tBefore = usdc.balanceOf(treasury);
        vm.prank(alice);
        subs.subscribe(1, price);

        assertEq(usdc.balanceOf(treasury) - tBefore, price, "treasury received price");
        assertEq(usdc.balanceOf(address(subs)), 0, "non-custodial");
        assertEq(subs.getSubscription(alice, 1).expiresAt, block.timestamp + period);
        assertTrue(subs.isActive(alice, 1));
    }

    function testFuzz_renewStacksExactly(uint64 period, uint8 renewals) public {
        period = uint64(bound(period, subs.MIN_PERIOD(), 60 days));
        uint256 n = bound(renewals, 1, 12);

        vm.prank(admin);
        subs.createPlan(1, address(usdc), 1e6, period);

        uint64 start = uint64(block.timestamp);
        for (uint256 i = 0; i < n; i++) {
            vm.prank(alice);
            subs.subscribe(1, 1e6);
        }
        // n back-to-back renewals buy exactly n periods from the start.
        assertEq(subs.getSubscription(alice, 1).expiresAt, start + period * uint64(n));
        assertEq(usdc.balanceOf(treasury), 1e6 * n);
    }

    function testFuzz_maxPriceAlwaysBinds(uint256 price, uint256 maxPrice) public {
        price = bound(price, 2, 1_000e6);
        maxPrice = bound(maxPrice, 0, price - 1); // strictly below price

        uint64 minPeriod = subs.MIN_PERIOD();
        vm.prank(admin);
        subs.createPlan(1, address(usdc), price, minPeriod);

        vm.prank(alice);
        vm.expectRevert(
            abi.encodeWithSelector(AgoreumSubscriptions.PriceExceedsMax.selector, price, maxPrice)
        );
        subs.subscribe(1, maxPrice);
        // Nothing moved.
        assertEq(usdc.balanceOf(treasury), 0);
        assertFalse(subs.isActive(alice, 1));
    }

    function testFuzz_lapseNeverChargesForTheGap(uint64 gap) public {
        gap = uint64(bound(gap, 1, 200 days));
        vm.prank(admin);
        subs.createPlan(1, address(usdc), 5e6, 30 days);

        vm.prank(alice);
        subs.subscribe(1, 5e6);
        vm.warp(block.timestamp + 30 days + gap); // lapse by `gap`

        vm.prank(alice);
        subs.subscribe(1, 5e6);
        // Fresh 30 days from now regardless of how long the lapse was.
        assertEq(subs.getSubscription(alice, 1).expiresAt, block.timestamp + 30 days);
    }
}
