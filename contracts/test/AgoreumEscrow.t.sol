// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {IERC20Errors} from "@openzeppelin/contracts/interfaces/draft-IERC6093.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

import {AgoreumEscrow} from "../src/AgoreumEscrow.sol";
import {
    FeeOnTransferToken,
    MockUSDC,
    ReentrancyAttacker,
    ReentrantToken,
    SilentlyFailingToken
} from "./mocks/Mocks.sol";

/// @dev Shared setup for every escrow test.
abstract contract EscrowTestBase is Test {
    AgoreumEscrow internal escrow;
    MockUSDC internal usdc;

    address internal admin = makeAddr("admin");
    address internal arbiter = makeAddr("arbiter");
    address internal feeRecipient = makeAddr("feeRecipient");
    address internal buyer = makeAddr("buyer");
    address internal provider = makeAddr("provider");
    address internal stranger = makeAddr("stranger");

    uint256 internal constant FEE_BPS = 250; // 2.5%
    uint256 internal constant AMOUNT = 1_000e6; // 1,000 USDC
    uint64 internal constant DELIVERY_WINDOW = 7 days;
    uint64 internal constant AUTO_RELEASE_WINDOW = 7 days;

    bytes32 internal constant ID = keccak256("order-1");

    function setUp() public virtual {
        escrow = new AgoreumEscrow(admin, arbiter, feeRecipient, FEE_BPS);
        usdc = new MockUSDC();

        usdc.mint(buyer, 1_000_000e6);
        vm.prank(buyer);
        usdc.approve(address(escrow), type(uint256).max);
    }

    function _create(bytes32 id, uint256 amount) internal {
        vm.prank(buyer);
        escrow.createEscrow(
            id, provider, address(usdc), amount, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );
    }

    function _create() internal {
        _create(ID, AMOUNT);
    }

    /// @dev The escrow's central invariant, checked from outside the contract.
    function _assertAccountingHolds(bytes32 id) internal view {
        AgoreumEscrow.Escrow memory e = escrow.getEscrow(id);
        assertLe(e.released + e.refunded, e.amount, "paid out more than was deposited");
    }
}

// ---------------------------------------------------------------- Creation

contract EscrowCreationTest is EscrowTestBase {
    function test_createEscrowHoldsTheFunds() public {
        uint256 buyerBefore = usdc.balanceOf(buyer);
        _create();

        assertEq(usdc.balanceOf(address(escrow)), AMOUNT, "contract should hold the deposit");
        assertEq(usdc.balanceOf(buyer), buyerBefore - AMOUNT);

        AgoreumEscrow.Escrow memory e = escrow.getEscrow(ID);
        assertEq(uint8(e.status), uint8(AgoreumEscrow.Status.Funded));
        assertEq(e.amount, AMOUNT);
        assertEq(e.released, 0);
        assertEq(e.refunded, 0);
        assertEq(e.feeBps, FEE_BPS, "fee must be frozen at creation");
    }

    function test_duplicateIdIsRejected() public {
        _create();
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(AgoreumEscrow.EscrowAlreadyExists.selector, ID));
        escrow.createEscrow(
            ID, provider, address(usdc), AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );
    }

    function test_zeroAmountIsRejected() public {
        vm.prank(buyer);
        vm.expectRevert(AgoreumEscrow.InvalidAmount.selector);
        escrow.createEscrow(ID, provider, address(usdc), 0, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW);
    }

    function test_buyerCannotBeTheProvider() public {
        vm.prank(buyer);
        vm.expectRevert(AgoreumEscrow.InvalidAddress.selector);
        escrow.createEscrow(ID, buyer, address(usdc), AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW);
    }

    function test_windowsOutsideBoundsAreRejected() public {
        vm.startPrank(buyer);

        vm.expectRevert(AgoreumEscrow.InvalidWindow.selector);
        escrow.createEscrow(ID, provider, address(usdc), AMOUNT, 1 minutes, AUTO_RELEASE_WINDOW);

        vm.expectRevert(AgoreumEscrow.InvalidWindow.selector);
        escrow.createEscrow(ID, provider, address(usdc), AMOUNT, 366 days, AUTO_RELEASE_WINDOW);

        vm.stopPrank();
    }

    function test_feeOnTransferTokenIsRejected() public {
        // Crediting the requested amount when less arrived would leave the
        // contract promising more than it holds.
        FeeOnTransferToken feeToken = new FeeOnTransferToken(100); // 1%
        feeToken.mint(buyer, AMOUNT);

        vm.startPrank(buyer);
        feeToken.approve(address(escrow), AMOUNT);
        vm.expectRevert(
            abi.encodeWithSelector(
                AgoreumEscrow.UnsupportedToken.selector, AMOUNT, AMOUNT - (AMOUNT / 100)
            )
        );
        escrow.createEscrow(
            ID, provider, address(feeToken), AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );
        vm.stopPrank();
    }

    function test_creationIsBlockedWhilePaused() public {
        vm.prank(admin);
        escrow.pause();

        vm.prank(buyer);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        escrow.createEscrow(
            ID, provider, address(usdc), AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );
    }

    function test_creationWithoutApprovalReverts() public {
        address poorBuyer = makeAddr("poorBuyer");
        usdc.mint(poorBuyer, AMOUNT);

        vm.prank(poorBuyer);
        vm.expectRevert(
            abi.encodeWithSelector(
                IERC20Errors.ERC20InsufficientAllowance.selector, address(escrow), 0, AMOUNT
            )
        );
        escrow.createEscrow(
            ID, provider, address(usdc), AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );
    }
}

