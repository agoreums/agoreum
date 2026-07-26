"""Exceptions raised by the Agoreum SDK.

Every error the API returns uses one envelope::

    {"error": {"code": "...", "message": "...", "details": {...}, "request_id": "..."}}

`raise_for_status` maps that envelope onto a typed exception so callers can branch
on the class (``except NotFoundError``) or on ``err.code`` without parsing JSON.
"""
from __future__ import annotations

from typing import Any


class AgoreumError(Exception):
    """Base class for every error raised by the SDK.

    Attributes mirror the API error envelope. ``status_code`` and ``request_id`` are
    ``None`` for errors that never reached the server (connection or timeout).
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details or {}
        self.request_id = request_id

    def __str__(self) -> str:
        parts = [self.message]
        if self.code:
            parts.append(f"code={self.code}")
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        return " ".join(parts) if len(parts) == 1 else f"{parts[0]} ({', '.join(parts[1:])})"


class APIConnectionError(AgoreumError):
    """The request never got a response (DNS, TCP, TLS, or the connection dropped)."""


class APITimeoutError(APIConnectionError):
    """The request exceeded the configured timeout."""


class APIStatusError(AgoreumError):
    """Base for every error that carries an HTTP status from the server."""


class AuthenticationError(APIStatusError):
    """401 — the API key is missing, malformed, expired, or revoked."""


class PermissionDeniedError(APIStatusError):
    """403 — the key is valid but not allowed to do this."""


class InsufficientScopeError(PermissionDeniedError):
    """403 with code ``insufficient_scope`` — the key lacks a required scope.

    The missing scopes, when the API reports them, are in ``details``.
    """


class NotFoundError(APIStatusError):
    """404 — no such resource."""


class ConflictError(APIStatusError):
    """409 — the request conflicts with the current state."""


class UnprocessableEntityError(APIStatusError):
    """422 — the request was well-formed but failed validation."""


class RateLimitError(APIStatusError):
    """429 — too many requests. ``retry_after`` is seconds to wait, when supplied."""

    def __init__(self, *args: Any, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


class ServiceUnavailableError(APIStatusError):
    """503 — a feature is not configured or is temporarily down (e.g. no chain wired)."""


class ServerError(APIStatusError):
    """5xx — the server failed to handle a valid request."""


_STATUS_MAP: dict[int, type[APIStatusError]] = {
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: UnprocessableEntityError,
    429: RateLimitError,
    503: ServiceUnavailableError,
}


def error_from_response(
    status_code: int,
    body: Any,
    *,
    retry_after: float | None = None,
) -> APIStatusError:
    """Build the most specific exception for an HTTP error response.

    ``body`` is the decoded JSON (or ``None`` if the body was not JSON). The Agoreum
    error envelope is honoured when present; anything else falls back to the status.
    """
    code: str | None = None
    message: str | None = None
    details: dict[str, Any] = {}
    request_id: str | None = None

    if isinstance(body, dict):
        envelope = body.get("error")
        if isinstance(envelope, dict):
            code = envelope.get("code")
            message = envelope.get("message")
            request_id = envelope.get("request_id")
            raw_details = envelope.get("details")
            if isinstance(raw_details, dict):
                details = raw_details

    if not message:
        message = f"HTTP {status_code}"

    cls: type[APIStatusError]
    if code == "insufficient_scope":
        cls = InsufficientScopeError
    elif status_code in _STATUS_MAP:
        cls = _STATUS_MAP[status_code]
    elif status_code >= 500:
        cls = ServerError
    else:
        cls = APIStatusError

    kwargs: dict[str, Any] = {
        "status_code": status_code,
        "code": code,
        "details": details,
        "request_id": request_id,
    }
    if cls is RateLimitError:
        return RateLimitError(message, retry_after=retry_after, **kwargs)
    return cls(message, **kwargs)
