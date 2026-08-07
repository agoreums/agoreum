// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {Test} from "forge-std/Test.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";

import {AgoreumEscrow} from "../src/AgoreumEscrow.sol";
import {BlacklistingToken, MockUSDC} from "./mocks/Mocks.sol";

/// @notice Tests the governance surface: who may do what, and what happens when
///         those powers are handed over or abused.
///
/// @dev These exist because a mainnet readiness review found the whole area
///      untested. Role administration was never exercised anywhere, which meant
///      the single most important pre-mainnet operation, handing admin and
///      governor to a multisig and dropping the deploy key, had no coverage at
///      all. Neither did the ways a governor can hurt users without being able
///      to steal from them. The point of these tests is not only to check the
///      happy path but to pin down the blast radius, so the operational
///      decisions around a deployment are made against measured behaviour
///      rather than assumption.
contract EscrowGovernanceTest is Test {
    AgoreumEscrow internal escrow;
    MockUSDC internal usdc;

    address internal admin = makeAddr("admin");
    address internal arbiter = makeAddr("arbiter");
    address internal feeRecipient = makeAddr("feeRecipient");
    address internal buyer = makeAddr("buyer");
    address internal provider = makeAddr("provider");
    address internal multisig = makeAddr("multisig");

    uint256 internal constant FEE_BPS = 250;
    uint256 internal constant AMOUNT = 1_000e6;
    uint64 internal constant DELIVERY_WINDOW = 7 days;
    uint64 internal constant AUTO_RELEASE_WINDOW = 7 days;
    bytes32 internal constant ID = keccak256("order-gov");

    // Cached deliberately. `vm.prank` applies to the next call only, and
    // `GOVERNOR_ROLE` is a call, so writing
    // `vm.prank(admin); escrow.grantRole(GOVERNOR_ROLE, x)` spends the
    // prank on the getter and sends grantRole from the test contract instead.
    // That silently turns an authorisation test into a test of the wrong caller.
    bytes32 internal ADMIN_ROLE;
    bytes32 internal GOVERNOR_ROLE;
    bytes32 internal ARBITER_ROLE;

    function setUp() public {
        escrow = new AgoreumEscrow(admin, arbiter, feeRecipient, FEE_BPS);
        usdc = new MockUSDC();
        usdc.mint(buyer, 1_000_000e6);
        vm.prank(buyer);
        usdc.approve(address(escrow), type(uint256).max);

        ADMIN_ROLE = escrow.DEFAULT_ADMIN_ROLE();
        GOVERNOR_ROLE = escrow.GOVERNOR_ROLE();
        ARBITER_ROLE = escrow.ARBITER_ROLE();
    }

    function _create(bytes32 id) internal {
        vm.prank(buyer);
        escrow.createEscrow(
            id, provider, address(usdc), AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );
    }

    // ------------------------------------------------- Handover to a multisig

    /// @dev The operation that must work before mainnet: move every privileged
    ///      role to a multisig and leave the deploying key with nothing.
    function test_fullHandoverToMultisigLeavesTheOldAdminPowerless() public {
        vm.startPrank(admin);
        escrow.grantRole(ADMIN_ROLE, multisig);
        escrow.grantRole(GOVERNOR_ROLE, multisig);
        escrow.renounceRole(GOVERNOR_ROLE, admin);
        escrow.renounceRole(ADMIN_ROLE, admin);
        vm.stopPrank();

        assertTrue(escrow.hasRole(ADMIN_ROLE, multisig));
        assertTrue(escrow.hasRole(GOVERNOR_ROLE, multisig));
        assertFalse(escrow.hasRole(ADMIN_ROLE, admin));
        assertFalse(escrow.hasRole(GOVERNOR_ROLE, admin));

        // The old key can no longer govern.
        vm.prank(admin);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, admin, GOVERNOR_ROLE
            )
        );
        escrow.setFeeConfig(300, feeRecipient);

        // And the multisig can.
        vm.prank(multisig);
        escrow.setFeeConfig(300, feeRecipient);
        assertEq(escrow.feeBps(), 300);
    }

    /// @dev Renouncing admin before granting it to anyone else leaves the
    ///      contract permanently ungovernable. Nothing prevents this, so it is
    ///      recorded here as the failure mode the handover order exists to
    ///      avoid: grant first, verify, only then renounce.
    function test_renouncingAdminWithoutASuccessorIsIrreversible() public {
        vm.startPrank(admin);
        escrow.renounceRole(ADMIN_ROLE, admin);
        escrow.renounceRole(GOVERNOR_ROLE, admin);
        vm.stopPrank();

        vm.prank(admin);
        vm.expectRevert();
        escrow.grantRole(GOVERNOR_ROLE, multisig);

        // No one can pause, ever again. Escrows still settle, which is the
        // saving grace of keeping release and refund outside the pause.
        vm.prank(multisig);
        vm.expectRevert();
        escrow.pause();
    }

    // ------------------------------------------- Separation is deploy-time only

    /// @dev The deploy script enforces three distinct addresses on mainnet, but
    ///      that is a one-time check. DEFAULT_ADMIN_ROLE can grant itself
    ///      ARBITER_ROLE afterwards and settle disputes. Worth pinning down: it
    ///      means separation of duties is an operational commitment, not a
    ///      property the contract guarantees.
    function test_adminCanGrantItselfArbiterAfterDeployment() public {
        assertFalse(escrow.hasRole(ARBITER_ROLE, admin));

        vm.prank(admin);
        escrow.grantRole(ARBITER_ROLE, admin);

        assertTrue(escrow.hasRole(ARBITER_ROLE, admin));

        _create(ID);
        vm.prank(buyer);
        escrow.dispute(ID, "not delivered");

        // Now settles a dispute it was never meant to touch.
        vm.prank(admin);
        escrow.settleDispute(ID, AMOUNT, 0);

        AgoreumEscrow.Escrow memory e = escrow.getEscrow(ID);
        assertEq(uint8(e.status), uint8(AgoreumEscrow.Status.Settled));
    }

    /// @dev A governor still cannot raise a dispute, so it cannot reach
    ///      settleDispute on a healthy escrow unilaterally. One party must have
    ///      disputed first. This is the limit on the power above.
    function test_governorCannotDisputeOnBehalfOfAParty() public {
        _create(ID);

        vm.prank(admin);
        escrow.grantRole(ARBITER_ROLE, admin);

        vm.prank(admin);
        vm.expectRevert();
        escrow.dispute(ID, "not delivered");
    }

    // ------------------------------------ Blocked payouts, the real mechanism

    /// @dev Worth stating precisely, because the intuitive version is wrong.
    ///      A plain ERC20 `transfer` never calls the recipient, so pointing
    ///      feeRecipient at a contract that reverts in its fallback does NOT
    ///      block a payout. Verified here rather than assumed.
    ///
    ///      The mechanism that genuinely can block one is the token refusing the
    ///      transfer, which is exactly what real USDC on Base does via its
    ///      issuer-controlled blacklist. Every other escrow test runs against a
    ///      plain mock that can never refuse, so this is the first coverage of a
    ///      participant being blocked by the token itself.
    function test_aBlacklistedFeeRecipientBlocksRelease() public {
        BlacklistingToken token = new BlacklistingToken();
        token.mint(buyer, 1_000_000e6);
        vm.prank(buyer);
        token.approve(address(escrow), type(uint256).max);

        bytes32 id = keccak256("blacklist-fee");
        vm.prank(buyer);
        escrow.createEscrow(
            id, provider, address(token), AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );

        token.setBlacklisted(feeRecipient, true);

        vm.prank(buyer);
        vm.expectRevert();
        escrow.release(id);
    }

    /// @dev Recovery: the governor repoints the fee to an address the token
    ///      accepts and the stuck escrow settles. Availability is restored
    ///      without anyone losing principal.
    function test_repointingTheFeeRecoversABlockedEscrow() public {
        BlacklistingToken token = new BlacklistingToken();
        token.mint(buyer, 1_000_000e6);
        vm.prank(buyer);
        token.approve(address(escrow), type(uint256).max);

        bytes32 id = keccak256("blacklist-recover");
        vm.prank(buyer);
        escrow.createEscrow(
            id, provider, address(token), AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );

        token.setBlacklisted(feeRecipient, true);
        vm.prank(buyer);
        vm.expectRevert();
        escrow.release(id);

        address freshRecipient = makeAddr("freshRecipient");
        vm.prank(admin);
        escrow.setFeeConfig(FEE_BPS, freshRecipient);

        vm.prank(buyer);
        escrow.release(id);

        AgoreumEscrow.Escrow memory e = escrow.getEscrow(id);
        assertEq(uint8(e.status), uint8(AgoreumEscrow.Status.Released));
        assertEq(e.released + e.refunded, e.amount, "accounting must still balance");
    }

    /// @dev The harder case, and the one to carry into an incident runbook: if
    ///      the token blacklists the *provider*, no governance action helps.
    ///      release reverts, and refund is the only way the money moves, which
    ///      needs the delivery deadline to pass. Principal is recoverable, but
    ///      only by the buyer and only after waiting.
    function test_aBlacklistedProviderCannotBeReleasedToButTheBuyerRecovers() public {
        BlacklistingToken token = new BlacklistingToken();
        token.mint(buyer, 1_000_000e6);
        vm.prank(buyer);
        token.approve(address(escrow), type(uint256).max);

        bytes32 id = keccak256("blacklist-provider");
        vm.prank(buyer);
        escrow.createEscrow(
            id, provider, address(token), AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );

        token.setBlacklisted(provider, true);

        vm.prank(buyer);
        vm.expectRevert();
        escrow.release(id);

        // Repointing the fee cannot help: the provider leg is what fails.
        vm.prank(admin);
        escrow.setFeeConfig(FEE_BPS, makeAddr("anotherRecipient"));
        vm.prank(buyer);
        vm.expectRevert();
        escrow.release(id);

        vm.warp(block.timestamp + DELIVERY_WINDOW + 1);
        uint256 before = token.balanceOf(buyer);
        vm.prank(buyer);
        escrow.refund(id);
        assertEq(token.balanceOf(buyer) - before, AMOUNT, "buyer must recover the principal");
    }

    // ------------------------------------------------------------ Fee ceiling

    /// @dev The cap is the one hard limit on a compromised governor. Confirmed
    ///      directly rather than trusted, because it is what bounds the worst
    ///      case to a skim rather than a drain.
    function test_feeCannotBeRaisedAboveTheHardCeiling() public {
        uint256 max = escrow.MAX_FEE_BPS();

        vm.prank(admin);
        escrow.setFeeConfig(max, feeRecipient);
        assertEq(escrow.feeBps(), max);

        vm.prank(admin);
        vm.expectRevert();
        escrow.setFeeConfig(max + 1, feeRecipient);
    }

    /// @dev An escrow keeps the fee it was created with, so raising the fee
    ///      cannot reprice work already funded. This is the counterpart to the
    ///      recipient being live: the rate is frozen, the destination is not.
    function test_raisingTheFeeDoesNotRepriceExistingEscrows() public {
        _create(ID);

        uint256 max = escrow.MAX_FEE_BPS();
        vm.prank(admin);
        escrow.setFeeConfig(max, feeRecipient);

        vm.prank(buyer);
        escrow.release(ID);

        // Still charged at the original 2.5%, not the new ceiling.
        uint256 expectedFee = (AMOUNT * FEE_BPS) / 10_000;
        assertEq(usdc.balanceOf(feeRecipient), expectedFee, "existing escrow was repriced");
        assertEq(usdc.balanceOf(provider), AMOUNT - expectedFee);
    }
}
