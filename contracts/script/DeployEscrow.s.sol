// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Script} from "forge-std/Script.sol";
import {console} from "forge-std/console.sol";

import {AgoreumEscrow} from "../src/AgoreumEscrow.sol";

/// @notice Deploys AgoreumEscrow.
/// @dev Deliberately refuses to run against Base mainnet. Mainnet deployment is
///      an explicit, human decision that must be taken after reviewing testnet
///      results, so the script will not perform it even if handed mainnet
///      credentials by accident. Removing this guard is itself a reviewable
///      change rather than a flag someone can set under time pressure.
contract DeployEscrow is Script {
    uint256 internal constant BASE_MAINNET = 8453;
    uint256 internal constant BASE_SEPOLIA = 84532;

    error MainnetDeploymentNotAuthorized(uint256 chainId);
    error MissingConfiguration(string name);

    function run() external returns (AgoreumEscrow escrow) {
        uint256 chainId = block.chainid;

        if (chainId == BASE_MAINNET) {
            revert MainnetDeploymentNotAuthorized(chainId);
        }

        address admin = _requireAddress("ESCROW_ADMIN_ADDRESS");
        address arbiter = _requireAddress("ESCROW_ARBITER_ADDRESS");
        address feeRecipient = _requireAddress("ESCROW_FEE_RECIPIENT");
        uint256 feeBps = vm.envOr("ESCROW_FEE_BPS", uint256(250));

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
        value = vm.envOr(name, address(0));
        if (value == address(0)) revert MissingConfiguration(name);
    }
}
