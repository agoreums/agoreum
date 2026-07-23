// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

import {AgoreumEscrow} from "../../src/AgoreumEscrow.sol";

/// @notice A standard 6-decimal token, matching USDC on Base.
contract MockUSDC is ERC20 {
    constructor() ERC20("USD Coin", "USDC") {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}

/// @notice A token that keeps a cut of every transfer.
/// @dev Used to prove the escrow *rejects* such tokens rather than silently
///      under-collateralising an escrow.
contract FeeOnTransferToken is ERC20 {
    uint256 public immutable feeBps;

    constructor(uint256 feeBps_) ERC20("Fee Token", "FEE") {
        feeBps = feeBps_;
    }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }

    function _update(address from, address to, uint256 value) internal override {
        if (from == address(0) || to == address(0)) {
            super._update(from, to, value);
            return;
        }
        uint256 fee = (value * feeBps) / 10_000;
        super._update(from, to, value - fee);
        if (fee > 0) super._update(from, address(0xdead), fee);
    }
}

/// @notice A token whose transfer hook calls back into the escrow.
/// @dev This is the reentrancy vector a real ERC-777-style or hook-bearing token
///      would present. `target` and `payload` are set by the test to whichever
///      escrow function is being attacked.
contract ReentrantToken is ERC20 {
    address public target;
    bytes public payload;
    bool public attacking;

    uint256 public reentryAttempts;
    bool public lastReentrySucceeded;
    bytes public lastReentryReturn;

    constructor() ERC20("Reentrant", "RE") {}

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }

    function arm(address target_, bytes calldata payload_) external {
        target = target_;
        payload = payload_;
        attacking = true;
    }

    function disarm() external {
        attacking = false;
    }

    function _update(address from, address to, uint256 value) internal override {
        super._update(from, to, value);

        // Re-enter only on the way out of the escrow, which is where a real
        // callback token would strike.
        if (attacking && from == target && target != address(0)) {
            attacking = false; // one attempt per transfer, so tests terminate
            reentryAttempts++;
            (bool ok, bytes memory ret) = target.call(payload);
            lastReentrySucceeded = ok;
            lastReentryReturn = ret;
        }
    }
}

/// @notice An external contract that attempts to re-enter the escrow directly.
contract ReentrancyAttacker {
    AgoreumEscrow public immutable escrow;
    bytes32 public escrowId;
    uint256 public attempts;
    bool public lastCallSucceeded;

    constructor(AgoreumEscrow escrow_) {
        escrow = escrow_;
    }

    function setEscrowId(bytes32 id) external {
        escrowId = id;
    }

    /// @dev Invoked as the payout recipient; tries to claim a second time.
    function attack() external {
        attempts++;
        try escrow.release(escrowId) {
            lastCallSucceeded = true;
        } catch {
            lastCallSucceeded = false;
        }
    }

    receive() external payable {}
}

/// @notice A token that silently returns false instead of reverting.
/// @dev SafeERC20 must turn this into a revert; if it did not, the escrow would
///      mark funds as paid that never moved.
contract SilentlyFailingToken is ERC20 {
    bool public failTransfers;

    constructor() ERC20("Silent", "SIL") {}

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }

    function setFailTransfers(bool value) external {
        failTransfers = value;
    }

    function transfer(address to, uint256 value) public override returns (bool) {
        if (failTransfers) return false;
        return super.transfer(to, value);
    }

    function transferFrom(address from, address to, uint256 value) public override returns (bool) {
        if (failTransfers) return false;
        return super.transferFrom(from, to, value);
    }
}
