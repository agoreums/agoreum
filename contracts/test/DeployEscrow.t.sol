// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";

import {AgoreumEscrow} from "../src/AgoreumEscrow.sol";
import {DeployEscrow} from "../script/DeployEscrow.s.sol";

/// @notice Tests the deployment script's own safety rails.
contract DeployEscrowTest is Test {
    DeployEscrow internal script;

    address internal admin = makeAddr("admin");
    address internal arbiter = makeAddr("arbiter");
    address internal feeRecipient = makeAddr("feeRecipient");

    function setUp() public {
        script = new DeployEscrow();
        vm.setEnv("ESCROW_ADMIN_ADDRESS", vm.toString(admin));
        vm.setEnv("ESCROW_ARBITER_ADDRESS", vm.toString(arbiter));
        vm.setEnv("ESCROW_FEE_RECIPIENT", vm.toString(feeRecipient));
        vm.setEnv("ESCROW_FEE_BPS", "250");
    }

    /// @dev The guard that matters most: the script must refuse mainnet even
    ///      when everything else is correctly configured.
    function test_refusesToDeployToBaseMainnet() public {
        vm.chainId(8453);
        vm.expectRevert(
            abi.encodeWithSelector(DeployEscrow.MainnetDeploymentNotAuthorized.selector, 8453)
        );
        script.run();
    }

    function test_deploysToBaseSepolia() public {
        vm.chainId(84532);
        AgoreumEscrow escrow = script.run();

        assertEq(escrow.feeBps(), 250);
        assertEq(escrow.feeRecipient(), feeRecipient);
        assertTrue(escrow.hasRole(escrow.ARBITER_ROLE(), arbiter));
        assertTrue(escrow.hasRole(escrow.GOVERNOR_ROLE(), admin));
        assertTrue(escrow.hasRole(escrow.DEFAULT_ADMIN_ROLE(), admin));
    }

    function test_refusesWithoutRequiredConfiguration() public {
        vm.chainId(84532);
        vm.setEnv("ESCROW_ARBITER_ADDRESS", vm.toString(address(0)));

        vm.expectRevert(
            abi.encodeWithSelector(
                DeployEscrow.MissingConfiguration.selector, "ESCROW_ARBITER_ADDRESS"
            )
        );
        script.run();
    }

    function test_arbiterIsNotAutomaticallyAGovernor() public {
        // Separation of duties: whoever resolves disputes should not also be
        // able to change the fee or pause the contract.
        vm.chainId(84532);
        AgoreumEscrow escrow = script.run();

        assertFalse(escrow.hasRole(escrow.GOVERNOR_ROLE(), arbiter));
        assertFalse(escrow.hasRole(escrow.DEFAULT_ADMIN_ROLE(), arbiter));
    }
}