// ----------------------------------------------------------------- Release

contract EscrowReleaseTest is EscrowTestBase {
    function test_buyerCanReleaseImmediately() public {
        _create();

        vm.prank(buyer);
        escrow.release(ID);

        uint256 expectedFee = (AMOUNT * FEE_BPS) / 10_000;
        assertEq(usdc.balanceOf(provider), AMOUNT - expectedFee);
        assertEq(usdc.balanceOf(feeRecipient), expectedFee);
        assertEq(usdc.balanceOf(address(escrow)), 0, "contract should retain nothing");
        _assertAccountingHolds(ID);
    }

    function test_doubleReleaseIsRejected() public {
        _create();

        vm.prank(buyer);
        escrow.release(ID);

        vm.prank(buyer);
        vm.expectRevert(
            abi.encodeWithSelector(
                AgoreumEscrow.InvalidStatus.selector,
                ID,
                AgoreumEscrow.Status.Released,
                AgoreumEscrow.Status.Funded
            )
        );
        escrow.release(ID);

        _assertAccountingHolds(ID);
    }

    /// @dev The same settlement transaction being submitted twice is a normal
    ///      operational event (a retry, or a stuck nonce replaced). The second
    ///      must be inert rather than paying twice.
    function test_settlementSubmittedTwicePaysOnce() public {
        _create();

        vm.prank(buyer);
        escrow.release(ID);
        uint256 providerAfterFirst = usdc.balanceOf(provider);

        vm.prank(buyer);
        vm.expectRevert();
        escrow.release(ID);

        assertEq(usdc.balanceOf(provider), providerAfterFirst, "paid twice");
        assertEq(usdc.balanceOf(address(escrow)), 0);
    }

    function test_strangerCannotReleaseBeforeAutoRelease() public {
        _create();

        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(AgoreumEscrow.NotAuthorized.selector, stranger));
        escrow.release(ID);
    }

    function test_providerCannotReleaseToThemselvesEarly() public {
        _create();

        vm.prank(provider);
        vm.expectRevert(abi.encodeWithSelector(AgoreumEscrow.NotAuthorized.selector, provider));
        escrow.release(ID);
    }

    function test_anyoneCanReleaseAfterAutoReleaseDeadline() public {
        // A provider must not depend on the buyer, or on the platform, staying
        // available in order to be paid.
        _create();
        vm.warp(block.timestamp + DELIVERY_WINDOW + AUTO_RELEASE_WINDOW);

        vm.prank(stranger);
        escrow.release(ID);

        uint256 expectedFee = (AMOUNT * FEE_BPS) / 10_000;
        assertEq(usdc.balanceOf(provider), AMOUNT - expectedFee);
        _assertAccountingHolds(ID);
    }

    function test_releaseOnUnknownEscrowReverts() public {
        bytes32 unknown = keccak256("nope");
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(AgoreumEscrow.EscrowNotFound.selector, unknown));
        escrow.release(unknown);
    }

    function test_releaseStillWorksWhilePaused() public {
        // A pause that could strand committed funds would be a custody risk.
        _create();
        vm.prank(admin);
        escrow.pause();

        vm.prank(buyer);
        escrow.release(ID);

        assertEq(usdc.balanceOf(address(escrow)), 0);
    }
}

