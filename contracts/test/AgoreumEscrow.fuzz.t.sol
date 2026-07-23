// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";

import {AgoreumEscrow} from "../src/AgoreumEscrow.sol";
import {MockUSDC} from "./mocks/Mocks.sol";

/// @notice Property-based tests over the escrow's accounting.
/// @dev These assert properties that must hold for *every* input, rather than
///      checking a handful of chosen values. The central one is the same
///      invariant the database enforces: the contract can never pay out more
///      than it took in.
contract AgoreumEscrowFuzzTest is Test {
    AgoreumEscrow internal escrow;
    MockUSDC internal usdc;

    address internal admin = makeAddr("admin");
    address internal arbiter = makeAddr("arbiter");
    address internal feeRecipient = makeAddr("feeRecipient");

    uint256 internal constant MAX_AMOUNT = type(uint128).max;

    function setUp() public {
        escrow = new AgoreumEscrow(admin, arbiter, feeRecipient, 250);
        usdc = new MockUSDC();
    }

    function _fund(address who, uint256 amount) internal {
        usdc.mint(who, amount);
        vm.prank(who);
        usdc.approve(address(escrow), type(uint256).max);
    }

    function _bounded(uint256 amount) internal pure returns (uint256) {
        return bound(amount, 1, MAX_AMOUNT);
    }

    function _validParties(address buyer, address provider) internal view returns (bool) {
        return buyer != address(0) && provider != address(0) && buyer != provider
            && buyer != address(escrow) && provider != address(escrow) && buyer != feeRecipient
            && provider != feeRecipient && buyer.code.length == 0 && provider.code.length == 0;
    }

    // ------------------------------------------------------------ Properties

    /// @notice Release never pays out more than was deposited, for any amount.
    function testFuzz_releaseNeverOverpays(uint256 rawAmount, uint16 feeBps) public {
        uint256 amount = _bounded(rawAmount);
        uint256 fee = bound(feeBps, 0, escrow.MAX_FEE_BPS());

        vm.prank(admin);
        escrow.setFeeConfig(fee, feeRecipient);

        address buyer = makeAddr("fuzzBuyer");
        address provider = makeAddr("fuzzProvider");
        _fund(buyer, amount);

        bytes32 id = keccak256(abi.encode(rawAmount, feeBps));
        vm.startPrank(buyer);
        escrow.createEscrow(id, provider, address(usdc), amount, 1 days, 1 days);
        escrow.release(id);
        vm.stopPrank();

        AgoreumEscrow.Escrow memory e = escrow.getEscrow(id);
        assertLe(e.released + e.refunded, e.amount, "paid out more than deposited");

        // Everything deposited must have gone somewhere: nothing created, nothing lost.
        assertEq(
            usdc.balanceOf(provider) + usdc.balanceOf(feeRecipient),
            amount,
            "value created or destroyed"
        );
        assertEq(usdc.balanceOf(address(escrow)), 0, "funds stranded in the contract");
    }

    /// @notice A refund always returns the whole deposit, with no fee taken.
    function testFuzz_refundReturnsEverything(uint256 rawAmount) public {
        uint256 amount = _bounded(rawAmount);

        address buyer = makeAddr("fuzzBuyer2");
        address provider = makeAddr("fuzzProvider2");
        _fund(buyer, amount);

        bytes32 id = keccak256(abi.encode("refund", rawAmount));
        vm.prank(buyer);
        escrow.createEscrow(id, provider, address(usdc), amount, 1 days, 1 days);

        uint256 buyerBefore = usdc.balanceOf(buyer);
        vm.prank(provider);
        escrow.refund(id);

        assertEq(usdc.balanceOf(buyer) - buyerBefore, amount, "refund was not whole");
        assertEq(usdc.balanceOf(feeRecipient), 0, "a fee was taken on a refund");
        assertEq(usdc.balanceOf(address(escrow)), 0);
        _assertSolvent(id);
    }

    /// @notice No dispute split can distribute more than the escrow holds.
    function testFuzz_settlementNeverExceedsDeposit(
        uint256 rawAmount,
        uint256 rawProviderShare,
        uint256 rawBuyerShare
    ) public {
        uint256 amount = _bounded(rawAmount);

        address buyer = makeAddr("fuzzBuyer3");
        address provider = makeAddr("fuzzProvider3");
        _fund(buyer, amount);

        bytes32 id = keccak256(abi.encode("settle", rawAmount, rawProviderShare));
        vm.prank(buyer);
        escrow.createEscrow(id, provider, address(usdc), amount, 1 days, 1 days);
        vm.prank(buyer);
        escrow.dispute(id, "fuzz");

        // Deliberately unbounded: most draws are invalid splits and must revert.
        uint256 providerShare = bound(rawProviderShare, 0, type(uint128).max);
        uint256 buyerShare = bound(rawBuyerShare, 0, type(uint128).max);

        vm.prank(arbiter);
        if (providerShare > amount || buyerShare > amount - providerShare) {
            vm.expectRevert();
            escrow.settleDispute(id, providerShare, buyerShare);

            // A rejected settlement must leave every token untouched.
            assertEq(usdc.balanceOf(address(escrow)), amount, "funds moved on a failed split");
        } else {
            escrow.settleDispute(id, providerShare, buyerShare);

            assertEq(usdc.balanceOf(address(escrow)), 0, "funds stranded after settlement");
            assertEq(
                usdc.balanceOf(provider) + usdc.balanceOf(buyer) + usdc.balanceOf(feeRecipient),
                amount,
                "value created or destroyed in settlement"
            );
        }
        _assertSolvent(id);
    }

    /// @notice The fee can never exceed the configured rate, at any amount.
    function testFuzz_feeNeverExceedsConfiguredRate(uint256 rawAmount, uint16 rawFee) public {
        uint256 amount = _bounded(rawAmount);
        uint256 fee = bound(rawFee, 0, escrow.MAX_FEE_BPS());

        vm.prank(admin);
        escrow.setFeeConfig(fee, feeRecipient);

        address buyer = makeAddr("fuzzBuyer4");
        address provider = makeAddr("fuzzProvider4");
        _fund(buyer, amount);

        bytes32 id = keccak256(abi.encode("fee", rawAmount, rawFee));
        vm.startPrank(buyer);
        escrow.createEscrow(id, provider, address(usdc), amount, 1 days, 1 days);
        escrow.release(id);
        vm.stopPrank();

        uint256 charged = usdc.balanceOf(feeRecipient);
        assertLe(charged, (amount * fee) / 10_000, "charged more than the configured rate");
        // Rounding must always favour the provider, never the platform.
        assertLe(charged * 10_000, amount * fee + 10_000);
    }

    /// @notice Escrow state is never reachable where payouts exceed the deposit,
    ///         whichever terminal path is taken.
    function testFuzz_anyTerminalPathKeepsAccountingSound(uint256 rawAmount, uint8 path) public {
        uint256 amount = _bounded(rawAmount);
        uint8 chosen = uint8(bound(path, 0, 2));

        address buyer = makeAddr("fuzzBuyer5");
        address provider = makeAddr("fuzzProvider5");
        _fund(buyer, amount);

        bytes32 id = keccak256(abi.encode("path", rawAmount, path));
        vm.prank(buyer);
        escrow.createEscrow(id, provider, address(usdc), amount, 1 days, 1 days);

        if (chosen == 0) {
            vm.prank(buyer);
            escrow.release(id);
        } else if (chosen == 1) {
            vm.prank(provider);
            escrow.refund(id);
        } else {
            vm.prank(buyer);
            escrow.dispute(id, "fuzz");
            vm.prank(arbiter);
            escrow.settleDispute(id, amount / 2, amount - (amount / 2));
        }

        _assertSolvent(id);
        assertEq(usdc.balanceOf(address(escrow)), 0, "terminal path stranded funds");
    }

    /// @notice A second call on any terminal escrow must never move money.
    function testFuzz_terminalEscrowCannotBePaidTwice(uint256 rawAmount, uint8 path) public {
        uint256 amount = _bounded(rawAmount);
        uint8 chosen = uint8(bound(path, 0, 1));

        address buyer = makeAddr("fuzzBuyer6");
        address provider = makeAddr("fuzzProvider6");
        _fund(buyer, amount);

        bytes32 id = keccak256(abi.encode("twice", rawAmount, path));
        vm.prank(buyer);
        escrow.createEscrow(id, provider, address(usdc), amount, 1 days, 1 days);

        if (chosen == 0) {
            vm.prank(buyer);
            escrow.release(id);
        } else {
            vm.prank(provider);
            escrow.refund(id);
        }

        uint256 providerAfter = usdc.balanceOf(provider);
        uint256 buyerAfter = usdc.balanceOf(buyer);

        // Every re-entry into a terminal escrow must revert.
        vm.prank(buyer);
        vm.expectRevert();
        escrow.release(id);

        vm.prank(provider);
        vm.expectRevert();
        escrow.refund(id);

        vm.prank(buyer);
        vm.expectRevert();
        escrow.dispute(id, "too late");

        assertEq(usdc.balanceOf(provider), providerAfter, "provider paid twice");
        assertEq(usdc.balanceOf(buyer), buyerAfter, "buyer paid twice");
        _assertSolvent(id);
    }

    /// @notice Arbitrary callers can never move funds they are not entitled to.
    function testFuzz_unauthorisedCallersCannotMoveFunds(uint256 rawAmount, address caller) public {
        uint256 amount = _bounded(rawAmount);
        address buyer = makeAddr("fuzzBuyer7");
        address provider = makeAddr("fuzzProvider7");

        vm.assume(caller != buyer && caller != provider && caller != arbiter);
        vm.assume(_validParties(buyer, provider) && caller != address(0));
        vm.assume(caller.code.length == 0);

        _fund(buyer, amount);
        bytes32 id = keccak256(abi.encode("auth", rawAmount, caller));
        vm.prank(buyer);
        escrow.createEscrow(id, provider, address(usdc), amount, 1 days, 1 days);

        // Before auto-release, a stranger can do nothing at all.
        vm.prank(caller);
        vm.expectRevert();
        escrow.release(id);

        vm.prank(caller);
        vm.expectRevert();
        escrow.refund(id);

        vm.prank(caller);
        vm.expectRevert();
        escrow.dispute(id, "not mine");

        assertEq(usdc.balanceOf(address(escrow)), amount, "stranger moved funds");
        _assertSolvent(id);
    }

    function _assertSolvent(bytes32 id) internal view {
        AgoreumEscrow.Escrow memory e = escrow.getEscrow(id);
        assertLe(e.released + e.refunded, e.amount, "released + refunded exceeded amount");
    }
}
