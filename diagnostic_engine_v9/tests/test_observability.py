"""Tests for engine.observability.logging."""

import io
import logging
import sys
from contextlib import redirect_stdout

import pytest
import structlog

from engine.observability.logging import (
    ALLOWED_LOG_FIELDS,
    SERVICE_NAME,
    _pii_allow_list_filter,
    _rename_event_to_message,
    configure_logging,
    get_logger,
)


class TestAllowList:
    def test_spec_fields_are_in_allow_list(self):
        # Spec section 9.3 fields
        for f in ("ts", "level", "service", "version", "request_id",
                  "learner_id", "tenant_id", "sub_session_id", "message", "error"):
            assert f in ALLOWED_LOG_FIELDS

    def test_extra_field_is_dropped(self):
        event_dict = {"message": "hello", "credit_card_number": "1234-5678"}
        result = _pii_allow_list_filter(None, "info", event_dict)
        assert "credit_card_number" not in result

    def test_extra_field_warning_prepended(self):
        event_dict = {"message": "hello", "password": "secret"}
        result = _pii_allow_list_filter(None, "info", event_dict)
        assert "[pii-filter dropped extra fields:" in result["message"]
        assert "password" in result["message"]

    def test_allowed_fields_pass_through(self):
        event_dict = {
            "message": "session started",
            "learner_id": "l1",
            "tenant_id": "t1",
            "sub_session_id": "s1",
        }
        result = _pii_allow_list_filter(None, "info", event_dict)
        assert result["learner_id"] == "l1"
        assert result["tenant_id"] == "t1"

    def test_multiple_extras_all_reported(self):
        event_dict = {"message": "x", "ssn": "1", "dob": "2"}
        result = _pii_allow_list_filter(None, "info", event_dict)
        assert "ssn" in result["message"]
        assert "dob" in result["message"]
        assert "ssn" not in result
        assert "dob" not in result


class TestEventRename:
    def test_event_becomes_message(self):
        event_dict = {"event": "log line"}
        result = _rename_event_to_message(None, "info", event_dict)
        assert "event" not in result
        assert result["message"] == "log line"

    def test_explicit_message_wins(self):
        event_dict = {"event": "log line", "message": "explicit"}
        result = _rename_event_to_message(None, "info", event_dict)
        assert result["message"] == "explicit"
        assert "event" not in result


class TestConfigureLogging:
    def teardown_method(self):
        # Reset structlog config between tests
        structlog.reset_defaults()
        logging.root.handlers.clear()

    def test_configure_does_not_crash(self):
        configure_logging(level="debug", fmt="json")
        log = get_logger("test")
        log.info("hello world")  # should not raise

    def test_json_output_includes_service_and_version(self):
        configure_logging(level="info", fmt="json", service="test-svc", version="9.9.9")
        log = get_logger("test")
        buf = io.StringIO()
        with redirect_stdout(buf):
            log.info("test message")
        out = buf.getvalue()
        assert "test-svc" in out
        assert "9.9.9" in out
        assert "test message" in out

    def test_text_format_renders(self):
        configure_logging(level="info", fmt="text", service="test-svc")
        log = get_logger("test")
        buf = io.StringIO()
        with redirect_stdout(buf):
            log.info("text test")
        out = buf.getvalue()
        assert "text test" in out

    def test_pii_filter_active_in_pipeline(self):
        configure_logging(level="info", fmt="json", service="test-svc", version="0.0.0")
        log = get_logger("test")
        buf = io.StringIO()
        with redirect_stdout(buf):
            log.info("with extras", password="not-logged", learner_id="l1")
        out = buf.getvalue()
        # The actual password value must NOT appear
        assert "not-logged" not in out
        # The allowed learner_id should appear
        assert "l1" in out
        # The filter warning should mention the dropped field
        assert "password" in out


# === B2: raw_response must never reach logs ================================


def test_raw_response_not_in_allow_list():
    # The learner's typed answer is deliberately NOT allow-listed, so the
    # default-deny filter drops it if any code path ever logs it.
    assert "raw_response" not in ALLOWED_LOG_FIELDS


def test_pii_filter_drops_raw_response_value():
    import json
    secret = "the learner typed 42 which is wrong"
    event = {
        "event": "response_recorded",
        "tenant_id": "Delhi",
        "sub_session_id": "s1",
        "raw_response": secret,
    }
    out = _pii_allow_list_filter(None, "info", dict(event))
    # The key is dropped from the emitted record...
    assert "raw_response" not in out
    # ...and the raw VALUE never appears anywhere in the serialized line.
    assert secret not in json.dumps(out, default=str)
    # Allow-listed fields survive.
    assert out.get("tenant_id") == "Delhi"
