"""Webhook payload signing.

Each delivery carries an `X-Agoreum-Signature: t=<unix>,v1=<hex>` header. The
signature is HMAC-SHA256 over `"<timestamp>.<body>"` using the endpoint's secret.
Binding the timestamp into the signed string lets a receiver reject a replayed
delivery by checking the timestamp is recent, and signing the exact body lets them
confirm it was not altered in transit.

A receiver verifies by recomputing the HMAC with their copy of the secret and
comparing in constant time, the same computation `sign()` performs here.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

SECRET_PREFIX = "whsec_"  # noqa: S105 - a public prefix, not a credential


def generate_secret() -> str:
    """A signing secret, shown to the owner once and stored to sign with."""
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def sign(*, secret: str, timestamp: int, body: str) -> str:
    """The hex HMAC-SHA256 for a delivery, over "<timestamp>.<body>"."""
    signed = f"{timestamp}.{body}".encode()
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def signature_header(*, secret: str, timestamp: int, body: str) -> str:
    return f"t={timestamp},v1={sign(secret=secret, timestamp=timestamp, body=body)}"
