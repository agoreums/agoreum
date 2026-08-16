// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {Test, console2} from "forge-std/Test.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

import {AgoreumEscrow} from "../src/AgoreumEscrow.sol";

interface IFiatTokenV2 {
    function masterMinter() external view returns (address);
    function configureMinter(address minter, uint256 allowance) external returns (bool);
    function mint(address to, uint256 amount) external returns (bool);
}

/// @notice What a settlement actually costs on Base, measured rather than assumed.
interface IGasPriceOracle {
    function getL1Fee(bytes memory data) external view returns (uint256);
}

interface IAggregatorV3 {
    function decimals() external view returns (uint8);
    function latestRoundData()
        external
        view
        returns (uint80, int256, uint256, uint256, uint80);
}

/// @notice Measures the real cost of settling a payment on Base, to decide
///         whether a payment channel is worth building at all.
///
/// @dev The proposal on the table is a payment-channel primitive so that many
///      small agent-to-agent calls can settle against one bounded commitment.
///      That is only worth building if settling each call directly on chain is
///      genuinely too expensive. Nobody had measured that, so the premise was
///      unproven and the correct thing to do was measure before designing.
///
///      Two traps this suite exists to avoid.
///
///      First, `gasleft()` on an OP-stack chain measures L2 execution only. Base
///      charges that plus an L1 data-availability fee derived from the
///      compressed transaction size, and the L1 term is frequently the larger of
///      the two. A measurement that reported only execution gas would understate
///      the true cost, and would understate it *most* for exactly the small
///      simple transactions a channel is meant to optimise, which is the
///      direction that would falsely justify building one. So the L1 term is
///      taken from Base's own GasPriceOracle predeploy, against the real
///      calldata, at a real block.
///
///      Second, a cost in gas is not a cost in money. The figure that decides
///      this is dollars per settlement, so the L2 base fee is read from the
///      forked block and ETH is priced from Chainlink's feed on Base rather than
///      from a number typed into a test.
///
///      Skips itself when no mainnet RPC is configured, via `vm.skip` so the
///      skip is visible rather than reported as a pass.
contract MicropaymentGasForkTest is Test {
    address internal constant USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address internal constant GAS_ORACLE = 0x420000000000000000000000000000000000000F;
    address internal constant ETH_USD_FEED = 0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70;

    /// @dev A standalone transaction pays this before executing a single opcode.
    uint256 internal constant INTRINSIC_GAS = 21_000;

    /// @dev One cent, in micro-USD. See the assertion at the end of the test.
    uint256 internal constant CHANNEL_RECONSIDERATION_THRESHOLD = 10_000;

    AgoreumEscrow internal escrow;
    IERC20 internal usdc = IERC20(USDC);

    address internal admin = makeAddr("admin");
    address internal arbiter = makeAddr("arbiter");
    address internal feeRecipient = makeAddr("feeRecipient");
    address internal buyer = makeAddr("buyer");
    address internal provider = makeAddr("provider");

    uint256 internal constant FEE_BPS = 250;
    uint64 internal constant DELIVERY_WINDOW = 7 days;
    uint64 internal constant AUTO_RELEASE_WINDOW = 7 days;

    bool internal active;
    uint256 internal ethUsd8;

    function setUp() public {
        string memory url = vm.envOr("BASE_MAINNET_RPC_URL", string(""));
        if (bytes(url).length == 0) {
            url = vm.envOr("ALCHEMY_BASE_URL_MAINNET", string(""));
        }
        if (bytes(url).length == 0) return;

        try vm.createSelectFork(url) {
            active = true;
        } catch {
            return;
        }

        escrow = new AgoreumEscrow(admin, arbiter, feeRecipient, FEE_BPS);
        _mintUsdc(buyer, 1_000_000e6);
        vm.prank(buyer);
        usdc.approve(address(escrow), type(uint256).max);

        ethUsd8 = _ethUsd();
    }

    modifier onFork() {
        vm.skip(!active);
        _;
    }

    function _mintUsdc(address to, uint256 amount) internal {
        IFiatTokenV2 token = IFiatTokenV2(USDC);
        vm.prank(token.masterMinter());
        token.configureMinter(address(this), type(uint256).max);
        token.mint(to, amount);
    }

    /// @dev Reverts or fails loudly if the feed address is wrong, rather than
    ///      producing a plausible-looking dollar figure from a garbage answer.
    function _ethUsd() internal view returns (uint256) {
        IAggregatorV3 feed = IAggregatorV3(ETH_USD_FEED);
        require(feed.decimals() == 8, "unexpected feed decimals");
        (, int256 answer,,,) = feed.latestRoundData();
        require(answer > 100e8 && answer < 1_000_000e8, "implausible ETH price");
        return uint256(answer);
    }

    /// @dev Total cost in USD, scaled by 1e18 for readability at micro amounts.
    ///      L2 execution at the block's base fee, plus Base's own L1 data fee for
    ///      this exact calldata.
    function _costMicroUsd(uint256 gasUsed, bytes memory callData)
        internal
        view
        returns (uint256 microUsd, uint256 l1FeeWei, uint256 l2FeeWei)
    {
        l2FeeWei = (gasUsed + INTRINSIC_GAS) * block.basefee;
        l1FeeWei = IGasPriceOracle(GAS_ORACLE).getL1Fee(callData);
        // wei * (usd * 1e8) / 1e18 => usd * 1e8 ; scale to micro-dollars (1e6).
        microUsd = ((l1FeeWei + l2FeeWei) * ethUsd8) / 1e20;
    }

    function _report(string memory label, uint256 gasUsed, bytes memory callData)
        internal
        view
    {
        (uint256 microUsd, uint256 l1, uint256 l2) = _costMicroUsd(gasUsed, callData);
        console2.log("---", label);
        console2.log("  l2 gas (incl. intrinsic):", gasUsed + INTRINSIC_GAS);
        console2.log("  l1 data fee (wei):       ", l1);
        console2.log("  l2 exec fee (wei):       ", l2);
        console2.log("  total cost (micro-USD):  ", microUsd);
    }

    function test_measure_settlement_costs() public onFork {
        console2.log("=== Base mainnet, block", block.number);
        console2.log("l2 base fee (wei):", block.basefee);
        console2.log("ETH/USD (1e8):    ", ethUsd8);

        // 1. The floor. Any settlement design must beat a bare token transfer,
        //    because a bare transfer is already a settlement.
        //    Cold: the payee holds no USDC yet, so their balance slot goes from
        //    zero to non-zero. This is the honest case for a new counterparty
        //    and costs far more than paying somebody you have paid before.
        address coldPayee = makeAddr("coldPayee");
        bytes memory transferData =
            abi.encodeCall(IERC20.transfer, (coldPayee, 10_000));
        vm.prank(buyer);
        uint256 g0 = gasleft();
        usdc.transfer(coldPayee, 10_000);
        uint256 coldTransfer = g0 - gasleft();
        _report("USDC transfer, new payee (cold)", coldTransfer, transferData);

        // Warm: the payee already holds USDC. The repeat-business case, and the
        // one a channel would actually be competing against for an agent that
        // calls the same provider many times.
        vm.prank(buyer);
        g0 = gasleft();
        usdc.transfer(coldPayee, 10_000);
        uint256 warmTransfer = g0 - gasleft();
        _report("USDC transfer, repeat payee (warm)", warmTransfer, transferData);

        // 2. The current model, for contrast. Escrow is not what a micropayment
        //    would use, but it sets the number a channel has to improve on.
        bytes32 id = keccak256("gas-measurement");
        bytes memory createData = abi.encodeCall(
            AgoreumEscrow.createEscrow,
            (id, provider, USDC, 1_000e6, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW)
        );
        vm.prank(buyer);
        g0 = gasleft();
        escrow.createEscrow(
            id, provider, USDC, 1_000e6, DELIVERY_WINDOW, AUTO_RELEASE_WINDOW
        );
        uint256 createGas = g0 - gasleft();
        _report("escrow createEscrow + fund", createGas, createData);

        bytes memory releaseData = abi.encodeCall(AgoreumEscrow.release, (id));
        vm.prank(buyer);
        g0 = gasleft();
        escrow.release(id);
        uint256 releaseGas = g0 - gasleft();
        _report("escrow release", releaseGas, releaseData);

        (uint256 createUsd,,) = _costMicroUsd(createGas, createData);
        (uint256 releaseUsd,,) = _costMicroUsd(releaseGas, releaseData);
        (uint256 warmUsd,,) = _costMicroUsd(warmTransfer, transferData);
        console2.log("=== escrow round trip (micro-USD):", createUsd + releaseUsd);
        console2.log("=== direct warm transfer (micro-USD):", warmUsd);

        // A zero here would mean nothing was measured, and a zero cost would
        // read as "settlement is free" rather than as a broken harness.
        assertGt(warmUsd, 0, "measured a zero cost, which means nothing was measured");

        // The standing guard on the decision itself.
        //
        // docs/micropayment-settlement-cost.md concludes that no payment channel
        // should be built, and that conclusion is only true while direct
        // settlement stays cheap. A document asserting an outcome is unproven
        // until something checks it, so this checks it on every run.
        //
        // One cent, against a measured 253 micro-USD, is roughly 40x headroom.
        // It is not a performance target and tightening it would make the suite
        // flap on ordinary gas movement. It is the point at which the channel
        // question genuinely reopens and somebody should be told.
        assertLt(
            warmUsd,
            CHANNEL_RECONSIDERATION_THRESHOLD,
            "a direct settlement now costs more than a cent, so the conclusion in "
            "docs/micropayment-settlement-cost.md that no payment channel is needed "
            "no longer follows from the numbers it was based on"
        );
    }
}
