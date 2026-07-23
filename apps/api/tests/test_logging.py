"""Logging tests.

The structured-logging path must never be able to raise. A crash inside a log
call takes down the request it was describing, which is the worst possible time
to fail.
"""
from __future__ import annotations

import logging

import pytest

from app.core.logging import _RESERVED, JsonFormatter, get_logger, request_id_ctx


@pytest.mark.parametrize("reserved_key", sorted(_RESERVED))
def test_reserved_extra_keys_do_not_raise(
    reserved_key: str, caplog: pytest.LogCaptureFixture
) -> None:
    """`extra={"created": ...}` used to crash with KeyError inside makeRecord."""
    logger = get_logger("test.reserved")
    with caplog.at_level(logging.INFO):
        logger.info("event", extra={reserved_key: "value"})

    assert caplog.records, f"no record emitted for reserved key {reserved_key!r}"


def test_reserved_key_is_preserved_under_a_suffixed_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Colliding keys are renamed rather than dropped, so nothing is lost."""
    logger = get_logger("test.suffix")
    with caplog.at_level(logging.INFO):
        logger.info("event", extra={"created": 25})

    assert caplog.records[-1].created_ == 25


def test_non_reserved_keys_pass_through_unchanged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = get_logger("test.passthrough")
    with caplog.at_level(logging.INFO):
        logger.info("event", extra={"order_reference": "AGO-1234"})

    assert caplog.records[-1].order_reference == "AGO-1234"


def test_json_formatter_emits_valid_json_with_extras() -> None:
    import json

    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="something happened", args=(), exc_info=None,
    )
    record.order_reference = "AGO-1234"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "something happened"
    assert payload["level"] == "INFO"
    assert payload["order_reference"] == "AGO-1234"
    assert "timestamp" in payload


def test_json_formatter_includes_request_id_when_set() -> None:
    import json

    token = request_id_ctx.set("3f2504e0-4f89-41d3-9a0c-0305e82c3301")
    try:
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=1,
            msg="m", args=(), exc_info=None,
        )
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_ctx.reset(token)

    assert payload["request_id"] == "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
