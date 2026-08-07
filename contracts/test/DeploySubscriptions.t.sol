// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {Test} from "forge-std/Test.sol";

import {AgoreumSubscriptions} from "../src/AgoreumSubscriptions.sol";
import {DeploySubscriptions} from "../script/DeploySubscriptions.s.sol";

/// @dev A deploy script whose configuration is supplied directly rather than read
///      from the environment. See the equivalent harness in DeployEscrow.t.sol for
///      the full reasoning: `vm.setEnv` writes to the shared process environment
///      and Foundry runs tests in parallel, so tests within one suite race each
///      other even when the variables are namespaced per contract.
contract DeploySubscriptionsHarness is DeploySubscriptions {
    mapping(string => address) private _addresses;
    bool private _allowMainnet;

    function configure(address admin_, address treasury_) external {
        _addresses["SUBSCRIPTIONS_ADMIN_ADDRESS"] = admin_;
        _addresses["SUBSCRIPTIONS_TREASURY_ADDRESS"] = treasury_;
    }

    function allowMainnet(bool allowed) external {
        _allowMainnet = allowed;
    }

    function _configuredAddress(string memory name) internal view override returns (address) {
        return _addresses[name];
    }

    function _mainnetDeploymentAllowed() internal view override returns (bool) {
        return _allowMainnet;
    }
}

contract DeploySubscriptionsTest is Test {
    DeploySubscriptionsHarness internal deployer;
    address internal admin = makeAddr("admin");
    address internal treasury = makeAddr("treasury");

    function setUp() public {
        deployer = new DeploySubscriptionsHarness();
    }

    function _configure(address admin_, address treasury_) internal {
        deployer.configure(admin_, treasury_);
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
        // Mainnet now requires a contract admin, as above.
        address contractAdmin = address(new DeploySubscriptionsHarness());
        _configure(contractAdmin, treasury);
        deployer.allowMainnet(true);
        vm.chainId(8453);
        AgoreumSubscriptions subs = deployer.run();
        assertEq(subs.treasury(), treasury);
        assertTrue(subs.hasRole(subs.GOVERNOR_ROLE(), contractAdmin));
        assertTrue(subs.hasRole(subs.DEFAULT_ADMIN_ROLE(), contractAdmin));
    }

    function test_mainnetRefusesUnseparatedAdminAndTreasury() public {
        // Governor and revenue address collapsed onto one address: refused.
        _configure(admin, admin);
        deployer.allowMainnet(true);
        vm.chainId(8453);
        vm.expectRevert(
            abi.encodeWithSelector(
                DeploySubscriptions.RolesNotSeparated.selector,
                "SUBSCRIPTIONS_ADMIN_ADDRESS",
                "SUBSCRIPTIONS_TREASURY_ADDRESS"
            )
        );
        deployer.run();
    }

    function test_deploysToBaseSepolia() public {
        // Testnet deliberately still accepts an EOA admin, so the rehearsal
        // stays cheap. The code requirement is mainnet only.
        _configure(admin, treasury);
        vm.chainId(84532);
        AgoreumSubscriptions subs = deployer.run();
        assertEq(subs.treasury(), treasury);
        assertTrue(subs.hasRole(subs.GOVERNOR_ROLE(), admin));
        assertTrue(subs.hasRole(subs.DEFAULT_ADMIN_ROLE(), admin));
    }

    /// @dev Same reasoning as the escrow: the admin can redirect all future
    ///      revenue in one transaction, so mainnet requires it to have code.
    function test_mainnetRefusesAnEoaAdmin() public {
        _configure(admin, treasury);
        deployer.allowMainnet(true);
        vm.chainId(8453);
        vm.expectRevert(
            abi.encodeWithSelector(DeploySubscriptions.AdminMustBeAContract.selector, admin)
        );
        deployer.run();
    }

    function test_mainnetAcceptsAContractAdmin() public {
        address contractAdmin = address(new DeploySubscriptionsHarness());
        _configure(contractAdmin, treasury);
        deployer.allowMainnet(true);
        vm.chainId(8453);
        AgoreumSubscriptions subs = deployer.run();
        assertTrue(subs.hasRole(subs.GOVERNOR_ROLE(), contractAdmin));
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
