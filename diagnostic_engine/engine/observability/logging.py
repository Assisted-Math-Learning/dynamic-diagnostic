"""
Structured logging for the dynamic diagnostic engine.

JSON output to stdout per spec section 9.3. A PII allow-list filter drops
log entries that include fields outside the spec's allow-list to prevent
accidental PII leakage.

Allow-list (spec section 9.3):
  ts, level, service, version, request_id, learner_id, tenant_id,
  sub_session_id, message, error

If a log call includes a non-allow-list field, the filter drops the extra
keys and emits a warning at the top of the line. This is per spec's
"strips or rejects" wording, leaning toward strip-with-warning so a small
slip doesn't break production but is still visible.
"""

import logging
import sys
from typing import Any, Dict, Iterable, MutableMapping

import structlog

# Allow-listed log fields per spec section 9.3.
ALLOWED_LOG_FIELDS = frozenset({
    "ts", "level", "service", "version",
    "request_id", "learner_id", "tenant_id", "sub_session_id",
    "message", "error",
    # Internal structlog/logger fields - always allowed.
    "event", "logger", "timestamp", "_record",
})

# Service identifier baked into every log line per spec section 9.3.
SERVICE_NAME = "aml-diagnostic-engine"


def _pii_allow_list_filter(
    logger: Any,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """structlog processor: drop keys not in the allow-list.

    If extra keys are present, prefix the event with a warning so the
    accidental field is visible during development.
    """
    extras = [k for k in event_dict if k not in ALLOWED_LOG_FIELDS]
    if extras:
        for k in extras:
            event_dict.pop(k, None)
        event_dict["message"] = (
            f"[pii-filter dropped extra fields: {','.join(sorted(extras))}] "
            f"{event_dict.get('message', '') or event_dict.get('event', '')}"
        )
    return event_dict


def _rename_event_to_message(
    logger: Any,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """structlog uses 'event' as the message key; spec uses 'message'. Map."""
    if "event" in event_dict and "message" not in event_dict:
        event_dict["message"] = event_dict.pop("event")
    elif "event" in event_dict:
        event_dict.pop("event")
    return event_dict


def configure_logging(
    *,
    level: str = "info",
    fmt: str = "json",
    service: str = SERVICE_NAME,
    version: str = "0.0.0",
) -> None:
    """Configure structlog and the stdlib logger.

    Args:
        level: log level name (debug/info/warn/error).
        fmt: 'json' for structured output (default), 'text' for plain key=value.
        service: service name added to every log line.
        version: engine version string added to every log line.
    """
    level_value = getattr(logging, level.upper(), logging.INFO)

    # stdlib logging goes to stderr for warn+ and stdout for everything else.
    stdout = logging.StreamHandler(sys.stdout)
    stdout.addFilter(lambda r: r.levelno < logging.WARNING)
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setLevel(logging.WARNING)
    logging.basicConfig(level=level_value, handlers=[stdout, stderr], force=True)

    if fmt == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            _bind_service_and_version(service, version),
            _rename_event_to_message,
            _pii_allow_list_filter,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_value),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _bind_service_and_version(service: str, version: str):
    """Returns a structlog processor that stamps service and version on every line."""

    def processor(logger, method_name, event_dict):
        event_dict.setdefault("service", service)
        event_dict.setdefault("version", version)
        return event_dict

    return processor


def get_logger(name: str = "engine"):
    """Get a structured logger. Configure_logging must be called first."""
    return structlog.get_logger(name)