// ------------------------------------------------------------------ Refund

contract EscrowRefundTest is EscrowTestBase {
    function test_providerCanRefundAtAnyTime() public {
        _create();
        uint256 buyerBefore = usdc.balanceOf(buyer);

        vm.prank(provider);
        escrow.refund(ID);

        assertEq(usdc.balanceOf(buyer), buyerBefore + AMOUNT, "buyer refunded in full");
        assertEq(usdc.balanceOf(feeRecipient), 0, "no fee on a refund");
        _assertAccountingHolds(ID);
    }

    function test_buyerCannotRefundBeforeDeadline() public {
        _create();

        vm.prank(buyer);
        vm.expectRevert(
            abi.encodeWithSelector(
                AgoreumEscrow.DeadlineNotReached.selector,
                uint64(block.timestamp + DELIVERY_WINDOW),
                uint64(block.timestamp)
            )
        );
        escrow.refund(ID);
    }

    function test_buyerCanReclaimAfterDeadline() public {
        _create();
        vm.warp(block.timestamp + DELIVERY_WINDOW);

        uint256 buyerBefore = usdc.balanceOf(buyer);
        vm.prank(buyer);
        escrow.refund(ID);

        assertEq(usdc.balanceOf(buyer), buyerBefore + AMOUNT);
        _assertAccountingHolds(ID);
    }

    function test_refundAfterReleaseIsRejected() public {
        // The attack that would drain the contract: collect twice.
        _create();

        vm.prank(buyer);
        escrow.release(ID);

        vm.prank(provider);
        vm.expectRevert(
            abi.encodeWithSelector(
                AgoreumEscrow.InvalidStatus.selector,
                ID,
                AgoreumEscrow.Status.Released,
                AgoreumEscrow.Status.Funded
            )
        );
        escrow.refund(ID);

        assertEq(usdc.balanceOf(address(escrow)), 0);
        _assertAccountingHolds(ID);
    }

    function test_releaseAfterRefundIsRejected() public {
        _create();

        vm.prank(provider);
        escrow.refund(ID);

        vm.warp(block.timestamp + DELIVERY_WINDOW + AUTO_RELEASE_WINDOW);
        vm.prank(stranger);
        vm.expectRevert(
            abi.encodeWithSelector(
                AgoreumEscrow.InvalidStatus.selector,
                ID,
                AgoreumEscrow.Status.Refunded,
                AgoreumEscrow.Status.Funded
            )
        );
        escrow.release(ID);

        _assertAccountingHolds(ID);
    }

    function test_doubleRefundIsRejected() public {
        _create();

        vm.prank(provider);
        escrow.refund(ID);

        vm.prank(provider);
        vm.expectRevert();
        escrow.refund(ID);

        _assertAccountingHolds(ID);
    }

    function test_strangerCannotRefund() public {
        _create();
        vm.warp(block.timestamp + DELIVERY_WINDOW);

        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(AgoreumEscrow.NotAuthorized.selector, stranger));
        escrow.refund(ID);
    }
}

// ---------------------------------------------------------------- Disputes

