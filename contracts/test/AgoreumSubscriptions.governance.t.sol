// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {Test} from "forge-std/Test.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";

import {AgoreumSubscriptions} from "../src/AgoreumSubscriptions.sol";
import {BlacklistingToken, MockUSDC} from "./mocks/Mocks.sol";

/// @notice What governance can and cannot do to subscriptions.
///
/// @dev The counterpart of AgoreumEscrow.governance.t.sol, which existed while
///      this contract had no governance suite at all. The valuable assertions are
///      the refusals and the blast radius: what a governor can reach, what it
///      cannot, and what a subscriber keeps hold of regardless.
contract AgoreumSubscriptionsGovernanceTest is Test {
    AgoreumSubscriptions internal subs;
    MockUSDC internal usdc;

    address internal admin = makeAddr("admin");
    address internal treasury = makeAddr("treasury");
    address internal outsider = makeAddr("outsider");
    address internal subscriber = makeAddr("subscriber");

    bytes32 internal governorRole;
    bytes32 internal adminRole;

    uint256 internal constant PLAN = 1;
    uint256 internal constant PRICE = 10e6;
    uint64 internal constant PERIOD = 30 days;

    function setUp() public {
        usdc = new MockUSDC();
        subs = new AgoreumSubscriptions(admin, treasury);

        // Cached in setUp: reading them through the contract inside a test would
        // consume a pending vm.prank and run the call as the wrong caller, which
        // has silently mis-authorised tests in this repo before.
        governorRole = subs.GOVERNOR_ROLE();
        adminRole = subs.DEFAULT_ADMIN_ROLE();

        vm.prank(admin);
        subs.createPlan(PLAN, address(usdc), PRICE, PERIOD);

        usdc.mint(subscriber, 1_000e6);
        vm.prank(subscriber);
        usdc.approve(address(subs), type(uint256).max);
    }

    // ------------------------------------------------------------ Who may act

    function test_anOutsiderCannotDefineOrChangePlans() public {
        vm.startPrank(outsider);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, outsider, governorRole
            )
        );
        subs.createPlan(99, address(usdc), PRICE, PERIOD);

        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, outsider, governorRole
            )
        );
        subs.updatePlan(PLAN, PRICE, PERIOD, false);
        vm.stopPrank();
    }

    function test_anOutsiderCannotRepointTheTreasury() public {
        vm.prank(outsider);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, outsider, governorRole
            )
        );
        subs.setTreasury(outsider);
    }

    function test_anOutsiderCannotPause() public {
        vm.prank(outsider);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, outsider, governorRole
            )
        );
        subs.pause();
    }

    function test_handoverToAMultisigLeavesTheOldAdminPowerless() public {
        address multisig = makeAddr("multisig");

        vm.startPrank(admin);
        subs.grantRole(adminRole, multisig);
        subs.grantRole(governorRole, multisig);
        subs.renounceRole(governorRole, admin);
        subs.renounceRole(adminRole, admin);
        vm.stopPrank();

        assertFalse(subs.hasRole(governorRole, admin), "old admin kept governor");
        assertFalse(subs.hasRole(adminRole, admin), "old admin kept admin");

        vm.prank(admin);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, admin, governorRole
            )
        );
        subs.setTreasury(outsider);

        vm.prank(multisig);
        subs.setTreasury(multisig);
        assertEq(subs.treasury(), multisig, "successor cannot govern");
    }

    // ------------------------------------------- What governance cannot reach

    function test_governanceCannotGrantCoverageWithoutPayment() public {
        // There is no function that writes expiresAt other than subscribe. This
        // asserts the property by exhausting what a governor can do and showing
        // the subscriber is still uncovered.
        vm.startPrank(admin);
        subs.updatePlan(PLAN, 1, PERIOD, true);
        subs.setTreasury(admin);
        vm.stopPrank();

        assertFalse(subs.isActive(subscriber, PLAN), "coverage appeared without payment");
        assertEq(subs.getSubscription(subscriber, PLAN).expiresAt, 0);
    }

    function test_repricingDoesNotShortenCoverageAlreadyPaidFor() public {
        vm.prank(subscriber);
        subs.subscribe(PLAN, PRICE);
        uint64 boughtUntil = subs.getSubscription(subscriber, PLAN).expiresAt;

        vm.prank(admin);
        subs.updatePlan(PLAN, PRICE * 100, uint64(1 days), true);

        assertEq(
            subs.getSubscription(subscriber, PLAN).expiresAt,
            boughtUntil,
            "an existing subscription was repriced or shortened"
        );
        assertTrue(subs.isActive(subscriber, PLAN));
    }

    function test_deactivatingAPlanDoesNotRevokeExistingCoverage() public {
        vm.prank(subscriber);
        subs.subscribe(PLAN, PRICE);

        vm.prank(admin);
        subs.updatePlan(PLAN, PRICE, PERIOD, false);

        assertTrue(subs.isActive(subscriber, PLAN), "paid coverage was revoked");

        // New payments are refused, which is the intended effect.
        vm.prank(subscriber);
        vm.expectRevert(abi.encodeWithSelector(AgoreumSubscriptions.PlanInactive.selector, PLAN));
        subs.subscribe(PLAN, PRICE);
    }

    function test_aPriceRiseCannotOverchargeAnApprovedWallet() public {
        // The subscriber agreed to PRICE. Governance raises it in between.
        vm.prank(admin);
        subs.updatePlan(PLAN, PRICE * 2, PERIOD, true);

        vm.prank(subscriber);
        vm.expectRevert(
            abi.encodeWithSelector(
                AgoreumSubscriptions.PriceExceedsMax.selector, PRICE * 2, PRICE
            )
        );
        subs.subscribe(PLAN, PRICE);
    }

    // ------------------------------------------------------ Treasury changes

    function test_repointingTheTreasuryOnlyAffectsLaterPayments() public {
        vm.prank(subscriber);
        subs.subscribe(PLAN, PRICE);
        assertEq(usdc.balanceOf(treasury), PRICE, "first payment missed the treasury");

        address newTreasury = makeAddr("newTreasury");
        vm.prank(admin);
        subs.setTreasury(newTreasury);

        vm.prank(subscriber);
        subs.subscribe(PLAN, PRICE);

        assertEq(usdc.balanceOf(treasury), PRICE, "an earlier payment moved");
        assertEq(usdc.balanceOf(newTreasury), PRICE, "later payment missed the new treasury");
    }

    function test_aBlacklistedTreasuryBlocksPaymentAndRepointingRecoversIt() public {
        BlacklistingToken token = new BlacklistingToken();
        token.mint(subscriber, 1_000e6);
        vm.prank(subscriber);
        token.approve(address(subs), type(uint256).max);

        vm.startPrank(admin);
        subs.createPlan(2, address(token), PRICE, PERIOD);
        subs.setTreasury(treasury);
        vm.stopPrank();

        token.setBlacklisted(treasury, true);

        vm.prank(subscriber);
        vm.expectRevert();
        subs.subscribe(2, PRICE);

        // The escrow contract has the same shape of failure and the same remedy:
        // the destination is configuration, so it can be moved.
        address rescue = makeAddr("rescueTreasury");
        vm.prank(admin);
        subs.setTreasury(rescue);

        vm.prank(subscriber);
        subs.subscribe(2, PRICE);
        assertEq(token.balanceOf(rescue), PRICE, "recovery payment did not land");
    }

    // ---------------------------------------------------------------- Pausing

    function test_pauseStopsPaymentsButNeverCancellation() public {
        vm.prank(subscriber);
        subs.subscribe(PLAN, PRICE);

        vm.prank(admin);
        subs.pause();

        vm.prank(subscriber);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        subs.subscribe(PLAN, PRICE);

        // Cancelling is a statement of intent and must never be blocked: a paused
        // contract that also traps somebody in a subscription would be worse than
        // one that simply stops selling.
        vm.prank(subscriber);
        subs.cancel(PLAN);
        assertTrue(subs.getSubscription(subscriber, PLAN).autoRenewCancelled);
    }

    function test_pausingDoesNotStrandFundsBecauseNoneAreHeld() public {
        vm.prank(subscriber);
        subs.subscribe(PLAN, PRICE);

        vm.prank(admin);
        subs.pause();

        assertTrue(subs.contractHoldsNothing(address(usdc)), "paused contract holds funds");
        assertEq(usdc.balanceOf(address(subs)), 0);
    }

    // ------------------------------------------------------------- Plan rules

    function test_aPlanIdCannotBeRedefined() public {
        vm.prank(admin);
        vm.expectRevert(
            abi.encodeWithSelector(AgoreumSubscriptions.PlanAlreadyExists.selector, PLAN)
        );
        subs.createPlan(PLAN, address(usdc), PRICE, PERIOD);
    }

    function test_theTokenOfAPlanCannotBeChanged() public {
        // updatePlan takes no token argument at all, which is the enforcement.
        // Asserted so that adding one later fails here rather than silently
        // changing what every existing subscriber renews in.
        MockUSDC other = new MockUSDC();
        vm.prank(admin);
        subs.updatePlan(PLAN, PRICE, PERIOD, true);
        assertEq(subs.getPlan(PLAN).token, address(usdc), "plan token moved");
        assertTrue(address(other) != address(usdc));
    }

    function test_periodBoundsAreEnforcedOnCreateAndUpdate() public {
        uint64 minPeriod = subs.MIN_PERIOD();
        uint64 maxPeriod = subs.MAX_PERIOD();

        vm.startPrank(admin);
        vm.expectRevert(AgoreumSubscriptions.InvalidPeriod.selector);
        subs.createPlan(10, address(usdc), PRICE, minPeriod - 1);

        vm.expectRevert(AgoreumSubscriptions.InvalidPeriod.selector);
        subs.createPlan(11, address(usdc), PRICE, maxPeriod + 1);

        vm.expectRevert(AgoreumSubscriptions.InvalidPeriod.selector);
        subs.updatePlan(PLAN, PRICE, minPeriod - 1, true);
        vm.stopPrank();
    }

    function test_aFreePlanCannotBeCreatedOrUpdatedInto() public {
        vm.startPrank(admin);
        vm.expectRevert(AgoreumSubscriptions.InvalidAmount.selector);
        subs.createPlan(12, address(usdc), 0, PERIOD);

        vm.expectRevert(AgoreumSubscriptions.InvalidAmount.selector);
        subs.updatePlan(PLAN, 0, PERIOD, true);
        vm.stopPrank();
    }
}
