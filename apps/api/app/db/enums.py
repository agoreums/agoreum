"""Domain enumerations.

These are persisted as native PostgreSQL enum types. Each member's *value* is the
stored representation and is part of the database contract — renaming one requires
a migration, so values are chosen to be stable and self-describing.
"""
from __future__ import annotations

import enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import Enum as SAEnum

# Python's built-in StrEnum (3.11+) already gives us `str` semantics and a `__str__`
# that returns the value, which is exactly what these need for JSON serialisation
# and for SQLAlchemy's native enum binding.
StrEnum = enum.StrEnum


# --- Accounts ---------------------------------------------------------------


class AccountStatus(StrEnum):
    """Lifecycle of any principal (user or agent) on the platform."""

    ACTIVE = "active"
    # Self-initiated pause; the account can restore itself.
    SUSPENDED_BY_USER = "suspended_by_user"
    # Administrative action; requires an admin to lift.
    SUSPENDED_BY_ADMIN = "suspended_by_admin"
    # Soft-deleted. Retained because on-chain history referencing it is immutable.
    DEACTIVATED = "deactivated"


class UserRole(StrEnum):
    """Platform-wide authorisation roles.

    Deliberately coarse. Fine-grained rights (e.g. "may edit this service") are
    ownership questions answered per-resource, not roles — encoding them here
    would make the model drift out of sync with reality.
    """

    USER = "user"
    ADMIN = "admin"


# --- Wallets ----------------------------------------------------------------


class WalletProvider(StrEnum):
    """How the wallet connection was established. Informational only.

    The platform is non-custodial: this records which connector the owner used,
    never anything that could reconstruct a key.
    """

    METAMASK = "metamask"
    COINBASE = "coinbase"
    WALLETCONNECT = "walletconnect"
    INJECTED = "injected"
    OTHER = "other"


class WalletVerificationStatus(StrEnum):
    """Whether control of the wallet has been cryptographically proven."""

    # Address recorded but no signature yet; cannot receive payouts.
    UNVERIFIED = "unverified"
    # Owner produced a valid signature over a server-issued nonce.
    VERIFIED = "verified"
    # Ownership proof withdrawn or invalidated.
    REVOKED = "revoked"


# --- Agents -----------------------------------------------------------------


class AgentStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class AgentVerificationTier(StrEnum):
    """How much has actually been proven about an agent.

    Tiers reflect verifiable facts only. There is no tier that can be bought, and
    none is granted without the corresponding proof having been performed.
    """

    # Registered, wallet signature proven. The floor for every agent.
    UNVERIFIED = "unverified"
    # Control of a claimed domain proven via DNS TXT or well-known endpoint.
    DOMAIN_VERIFIED = "domain_verified"
    # Domain verified and the operating entity confirmed by a human reviewer.
    ORGANIZATION_VERIFIED = "organization_verified"


# --- Services ---------------------------------------------------------------


class ServiceStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    # Temporarily not accepting orders; existing orders continue.
    UNAVAILABLE = "unavailable"
    # Withdrawn from the marketplace; existing orders continue to settlement.
    ARCHIVED = "archived"
    SUSPENDED = "suspended"


class PricingModel(StrEnum):
    """How a service's price is computed."""

    FIXED = "fixed"
    PER_UNIT = "per_unit"
    HOURLY = "hourly"
    # Price agreed per engagement; the order carries the negotiated amount.
    NEGOTIATED = "negotiated"


# --- Orders, escrow, settlement ---------------------------------------------


class OrderStatus(StrEnum):
    """Order lifecycle.

    An order is the off-chain record of an engagement. Money movement is tracked
    separately on the escrow record, because the two can legitimately diverge:
    a chain reorg or a stuck transaction must never silently rewrite order state.
    """

    # Created, awaiting on-chain funding of the escrow.
    PENDING_PAYMENT = "pending_payment"
    # Escrow funded and confirmed; provider may begin.
    FUNDED = "funded"
    IN_PROGRESS = "in_progress"
    # Provider asserts completion; awaiting buyer acceptance or auto-release.
    DELIVERED = "delivered"
    # Accepted and funds released. Terminal, and the only state that counts
    # toward reputation.
    COMPLETED = "completed"
    # Buyer raised a dispute before release.
    DISPUTED = "disputed"
    # Ended without delivery; escrowed funds returned.
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    # Escrow funding never arrived within the funding window.
    EXPIRED = "expired"


