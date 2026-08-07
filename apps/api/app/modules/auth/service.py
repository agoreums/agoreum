"""Authentication service: nonces, sign-in, sessions, and refresh rotation."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.errors import AuthenticationError, ConflictError, PermissionDeniedError
from app.core.logging import get_logger
from app.db.enums import AccountStatus, WalletProvider, WalletVerificationStatus
from app.modules.auth import siwe_verifier
from app.modules.organizations import service as organizations_service
from app.modules.users.models import (
    EmailVerificationToken,
    Session,
    SiweNonce,
    User,
    Wallet,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    session_id: uuid.UUID


# --- Nonce lifecycle --------------------------------------------------------


async def issue_nonce(db: AsyncSession, *, address: str | None = None) -> SiweNonce:
    """Create a single-use nonce for a sign-in challenge.

    Binding the nonce to an address when one is supplied narrows the window
    further: a nonce issued for one wallet cannot be spent by another.
    """
    nonce = SiweNonce(
        nonce=security.generate_nonce(),
        address=address.lower() if address else None,
        expires_at=security.nonce_expiry(),
    )
    db.add(nonce)
    await db.flush()
    return nonce


async def consume_nonce(db: AsyncSession, *, nonce: str, address: str) -> None:
    """Atomically spend a nonce, or reject the sign-in.

    The conditional UPDATE is what makes this safe under concurrency: two requests
    racing with the same nonce cannot both match `consumed_at IS NULL`, so exactly
    one wins. Checking then updating in separate statements would leave a window
    in which a captured signature could be replayed.
    """
    now = datetime.now(UTC)
    result = await db.execute(
        update(SiweNonce)
        .where(
            SiweNonce.nonce == nonce,
            SiweNonce.consumed_at.is_(None),
            SiweNonce.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(SiweNonce.address)
    )
    row = result.first()

    if row is None:
        logger.warning("siwe_nonce_rejected")
        raise AuthenticationError(
            "This sign-in request has expired. Please try again.",
            code="nonce_invalid",
        )

    bound_address = row[0]
    if bound_address is not None and bound_address != address.lower():
        logger.warning("siwe_nonce_address_mismatch")
        raise AuthenticationError(
            "This sign-in request was issued for a different wallet."
        )


async def purge_expired_nonces(db: AsyncSession) -> int:
    """Delete nonces that can no longer be used. Safe to run repeatedly."""
    result = await db.execute(
        delete(SiweNonce).where(SiweNonce.expires_at < datetime.now(UTC))
    )
    return result.rowcount or 0


# --- Sign-in ----------------------------------------------------------------


async def sign_in(
    db: AsyncSession,
    *,
    message: str,
    signature: str,
    nonce: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
    wallet_provider: WalletProvider = WalletProvider.OTHER,
) -> tuple[User, IssuedTokens]:
    """Verify a SIWE signature and establish a session.

    The nonce is consumed *before* the signature is verified so that a failed
    verification still burns it. Otherwise an attacker could retry signatures
    against a single nonce indefinitely.
    """
    parsed = siwe_verifier.parse_message(message)
    claimed_address = parsed.address.lower()

    await consume_nonce(db, nonce=nonce, address=claimed_address)

    address, chain_id = siwe_verifier.verify_signature(
        raw_message=message, signature=signature, expected_nonce=nonce
    )

    user = await _get_or_create_user(db, address=address)

    if user.status in {
        AccountStatus.SUSPENDED_BY_ADMIN,
        AccountStatus.DEACTIVATED,
    }:
        logger.warning("signin_blocked", extra={"account_status": user.status.value})
        raise PermissionDeniedError(
            "This account is not permitted to sign in. Contact support if you "
            "believe this is a mistake.",
            code="account_suspended",
        )

    # Signing in from a self-suspended account restores it: the owner has just
    # proven control of the wallet, which is the strongest signal available.
    if user.status == AccountStatus.SUSPENDED_BY_USER:
        user.status = AccountStatus.ACTIVE

    await _ensure_wallet_record(
        db,
        user=user,
        address=address,
        chain_id=chain_id,
        message=message,
        provider=wallet_provider,
    )

    user.last_seen_at = datetime.now(UTC)

    tokens = await _create_session(
        db,
        user=user,
        address=address,
        chain_id=chain_id,
        user_agent=user_agent,
        ip_address=ip_address,
    )

    logger.info(
        "signin_succeeded",
        extra={"user_id": str(user.id), "chain_id": chain_id},
    )
    return user, tokens


async def _get_or_create_user(db: AsyncSession, *, address: str) -> User:
    existing = (
        await db.execute(select(User).where(User.primary_address == address))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    user = User(primary_address=address)
    db.add(user)
    await db.flush()
    # Every user gets a personal organization to hold their own agents.
    await organizations_service.ensure_personal_org(db, user=user)
    logger.info("user_registered", extra={"user_id": str(user.id)})
    return user


async def _ensure_wallet_record(
    db: AsyncSession,
    *,
    user: User,
    address: str,
    chain_id: int,
    message: str,
    provider: WalletProvider,
) -> Wallet:
    """Record the wallet as verified, the signature just proved control of it."""
    wallet = (
        await db.execute(
            select(Wallet).where(
                Wallet.address == address, Wallet.chain_id == chain_id
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC)

    if wallet is None:
        # The first verified wallet becomes the payout target, since the user has
        # no other proven address to be paid at.
        has_payout = (
            await db.execute(
                select(Wallet.id).where(
                    Wallet.user_id == user.id, Wallet.is_payout.is_(True)
                )
            )
        ).first() is not None

        wallet = Wallet(
            user_id=user.id,
            address=address,
            chain_id=chain_id,
            provider=provider,
            verification_status=WalletVerificationStatus.VERIFIED,
            verified_at=now,
            verification_message=message[:2048],
            is_payout=not has_payout,
        )
        db.add(wallet)
        await db.flush()
        return wallet

    if wallet.user_id != user.id:
        # The address/chain pair is unique platform-wide, so this means the wallet
        # is already claimed by another account.
        logger.warning("wallet_claimed_by_other_user")
        raise AuthenticationError(
            "This wallet is already linked to another account."
        )

    wallet.verification_status = WalletVerificationStatus.VERIFIED
    wallet.verified_at = now
    wallet.verification_message = message[:2048]
    wallet.provider = provider
    return wallet


# --- Sessions ---------------------------------------------------------------


async def _create_session(
    db: AsyncSession,
    *,
    user: User,
    address: str,
    chain_id: int,
    user_agent: str | None,
    ip_address: str | None,
) -> IssuedTokens:
    refresh_token = security.generate_refresh_token()
    session = Session(
        user_id=user.id,
        refresh_token_hash=security.hash_token(refresh_token),
        address=address,
        chain_id=chain_id,
        user_agent=(user_agent or "")[:512] or None,
        ip_address=ip_address,
        expires_at=security.refresh_token_expiry(),
    )
    db.add(session)
    await db.flush()

    access_token, access_expires_at = security.create_access_token(
        user_id=user.id,
        address=address,
        role=user.role.value,
        session_id=session.id,
    )

    return IssuedTokens(
        access_token=access_token,
        access_expires_at=access_expires_at,
        refresh_token=refresh_token,
        refresh_expires_at=session.expires_at,
        session_id=session.id,
    )


async def refresh_session(
    db: AsyncSession,
    *,
    refresh_token: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> tuple[User, IssuedTokens]:
    """Rotate a refresh token, issuing a new session and retiring the old one.

    Rotation with reuse detection: a spent token is retained in a revoked state.
    If one is presented again, the only explanations are theft or a replay, so
    every session for that user is revoked. Losing a legitimate session to a
    false positive is a far better outcome than leaving a stolen one alive.
    """
    token_hash = security.hash_token(refresh_token)
    session = (
        await db.execute(select(Session).where(Session.refresh_token_hash == token_hash))
    ).scalar_one_or_none()

    if session is None:
        raise AuthenticationError("Invalid session. Please sign in again.")

    if session.revoked_at is not None:
        if session.revoked_reason == "rotated":
            logger.warning(
                "refresh_token_reuse_detected", extra={"user_id": str(session.user_id)}
            )
            await revoke_all_sessions(
                db, user_id=session.user_id, reason="reuse_detected"
            )
            # Commit before raising. The request-scoped session rolls back on any
            # exception, which would otherwise undo the revocation we just made, 
            # leaving the stolen token's whole session family alive. The security
            # response has to outlive the failed request that triggered it.
            await db.commit()
        raise AuthenticationError("Invalid session. Please sign in again.")

    if session.expires_at <= datetime.now(UTC):
        session.revoked_at = datetime.now(UTC)
        session.revoked_reason = "expired"
        raise AuthenticationError("Your session has expired. Please sign in again.")

    user = (
        await db.execute(select(User).where(User.id == session.user_id))
    ).scalar_one_or_none()
    if user is None or user.status in {
        AccountStatus.SUSPENDED_BY_ADMIN,
        AccountStatus.DEACTIVATED,
    }:
        raise AuthenticationError("Invalid session. Please sign in again.")

    now = datetime.now(UTC)
    session.revoked_at = now
    session.revoked_reason = "rotated"

    tokens = await _create_session(
        db,
        user=user,
        address=session.address,
        chain_id=session.chain_id,
        user_agent=user_agent or session.user_agent,
        ip_address=ip_address or session.ip_address,
    )
    user.last_seen_at = now
    return user, tokens


async def revoke_session(db: AsyncSession, *, refresh_token: str) -> bool:
    """Sign out a single session. Returns whether anything was revoked."""
    now = datetime.now(UTC)
    result = await db.execute(
        update(Session)
        .where(
            Session.refresh_token_hash == security.hash_token(refresh_token),
            Session.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoked_reason="logout")
    )
    return (result.rowcount or 0) > 0


async def revoke_session_by_id(
    db: AsyncSession, *, session_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    """Sign out one session by its id. Returns whether anything was revoked.

    For logging out with only an access token in hand, which is the position an
    SDK is in when it never stored the refresh token. `user_id` is part of the
    predicate rather than assumed from the session id, so a caller can only ever
    end a session that is genuinely their own.
    """
    result = await db.execute(
        update(Session)
        .where(
            Session.id == session_id,
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC), revoked_reason="logout")
    )
    return (result.rowcount or 0) > 0


async def revoke_all_sessions(
    db: AsyncSession, *, user_id: uuid.UUID, reason: str = "logout_all"
) -> int:
    """Sign out every active session for a user."""
    now = datetime.now(UTC)
    result = await db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason=reason)
    )
    count = result.rowcount or 0
    logger.info(
        "sessions_revoked",
        extra={"user_id": str(user_id), "count": count, "reason": reason},
    )
    return count


async def list_active_sessions(
    db: AsyncSession, *, user_id: uuid.UUID
) -> list[Session]:
    result = await db.execute(
        select(Session)
        .where(
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
            Session.expires_at > datetime.now(UTC),
        )
        .order_by(Session.last_used_at.desc())
    )
    return list(result.scalars().all())


async def update_profile(
    db: AsyncSession, *, user: User, changes: dict[str, object]
) -> User:
    """Apply a partial update to a user's own profile.

    Only the keys present in ``changes`` are touched. Changing the email clears
    its verification, since a new address has not been proven. Uniqueness on the
    username and email is enforced by the database; a collision is reported as a
    conflict rather than surfacing as a raw integrity error.
    """
    if "email" in changes and changes["email"] != user.email:
        # A different address (including clearing it) invalidates any prior proof.
        user.email_verified_at = None

    for field, value in changes.items():
        setattr(user, field, value)

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        # The unique indexes on username and email are the authority.
        raise ConflictError(
            "That username or email is already taken.",
            code="profile_conflict",
        ) from exc

    await db.refresh(user)
    logger.info("profile_updated", extra={"user_id": str(user.id)})
    return user


async def suspend_own_account(db: AsyncSession, *, user: User) -> None:
    """Pause the caller's own account.

    A self-suspension the owner can lift simply by signing in again, which is why
    every session is revoked here: the account goes quiet until its owner returns
    and proves control of the wallet, at which point sign-in restores it.
    """
    user.status = AccountStatus.SUSPENDED_BY_USER
    await db.flush()
    await revoke_all_sessions(db, user_id=user.id, reason="self_suspended")
    logger.info("account_self_suspended", extra={"user_id": str(user.id)})


async def purge_expired_sessions(db: AsyncSession) -> int:
    """Delete sessions that expired long enough ago to be of no forensic value."""
    from datetime import timedelta

    cutoff = datetime.now(UTC) - timedelta(days=30)
    result = await db.execute(delete(Session).where(Session.expires_at < cutoff))
    return result.rowcount or 0


def build_challenge(*, address: str, nonce: str, chain_id: int | None = None) -> str:
    """Construct the message the wallet is asked to sign."""
    return siwe_verifier.build_message(
        address=address,
        nonce=nonce,
        chain_id=chain_id or settings.CHAIN_ID,
    )


# --- Email verification -----------------------------------------------------
#
# An address on a profile is only a string somebody typed until it is proven.
# Everything below exists so that "we have an email for this user" and "this user
# controls that email" stop being the same claim.

# A day is long enough for someone to find the message and short enough that a
# link sitting in an old inbox stops working.
EMAIL_VERIFICATION_TTL_HOURS = 24


async def issue_email_verification(
    db: AsyncSession, *, user: User
) -> tuple[str, EmailVerificationToken]:
    """Mint a verification token for the user's current address.

    Returns the raw token, which is the only time it exists in plaintext, and the
    stored row. The caller is responsible for delivering it; nothing here sends
    anything.

    Any earlier unused token for this user is consumed first. Otherwise asking for
    a fresh link would leave the previous one live, so a link captured from an old
    message would keep working after the user requested a replacement, which is
    usually exactly when they suspect the first one went astray.
    """
    if not user.email:
        raise ConflictError(
            "Add an email address before requesting verification.",
            code="email_missing",
        )
    if user.email_verified_at is not None:
        raise ConflictError(
            "That email address is already verified.", code="email_already_verified"
        )

    now = datetime.now(UTC)

    await db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )

    raw = security.generate_email_verification_token()
    row = EmailVerificationToken(
        user_id=user.id,
        email=user.email,
        token_hash=security.hash_token(raw),
        expires_at=now + timedelta(hours=EMAIL_VERIFICATION_TTL_HOURS),
    )
    db.add(row)
    await db.flush()

    logger.info("email_verification_issued", extra={"user_id": str(user.id)})
    return raw, row


async def confirm_email_verification(db: AsyncSession, *, token: str) -> User:
    """Spend a verification token and mark the address proven.

    The conditional UPDATE is what makes this safe under concurrency, the same
    reasoning as `consume_nonce`: two requests racing with one token cannot both
    match `consumed_at IS NULL`, so exactly one wins.

    The address is then compared against the one the token was issued for. A token
    proves control of that address and no other, so if the profile changed in the
    meantime this refuses rather than verifying an address nobody proved.
    """
    now = datetime.now(UTC)

    result = await db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.token_hash == security.hash_token(token),
            EmailVerificationToken.consumed_at.is_(None),
            EmailVerificationToken.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(EmailVerificationToken.user_id, EmailVerificationToken.email)
    )
    row = result.first()

    if row is None:
        logger.warning("email_verification_rejected")
        raise AuthenticationError(
            "That verification link is invalid or has expired. Request a new one.",
            code="verification_invalid",
        )

    user_id, issued_for = row
    user = await db.get(User, user_id)
    if user is None:
        raise AuthenticationError(
            "That verification link is invalid or has expired.",
            code="verification_invalid",
        )

    if not user.email or user.email != issued_for:
        # The address moved after the link was sent. Committing the spend is
        # deliberate: the token is burned either way, so a stale link cannot be
        # held and retried later.
        await db.commit()
        logger.warning("email_verification_address_changed", extra={"user_id": str(user.id)})
        raise ConflictError(
            "This link was sent to a different address than the one on your "
            "account. Request a new one.",
            code="verification_address_changed",
        )

    user.email_verified_at = now
    await db.flush()
    logger.info("email_verified", extra={"user_id": str(user.id)})
    return user


async def purge_expired_email_verifications(db: AsyncSession) -> int:
    """Delete tokens that can no longer be used. Safe to run repeatedly."""
    result = await db.execute(
        delete(EmailVerificationToken).where(
            EmailVerificationToken.expires_at < datetime.now(UTC)
        )
    )
    return result.rowcount or 0
