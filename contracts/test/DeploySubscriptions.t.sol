// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";

import {AgoreumSubscriptions} from "../src/AgoreumSubscriptions.sol";
import {DeploySubscriptions} from "../script/DeploySubscriptions.s.sol";

/// @dev A deploy script that authorizes mainnet, exercising the opt-in branch
///      without toggling a process-global env var (which races under Foundry's
///      parallel test execution).
contract DeploySubscriptionsMainnetAllowed is DeploySubscriptions {
    function _mainnetDeploymentAllowed() internal pure override returns (bool) {
        return true;
    }
}

/// @dev Address env vars are namespaced per contract (SUBSCRIPTIONS_*), so setting
///      them here does not race with the escrow deploy tests running in parallel.
contract DeploySubscriptionsTest is Test {
    DeploySubscriptions internal deployer;
    address internal admin = makeAddr("admin");
    address internal treasury = makeAddr("treasury");

    function setUp() public {
        deployer = new DeploySubscriptions();
    }

    function _configure(address admin_, address treasury_) internal {
        vm.setEnv("SUBSCRIPTIONS_ADMIN_ADDRESS", vm.toString(admin_));
        vm.setEnv("SUBSCRIPTIONS_TREASURY_ADDRESS", vm.toString(treasury_));
    }

    function test_refusesToDeployToBaseMainnet() public {
        _configure(admin, treasury);
        vm.chainId(8453);
        vm.expectRevert(
            abi.encodeWithSelector(
                DeploySubscriptions.MainnetDeploymentNotAuthorized.selector, 8453
            )
        );
        deployer.run();
    }

    function test_deploysToBaseMainnetWithExplicitOptIn() public {
        DeploySubscriptions allowed = new DeploySubscriptionsMainnetAllowed();
        _configure(admin, treasury);
        vm.chainId(8453);
        AgoreumSubscriptions subs = allowed.run();
        assertEq(subs.treasury(), treasury);
        assertTrue(subs.hasRole(subs.GOVERNOR_ROLE(), admin));
        assertTrue(subs.hasRole(subs.DEFAULT_ADMIN_ROLE(), admin));
    }

    function test_mainnetRefusesUnseparatedAdminAndTreasury() public {
        DeploySubscriptions allowed = new DeploySubscriptionsMainnetAllowed();
        // Governor and revenue address collapsed onto one address: refused.
        _configure(admin, admin);
        vm.chainId(8453);
        vm.expectRevert(
            abi.encodeWithSelector(
                DeploySubscriptions.RolesNotSeparated.selector,
                "SUBSCRIPTIONS_ADMIN_ADDRESS",
                "SUBSCRIPTIONS_TREASURY_ADDRESS"
            )
        );
        allowed.run();
    }

    function test_deploysToBaseSepolia() public {
        _configure(admin, treasury);
        vm.chainId(84532);
        AgoreumSubscriptions subs = deployer.run();
        assertEq(subs.treasury(), treasury);
        assertTrue(subs.hasRole(subs.GOVERNOR_ROLE(), admin));
        assertTrue(subs.hasRole(subs.DEFAULT_ADMIN_ROLE(), admin));
    }

    function test_refusesWithoutRequiredConfiguration() public {
        _configure(admin, address(0));
        vm.chainId(84532);
        vm.expectRevert(
            abi.encodeWithSelector(
                DeploySubscriptions.MissingConfiguration.selector, "SUBSCRIPTIONS_TREASURY_ADDRESS"
            )
        );
        deployer.run();
    }
}
