// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @title AgoreumEscrow
/// @notice Holds ERC-20 payment for a single engagement between a buyer and a
///         provider, and releases it only under defined settlement conditions.
///
/// @dev Design rules, in order of importance:
///
///      1. **The contract can never pay out more than it took in.** Every escrow
///         tracks `amount`, `released` and `refunded`, and the only functions
///         that move money assert `released + refunded <= amount`. This is the
///         same invariant the off-chain database enforces, restated where it is
///         actually authoritative.
///
///      2. **State is written before value moves.** Every payout follows
///         checks-effects-interactions and is additionally wrapped in a
///         reentrancy guard. The guard is defence in depth: correct ordering
///         alone already prevents reentrancy, but escrow balances are worth
///         belt and braces.
///
///      3. **Money is never trapped.** Every funded escrow has at least one
///         terminal path available to it at all times. If a provider never
///         delivers, the buyer can reclaim after the deadline without needing
///         anyone's cooperation, including the platform's.
///
///      4. **The platform is not a custodian.** The operator can resolve
///         disputes and set the fee, but has no function that moves funds to
///         itself beyond the fee agreed when the escrow was created, and cannot
///         alter the fee on an escrow that already exists.
///
///      Fee-on-transfer and rebasing tokens are deliberately unsupported: the
///      funding path records the balance actually received, and rejects any
///      token that delivers less than was sent. Supporting them silently would
///      make the accounting invariant unprovable.
contract AgoreumEscrow is AccessControl, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ---------------------------------------------------------------- Roles

    /// @notice May resolve disputes. Held by the platform's operations key.
    bytes32 public constant ARBITER_ROLE = keccak256("ARBITER_ROLE");

    /// @notice May pause new escrows and adjust the fee configuration.
    bytes32 public constant GOVERNOR_ROLE = keccak256("GOVERNOR_ROLE");

    // ----------------------------------------------------------------- Types

    enum Status {
        None, // never created
        Funded, // holding funds, work may proceed
        Released, // paid out to the provider (terminal)
        Refunded, // returned to the buyer (terminal)
        Disputed, // frozen pending arbitration
        Settled // split between both parties by an arbiter (terminal)
    }

    struct Escrow {
        address buyer;
        address provider;
        address token;
        uint256 amount; // gross, as actually received by this contract
        uint256 released; // paid to provider so far
        uint256 refunded; // returned to buyer so far
        uint256 feeBps; // frozen at creation; later changes cannot apply
        uint64 deliveryDeadline; // after this the buyer may reclaim unilaterally
        uint64 autoReleaseAt; // after this the provider may claim unilaterally
        Status status;
    }

    // ------------------------------------------------------------- Constants

    uint256 public constant BPS_DENOMINATOR = 10_000;

    /// @notice Hard ceiling on the platform fee, enforced at compile time.
    /// @dev A governor cannot raise the fee above this, so no future operator,
    ///      including a compromised one, can set a confiscatory rate.
    uint256 public constant MAX_FEE_BPS = 1_000; // 10%

    /// @notice Bounds on how long funds may sit before a unilateral path opens.
    uint64 public constant MIN_WINDOW = 1 hours;
    uint64 public constant MAX_WINDOW = 365 days;

    // --------------------------------------------------------------- Storage

    mapping(bytes32 escrowId => Escrow) private _escrows;

    /// @notice Where platform fees are sent.
    address public feeRecipient;

    /// @notice Fee applied to escrows created from now on, in basis points.
    uint256 public feeBps;

    /// @notice Total fees accrued per token, for reconciliation.
    mapping(address token => uint256) public feesCollected;

    // ---------------------------------------------------------------- Events

    event EscrowCreated(
        bytes32 indexed escrowId,
        address indexed buyer,
        address indexed provider,
        address token,
        uint256 amount,
        uint256 feeBps,
        uint64 deliveryDeadline,
        uint64 autoReleaseAt
    );
    event EscrowReleased(
        bytes32 indexed escrowId,
        address indexed provider,
        uint256 providerAmount,
        uint256 feeAmount,
        address releasedBy
    );
    event EscrowRefunded(
        bytes32 indexed escrowId, address indexed buyer, uint256 amount, address refundedBy
    );
    event EscrowDisputed(bytes32 indexed escrowId, address indexed raisedBy, string reason);
    event EscrowSettled(
        bytes32 indexed escrowId,
        uint256 providerAmount,
        uint256 buyerAmount,
        uint256 feeAmount,
        address arbiter
    );
    event FeeConfigUpdated(uint256 feeBps, address feeRecipient);

    // ---------------------------------------------------------------- Errors

    error EscrowAlreadyExists(bytes32 escrowId);
    error EscrowNotFound(bytes32 escrowId);
    error InvalidStatus(bytes32 escrowId, Status actual, Status required);
    error NotAuthorized(address caller);
    error InvalidAddress();
    error InvalidAmount();
    error InvalidWindow();
    error FeeTooHigh(uint256 requested, uint256 maximum);
    error DeadlineNotReached(uint64 deadline, uint64 currentTime);
    error SplitExceedsAmount(uint256 providerAmount, uint256 buyerAmount, uint256 amount);
    error UnsupportedToken(uint256 sent, uint256 received);

    // ----------------------------------------------------------- Constructor

    constructor(address admin, address arbiter, address feeRecipient_, uint256 feeBps_) {
        if (admin == address(0) || arbiter == address(0) || feeRecipient_ == address(0)) {
            revert InvalidAddress();
        }
        if (feeBps_ > MAX_FEE_BPS) revert FeeTooHigh(feeBps_, MAX_FEE_BPS);

        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(GOVERNOR_ROLE, admin);
        _grantRole(ARBITER_ROLE, arbiter);

        feeRecipient = feeRecipient_;
        feeBps = feeBps_;

        emit FeeConfigUpdated(feeBps_, feeRecipient_);
    }

    // ------------------------------------------------------------ Escrow API

    /// @notice Create and fund an escrow in a single transaction.
    /// @dev The caller must have approved this contract for `amount` first.
    ///      Funding and creation are deliberately not separable: an escrow that
    ///      exists but is unfunded is a state with no useful meaning and one
    ///      more path to get wrong.
    /// @param escrowId Caller-supplied identifier, unique per escrow. The
    ///        backend derives this from the order so the two can be reconciled
    ///        without trusting log ordering.
    function createEscrow(
        bytes32 escrowId,
        address provider,
        address token,
        uint256 amount,
        uint64 deliveryWindow,
        uint64 autoReleaseWindow
    ) external nonReentrant whenNotPaused {
        if (_escrows[escrowId].status != Status.None) {
            revert EscrowAlreadyExists(escrowId);
        }
        if (provider == address(0) || token == address(0)) revert InvalidAddress();
        if (provider == msg.sender) revert InvalidAddress();
        if (amount == 0) revert InvalidAmount();
        if (deliveryWindow < MIN_WINDOW || deliveryWindow > MAX_WINDOW) revert InvalidWindow();
        if (autoReleaseWindow < MIN_WINDOW || autoReleaseWindow > MAX_WINDOW) {
            revert InvalidWindow();
        }

        // Measure what actually arrived rather than trusting `amount`. A
        // fee-on-transfer token would deliver less, and crediting the requested
        // figure would let the contract promise more than it holds.
        IERC20 erc20 = IERC20(token);
        uint256 balanceBefore = erc20.balanceOf(address(this));
        erc20.safeTransferFrom(msg.sender, address(this), amount);
        uint256 received = erc20.balanceOf(address(this)) - balanceBefore;
        if (received != amount) revert UnsupportedToken(amount, received);

        uint64 nowTs = uint64(block.timestamp);
        uint64 deliveryDeadline = nowTs + deliveryWindow;
        uint64 autoReleaseAt = deliveryDeadline + autoReleaseWindow;

        _escrows[escrowId] = Escrow({
            buyer: msg.sender,
            provider: provider,
            token: token,
            amount: amount,
            released: 0,
            refunded: 0,
            // Frozen here. A later governor change cannot reprice work that has
            // already been agreed and paid for.
            feeBps: feeBps,
            deliveryDeadline: deliveryDeadline,
            autoReleaseAt: autoReleaseAt,
            status: Status.Funded
        });

        emit EscrowCreated(
            escrowId, msg.sender, provider, token, amount, feeBps, deliveryDeadline, autoReleaseAt
        );
    }

    /// @notice Release the full amount to the provider, less the platform fee.
    /// @dev Callable by the buyer at any time (accepting delivery), or by anyone
    ///      once `autoReleaseAt` has passed. The permissionless path after the
    ///      deadline is deliberate: a provider must not depend on the buyer, or
    ///      on the platform, remaining available in order to be paid.
    function release(bytes32 escrowId) external nonReentrant {
        Escrow storage escrow = _requireEscrow(escrowId);
        if (escrow.status != Status.Funded) {
            revert InvalidStatus(escrowId, escrow.status, Status.Funded);
        }

        // Deadlines here are hours to days apart. A validator can nudge
        // block.timestamp by seconds, which cannot move a decision either way.
        // forge-lint: disable-next-line(block-timestamp)
        bool autoReleaseDue = block.timestamp >= escrow.autoReleaseAt;
        if (msg.sender != escrow.buyer && !autoReleaseDue) {
            revert NotAuthorized(msg.sender);
        }

        uint256 amount = escrow.amount;
        uint256 fee = (amount * escrow.feeBps) / BPS_DENOMINATOR;
        uint256 providerAmount = amount - fee;

        // Effects first: the escrow is terminal before any token moves, so a
        // reentrant call finds Status.Released and reverts on the status check.
        escrow.released = amount;
        escrow.status = Status.Released;
        feesCollected[escrow.token] += fee;

        _assertSolvent(escrow);

        _payOut(escrow.token, escrow.provider, providerAmount);
        _payOut(escrow.token, feeRecipient, fee);

        emit EscrowReleased(escrowId, escrow.provider, providerAmount, fee, msg.sender);
    }

    /// @notice Return the full amount to the buyer.
    /// @dev Callable by the provider at any time (declining the work), or by the
    ///      buyer once the delivery deadline has passed without delivery. No fee
    ///      is taken on a refund: the platform did not broker a completed
    ///      engagement, so it has not earned anything.
    function refund(bytes32 escrowId) external nonReentrant {
        Escrow storage escrow = _requireEscrow(escrowId);
        if (escrow.status != Status.Funded) {
            revert InvalidStatus(escrowId, escrow.status, Status.Funded);
        }

        // Deadlines here are hours to days apart. A validator can nudge
        // block.timestamp by seconds, which cannot move a decision either way.
        // forge-lint: disable-next-line(block-timestamp)
        bool deliveryOverdue = block.timestamp >= escrow.deliveryDeadline;
        bool callerMayRefund =
            msg.sender == escrow.provider || (msg.sender == escrow.buyer && deliveryOverdue);
        if (!callerMayRefund) {
            if (msg.sender == escrow.buyer) {
                revert DeadlineNotReached(escrow.deliveryDeadline, uint64(block.timestamp));
            }
            revert NotAuthorized(msg.sender);
        }

        uint256 amount = escrow.amount;

        escrow.refunded = amount;
        escrow.status = Status.Refunded;

        _assertSolvent(escrow);

        _payOut(escrow.token, escrow.buyer, amount);

        emit EscrowRefunded(escrowId, escrow.buyer, amount, msg.sender);
    }

    /// @notice Freeze an escrow pending arbitration.
    /// @dev Either party may raise a dispute while funds are held. This closes
    ///      the unilateral auto-release path, which is the point: an unresolved
    ///      disagreement must not resolve itself in the provider's favour purely
    ///      by the passage of time.
    function dispute(bytes32 escrowId, string calldata reason) external whenNotPaused {
        Escrow storage escrow = _requireEscrow(escrowId);
        if (escrow.status != Status.Funded) {
            revert InvalidStatus(escrowId, escrow.status, Status.Funded);
        }
        if (msg.sender != escrow.buyer && msg.sender != escrow.provider) {
            revert NotAuthorized(msg.sender);
        }

        escrow.status = Status.Disputed;
        emit EscrowDisputed(escrowId, msg.sender, reason);
    }

    /// @notice Resolve a dispute by splitting the escrowed amount.
    /// @dev The only function an arbiter can use to move funds, and it cannot
    ///      distribute more than the escrow holds. The fee is taken only from
    ///      the provider's share, so a buyer who is refunded in full pays
    ///      nothing for the failed engagement.
    function settleDispute(bytes32 escrowId, uint256 providerAmount, uint256 buyerAmount)
        external
        nonReentrant
        onlyRole(ARBITER_ROLE)
    {
        Escrow storage escrow = _requireEscrow(escrowId);
        if (escrow.status != Status.Disputed) {
            revert InvalidStatus(escrowId, escrow.status, Status.Disputed);
        }

        uint256 amount = escrow.amount;
        // Unchecked addition would be safe under 0.8 anyway; the explicit check
        // exists so the failure is a named error rather than a panic.
        if (providerAmount > amount || buyerAmount > amount - providerAmount) {
            revert SplitExceedsAmount(providerAmount, buyerAmount, amount);
        }

        uint256 fee = (providerAmount * escrow.feeBps) / BPS_DENOMINATOR;
        uint256 providerNet = providerAmount - fee;
        // Any rounding dust left by an uneven split stays with the buyer rather
        // than accruing silently to the platform.
        uint256 buyerTotal = amount - providerAmount;

        escrow.released = providerAmount;
        escrow.refunded = buyerTotal;
        escrow.status = Status.Settled;
        feesCollected[escrow.token] += fee;

        _assertSolvent(escrow);

        if (providerNet > 0) _payOut(escrow.token, escrow.provider, providerNet);
        if (buyerTotal > 0) _payOut(escrow.token, escrow.buyer, buyerTotal);
        if (fee > 0) _payOut(escrow.token, feeRecipient, fee);

        emit EscrowSettled(escrowId, providerNet, buyerTotal, fee, msg.sender);
    }

    // ------------------------------------------------------------- Governance

    /// @notice Update the fee taken on escrows created after this call.
    /// @dev Existing escrows keep the fee they were created with.
    function setFeeConfig(uint256 newFeeBps, address newRecipient)
        external
        onlyRole(GOVERNOR_ROLE)
    {
        if (newFeeBps > MAX_FEE_BPS) {
            revert FeeTooHigh(newFeeBps, MAX_FEE_BPS);
        }
        if (newRecipient == address(0)) revert InvalidAddress();

        feeBps = newFeeBps;
        feeRecipient = newRecipient;
        emit FeeConfigUpdated(newFeeBps, newRecipient);
    }

    /// @notice Stop new escrows being created.
    /// @dev Pausing deliberately does not block `release`, `refund` or
    ///      `settleDispute`. Funds already committed must always be able to
    ///      reach a terminal state, even while the platform is halted, a pause
    ///      that could strand money would be a custody risk, not a safety
    ///      mechanism.
    function pause() external onlyRole(GOVERNOR_ROLE) {
        _pause();
    }

    /// @notice Resume accepting new escrows.
    /// @dev Pausing never blocked release, refund or settlement, so unpausing
    ///      restores only the ability to create new ones.
    function unpause() external onlyRole(GOVERNOR_ROLE) {
        _unpause();
    }

    // ------------------------------------------------------------------ Views

    /// @notice The full escrow record.
    /// @dev Returns a zeroed struct for an unknown id, whose `status` is
    ///      `Status.None`. Callers must check that rather than assuming a zeroed
    ///      record is a funded one with zero amount.
    /// @param escrowId The escrow to read.
    function getEscrow(bytes32 escrowId) external view returns (Escrow memory) {
        return _escrows[escrowId];
    }

    /// @notice The lifecycle state of an escrow.
    /// @dev `Status.None` means it was never created, which is distinct from any
    ///      terminal state.
    /// @param escrowId The escrow to read.
    function statusOf(bytes32 escrowId) external view returns (Status) {
        return _escrows[escrowId].status;
    }

    /// @notice Amount still held by the contract for this escrow.
    function outstanding(bytes32 escrowId) external view returns (uint256) {
        Escrow storage escrow = _escrows[escrowId];
        return escrow.amount - escrow.released - escrow.refunded;
    }

    /// @notice Whether the provider can currently be paid without the buyer.
    function autoReleaseAvailable(bytes32 escrowId) external view returns (bool) {
        Escrow storage escrow = _escrows[escrowId];
        // forge-lint: disable-next-line(block-timestamp)
        return escrow.status == Status.Funded && block.timestamp >= escrow.autoReleaseAt;
    }

    /// @notice Whether the buyer can currently reclaim without the provider.
    function refundAvailable(bytes32 escrowId) external view returns (bool) {
        Escrow storage escrow = _escrows[escrowId];
        // forge-lint: disable-next-line(block-timestamp)
        return escrow.status == Status.Funded && block.timestamp >= escrow.deliveryDeadline;
    }

    // -------------------------------------------------------------- Internals

    function _requireEscrow(bytes32 escrowId) private view returns (Escrow storage) {
        Escrow storage escrow = _escrows[escrowId];
        if (escrow.status == Status.None) revert EscrowNotFound(escrowId);
        return escrow;
    }

    /// @dev The contract's central accounting invariant, asserted on every path
    ///      that moves money, immediately after the state write and before the
    ///      transfer. If this ever fails the transaction reverts and nothing
    ///      moves, so an accounting bug cannot become a loss of funds.
    function _assertSolvent(Escrow storage escrow) private view {
        assert(escrow.released + escrow.refunded <= escrow.amount);
    }

    function _payOut(address token, address to, uint256 value) private {
        if (value == 0) return;
        IERC20(token).safeTransfer(to, value);
    }
}
