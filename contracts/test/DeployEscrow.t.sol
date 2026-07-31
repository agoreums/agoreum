// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";

import {AgoreumEscrow} from "../src/AgoreumEscrow.sol";
import {DeployEscrow} from "../script/DeployEscrow.s.sol";

/// @dev A deploy script that authorizes mainnet, exercising the opt-in branch
///      without toggling a process-global env var (which races under Foundry's
///      parallel test execution).
contract DeployEscrowMainnetAllowed is DeployEscrow {
    function _mainnetDeploymentAllowed() internal pure override returns (bool) {
        return true;
    }
}

/// @notice Tests the deployment script's own safety rails.
/// @dev Address env vars are namespaced per contract (ESCROW_*), so setting them
///      here does not race with the subscriptions deploy tests running in parallel.
contract DeployEscrowTest is Test {
    DeployEscrow internal script;

    address internal admin = makeAddr("admin");
    address internal arbiter = makeAddr("arbiter");
    address internal feeRecipient = makeAddr("feeRecipient");

    function setUp() public {
        script = new DeployEscrow();
    }

    function _configure(address admin_, address arbiter_, address feeRecipient_) internal {
        vm.setEnv("ESCROW_ADMIN_ADDRESS", vm.toString(admin_));
        vm.setEnv("ESCROW_ARBITER_ADDRESS", vm.toString(arbiter_));
        vm.setEnv("ESCROW_FEE_RECIPIENT", vm.toString(feeRecipient_));
        vm.setEnv("ESCROW_FEE_BPS", "250");
    }

    /// @dev The default that matters most: without the deliberate opt-in the script
    ///      refuses mainnet even when everything else is correctly configured.
    function test_refusesToDeployToBaseMainnet() public {
        _configure(admin, arbiter, feeRecipient);
        vm.chainId(8453);
        vm.expectRevert(
            abi.encodeWithSelector(DeployEscrow.MainnetDeploymentNotAuthorized.selector, 8453)
        );
        script.run();
    }

    function test_deploysToBaseMainnetWithExplicitOptIn() public {
        DeployEscrow allowed = new DeployEscrowMainnetAllowed();
        _configure(admin, arbiter, feeRecipient);
        vm.chainId(8453);
        AgoreumEscrow escrow = allowed.run();
        assertEq(escrow.feeBps(), 250);
        assertEq(escrow.feeRecipient(), feeRecipient);
        assertTrue(escrow.hasRole(escrow.ARBITER_ROLE(), arbiter));
        assertTrue(escrow.hasRole(escrow.GOVERNOR_ROLE(), admin));
    }

    function test_mainnetRefusesUnseparatedRoles() public {
        DeployEscrow allowed = new DeployEscrowMainnetAllowed();
        // Fee recipient collapsed onto the admin: separation of duties refused.
        _configure(admin, arbiter, admin);
        vm.chainId(8453);
        vm.expectRevert(
            abi.encodeWithSelector(
                DeployEscrow.RolesNotSeparated.selector,
                "ESCROW_ADMIN_ADDRESS",
                "ESCROW_FEE_RECIPIENT"
            )
        );
        allowed.run();
    }

    function test_deploysToBaseSepolia() public {
        _configure(admin, arbiter, feeRecipient);
        vm.chainId(84532);
        AgoreumEscrow escrow = script.run();

        assertEq(escrow.feeBps(), 250);
        assertEq(escrow.feeRecipient(), feeRecipient);
        assertTrue(escrow.hasRole(escrow.ARBITER_ROLE(), arbiter));
        assertTrue(escrow.hasRole(escrow.GOVERNOR_ROLE(), admin));
        assertTrue(escrow.hasRole(escrow.DEFAULT_ADMIN_ROLE(), admin));
    }

    function test_refusesWithoutRequiredConfiguration() public {
        _configure(admin, address(0), feeRecipient);
        vm.chainId(84532);
        vm.expectRevert(
            abi.encodeWithSelector(
                DeployEscrow.MissingConfiguration.selector, "ESCROW_ARBITER_ADDRESS"
            )
        );
        script.run();
    }

    function test_arbiterIsNotAutomaticallyAGovernor() public {
        // Separation of duties: whoever resolves disputes should not also be able
        // to change the fee or pause the contract.
        _configure(admin, arbiter, feeRecipient);
        vm.chainId(84532);
        AgoreumEscrow escrow = script.run();

        assertFalse(escrow.hasRole(escrow.GOVERNOR_ROLE(), arbiter));
        assertFalse(escrow.hasRole(escrow.DEFAULT_ADMIN_ROLE(), arbiter));
    }
}
