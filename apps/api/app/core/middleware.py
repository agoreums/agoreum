"""HTTP middleware: request correlation, access logging, and security headers."""
from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.config import settings
from app.core.logging import get_logger, request_id_ctx

logger = get_logger("app.access")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request ID, logs the request, and records its duration."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        # Only trust an inbound ID if it is a well-formed UUID, so the header
        # cannot be used to inject arbitrary content into logs.
        try:
            request_id = str(uuid.UUID(incoming)) if incoming else str(uuid.uuid4())
        except ValueError:
            request_id = str(uuid.uuid4())

        token = request_id_ctx.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.exception(
                "request_failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                },
            )
            raise
        else:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            response.headers[REQUEST_ID_HEADER] = request_id
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        finally:
            request_id_ctx.reset(token)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Applies defensive response headers.

    The API serves JSON only, so the CSP is deliberately restrictive; the frontend
    sets its own policy independently.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
            "Cross-Origin-Opener-Policy": "same-origin",
            "Cross-Origin-Resource-Policy": "same-site",
        }
        if settings.is_production:
            self._headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        for key, value in self._headers.items():
            response.headers.setdefault(key, value)
        return response


class RateLimitHeadersMiddleware(BaseHTTPMiddleware):
    """Publishes the caller's remaining quota on every response.

    A client that can see how much allowance it has left can back off before
    being refused. Discovering a limit only by hitting it is worse for everyone.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)

        decision = getattr(request.state, "rate_limit", None)
        if decision is not None:
            response.headers["X-RateLimit-Limit"] = str(decision.limit)
            response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
            response.headers["X-RateLimit-Reset"] = str(decision.reset_after)
            if not decision.allowed:
                response.headers["Retry-After"] = str(decision.reset_after)

        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects request bodies above a fixed ceiling.

    Without this, a single request declaring a multi-gigabyte body can exhaust
    memory before any handler or validator sees it. The check is on the declared
    Content-Length, which is what a proxy has already parsed; Nginx enforces the
    same ceiling in front, so this is defence in depth rather than the only gate.
    """

    # Generous for JSON payloads (an agent description, a delivery note) and far
    # below anything that would threaten the process.
    MAX_BODY_BYTES = 1_048_576  # 1 MiB

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "code": "invalid_content_length",
                            "message": "The Content-Length header is malformed.",
                        }
                    },
                )

            if length > self.MAX_BODY_BYTES:
                logger.warning(
                    "request_body_too_large", extra={"declared_bytes": length}
                )
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "payload_too_large",
                            "message": (
                                f"Request body exceeds the "
                                f"{self.MAX_BODY_BYTES // 1024} KiB limit."
                            ),
                        }
                    },
                )

        return await call_next(request)
