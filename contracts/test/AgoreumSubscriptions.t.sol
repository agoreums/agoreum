// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {Test} from "forge-std/Test.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";

import {AgoreumSubscriptions} from "../src/AgoreumSubscriptions.sol";
import {MockUSDC, FeeOnTransferToken} from "./mocks/Mocks.sol";

contract AgoreumSubscriptionsTest is Test {
    AgoreumSubscriptions internal subs;
    MockUSDC internal usdc;

    address internal admin = makeAddr("admin");
    address internal treasury = makeAddr("treasury");
    address internal alice = makeAddr("alice");
    address internal bob = makeAddr("bob");

    uint256 internal constant MONTHLY = 1;
    uint256 internal constant YEARLY = 2;
    uint256 internal constant MONTH_PRICE = 10e6; // 10 USDC
    uint256 internal constant YEAR_PRICE = 100e6;
    uint64 internal constant MONTH = 30 days;
    uint64 internal constant YEAR = 365 days;

    function setUp() public {
        usdc = new MockUSDC();
        subs = new AgoreumSubscriptions(admin, treasury);

        vm.startPrank(admin);
        subs.createPlan(MONTHLY, address(usdc), MONTH_PRICE, MONTH);
        subs.createPlan(YEARLY, address(usdc), YEAR_PRICE, YEAR);
        vm.stopPrank();

        usdc.mint(alice, 1_000e6);
        usdc.mint(bob, 1_000e6);
        vm.prank(alice);
        usdc.approve(address(subs), type(uint256).max);
        vm.prank(bob);
        usdc.approve(address(subs), type(uint256).max);
    }

    // ------------------------------------------------------------- Subscribe

    function test_subscribe_paysTreasuryAndActivates() public {
        vm.prank(alice);
        subs.subscribe(MONTHLY, MONTH_PRICE);

        assertEq(usdc.balanceOf(treasury), MONTH_PRICE, "treasury paid");
        assertEq(usdc.balanceOf(address(subs)), 0, "contract holds nothing");
        assertTrue(subs.isActive(alice, MONTHLY), "active");
        assertEq(subs.getSubscription(alice, MONTHLY).expiresAt, block.timestamp + MONTH);
        assertEq(subs.revenueRouted(address(usdc)), MONTH_PRICE);
    }

    function test_renew_beforeExpiry_stacksPeriods() public {
        vm.startPrank(alice);
        subs.subscribe(MONTHLY, MONTH_PRICE);
        uint64 firstExpiry = subs.getSubscription(alice, MONTHLY).expiresAt;
        subs.subscribe(MONTHLY, MONTH_PRICE); // renew immediately
        vm.stopPrank();

        assertEq(subs.getSubscription(alice, MONTHLY).expiresAt, firstExpiry + MONTH, "stacked");
        assertEq(usdc.balanceOf(treasury), MONTH_PRICE * 2);
    }

    function test_resubscribe_afterLapse_startsFresh() public {
        vm.prank(alice);
        subs.subscribe(MONTHLY, MONTH_PRICE);

        vm.warp(block.timestamp + MONTH + 10 days); // lapse
        assertFalse(subs.isActive(alice, MONTHLY));

        vm.prank(alice);
        subs.subscribe(MONTHLY, MONTH_PRICE);
        // Fresh run from now, not from the old expiry: no paying for the gap.
        assertEq(subs.getSubscription(alice, MONTHLY).expiresAt, block.timestamp + MONTH);
    }

    function test_subscribe_reverts_whenPriceExceedsMax() public {
        vm.prank(admin);
        subs.updatePlan(MONTHLY, MONTH_PRICE + 1, MONTH, true); // price bumped

        vm.prank(alice);
        vm.expectRevert(
            abi.encodeWithSelector(
                AgoreumSubscriptions.PriceExceedsMax.selector, MONTH_PRICE + 1, MONTH_PRICE
            )
        );
        subs.subscribe(MONTHLY, MONTH_PRICE);
    }

    function test_subscribe_reverts_onFeeOnTransferToken() public {
        FeeOnTransferToken fee = new FeeOnTransferToken(100); // 1% skim
        vm.prank(admin);
        subs.createPlan(99, address(fee), 50e6, MONTH);
        fee.mint(alice, 1_000e6);
        vm.prank(alice);
        fee.approve(address(subs), type(uint256).max);

        vm.prank(alice);
        vm.expectRevert(); // UnsupportedToken: treasury receives less than price
        subs.subscribe(99, 50e6);
    }

    function test_subscribe_reverts_whenPaused() public {
        vm.prank(admin);
        subs.pause();
        vm.prank(alice);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        subs.subscribe(MONTHLY, MONTH_PRICE);
    }

    function test_subscribe_reverts_onInactivePlan() public {
        vm.prank(admin);
        subs.updatePlan(MONTHLY, MONTH_PRICE, MONTH, false); // deactivate
        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(AgoreumSubscriptions.PlanInactive.selector, MONTHLY));
        subs.subscribe(MONTHLY, MONTH_PRICE);
    }

    function test_subscribe_reverts_onUnknownPlan() public {
        vm.prank(alice);
        vm.expectRevert(
            abi.encodeWithSelector(AgoreumSubscriptions.PlanNotFound.selector, uint256(404))
        );
        subs.subscribe(404, MONTH_PRICE);
    }

    // --------------------------------------------------------------- Cancel

    function test_cancel_recordsIntentWithoutRefund() public {
        vm.startPrank(alice);
        subs.subscribe(MONTHLY, MONTH_PRICE);
        subs.cancel(MONTHLY);
        vm.stopPrank();

        assertTrue(subs.getSubscription(alice, MONTHLY).autoRenewCancelled);
        // Still covered until expiry; nothing refunded.
        assertTrue(subs.isActive(alice, MONTHLY));
        assertEq(usdc.balanceOf(treasury), MONTH_PRICE);
    }

    function test_resubscribe_clearsCancellation() public {
        vm.startPrank(alice);
        subs.subscribe(MONTHLY, MONTH_PRICE);
        subs.cancel(MONTHLY);
        subs.subscribe(MONTHLY, MONTH_PRICE);
        vm.stopPrank();
        assertFalse(subs.getSubscription(alice, MONTHLY).autoRenewCancelled);
    }

    function test_cancel_reverts_whenNotSubscribed() public {
        vm.prank(alice);
        vm.expectRevert(
            abi.encodeWithSelector(AgoreumSubscriptions.NotSubscribed.selector, alice, MONTHLY)
        );
        subs.cancel(MONTHLY);
    }

    function test_cancel_reverts_whenAlreadyCancelled() public {
        vm.startPrank(alice);
        subs.subscribe(MONTHLY, MONTH_PRICE);
        subs.cancel(MONTHLY);
        vm.expectRevert(AgoreumSubscriptions.AlreadyCancelled.selector);
        subs.cancel(MONTHLY);
        vm.stopPrank();
    }

    // ------------------------------------------------------------ Governance

    function test_createPlan_validations() public {
        vm.startPrank(admin);
        vm.expectRevert(
            abi.encodeWithSelector(AgoreumSubscriptions.PlanAlreadyExists.selector, MONTHLY)
        );
        subs.createPlan(MONTHLY, address(usdc), MONTH_PRICE, MONTH);

        vm.expectRevert(AgoreumSubscriptions.InvalidAddress.selector);
        subs.createPlan(10, address(0), MONTH_PRICE, MONTH);

        vm.expectRevert(AgoreumSubscriptions.InvalidAmount.selector);
        subs.createPlan(11, address(usdc), 0, MONTH);

        vm.expectRevert(AgoreumSubscriptions.InvalidPeriod.selector);
        subs.createPlan(12, address(usdc), MONTH_PRICE, 1 hours); // below MIN_PERIOD

        vm.expectRevert(AgoreumSubscriptions.InvalidPeriod.selector);
        subs.createPlan(13, address(usdc), MONTH_PRICE, 800 days); // above MAX_PERIOD
        vm.stopPrank();
    }

    function test_onlyGovernor_canManage() public {
        bytes32 role = subs.GOVERNOR_ROLE();
        vm.startPrank(alice);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, alice, role
            )
        );
        subs.createPlan(20, address(usdc), MONTH_PRICE, MONTH);

        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, alice, role
            )
        );
        subs.setTreasury(alice);

        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, alice, role
            )
        );
        subs.pause();
        vm.stopPrank();
    }

    function test_setTreasury_routesFuturePayments() public {
        address newTreasury = makeAddr("newTreasury");
        vm.prank(admin);
        subs.setTreasury(newTreasury);

        vm.prank(alice);
        subs.subscribe(MONTHLY, MONTH_PRICE);
        assertEq(usdc.balanceOf(newTreasury), MONTH_PRICE);
        assertEq(usdc.balanceOf(treasury), 0);
    }

    function test_governanceCannotGrantSubscription() public {
        // There is no function by which a governor can move expiresAt. The only
        // path is subscribe, which requires payment. This asserts the surface:
        // governance functions are createPlan/updatePlan/setTreasury/pause only.
        assertFalse(subs.isActive(alice, MONTHLY));
        vm.prank(admin);
        subs.updatePlan(MONTHLY, 1, MONTH, true); // cheapest possible
        assertFalse(subs.isActive(alice, MONTHLY), "still inactive without payment");
    }

    function test_isActive_falseAfterExpiry() public {
        vm.prank(alice);
        subs.subscribe(MONTHLY, MONTH_PRICE);
        assertTrue(subs.isActive(alice, MONTHLY));
        vm.warp(block.timestamp + MONTH + 1);
        assertFalse(subs.isActive(alice, MONTHLY));
        assertEq(subs.timeRemaining(alice, MONTHLY), 0);
    }

    /// @notice The treasury cannot subscribe to its own plan.
    /// @dev `docs/incident-runbook.md` lists this as "one untested live-only
    ///      revert", which is an accurate description of a claim nobody had
    ///      checked. It is asserted here rather than described.
    ///
    ///      `subscribe` measures the treasury's balance delta and refuses
    ///      anything short of the full price, so a fee-on-transfer token cannot
    ///      buy a period. A self-transfer nets to zero, so the same guard fires
    ///      and the treasury cannot subscribe at all.
    ///
    ///      Moot on mainnet, where the treasury is a separated holding address,
    ///      and worth pinning anyway: the reason it reverts is a guard about
    ///      token behaviour, not about identity, so a future change to how the
    ///      payment is measured could silently turn this into a free
    ///      subscription rather than a revert.
    function test_theTreasuryCannotSubscribeToItsOwnPlan() public {
        usdc.mint(treasury, 1_000e6);
        vm.prank(treasury);
        usdc.approve(address(subs), type(uint256).max);

        vm.prank(treasury);
        vm.expectRevert(
            abi.encodeWithSelector(AgoreumSubscriptions.UnsupportedToken.selector, MONTH_PRICE, 0)
        );
        subs.subscribe(MONTHLY, MONTH_PRICE);

        // And it bought nothing: a revert that still left a subscription behind
        // would be the failure worth catching.
        assertFalse(subs.isActive(treasury, MONTHLY), "treasury gained a subscription");
    }
}