contract EscrowDisputeTest is EscrowTestBase {
    function _dispute() internal {
        vm.prank(buyer);
        escrow.dispute(ID, "work not delivered");
    }

    function test_eitherPartyCanDispute() public {
        _create();
        vm.prank(provider);
        escrow.dispute(ID, "buyer unresponsive");
        assertEq(uint8(escrow.statusOf(ID)), uint8(AgoreumEscrow.Status.Disputed));
    }

    function test_strangerCannotDispute() public {
        _create();
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(AgoreumEscrow.NotAuthorized.selector, stranger));
        escrow.dispute(ID, "meddling");
    }

    function test_disputeBlocksAutoRelease() public {
        // An unresolved disagreement must not resolve itself in the provider's
        // favour purely through the passage of time.
        _create();
        _dispute();

        vm.warp(block.timestamp + DELIVERY_WINDOW + AUTO_RELEASE_WINDOW);
        vm.prank(stranger);
        vm.expectRevert();
        escrow.release(ID);

        assertEq(usdc.balanceOf(address(escrow)), AMOUNT, "funds must stay held");
    }

    function test_arbiterCanSplit() public {
        _create();
        _dispute();

        uint256 toProvider = 600e6;
        uint256 toBuyer = 400e6;
        uint256 buyerBefore = usdc.balanceOf(buyer);

        vm.prank(arbiter);
        escrow.settleDispute(ID, toProvider, toBuyer);

        uint256 fee = (toProvider * FEE_BPS) / 10_000;
        assertEq(usdc.balanceOf(provider), toProvider - fee);
        assertEq(usdc.balanceOf(buyer), buyerBefore + toBuyer);
        assertEq(usdc.balanceOf(feeRecipient), fee);
        assertEq(usdc.balanceOf(address(escrow)), 0, "nothing left stranded");
        _assertAccountingHolds(ID);
    }

    function test_settlementCannotExceedTheDeposit() public {
        _create();
        _dispute();

        vm.prank(arbiter);
        vm.expectRevert(
            abi.encodeWithSelector(AgoreumEscrow.SplitExceedsAmount.selector, AMOUNT, 1, AMOUNT)
        );
        escrow.settleDispute(ID, AMOUNT, 1);

        assertEq(usdc.balanceOf(address(escrow)), AMOUNT);
    }

    function test_nonArbiterCannotSettle() public {
        _create();
        _dispute();

        // Read the role before pranking: vm.prank applies to the next call, and
        // escrow.ARBITER_ROLE() would consume it.
        bytes32 arbiterRole = escrow.ARBITER_ROLE();

        vm.prank(admin);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, admin, arbiterRole
            )
        );
        escrow.settleDispute(ID, AMOUNT, 0);
    }

    function test_doubleSettlementIsRejected() public {
        _create();
        _dispute();

        vm.prank(arbiter);
        escrow.settleDispute(ID, 500e6, 500e6);

        vm.prank(arbiter);
        vm.expectRevert();
        escrow.settleDispute(ID, 500e6, 500e6);

        _assertAccountingHolds(ID);
    }

    function test_cannotSettleAnUndisputedEscrow() public {
        _create();

        vm.prank(arbiter);
        vm.expectRevert(
            abi.encodeWithSelector(
                AgoreumEscrow.InvalidStatus.selector,
                ID,
                AgoreumEscrow.Status.Funded,
                AgoreumEscrow.Status.Disputed
            )
        );
        escrow.settleDispute(ID, AMOUNT, 0);
    }

    function test_partialSplitLeavesRemainderWithBuyer() public {
        // Under-allocating must not strand the difference in the contract.
        _create();
        _dispute();

        uint256 buyerBefore = usdc.balanceOf(buyer);
        vm.prank(arbiter);
        escrow.settleDispute(ID, 300e6, 0);

        assertEq(usdc.balanceOf(address(escrow)), 0, "remainder stranded");
        assertEq(usdc.balanceOf(buyer), buyerBefore + (AMOUNT - 300e6));
        _assertAccountingHolds(ID);
    }
}

