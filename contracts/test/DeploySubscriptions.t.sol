// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";

import {AgoreumSubscriptions} from "../src/AgoreumSubscriptions.sol";
import {DeploySubscriptions} from "../script/DeploySubscriptions.s.sol";

contract DeploySubscriptionsTest is Test {
    DeploySubscriptions internal deployer;
    address internal admin = makeAddr("admin");
    address internal treasury = makeAddr("treasury");

    function setUp() public {
        deployer = new DeploySubscriptions();
        vm.setEnv("SUBSCRIPTIONS_ADMIN_ADDRESS", vm.toString(admin));
        vm.setEnv("SUBSCRIPTIONS_TREASURY_ADDRESS", vm.toString(treasury));
    }

    function test_refusesToDeployToBaseMainnet() public {
        vm.chainId(8453);
        vm.expectRevert(
            abi.encodeWithSelector(
                DeploySubscriptions.MainnetDeploymentNotAuthorized.selector, 8453
            )
        );
        deployer.run();
    }

    function test_deploysToBaseSepolia() public {
        vm.chainId(84532);
        AgoreumSubscriptions subs = deployer.run();
        assertEq(subs.treasury(), treasury);
        assertTrue(subs.hasRole(subs.GOVERNOR_ROLE(), admin));
        assertTrue(subs.hasRole(subs.DEFAULT_ADMIN_ROLE(), admin));
    }

    function test_refusesWithoutRequiredConfiguration() public {
        vm.chainId(84532);
        vm.setEnv("SUBSCRIPTIONS_TREASURY_ADDRESS", vm.toString(address(0)));
        vm.expectRevert(
            abi.encodeWithSelector(
                DeploySubscriptions.MissingConfiguration.selector, "SUBSCRIPTIONS_TREASURY_ADDRESS"
            )
        );
        deployer.run();
    }
}
