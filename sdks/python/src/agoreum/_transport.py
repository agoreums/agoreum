"""Transport concerns shared by the sync and async clients.

Kept deliberately free of any I/O so both clients reuse exactly the same header,
parameter, retry, and error-decoding logic, only the httpx call itself differs.
"""
from __future__ import annotations

import random
from enum import Enum
from typing import Any

from ._version import __version__

DEFAULT_BASE_URL = "https://agoreum.xyz/api/v1"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 2

# Retried with backoff. 429 and transient 5xx are safe to retry for the read-only
# and idempotent calls that dominate this SDK; 408 covers a server-side timeout.
_RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})

USER_AGENT = f"agoreum-python/{__version__}"


def build_headers(api_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "X-API-Key": api_key,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if extra:
        headers.update(extra)
    return headers


def _encode_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def encode_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Drop ``None``s and normalise enums, bools, and lists for the query string.

    Lists are passed through so httpx repeats the key (``tags=a&tags=b``), matching
    how the API reads repeated query parameters.
    """
    if not params:
        return {}
    out: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            items = [_encode_value(v) for v in value if v is not None]
            if items:
                out[key] = items
        else:
            out[key] = _encode_value(value)
    return out


def is_retryable(status_code: int) -> bool:
    return status_code in _RETRY_STATUSES


def retry_after_seconds(header_value: str | None) -> float | None:
    """Parse a ``Retry-After`` header expressed as a number of seconds."""
    if not header_value:
        return None
    try:
        seconds = float(header_value)
    except ValueError:
        return None
    return max(0.0, seconds)


def backoff_delay(attempt: int, retry_after: float | None = None) -> float:
    """Delay before ``attempt`` (1-based). Honours ``Retry-After`` when given,
    otherwise exponential backoff with full jitter, capped at 20s."""
    if retry_after is not None:
        return retry_after
    base = min(20.0, 0.5 * (2 ** (attempt - 1)))
    # Jitter for retry spacing, not a security context, a PRNG is the right tool.
    return random.uniform(0.0, base)  # noqa: S311


def clean_json(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip ``None`` values from a JSON body so optional fields are simply omitted."""
    if data is None:
        return None
    return {k: v for k, v in data.items() if v is not None}


def join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"
