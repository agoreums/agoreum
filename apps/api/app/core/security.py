"""Security primitives: token generation, hashing, and JWT handling.

Two token types, with deliberately different properties:

* **Access token**, a short-lived signed JWT. Stateless, so every request can be
  authorised without touching the database. Cannot be revoked before it expires,
  which is precisely why it is short-lived.
* **Refresh token**, a long-lived opaque random string. Only its SHA-256 hash is
  ever stored, so a database disclosure yields nothing usable. It is rotated on
  every use, and reuse of a spent token is treated as theft.

No password hashing exists here because there are no passwords: identity is proven
by a wallet signature.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt

from app.core.config import settings
from app.core.errors import AuthenticationError

ALGORITHM = "HS256"

# Number of random bytes behind opaque tokens. 32 bytes = 256 bits, well beyond
# any feasible brute-force search.
TOKEN_ENTROPY_BYTES = 32


# --- Opaque tokens ----------------------------------------------------------


# EIP-4361 constrains the nonce to [a-zA-Z0-9], minimum 8 characters. A URL-safe
# token would include '-' and '_', which makes the resulting message unparseable
# by a spec-compliant wallet or verifier, and only some of the time, which is the
# worst kind of failure. The alphabet is therefore restricted explicitly.
NONCE_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
NONCE_LENGTH = 24  # ~143 bits of entropy


def generate_nonce() -> str:
    """A single-use, EIP-4361-compliant nonce for a SIWE challenge."""
    return "".join(secrets.choice(NONCE_ALPHABET) for _ in range(NONCE_LENGTH))


def generate_refresh_token() -> str:
    """A refresh token. Returned to the client once and never stored in the clear."""
    return secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


# A stable, greppable marker so a leaked key is recognisable in logs and secret
# scanners, and so authentication can reject anything not shaped like a key before
# spending a database lookup on it.
API_KEY_PREFIX = "ak_"


def generate_api_key() -> str:
    """A programmatic API key. Returned to its owner once; only its hash is stored."""
    return API_KEY_PREFIX + secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def generate_email_verification_token() -> str:
    """A single-use token proving control of an email address.

    URL-safe because it travels in a link. Same entropy as a refresh token: it is
    short-lived and single-use, but it is also emailed, so it passes through more
    hands than a token the client holds privately.
    """
    return secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 of an opaque token, hex-encoded.

    A plain hash is correct here (unlike for passwords): the input already has
    256 bits of entropy, so there is nothing for a slow KDF to protect against,
    and lookups must stay fast enough to run on every refresh.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(candidate: str, known_hash: str) -> bool:
    """Constant-time comparison, to avoid leaking a match through timing."""
    return secrets.compare_digest(hash_token(candidate), known_hash)


# --- JWT access tokens ------------------------------------------------------


def _secret() -> str:
    secret = settings.JWT_SECRET.get_secret_value()
    if not secret:
        # Failing loudly beats silently signing with an empty key.
        raise RuntimeError(
            "JWT_SECRET is not configured. Set it in the environment before starting."
        )
    if settings.is_production and len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters in production.")
    return secret


def create_access_token(
    *,
    user_id: uuid.UUID,
    address: str,
    role: str,
    session_id: uuid.UUID,
    expires_in: timedelta | None = None,
) -> tuple[str, datetime]:
    """Issue a signed access token. Returns the token and its expiry."""
    now = datetime.now(UTC)
    expires_at = now + (
        expires_in or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    claims: dict[str, Any] = {
        "sub": str(user_id),
        "adr": address,
        "role": role,
        "sid": str(session_id),
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": settings.APP_URL,
        # A unique id per token, so an individual token can be denylisted if ever
        # needed without invalidating the whole session.
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(claims, _secret(), algorithm=ALGORITHM), expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify and decode an access token, or raise AuthenticationError.

    Every failure mode returns the same generic message: telling a caller whether
    a token was expired, malformed, or forged is information they do not need.
    """
    try:
        claims = jwt.decode(
            token,
            _secret(),
            algorithms=[ALGORITHM],
            issuer=settings.APP_URL,
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError(
            "Your session has expired. Please sign in again.",
            code="token_expired",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid authentication token.") from exc

    if claims.get("typ") != "access":
        raise AuthenticationError("Invalid authentication token.")

    return claims


# --- Expiry helpers ---------------------------------------------------------


def refresh_token_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)


def nonce_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=settings.SIWE_NONCE_TTL_SECONDS)


RevocationReason = Literal[
    "logout", "logout_all", "rotated", "reuse_detected", "expired", "admin"
]
