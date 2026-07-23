"""Structured JSON logging.

Logs are emitted as single-line JSON in non-development environments so they can be
shipped and queried directly. Secrets are never logged: configuration values are held
as `SecretStr` and request bodies are not logged.
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings

# Correlates every log line emitted while handling a single request.
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName",
}


class _SafeExtraAdapter(logging.LoggerAdapter):
    """Prevents an `extra` key from colliding with a built-in LogRecord attribute.

    `logging.makeRecord` raises KeyError if `extra` contains a reserved name such
    as `created`, `module`, or `name`. That turns an innocuous structured-logging
    call into a runtime crash, which is unacceptable for a logging path. Colliding
    keys are suffixed instead of dropped, so no information is lost.
    """

    def process(
        self, msg: object, kwargs: dict[str, Any]
    ) -> tuple[object, dict[str, Any]]:
        extra = kwargs.get("extra")
        if extra:
            kwargs["extra"] = {
                (f"{key}_" if key in _RESERVED else key): value
                for key, value in extra.items()
            }
        return msg, kwargs


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=UTC
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = request_id_ctx.get()
        if request_id:
            payload["request_id"] = request_id

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Include structured extras passed via logger.info(..., extra={...})
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Readable formatter for local development."""

    def format(self, record: logging.LogRecord) -> str:
        request_id = request_id_ctx.get()
        prefix = f"[{request_id[:8]}] " if request_id else ""
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<8} {prefix}{record.name}: {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        ConsoleFormatter() if settings.APP_ENV == "development" else JsonFormatter()
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL.upper())

    # Uvicorn manages its own handlers; route them through ours instead.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DB_ECHO else logging.WARNING
    )


def get_logger(name: str) -> logging.LoggerAdapter:
    """Return a logger that is safe to call with arbitrary `extra` keys."""
    return _SafeExtraAdapter(logging.getLogger(name), {})
