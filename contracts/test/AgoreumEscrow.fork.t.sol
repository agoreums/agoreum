// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {Test} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

import {AgoreumEscrow} from "../src/AgoreumEscrow.sol";

interface IFiatTokenV2 {
    function blacklist(address account) external;
    function unBlacklist(address account) external;
    function isBlacklisted(address account) external view returns (bool);
    function blacklister() external view returns (address);
    function pause() external;
    function pauser() external view returns (address);
    function masterMinter() external view returns (address);
    function configureMinter(address minter, uint256 allowance) external returns (bool);
    function mint(address to, uint256 amount) external returns (bool);
}

/// @notice The escrow against the real USDC contract on Base, not a mock.
///
/// @dev Every other suite runs against MockUSDC, a plain OpenZeppelin ERC20 that
///      can never refuse a transfer. Real USDC on Base is an upgradeable proxy
///      with an issuer-controlled blacklist and a global pause, so the entire
///      class of "the token itself refuses" was untested. For a contract that
///      will hold user funds in exactly this token, that was the largest gap in
///      the suite.
///
///      Skipped automatically when no mainnet RPC is configured, so CI and a
///      developer without an API key still get a green run. Provide one with
///      BASE_MAINNET_RPC_URL, or ALCHEMY_BASE_URL_MAINNET which this repo
///      already defines. Note that Foundry reads .env from the directory it runs
///      in, and this repo keeps .env at the root, so run forge from the repo
///      root or export the variable.
contract EscrowForkTest is Test {
    // Native USDC on Base. Not USDbC, which is the bridged legacy token.
    address internal constant USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;

    AgoreumEscrow internal escrow;
    IERC20 internal usdc = IERC20(USDC);

    address internal admin = makeAddr("admin");
    address internal arbiter = makeAddr("arbiter");
    address internal feeRecipient = makeAddr("feeRecipient");
    address internal buyer = makeAddr("buyer");
    address internal provider = makeAddr("provider");

    uint256 internal constant FEE_BPS = 250;
    uint256 internal constant AMOUNT = 1_000e6;
    uint64 internal constant DELIVERY_WINDOW = 7 days;
    uint64 internal constant AUTO_RELEASE_WINDOW = 7 days;

    bool internal active;

    function setUp() public {
        string memory url = vm.envOr("BASE_MAINNET_RPC_URL", string(""));
        if (bytes(url).length == 0) {
            url = vm.envOr("ALCHEMY_BASE_URL_MAINNET", string(""));
        }
        if (bytes(url).length == 0) return; // no RPC, tests skip themselves

        try vm.createSelectFork(url) {
            active = true;
        } catch {
            return; // unreachable endpoint must not fail the suite
        }

        escrow = new AgoreumEscrow(admin, arbiter, feeRecipient, FEE_BPS);

        _mintUsdc(buyer, 1_000_000e6);
        vm.prank(buyer);
        usdc.approve(address(escrow), type(uint256).max);
    }

    /// @dev Mints through USDC's own masterMinter rather than writing storage
    ///      with vm.store. Going through the real code path means the balance is
    ///      produced the way the token itself produces one.
    function _mintUsdc(address to, uint256 amount) internal {
        IFiatTokenV2 token = IFiatTokenV2(USDC);
        address master = token.masterMinter();
        vm.startPrank(master);
        token.configureMinter(address(this), type(uint256).max);
        vm.stopPrank();
        token.mint(to, amount);
    }

    function _create(bytes32 id) internal {
        vm.prank(buyer);
        escrow.createEscrow(id, provider, USDC, AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW);
    }

    /// @dev `vm.skip` rather than an early return. A test that quietly returns is
    ///      reported as PASS, which is the worst possible signal: the run looks
    ///      green while the real token was never touched, and nobody notices the
    ///      coverage is gone. This reports SKIP, so a missing RPC is visible.
    modifier onFork() {
        vm.skip(!active);
        _;
    }

    /// @dev The baseline: the whole flow works against the real token, with the
    ///      exact fee split, so anything below that fails is the blacklist and
    ///      not an incompatibility with USDC.
    function test_fullEscrowFlowAgainstRealUsdc() public onFork {
        bytes32 id = keccak256("fork-happy");
        _create(id);

        assertEq(usdc.balanceOf(address(escrow)), AMOUNT);

        vm.prank(buyer);
        escrow.release(id);

        uint256 fee = (AMOUNT * FEE_BPS) / 10_000;
        assertEq(usdc.balanceOf(provider), AMOUNT - fee, "provider payout");
        assertEq(usdc.balanceOf(feeRecipient), fee, "fee payout");
        assertEq(usdc.balanceOf(address(escrow)), 0, "escrow should be empty");
    }

    /// @dev A blacklisted provider cannot be paid, confirmed against the real
    ///      blacklist rather than a mock of it. Governance cannot fix this: the
    ///      failing leg is the provider's.
    function test_realBlacklistOnProviderBlocksRelease() public onFork {
        bytes32 id = keccak256("fork-bl-provider");
        _create(id);

        IFiatTokenV2 token = IFiatTokenV2(USDC);
        vm.prank(token.blacklister());
        token.blacklist(provider);
        assertTrue(token.isBlacklisted(provider));

        vm.prank(buyer);
        vm.expectRevert();
        escrow.release(id);
    }

    /// @dev And the buyer still recovers the principal after the delivery
    ///      deadline, because refund never touches the provider. This is the
    ///      property that keeps a blacklisting event survivable, verified
    ///      against the real token.
    function test_buyerStillRecoversFromABlacklistedProvider() public onFork {
        bytes32 id = keccak256("fork-bl-recover");
        _create(id);

        IFiatTokenV2 token = IFiatTokenV2(USDC);
        vm.prank(token.blacklister());
        token.blacklist(provider);

        vm.warp(block.timestamp + DELIVERY_WINDOW + 1);

        uint256 before = usdc.balanceOf(buyer);
        vm.prank(buyer);
        escrow.refund(id);

        assertEq(usdc.balanceOf(buyer) - before, AMOUNT, "buyer must recover everything");
    }

    /// @dev A blacklisted fee recipient blocks release too, and unlike the
    ///      provider case this one governance CAN fix by repointing the fee.
    function test_realBlacklistOnFeeRecipientIsRecoverableByRepointing() public onFork {
        bytes32 id = keccak256("fork-bl-fee");
        _create(id);

        IFiatTokenV2 token = IFiatTokenV2(USDC);
        vm.prank(token.blacklister());
        token.blacklist(feeRecipient);

        vm.prank(buyer);
        vm.expectRevert();
        escrow.release(id);

        address fresh = makeAddr("freshFeeRecipient");
        vm.prank(admin);
        escrow.setFeeConfig(FEE_BPS, fresh);

        vm.prank(buyer);
        escrow.release(id);

        uint256 fee = (AMOUNT * FEE_BPS) / 10_000;
        assertEq(usdc.balanceOf(fresh), fee, "fee should reach the new recipient");
        assertEq(usdc.balanceOf(provider), AMOUNT - fee);
    }

    /// @dev USDC's global pause halts every transfer, so escrows cannot settle
    ///      while it is on. Nothing in Agoreum can work around that, and it is
    ///      worth having pinned down: the correct response is to wait, not to
    ///      attempt a migration. Funds are not lost, only immobile.
    function test_usdcGlobalPauseFreezesSettlementUntilLifted() public onFork {
        bytes32 id = keccak256("fork-pause");
        _create(id);

        IFiatTokenV2 token = IFiatTokenV2(USDC);
        vm.prank(token.pauser());
        token.pause();

        vm.prank(buyer);
        vm.expectRevert();
        escrow.release(id);
    }

    /// @dev A blacklisted buyer cannot open an escrow at all, since createEscrow
    ///      pulls the deposit. It fails at the door rather than stranding funds.
    function test_blacklistedBuyerCannotCreateAnEscrow() public onFork {
        IFiatTokenV2 token = IFiatTokenV2(USDC);
        vm.prank(token.blacklister());
        token.blacklist(buyer);

        vm.prank(buyer);
        vm.expectRevert();
        escrow.createEscrow(
            keccak256("fork-bl-buyer"), provider, USDC, AMOUNT, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );
    }
}
