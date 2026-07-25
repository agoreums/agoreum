// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Script} from "forge-std/Script.sol";
import {console} from "forge-std/console.sol";

import {AgoreumSubscriptions} from "../src/AgoreumSubscriptions.sol";

/// @notice Deploys AgoreumSubscriptions.
/// @dev Refuses to run against Base mainnet, exactly like the escrow deploy.
///      Mainnet deployment of a payment surface is an explicit human decision to
///      be taken after reviewing testnet results and an audit; the script will
///      not perform it even if handed mainnet credentials by accident. Removing
///      this guard is itself a reviewable change, not a flag set under pressure.
contract DeploySubscriptions is Script {
    uint256 internal constant BASE_MAINNET = 8453;

    error MainnetDeploymentNotAuthorized(uint256 chainId);
    error MissingConfiguration(string name);

    function run() external returns (AgoreumSubscriptions subscriptions) {
        uint256 chainId = block.chainid;
        if (chainId == BASE_MAINNET) {
            revert MainnetDeploymentNotAuthorized(chainId);
        }

        address admin = _requireAddress("SUBSCRIPTIONS_ADMIN_ADDRESS");
        address treasury = _requireAddress("SUBSCRIPTIONS_TREASURY_ADDRESS");

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
}
