"""
Response envelope helpers.

Every API response is wrapped in the envelope shape from spec section 5.1:

  {
    "id": "api.diagnostic.session.start",
    "ver": "1.0",
    "ts": "...ISO timestamp...",
    "params": {
      "status": "SUCCESS" | "FAILED",
      "msgid": "<caller-supplied or null>",
      "resmsgid": "<server-generated trace id>"
    },
    "responseCode": "OK" | "BAD_REQUEST" | ...,
    "result": { ... endpoint payload ... },
    "error": { "code": "...", "message": "..." }   // only on failure
  }
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Map HTTP status codes to the responseCode strings the envelope uses.
# Spec section 5.1 uses HTTP-status-style names; this map matches that style.
_RESPONSE_CODES: Dict[int, str] = {
    200: "OK",
    201: "OK",
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    500: "INTERNAL_SERVER_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def _now_iso() -> str:
    """ISO 8601 UTC timestamp with explicit offset (e.g. '2026-05-26T12:34:56+00:00')."""
    return datetime.now(timezone.utc).isoformat()


def _new_trace_id() -> str:
    return str(uuid.uuid4())


def _response_code_for(http_status: int) -> str:
    return _RESPONSE_CODES.get(http_status, "INTERNAL_SERVER_ERROR")


def success_envelope(
    endpoint_id: str,
    result: Dict[str, Any],
    *,
    msgid: Optional[str] = None,
    http_status: int = 200,
) -> Dict[str, Any]:
    """Wrap a successful response payload in the envelope."""
    return {
        "id": endpoint_id,
        "ver": "1.0",
        "ts": _now_iso(),
        "params": {
            "status": "SUCCESS",
            "msgid": msgid,
            "resmsgid": _new_trace_id(),
        },
        "responseCode": _response_code_for(http_status),
        "result": result,
    }


def error_envelope(
    endpoint_id: str,
    error_code: str,
    error_message: str,
    http_status: int,
    *,
    msgid: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrap an error response in the envelope."""
    return {
        "id": endpoint_id,
        "ver": "1.0",
        "ts": _now_iso(),
        "params": {
            "status": "FAILED",
            "msgid": msgid,
            "resmsgid": _new_trace_id(),
        },
        "responseCode": _response_code_for(http_status),
        "result": {},
        "error": {
            "code": error_code,
            "message": error_message,
        },
    }