// -------------------------------------------------------------- Reentrancy

contract EscrowReentrancyTest is EscrowTestBase {
    function test_reentrantTokenCannotDrainOnRelease() public {
        ReentrantToken evil = new ReentrantToken();
        evil.mint(buyer, AMOUNT * 2);

        bytes32 id = keccak256("reentrant-release");
        vm.startPrank(buyer);
        evil.approve(address(escrow), type(uint256).max);
        escrow.createEscrow(
            id, provider, address(evil), AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );
        vm.stopPrank();

        // On the way out of release(), the token calls release() again.
        evil.arm(address(escrow), abi.encodeWithSelector(AgoreumEscrow.release.selector, id));

        vm.prank(buyer);
        escrow.release(id);

        assertGt(evil.reentryAttempts(), 0, "the reentrancy vector never fired");
        assertFalse(evil.lastReentrySucceeded(), "reentrant call succeeded");
        assertEq(evil.balanceOf(address(escrow)), 0, "contract over-paid");
        _assertAccountingHolds(id);
    }

    function test_reentrantTokenCannotDrainOnRefund() public {
        ReentrantToken evil = new ReentrantToken();
        evil.mint(buyer, AMOUNT * 2);

        bytes32 id = keccak256("reentrant-refund");
        vm.startPrank(buyer);
        evil.approve(address(escrow), type(uint256).max);
        escrow.createEscrow(
            id, provider, address(evil), AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );
        vm.stopPrank();

        evil.arm(address(escrow), abi.encodeWithSelector(AgoreumEscrow.refund.selector, id));

        vm.prank(provider);
        escrow.refund(id);

        assertGt(evil.reentryAttempts(), 0, "the reentrancy vector never fired");
        assertFalse(evil.lastReentrySucceeded(), "reentrant call succeeded");
        assertEq(evil.balanceOf(address(escrow)), 0);
        _assertAccountingHolds(id);
    }

    function test_reentrantCrossFunctionAttackFails() public {
        // Re-enter refund() from inside release(): the status is already
        // terminal by then, so the cross-function path is closed too.
        ReentrantToken evil = new ReentrantToken();
        evil.mint(buyer, AMOUNT * 2);

        bytes32 id = keccak256("cross-function");
        vm.startPrank(buyer);
        evil.approve(address(escrow), type(uint256).max);
        escrow.createEscrow(
            id, provider, address(evil), AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );
        vm.stopPrank();

        evil.arm(address(escrow), abi.encodeWithSelector(AgoreumEscrow.refund.selector, id));

        vm.prank(buyer);
        escrow.release(id);

        assertFalse(evil.lastReentrySucceeded(), "cross-function reentry succeeded");
        assertEq(evil.balanceOf(address(escrow)), 0);
        _assertAccountingHolds(id);
    }

    function test_contractRecipientCannotReenter() public {
        ReentrancyAttacker attacker = new ReentrancyAttacker(escrow);
        bytes32 id = keccak256("attacker-provider");

        vm.prank(buyer);
        escrow.createEscrow(
            id, address(attacker), address(usdc), AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );
        attacker.setEscrowId(id);

        vm.prank(buyer);
        escrow.release(id);

        assertEq(usdc.balanceOf(address(escrow)), 0);
        _assertAccountingHolds(id);
    }
}

// ------------------------------------------------------------ Token safety

contract EscrowTokenSafetyTest is EscrowTestBase {
    function test_silentTransferFailureRevertsTheWholeRelease() public {
        // If the token lies about success, the escrow must not record a payout
        // that never happened.
        SilentlyFailingToken token = new SilentlyFailingToken();
        token.mint(buyer, AMOUNT);

        bytes32 id = keccak256("silent");
        vm.startPrank(buyer);
        token.approve(address(escrow), AMOUNT);
        escrow.createEscrow(
            id, provider, address(token), AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );
        vm.stopPrank();

        token.setFailTransfers(true);

        vm.prank(buyer);
        vm.expectRevert(
            abi.encodeWithSelector(SafeERC20.SafeERC20FailedOperation.selector, address(token))
        );
        escrow.release(id);

        // The revert rolled everything back: still funded, still holding.
        assertEq(uint8(escrow.statusOf(id)), uint8(AgoreumEscrow.Status.Funded));
        assertEq(token.balanceOf(address(escrow)), AMOUNT);
    }
}

