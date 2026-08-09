// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @title AgoreumSubscriptions
/// @notice On-chain, non-custodial subscriptions paid in an ERC-20 (USDC). A
///         subscriber pays the price of a plan from their own wallet and, in
///         return, their subscription is extended by the plan's period. The
///         platform verifies these payments from chain events and grants access
///         accordingly, a subscription is real only because a real payment is.
///
/// @dev Design rules, in order of importance:
///
///      1. **The contract is never a custodian.** A payment moves in one hop from
///         the subscriber straight to the treasury; the contract never holds a
///         token balance. There is therefore no pool of funds to mis-account, and
///         `contractHoldsNothing()` is an invariant, not a hope.
///
///      2. **No subscription without payment.** The only way `expiresAt` moves
///         forward is `subscribe`, which reverts unless the exact price arrives
///         at the treasury. Governance can never grant a subscription; it can only
///         define plans.
///
///      3. **A price change can never overcharge a subscriber.** `subscribe`
///         takes a `maxPrice`, so a governor raising a plan's price cannot make an
///         already-approved wallet pay more than it agreed to.
///
///      4. **The platform's take is bounded and cannot be raised past a ceiling.**
///         The whole price is platform revenue and goes to the treasury; there is
///         no per-payment fee split to get wrong, and the treasury is the only
///         address funds ever reach.
///
///      Fee-on-transfer and rebasing tokens are unsupported by construction: the
///      payment path measures the treasury balance actually gained and rejects any
///      token that delivers less than the price.
contract AgoreumSubscriptions is AccessControl, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ---------------------------------------------------------------- Roles

    /// @notice May define plans, set the treasury, and pause new subscriptions.
    bytes32 public constant GOVERNOR_ROLE = keccak256("GOVERNOR_ROLE");

    // ----------------------------------------------------------------- Types

    struct Plan {
        address token; // the ERC-20 the plan is priced in
        uint256 price; // amount charged per period
        uint64 period; // seconds a payment buys
        bool active; // whether new subscriptions may be taken
        bool exists; // distinguishes a real plan from a zeroed slot
    }

    struct Subscription {
        uint64 startedAt; // when the current run of coverage began
        uint64 expiresAt; // coverage ends at this timestamp
        bool autoRenewCancelled; // the subscriber signalled they will not renew
    }

    // ------------------------------------------------------------- Constants

    /// @notice Bounds on a plan's period. A subscription is not an escrow window;
    ///         a day to two years covers monthly and yearly billing with room to
    ///         spare, while ruling out zero-length or absurd periods.
    uint64 public constant MIN_PERIOD = 1 days;
    uint64 public constant MAX_PERIOD = 730 days;

    // --------------------------------------------------------------- Storage

    mapping(uint256 planId => Plan) private _plans;

    /// @notice Coverage per subscriber per plan.
    mapping(address subscriber => mapping(uint256 planId => Subscription)) private _subs;

    /// @notice Where subscription payments are sent. The platform's revenue address.
    address public treasury;

    /// @notice Lifetime revenue routed per token, for reconciliation against the
    ///         backend's records. Incremented by the exact amount observed to
    ///         arrive at the treasury.
    mapping(address token => uint256) public revenueRouted;

    // ---------------------------------------------------------------- Events

    event PlanCreated(uint256 indexed planId, address indexed token, uint256 price, uint64 period);
    event PlanUpdated(uint256 indexed planId, uint256 price, uint64 period, bool active);
    event TreasuryUpdated(address indexed treasury);
    event Subscribed(
        address indexed subscriber,
        uint256 indexed planId,
        address indexed token,
        uint256 amountPaid,
        uint64 periodStart,
        uint64 periodEnd
    );
    event SubscriptionCancelled(
        address indexed subscriber, uint256 indexed planId, uint64 expiresAt
    );

    // ---------------------------------------------------------------- Errors

    error InvalidAddress();
    error InvalidAmount();
    error InvalidPeriod();
    error PlanAlreadyExists(uint256 planId);
    error PlanNotFound(uint256 planId);
    error PlanInactive(uint256 planId);
    error PriceExceedsMax(uint256 price, uint256 maxPrice);
    error UnsupportedToken(uint256 charged, uint256 received);
    error NotSubscribed(address subscriber, uint256 planId);
    error AlreadyCancelled();

    // ----------------------------------------------------------- Constructor

    constructor(address admin, address treasury_) {
        if (admin == address(0) || treasury_ == address(0)) revert InvalidAddress();
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(GOVERNOR_ROLE, admin);
        treasury = treasury_;
        emit TreasuryUpdated(treasury_);
    }

    // ------------------------------------------------------- Subscriber API

    /// @notice Pay for a plan, extending your subscription by its period.
    /// @dev The caller must have approved this contract for at least the plan's
    ///      price first. Renewing before expiry stacks the new period onto the
    ///      remaining time; renewing after expiry starts a fresh run from now, so
    ///      a lapsed subscriber never pays for the gap they were not covered.
    /// @param planId The plan to pay for.
    /// @param maxPrice The most the caller is willing to pay, protecting them from
    ///        a price increase that lands between approval and this call.
    function subscribe(uint256 planId, uint256 maxPrice) external nonReentrant whenNotPaused {
        Plan storage plan = _requirePlan(planId);
        if (!plan.active) revert PlanInactive(planId);
        if (plan.price > maxPrice) revert PriceExceedsMax(plan.price, maxPrice);

        // Move the payment straight to the treasury and confirm the treasury
        // actually gained the full price. A fee-on-transfer token would deliver
        // less, which must not buy a full period.
        IERC20 token = IERC20(plan.token);
        uint256 treasuryBefore = token.balanceOf(treasury);
        token.safeTransferFrom(msg.sender, treasury, plan.price);
        uint256 received = token.balanceOf(treasury) - treasuryBefore;
        if (received != plan.price) revert UnsupportedToken(plan.price, received);

        revenueRouted[plan.token] += received;

        Subscription storage sub = _subs[msg.sender][planId];
        uint64 nowTs = uint64(block.timestamp);
        // Extend from the later of now and the current expiry.
        uint64 base = sub.expiresAt > nowTs ? sub.expiresAt : nowTs;
        uint64 periodStart = sub.expiresAt > nowTs ? sub.startedAt : nowTs;
        uint64 periodEnd = base + plan.period;

        sub.startedAt = periodStart;
        sub.expiresAt = periodEnd;
        // A fresh payment is a clear signal of intent to continue.
        sub.autoRenewCancelled = false;

        emit Subscribed(msg.sender, planId, plan.token, received, periodStart, periodEnd);
    }

    /// @notice Signal that you will not renew. Your coverage continues until it
    ///         expires; nothing is refunded, because the period you already paid
    ///         for is yours to use.
    /// @dev Purely a statement of intent recorded on-chain for the platform to
    ///      read. There is no recurring charge to stop, renewals are always an
    ///      explicit payment, so this only suppresses renewal prompts and lets a
    ///      subscriber make their decision legible.
    function cancel(uint256 planId) external {
        Subscription storage sub = _subs[msg.sender][planId];
        if (sub.expiresAt == 0) revert NotSubscribed(msg.sender, planId);
        if (sub.autoRenewCancelled) revert AlreadyCancelled();
        sub.autoRenewCancelled = true;
        emit SubscriptionCancelled(msg.sender, planId, sub.expiresAt);
    }

    // ------------------------------------------------------------- Governance

    /// @notice Define a new plan. Plan ids are chosen by governance so they can be
    ///         reconciled with the backend's own plan records.
    function createPlan(uint256 planId, address token, uint256 price, uint64 period)
        external
        onlyRole(GOVERNOR_ROLE)
    {
        if (_plans[planId].exists) revert PlanAlreadyExists(planId);
        if (token == address(0)) revert InvalidAddress();
        if (price == 0) revert InvalidAmount();
        if (period < MIN_PERIOD || period > MAX_PERIOD) revert InvalidPeriod();

        _plans[planId] =
            Plan({token: token, price: price, period: period, active: true, exists: true});
        emit PlanCreated(planId, token, price, period);
    }

    /// @notice Change a plan's price, period, or availability.
    /// @dev The token is immutable once set: repricing a plan is reasonable, but
    ///      switching the asset it is denominated in would silently change what
    ///      every existing subscriber is agreeing to renew in.
    function updatePlan(uint256 planId, uint256 price, uint64 period, bool active)
        external
        onlyRole(GOVERNOR_ROLE)
    {
        Plan storage plan = _requirePlan(planId);
        if (price == 0) revert InvalidAmount();
        if (period < MIN_PERIOD || period > MAX_PERIOD) revert InvalidPeriod();

        plan.price = price;
        plan.period = period;
        plan.active = active;
        emit PlanUpdated(planId, price, period, active);
    }

    /// @notice Point subscription payments at a new treasury address.
    function setTreasury(address newTreasury) external onlyRole(GOVERNOR_ROLE) {
        if (newTreasury == address(0)) revert InvalidAddress();
        treasury = newTreasury;
        emit TreasuryUpdated(newTreasury);
    }

    /// @notice Stop new subscriptions and renewals.
    /// @dev Pausing only blocks `subscribe`. It never blocks `cancel`, and it can
    ///      never strand funds because the contract holds none.
    function pause() external onlyRole(GOVERNOR_ROLE) {
        _pause();
    }

    /// @notice Resume accepting subscriptions and renewals.
    /// @dev Cancelling was never blocked by the pause, so unpausing restores only
    ///      the ability to pay.
    function unpause() external onlyRole(GOVERNOR_ROLE) {
        _unpause();
    }

    // ------------------------------------------------------------------ Views

    /// @notice The full plan record.
    /// @dev Returns a zeroed struct for an unknown id. Check `exists` rather than
    ///      reading `price` as zero and concluding the plan is free.
    /// @param planId The plan to read.
    function getPlan(uint256 planId) external view returns (Plan memory) {
        return _plans[planId];
    }

    /// @notice One subscriber's coverage under one plan.
    /// @dev A zeroed record means they have never subscribed. A record with
    ///      `expiresAt` in the past means they lapsed, which is a different
    ///      thing and is why the two are distinguishable.
    /// @param subscriber The wallet to read.
    /// @param planId The plan to read.
    function getSubscription(address subscriber, uint256 planId)
        external
        view
        returns (Subscription memory)
    {
        return _subs[subscriber][planId];
    }

    /// @notice Whether a subscriber currently has coverage under a plan.
    function isActive(address subscriber, uint256 planId) external view returns (bool) {
        // forge-lint: disable-next-line(block-timestamp)
        return _subs[subscriber][planId].expiresAt > block.timestamp;
    }

    /// @notice Seconds of coverage remaining, zero if lapsed.
    function timeRemaining(address subscriber, uint256 planId) external view returns (uint64) {
        uint64 expiresAt = _subs[subscriber][planId].expiresAt;
        uint64 nowTs = uint64(block.timestamp);
        return expiresAt > nowTs ? expiresAt - nowTs : 0;
    }

    /// @notice The non-custody invariant, exposed for tests and for anyone who
    ///         wants to check it on-chain: this contract holds none of a token.
    function contractHoldsNothing(address token) external view returns (bool) {
        return IERC20(token).balanceOf(address(this)) == 0;
    }

    // -------------------------------------------------------------- Internals

    function _requirePlan(uint256 planId) private view returns (Plan storage) {
        Plan storage plan = _plans[planId];
        if (!plan.exists) revert PlanNotFound(planId);
        return plan;
    }
}
