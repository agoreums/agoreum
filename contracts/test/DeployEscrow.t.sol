// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {Test} from "forge-std/Test.sol";

import {AgoreumEscrow} from "../src/AgoreumEscrow.sol";
import {DeployEscrow} from "../script/DeployEscrow.s.sol";

/// @dev A deploy script whose configuration is supplied directly rather than read
///      from the environment.
///
///      `vm.setEnv` writes to the process environment, which every test in the run
///      shares, and Foundry executes tests in parallel. Namespacing the variables
///      per contract stopped the escrow and subscriptions suites fighting each
///      other, but not the tests *inside* one suite: one needs a missing arbiter,
///      another needs a valid one, and whichever wrote last decided what both saw.
///      That produced a real intermittent failure in
///      `test_mainnetRefusesUnseparatedRoles`, which reverted with
///      MissingConfiguration instead of RolesNotSeparated.
///
///      Holding the values here removes the shared state instead of racing for it,
///      so these tests are order-independent by construction.
contract DeployEscrowHarness is DeployEscrow {
    mapping(string => address) private _addresses;
    bool private _allowMainnet;

    function configure(address admin_, address arbiter_, address feeRecipient_) external {
        _addresses["ESCROW_ADMIN_ADDRESS"] = admin_;
        _addresses["ESCROW_ARBITER_ADDRESS"] = arbiter_;
        _addresses["ESCROW_FEE_RECIPIENT"] = feeRecipient_;
    }

    function allowMainnet(bool allowed) external {
        _allowMainnet = allowed;
    }

    function _configuredAddress(string memory name) internal view override returns (address) {
        return _addresses[name];
    }

    function _configuredFeeBps() internal pure override returns (uint256) {
        return 250;
    }

    function _mainnetDeploymentAllowed() internal view override returns (bool) {
        return _allowMainnet;
    }
}

/// @notice Tests the deployment script's own safety rails.
contract DeployEscrowTest is Test {
    DeployEscrowHarness internal script;

    address internal admin = makeAddr("admin");
    address internal arbiter = makeAddr("arbiter");
    address internal feeRecipient = makeAddr("feeRecipient");

    function setUp() public {
        script = new DeployEscrowHarness();
    }

    function _configure(address admin_, address arbiter_, address feeRecipient_) internal {
        script.configure(admin_, arbiter_, feeRecipient_);
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
        // Mainnet now requires the admin to have code, so this uses a contract
        // rather than the EOA it used before the guard existed.
        address contractAdmin = address(new DeployEscrowHarness());
        _configure(contractAdmin, arbiter, feeRecipient);
        script.allowMainnet(true);
        vm.chainId(8453);
        AgoreumEscrow escrow = script.run();
        assertEq(escrow.feeBps(), 250);
        assertEq(escrow.feeRecipient(), feeRecipient);
        assertTrue(escrow.hasRole(escrow.ARBITER_ROLE(), arbiter));
        assertTrue(escrow.hasRole(escrow.GOVERNOR_ROLE(), contractAdmin));
    }

    function test_mainnetRefusesUnseparatedRoles() public {
        // Fee recipient collapsed onto the admin: separation of duties refused.
        _configure(admin, arbiter, admin);
        script.allowMainnet(true);
        vm.chainId(8453);
        vm.expectRevert(
            abi.encodeWithSelector(
                DeployEscrow.RolesNotSeparated.selector,
                "ESCROW_ADMIN_ADDRESS",
                "ESCROW_FEE_RECIPIENT"
            )
        );
        script.run();
    }

    /// @dev Distinctness is satisfied by three fresh EOAs from one seed phrase,
    ///      which is separation on paper and none in custody. Mainnet requires the
    ///      admin to have code so that handing governance to a bare key is a
    ///      deliberate act rather than something nobody noticed.
    function test_mainnetRefusesAnEoaAdmin() public {
        _configure(admin, arbiter, feeRecipient);
        script.allowMainnet(true);
        vm.chainId(8453);
        vm.expectRevert(abi.encodeWithSelector(DeployEscrow.AdminMustBeAContract.selector, admin));
        script.run();
    }

    function test_mainnetAcceptsAContractAdmin() public {
        // Any contract satisfies the check. It is not a proof of multisig, and is
        // not claimed to be: it rules out the bare-EOA case, which is the one
        // that happens by accident.
        address contractAdmin = address(new DeployEscrowHarness());
        _configure(contractAdmin, arbiter, feeRecipient);
        script.allowMainnet(true);
        vm.chainId(8453);
        AgoreumEscrow escrow = script.run();
        assertTrue(escrow.hasRole(escrow.GOVERNOR_ROLE(), contractAdmin));
    }

    /// @dev The check is mainnet only, so a testnet rehearsal stays cheap.
    function test_testnetStillAcceptsAnEoaAdmin() public {
        _configure(admin, arbiter, feeRecipient);
        vm.chainId(84532);
        AgoreumEscrow escrow = script.run();
        assertTrue(escrow.hasRole(escrow.GOVERNOR_ROLE(), admin));
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