// ------------------------------------------------------------- Fee & access

contract EscrowGovernanceTest is EscrowTestBase {
    function test_feeCannotExceedTheHardCeiling() public {
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(AgoreumEscrow.FeeTooHigh.selector, 1_001, 1_000));
        escrow.setFeeConfig(1_001, feeRecipient);
    }

    function test_feeChangeDoesNotAffectExistingEscrows() public {
        // Work already agreed and paid for cannot be repriced.
        _create();

        vm.prank(admin);
        escrow.setFeeConfig(1_000, feeRecipient);

        vm.prank(buyer);
        escrow.release(ID);

        uint256 expectedFee = (AMOUNT * FEE_BPS) / 10_000; // the original rate
        assertEq(usdc.balanceOf(feeRecipient), expectedFee);
    }

    function test_nonGovernorCannotChangeFee() public {
        bytes32 governorRole = escrow.GOVERNOR_ROLE();

        vm.prank(stranger);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, stranger, governorRole
            )
        );
        escrow.setFeeConfig(100, stranger);
    }

    function test_constructorRejectsExcessiveFee() public {
        vm.expectRevert(abi.encodeWithSelector(AgoreumEscrow.FeeTooHigh.selector, 5_000, 1_000));
        new AgoreumEscrow(admin, arbiter, feeRecipient, 5_000);
    }

    function test_constructorRejectsZeroAddresses() public {
        vm.expectRevert(AgoreumEscrow.InvalidAddress.selector);
        new AgoreumEscrow(address(0), arbiter, feeRecipient, FEE_BPS);
    }
}

// ------------------------------------------------------ Arithmetic boundaries

contract EscrowArithmeticTest is EscrowTestBase {
    function test_smallestPossibleAmount() public {
        // 1 base unit: the fee rounds to zero, so the provider takes it all.
        bytes32 id = keccak256("dust");
        _create(id, 1);

        vm.prank(buyer);
        escrow.release(id);

        assertEq(usdc.balanceOf(provider), 1, "dust must not vanish");
        assertEq(usdc.balanceOf(feeRecipient), 0);
        assertEq(usdc.balanceOf(address(escrow)), 0);
        _assertAccountingHolds(id);
    }

    function test_amountWhereFeeRoundsDown() public {
        // 399 units at 2.5% is 9.975, which truncates to 9. The rounding must
        // favour the provider, never create value.
        bytes32 id = keccak256("rounding");
        _create(id, 399);

        vm.prank(buyer);
        escrow.release(id);

        assertEq(usdc.balanceOf(feeRecipient), 9);
        assertEq(usdc.balanceOf(provider), 390);
        assertEq(usdc.balanceOf(address(escrow)), 0, "rounding dust stranded");
    }

    function test_veryLargeAmountDoesNotOverflow() public {
        uint256 huge = type(uint128).max;
        address whale = makeAddr("whale");
        usdc.mint(whale, huge);

        bytes32 id = keccak256("whale");
        vm.startPrank(whale);
        usdc.approve(address(escrow), huge);
        escrow.createEscrow(id, provider, address(usdc), huge, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW);
        escrow.release(id);
        vm.stopPrank();

        uint256 fee = (huge * FEE_BPS) / 10_000;
        assertEq(usdc.balanceOf(provider), huge - fee);
        assertEq(usdc.balanceOf(address(escrow)), 0);
        _assertAccountingHolds(id);
    }

    function test_zeroFeeConfigurationPaysEverythingToProvider() public {
        AgoreumEscrow freeEscrow = new AgoreumEscrow(admin, arbiter, feeRecipient, 0);
        usdc.mint(buyer, AMOUNT);

        bytes32 id = keccak256("zero-fee");
        vm.startPrank(buyer);
        usdc.approve(address(freeEscrow), AMOUNT);
        freeEscrow.createEscrow(
            id, provider, address(usdc), AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );
        freeEscrow.release(id);
        vm.stopPrank();

        assertEq(usdc.balanceOf(provider), AMOUNT);
        assertEq(usdc.balanceOf(feeRecipient), 0);
    }
}

