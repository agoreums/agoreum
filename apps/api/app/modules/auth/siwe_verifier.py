"""EIP-4361 (Sign-In With Ethereum) message construction and verification.

This is the boundary where an unauthenticated string becomes a proven identity, so
every field is checked rather than trusted:

* **domain** must match this deployment. Without this check a signature harvested
  by a phishing site could be replayed here.
* **nonce** must be one this server issued, unexpired, and unconsumed. This is what
  makes a captured signature useless a second time.
* **chain_id** must be a chain we accept.
* **uri / issued_at / expiration_time** are validated by the reference parser.

Smart-contract wallets (EIP-1271) are supported when an RPC provider is configured:
Coinbase Smart Wallet and other account-abstraction wallets do not produce ECDSA
signatures that recover to the signing address, and would otherwise be locked out.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from siwe import (
    DomainMismatch,
    ExpiredMessage,
    InvalidSignature,
    MalformedSession,
    NonceMismatch,
    NotYetValidMessage,
    SiweMessage,
    VerificationError,
)

from app.core.config import settings
from app.core.errors import AuthenticationError
from app.core.logging import get_logger
from app.db.types import is_evm_address

logger = get_logger(__name__)

# Chains this deployment will accept a sign-in from. Base mainnet today; Base
# Sepolia is accepted outside production so the flow can be exercised on testnet.
BASE_MAINNET: Final = 8453
BASE_SEPOLIA: Final = 84532


def accepted_chain_ids() -> set[int]:
    if settings.is_production:
        return {settings.CHAIN_ID}
    return {settings.CHAIN_ID, BASE_MAINNET, BASE_SEPOLIA}


def build_message(
    *,
    address: str,
    nonce: str,
    chain_id: int,
    issued_at: datetime | None = None,
    expiration_time: datetime | None = None,
) -> str:
    """Build the exact EIP-4361 message the wallet will be asked to sign.

    The server constructs this rather than accepting a client-supplied message, so
    the statement a user sees is always one we authored.
    """
    if not is_evm_address(address):
        raise AuthenticationError("Invalid wallet address.")

    message = SiweMessage(
        domain=settings.SIWE_DOMAIN,
        # EIP-55 checksummed form is required by the specification's grammar.
        address=to_checksum_address(address),
        statement=settings.SIWE_STATEMENT,
        uri=settings.APP_URL,
        version="1",
        chain_id=chain_id,
        nonce=nonce,
        issued_at=(issued_at or datetime.now(UTC)).isoformat(),
        expiration_time=expiration_time.isoformat() if expiration_time else None,
    )
    return message.prepare_message()


def to_checksum_address(address: str) -> str:
    """EIP-55 checksum form, required by the EIP-4361 message grammar."""
    from eth_utils import to_checksum_address as _checksum

    return _checksum(address)


def parse_message(raw_message: str) -> SiweMessage:
    """Parse a client-supplied SIWE message, rejecting anything malformed."""
    try:
        return SiweMessage.from_message(raw_message)
    except Exception as exc:
        logger.warning("siwe_parse_failed", extra={"error_type": type(exc).__name__})
        raise AuthenticationError("The sign-in message is malformed.") from exc


def verify_signature(
    *,
    raw_message: str,
    signature: str,
    expected_nonce: str,
) -> tuple[str, int]:
    """Verify a SIWE signature end to end.

    Returns the lowercase address and chain id that were proven. Raises
    AuthenticationError on any failure, without disclosing which check failed, 
    an attacker probing the endpoint learns nothing from the response.
    """
    message = parse_message(raw_message)

    # Checked before signature verification: these are cheap, and rejecting a
    # wrong-domain or wrong-chain message early avoids doing crypto for a request
    # that can never succeed.
    if message.domain != settings.SIWE_DOMAIN:
        logger.warning("siwe_domain_mismatch", extra={"presented_domain": message.domain})
        raise AuthenticationError("This sign-in request was issued for another site.")

    if message.chain_id not in accepted_chain_ids():
        raise AuthenticationError(
            f"Chain {message.chain_id} is not supported. "
            f"Please switch your wallet to Base."
        )

    provider = _rpc_provider()

    try:
        message.verify(
            signature,
            domain=settings.SIWE_DOMAIN,
            nonce=expected_nonce,
            timestamp=datetime.now(UTC),
            # When present this enables EIP-1271 verification for contract wallets.
            provider=provider,
        )
    except NonceMismatch as exc:
        raise AuthenticationError("This sign-in request has expired.") from exc
    except (ExpiredMessage, NotYetValidMessage) as exc:
        raise AuthenticationError("This sign-in request has expired.") from exc
    except DomainMismatch as exc:
        raise AuthenticationError(
            "This sign-in request was issued for another site."
        ) from exc
    except (InvalidSignature, MalformedSession, VerificationError) as exc:
        logger.warning(
            "siwe_verification_failed", extra={"error_type": type(exc).__name__}
        )
        raise AuthenticationError("Signature verification failed.") from exc
    except Exception as exc:
        # An unexpected failure here (e.g. the RPC provider being unreachable
        # during an EIP-1271 check) must not be reported as a valid signature.
        logger.exception(
            "siwe_verification_error", extra={"error_type": type(exc).__name__}
        )
        raise AuthenticationError("Signature verification failed.") from exc

    return message.address.lower(), message.chain_id


def _rpc_provider():
    """An HTTP provider for EIP-1271 checks, or None when unconfigured.

    Returning None degrades to ECDSA-only verification. That is stated plainly
    rather than silently accepting contract-wallet signatures we cannot check.
    """
    # A complete endpoint including the key, resolved for the configured chain.
    rpc_url = settings.rpc_url
    if not rpc_url:
        return None

    try:
        from web3 import HTTPProvider
    except ImportError:  # pragma: no cover - web3 ships with siwe
        return None

    return HTTPProvider(rpc_url)


def supports_contract_wallets() -> bool:
    """Whether EIP-1271 verification is available in this deployment."""
    return _rpc_provider() is not None
