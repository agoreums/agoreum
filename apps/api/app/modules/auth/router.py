"""Authentication endpoints.

The sign-in flow is:

    1. POST /auth/nonce    → server issues a single-use nonce (and the message)
    2. wallet signs the message
    3. POST /auth/signin   → server verifies, creates the user if new, returns tokens
    4. POST /auth/refresh  → rotates the refresh token before the access token dies
    5. POST /auth/logout   → revokes the session
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import CurrentUser, DbSession, client_ip, user_agent
from app.core.config import settings
from app.core.rate_limit import limiter
from app.modules.auth import service, siwe_verifier
from app.modules.auth.schemas import (
    AuthCapabilities,
    EmailVerificationConfirm,
    EmailVerificationStatus,
    LogoutRequest,
    NonceRequest,
    NonceResponse,
    ProfileUpdate,
    RefreshRequest,
    SessionSummary,
    SignInRequest,
    SignInResponse,
    TokenResponse,
    UserProfile,
    WalletSummary,
)
from app.modules.notifications import events as notification_events
from app.modules.notifications import service as notifications_service

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get(
    "/capabilities",
    response_model=AuthCapabilities,
    summary="What this deployment can verify",
)
async def capabilities() -> AuthCapabilities:
    return AuthCapabilities(
        siwe_domain=settings.SIWE_DOMAIN,
        accepted_chain_ids=sorted(siwe_verifier.accepted_chain_ids()),
        contract_wallets_supported=siwe_verifier.supports_contract_wallets(),
        nonce_ttl_seconds=settings.SIWE_NONCE_TTL_SECONDS,
    )


@router.post(
    "/nonce",
    response_model=NonceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a sign-in nonce",
    dependencies=[Depends(limiter("auth:nonce"))],
)
async def request_nonce(payload: NonceRequest, db: DbSession) -> NonceResponse:
    """Issue a single-use nonce, and the exact message to sign when possible.

    Building the message server-side means the statement the user approves in
    their wallet is always one this service authored.
    """
    nonce = await service.issue_nonce(db, address=payload.address)

    message = None
    if payload.address:
        message = service.build_challenge(
            address=payload.address,
            nonce=nonce.nonce,
            chain_id=payload.chain_id,
        )

    return NonceResponse(
        nonce=nonce.nonce, expires_at=nonce.expires_at, message=message
    )


@router.post(
    "/signin",
    response_model=SignInResponse,
    summary="Verify a signature and start a session",
    dependencies=[Depends(limiter("auth:signin"))],
)
async def sign_in(
    payload: SignInRequest, request: Request, db: DbSession
) -> SignInResponse:
    user, tokens = await service.sign_in(
        db,
        message=payload.message,
        signature=payload.signature,
        nonce=payload.nonce,
        user_agent=user_agent(request),
        ip_address=client_ip(request),
        wallet_provider=payload.wallet_provider,
    )
    return SignInResponse(
        user=UserProfile.model_validate(user),
        tokens=TokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_at=tokens.access_expires_at,
            refresh_expires_at=tokens.refresh_expires_at,
        ),
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate the refresh token",
    dependencies=[Depends(limiter("auth:refresh"))],
)
async def refresh(
    payload: RefreshRequest, request: Request, db: DbSession
) -> TokenResponse:
    """Exchange a refresh token for a new pair.

    The presented token is always retired, whether or not the caller uses the new
    one. Presenting a retired token again is treated as theft and revokes every
    session for that user.
    """
    _, tokens = await service.refresh_session(
        db,
        refresh_token=payload.refresh_token,
        user_agent=user_agent(request),
        ip_address=client_ip(request),
    )
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_at=tokens.access_expires_at,
        refresh_expires_at=tokens.refresh_expires_at,
    )


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End session(s)"
)
async def logout(
    request: Request, payload: LogoutRequest, user: CurrentUser, db: DbSession
) -> None:
    """End the caller's session, or every session they have.

    The third branch is not a nicety. With neither field set this used to fall
    through and return 204, reporting success while revoking nothing, which is
    the opposite of what LogoutRequest documents and the worst possible answer
    for a security endpoint. The site always sends the refresh token so browsers
    were unaffected, but any SDK that did not hold one was told it had signed out
    while the session stayed valid for its full thirty days.

    An access token is proof enough to end its own session, so the current
    session id is used when no refresh token is supplied.
    """
    if payload.all_sessions:
        await service.revoke_all_sessions(db, user_id=user.id)
    elif payload.refresh_token:
        await service.revoke_session(db, refresh_token=payload.refresh_token)
    else:
        session_id = getattr(request.state, "session_id", None)
        if session_id:
            await service.revoke_session_by_id(
                db, session_id=uuid.UUID(session_id), user_id=user.id
            )


@router.post(
    "/me/email/verify",
    response_model=EmailVerificationStatus,
    summary="Request an email verification link",
    dependencies=[Depends(limiter("auth:verify-email"))],
)
async def request_email_verification(
    user: CurrentUser, db: DbSession
) -> EmailVerificationStatus:
    """Send a verification link to the address on your profile.

    Rate limited hard, because this is the one endpoint that causes mail to be
    sent to an address the caller chose. Without a tight limit it is a way to
    repeatedly mail a stranger using this domain's reputation.

    Nothing is delivered yet: no code calls the notifier, and email sending is
    off. The token is minted and stored so the flow is complete and testable, and
    delivery is wired separately. Until then this returns sent=false rather than
    claiming a message went out, because reporting a send that did not happen is
    how someone ends up waiting for a link that will never arrive.
    """
    raw, _row = await service.issue_email_verification(db, user=user)
    await notification_events.email_verification_requested(db, user=user, token=raw)

    # Reports what actually happened rather than assuming. Delivery is gated on
    # EMAIL_SENDING_ENABLED and a configured key, so on a deployment without them
    # the notification row is written and suppressed. Saying "sent" there would
    # leave someone waiting for a link that was never going to arrive.
    can_send, reason = notifications_service.email_sending_available()
    return EmailVerificationStatus(
        sent=can_send,
        detail=(
            "Check your inbox for a confirmation link. It expires in 24 hours."
            if can_send
            else f"No message was sent: {reason}."
        ),
    )


@router.post(
    "/me/email/confirm",
    response_model=UserProfile,
    summary="Confirm an email address",
)
async def confirm_email_verification(
    payload: EmailVerificationConfirm, db: DbSession
) -> UserProfile:
    """Spend a verification token and mark the address proven.

    Deliberately unauthenticated. The token is the proof, and requiring a session
    as well would break the ordinary case of opening the link in whichever browser
    the inbox happens to be in. It is single use, expiring, and bound to the exact
    address it was issued for.
    """
    user = await service.confirm_email_verification(db, token=payload.token)
    return UserProfile.model_validate(user)


@router.get("/me", response_model=UserProfile, summary="The signed-in user")
async def me(user: CurrentUser) -> UserProfile:
    return UserProfile.model_validate(user)


@router.patch(
    "/me",
    response_model=UserProfile,
    summary="Update your profile",
)
async def update_me(
    payload: ProfileUpdate, user: CurrentUser, db: DbSession
) -> UserProfile:
    """Change your own profile: name, username, bio, avatar, email, or preferred
    language. Only the fields you send are altered. Changing your email clears its
    verification until it is proven again."""
    changes = payload.model_dump(exclude_unset=True)
    if changes:
        user = await service.update_profile(db, user=user, changes=changes)
    return UserProfile.model_validate(user)


@router.post(
    "/me/suspend",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Pause your account",
)
async def suspend_me(user: CurrentUser, db: DbSession) -> None:
    """Pause your own account and sign out everywhere. It stays paused until you
    sign in again, which restores it, no one else can lift it for you."""
    await service.suspend_own_account(db, user=user)


@router.get(
    "/me/wallets",
    response_model=list[WalletSummary],
    summary="Wallets linked to this account",
)
async def my_wallets(user: CurrentUser) -> list[WalletSummary]:
    return [WalletSummary.model_validate(w) for w in user.wallets]


@router.get(
    "/me/sessions",
    response_model=list[SessionSummary],
    summary="Active sessions",
)
async def my_sessions(user: CurrentUser, db: DbSession) -> list[SessionSummary]:
    sessions = await service.list_active_sessions(db, user_id=user.id)
    return [SessionSummary.model_validate(s) for s in sessions]
