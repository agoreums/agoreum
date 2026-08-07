// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {Script} from "forge-std/Script.sol";
import {console} from "forge-std/console.sol";

import {AgoreumEscrow} from "../src/AgoreumEscrow.sol";

/// @notice Deploys AgoreumEscrow.
/// @dev Mainnet deployment is an explicit human decision taken after reviewing
///      testnet results and an audit. On Base mainnet the script refuses to run
///      unless `ALLOW_MAINNET_DEPLOY=true` is set deliberately, and even then it
///      enforces separation of duties: the admin, the dispute arbiter, and the fee
///      recipient must be three distinct addresses. On any test network it deploys
///      freely. The opt-in flag is a deliberate act at the command line, never a
///      default.
contract DeployEscrow is Script {
    uint256 internal constant BASE_MAINNET = 8453;
    uint256 internal constant BASE_SEPOLIA = 84532;

    error MainnetDeploymentNotAuthorized(uint256 chainId);
    error MissingConfiguration(string name);
    error RolesNotSeparated(string roleA, string roleB);

    function run() external returns (AgoreumEscrow escrow) {
        uint256 chainId = block.chainid;

        address admin = _requireAddress("ESCROW_ADMIN_ADDRESS");
        address arbiter = _requireAddress("ESCROW_ARBITER_ADDRESS");
        address feeRecipient = _requireAddress("ESCROW_FEE_RECIPIENT");
        uint256 feeBps = _configuredFeeBps();

        if (chainId == BASE_MAINNET) {
            if (!_mainnetDeploymentAllowed()) {
                revert MainnetDeploymentNotAuthorized(chainId);
            }
            // Separation of duties across the three privileged addresses.
            if (admin == arbiter) {
                revert RolesNotSeparated("ESCROW_ADMIN_ADDRESS", "ESCROW_ARBITER_ADDRESS");
            }
            if (admin == feeRecipient) {
                revert RolesNotSeparated("ESCROW_ADMIN_ADDRESS", "ESCROW_FEE_RECIPIENT");
            }
            if (arbiter == feeRecipient) {
                revert RolesNotSeparated("ESCROW_ARBITER_ADDRESS", "ESCROW_FEE_RECIPIENT");
            }
        }

        console.log("chain id      :", chainId);
        console.log("admin         :", admin);
        console.log("arbiter       :", arbiter);
        console.log("fee recipient :", feeRecipient);
        console.log("fee bps       :", feeBps);

        vm.startBroadcast();
        escrow = new AgoreumEscrow(admin, arbiter, feeRecipient, feeBps);
        vm.stopBroadcast();

        console.log("AgoreumEscrow :", address(escrow));

        // Verify the deployed state matches what was intended, rather than
        // assuming the constructor did what the arguments implied.
        require(escrow.feeBps() == feeBps, "fee mismatch after deployment");
        require(escrow.feeRecipient() == feeRecipient, "recipient mismatch");
        require(escrow.hasRole(escrow.ARBITER_ROLE(), arbiter), "arbiter role not granted");
        require(escrow.hasRole(escrow.GOVERNOR_ROLE(), admin), "governor role not granted");
    }

    function _requireAddress(string memory name) internal view returns (address value) {
        value = _configuredAddress(name);
        if (value == address(0)) revert MissingConfiguration(name);
    }

    /// @dev The fee, in basis points. Virtual for the same reason as
    ///      `_configuredAddress`: a test that reads this from the environment would
    ///      pass or fail depending on what happens to be in the developer's `.env`,
    ///      which Foundry loads automatically.
    function _configuredFeeBps() internal view virtual returns (uint256) {
        return vm.envOr("ESCROW_FEE_BPS", uint256(250));
    }

    /// @dev Where a configured address comes from. Split out and virtual for the
    ///      same reason as `_mainnetDeploymentAllowed` below: `vm.setEnv` writes to
    ///      the process environment, which every test in the run shares, and
    ///      Foundry executes tests in parallel. A suite where one test needs a
    ///      missing address and another needs a valid one is then racing itself,
    ///      and the loser fails with whichever error the other test's value
    ///      produced. Overriding this lets a test supply addresses directly, so no
    ///      global state is touched at all.
    function _configuredAddress(string memory name) internal view virtual returns (address) {
        return vm.envOr(name, address(0));
    }

    /// @dev Whether a Base mainnet deployment is authorized. Reads the deliberate
    ///      `ALLOW_MAINNET_DEPLOY` opt-in from the environment. It is a separate
    ///      method so tests can exercise the guard by overriding it, rather than
    ///      toggling a process-global variable that races under parallel testing.
    function _mainnetDeploymentAllowed() internal view virtual returns (bool) {
        return vm.envOr("ALLOW_MAINNET_DEPLOY", false);
    }
}
