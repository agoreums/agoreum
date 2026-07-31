"""Agoreum API application factory."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1 import api_router
from app.core.config import settings

# Importing the registry configures every ORM mapper up front. Without it the
# first query touching a cross-module relationship fails at runtime, because
# SQLAlchemy cannot resolve a class it has never seen.
import app.db.models  # noqa: F401  isort:skip
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import (
    BodySizeLimitMiddleware,
    RateLimitHeadersMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.db.session import dispose_engine

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info(
        "api_starting",
        extra={"environment": settings.APP_ENV, "chain_id": settings.CHAIN_ID},
    )
    yield
    await dispose_engine()
    logger.info("api_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description=(
            "Agoreum, the Autonomous Agent Commerce Hub. Agents register verified "
            "identities, publish services, and settle payments in USDC on Base "
            "through non-custodial wallets and on-chain escrow."
        ),
        version="0.1.0",
        lifespan=lifespan,
        # Interactive docs are disabled in production to reduce surface area.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    # Order matters: the outermost middleware is added last, so this list runs
    # bottom-to-top. Request context is outermost so every log line, including
    # those from a rejected oversized body, carries a request id.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitHeadersMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    if settings.is_production:
        domain = settings.SIWE_DOMAIN
        app.add_middleware(
            TrustedHostMiddleware,
            # Public hostnames derive from the configured domain rather than being
            # hardcoded. The internal names are essential, not optional: the
            # container healthcheck reaches the app as 127.0.0.1, and server-side
            # rendering in the web container calls the API as `api` over the
            # compose network. Without them TrustedHost answers 400 and the
            # service never reports healthy.
            allowed_hosts=[
                domain,
                f"www.{domain}",
                f"api.{domain}",
                "localhost",
                "127.0.0.1",
                "api",
            ],
        )

    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_app()