// ------------------------------------------------------------------- Views

contract EscrowViewTest is EscrowTestBase {
    function test_outstandingTracksWhatIsStillHeld() public {
        _create();
        assertEq(escrow.outstanding(ID), AMOUNT);

        vm.prank(buyer);
        escrow.release(ID);
        assertEq(escrow.outstanding(ID), 0, "released escrow still shows a balance");
    }

    function test_outstandingAfterPartialSettlement() public {
        _create();
        vm.prank(buyer);
        escrow.dispute(ID, "partial");

        vm.prank(arbiter);
        escrow.settleDispute(ID, 400e6, 600e6);

        assertEq(escrow.outstanding(ID), 0);
    }

    function test_autoReleaseAvailableFlipsAtTheDeadline() public {
        _create();
        assertFalse(escrow.autoReleaseAvailable(ID));

        vm.warp(block.timestamp + DELIVERY_WINDOW + AUTO_RELEASE_WINDOW);
        assertTrue(escrow.autoReleaseAvailable(ID));

        vm.prank(stranger);
        escrow.release(ID);
        assertFalse(escrow.autoReleaseAvailable(ID), "terminal escrow still claimable");
    }

    function test_refundAvailableFlipsAtTheDeadline() public {
        _create();
        assertFalse(escrow.refundAvailable(ID));

        vm.warp(block.timestamp + DELIVERY_WINDOW);
        assertTrue(escrow.refundAvailable(ID));

        vm.prank(buyer);
        escrow.refund(ID);
        assertFalse(escrow.refundAvailable(ID));
    }

    function test_viewsOnUnknownEscrowAreInert() public view {
        bytes32 unknown = keccak256("never-created");
        assertEq(uint8(escrow.statusOf(unknown)), uint8(AgoreumEscrow.Status.None));
        assertEq(escrow.outstanding(unknown), 0);
        assertFalse(escrow.autoReleaseAvailable(unknown));
        assertFalse(escrow.refundAvailable(unknown));
    }

    function test_feesCollectedAccumulatesPerToken() public {
        _create();
        vm.prank(buyer);
        escrow.release(ID);

        uint256 expected = (AMOUNT * FEE_BPS) / 10_000;
        assertEq(escrow.feesCollected(address(usdc)), expected);
    }
}

// ------------------------------------------------------------------- Pause

contract EscrowPauseTest is EscrowTestBase {
    function test_unpauseRestoresCreation() public {
        vm.startPrank(admin);
        escrow.pause();
        escrow.unpause();
        vm.stopPrank();

        _create();
        assertEq(uint8(escrow.statusOf(ID)), uint8(AgoreumEscrow.Status.Funded));
    }

    function test_nonGovernorCannotPause() public {
        bytes32 governorRole = escrow.GOVERNOR_ROLE();
        vm.prank(stranger);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, stranger, governorRole
            )
        );
        escrow.pause();
    }

    function test_disputeIsBlockedWhilePaused() public {
        _create();
        vm.prank(admin);
        escrow.pause();

        vm.prank(buyer);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        escrow.dispute(ID, "while paused");
    }

    function test_refundAndSettlementSurviveAPause() public {
        // Committed funds must always be able to reach a terminal state.
        _create();
        vm.prank(admin);
        escrow.pause();

        vm.prank(provider);
        escrow.refund(ID);
        assertEq(usdc.balanceOf(address(escrow)), 0);
    }
}