class EscrowStatus(StrEnum):
    """State of the on-chain escrow backing an order."""

    # Created off-chain; no on-chain escrow exists yet.
    NONE = "none"
    # Funding transaction broadcast, awaiting sufficient confirmations.
    FUNDING = "funding"
    FUNDED = "funded"
    # Release transaction broadcast, awaiting confirmations.
    RELEASING = "releasing"
    RELEASED = "released"
    REFUNDING = "refunding"
    REFUNDED = "refunded"
    # Contract-level dispute hold.
    DISPUTED = "disputed"
    # A broadcast transaction reverted or was dropped. Requires operator attention.
    FAILED = "failed"


class TransactionType(StrEnum):
    """What an on-chain transaction record represents."""

    ESCROW_FUND = "escrow_fund"
    ESCROW_RELEASE = "escrow_release"
    ESCROW_REFUND = "escrow_refund"
    PLATFORM_FEE = "platform_fee"
    # noqa comment: S105 matches the substring "TOKEN" in the member name; this
    # is an ERC-20 approval transaction type, not a credential.
    TOKEN_APPROVAL = "token_approval"  # noqa: S105


class TransactionStatus(StrEnum):
    """Confirmation state of a broadcast transaction.

    A transaction is only `CONFIRMED` after the configured confirmation depth. It
    can still move to `REORGED` afterwards, which is why this is tracked explicitly
    rather than being inferred from a receipt existing.
    """

    PENDING = "pending"
    CONFIRMED = "confirmed"
    # Mined but the EVM reverted it.
    REVERTED = "reverted"
    # Dropped from the mempool without being mined.
    DROPPED = "dropped"
    # Was confirmed, then removed by a chain reorganisation.
    REORGED = "reorged"


class DisputeResolution(StrEnum):
    RELEASED_TO_PROVIDER = "released_to_provider"
    REFUNDED_TO_BUYER = "refunded_to_buyer"
    SPLIT = "split"


# --- Reputation -------------------------------------------------------------


class ReviewStatus(StrEnum):
    PUBLISHED = "published"
    # Withdrawn by its author.
    WITHDRAWN = "withdrawn"
    # Removed by moderation. The score contribution is removed with it.
    REMOVED = "removed"


# --- Notifications ----------------------------------------------------------


class NotificationChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"


# --- Subscriptions ----------------------------------------------------------


class SubscriptionInterval(StrEnum):
    """Billing cadence of a subscription plan."""

    MONTHLY = "monthly"
    YEARLY = "yearly"


class NotificationCategory(StrEnum):
    """Groups notifications for per-category delivery preferences."""

    ORDER = "order"
    PAYMENT = "payment"
    MESSAGE = "message"
    REPUTATION = "reputation"
    SECURITY = "security"
    SYSTEM = "system"


class NotificationDeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    # Suppressed by the recipient's preferences; recorded rather than silently dropped.
    SUPPRESSED = "suppressed"


# --- Webhooks ---------------------------------------------------------------


class WebhookDeliveryStatus(StrEnum):
    """State of a single webhook delivery attempt record.

    A delivery is created `PENDING`, retried while `FAILED` until it either
    succeeds or exhausts its attempts (`EXHAUSTED`), and is `SUPPRESSED` when
    outbound delivery is disabled for the deployment — recorded, never silently
    dropped, so the intent is always visible.
    """

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXHAUSTED = "exhausted"
    SUPPRESSED = "suppressed"


# --- SQLAlchemy binding ------------------------------------------------------


def pg_enum(enum_class: type[enum.Enum], name: str, **kwargs: object) -> SAEnum:
    """Build a PostgreSQL native ENUM whose labels are the members' *values*.

    SQLAlchemy defaults to using member **names** as the enum labels, which would
    store `USER` where the application expects `user`. Passing `values_callable`
    is the only way to correct that, so every enum column in the platform is built
    through this helper rather than constructing `Enum(...)` directly.
    """
    from sqlalchemy import Enum as SAEnum

    return SAEnum(
        enum_class,
        name=name,
        native_enum=True,
        validate_strings=True,
        values_callable=lambda members: [m.value for m in members],
        **kwargs,
    )
