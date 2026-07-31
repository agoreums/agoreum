// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Script} from "forge-std/Script.sol";
import {console} from "forge-std/console.sol";

import {AgoreumSubscriptions} from "../src/AgoreumSubscriptions.sol";

/// @notice Deploys AgoreumSubscriptions.
/// @dev Mainnet deployment of a payment surface is an explicit human decision to be
///      taken after reviewing testnet results and an audit. On Base mainnet the
///      script therefore refuses to run unless `ALLOW_MAINNET_DEPLOY=true` is set
///      deliberately, and even then it enforces separation of duties: the governor
///      admin must not also be the treasury that receives revenue. On any test
///      network it deploys freely. The opt-in flag is a deliberate act at the
///      command line, never a default.
contract DeploySubscriptions is Script {
    uint256 internal constant BASE_MAINNET = 8453;

    error MainnetDeploymentNotAuthorized(uint256 chainId);
    error MissingConfiguration(string name);
    error RolesNotSeparated(string roleA, string roleB);

    function run() external returns (AgoreumSubscriptions subscriptions) {
        uint256 chainId = block.chainid;

        address admin = _requireAddress("SUBSCRIPTIONS_ADMIN_ADDRESS");
        address treasury = _requireAddress("SUBSCRIPTIONS_TREASURY_ADDRESS");

        if (chainId == BASE_MAINNET) {
            if (!_mainnetDeploymentAllowed()) {
                revert MainnetDeploymentNotAuthorized(chainId);
            }
            // Separation of duties: whoever governs the contract must not also be
            // the address that collects subscription revenue.
            if (admin == treasury) {
                revert RolesNotSeparated(
                    "SUBSCRIPTIONS_ADMIN_ADDRESS", "SUBSCRIPTIONS_TREASURY_ADDRESS"
                );
            }
        }

        console.log("chain id :", chainId);
        console.log("admin    :", admin);
        console.log("treasury :", treasury);

        vm.startBroadcast();
        subscriptions = new AgoreumSubscriptions(admin, treasury);
        vm.stopBroadcast();

        console.log("AgoreumSubscriptions :", address(subscriptions));

        // Confirm the deployed state matches intent rather than assuming it.
        require(subscriptions.treasury() == treasury, "treasury mismatch");
        require(
            subscriptions.hasRole(subscriptions.GOVERNOR_ROLE(), admin), "governor role not granted"
        );
        require(
            subscriptions.hasRole(subscriptions.DEFAULT_ADMIN_ROLE(), admin),
            "admin role not granted"
        );
    }

    function _requireAddress(string memory name) internal view returns (address value) {
        value = vm.envOr(name, address(0));
        if (value == address(0)) revert MissingConfiguration(name);
    }

    /// @dev Whether a Base mainnet deployment is authorized. Reads the deliberate
    ///      `ALLOW_MAINNET_DEPLOY` opt-in from the environment. It is a separate
    ///      method so tests can exercise the guard by overriding it, rather than
    ///      toggling a process-global variable that races under parallel testing.
    function _mainnetDeploymentAllowed() internal view virtual returns (bool) {
        return vm.envOr("ALLOW_MAINNET_DEPLOY", false);
    }
}
