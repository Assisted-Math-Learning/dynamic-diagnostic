"""
HTTP middleware for the dynamic diagnostic engine.

`request_id_middleware` reads `X-Request-Id` from the incoming request
(or generates a UUID4 if the header is absent), binds it to structlog's
contextvars for the duration of the request, and echoes it back on the
response. Spec section 9.3 lists `request_id` in the allow-list so every
log line emitted during the request automatically carries the id.

The contextvars are unbound after the response is built, so the id does
not leak across requests.
"""

import uuid
from typing import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-Id"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Per-request request_id binding for structured logs.

    Header behavior:
      - If the incoming request has `X-Request-Id`, that value is reused.
      - Otherwise a fresh UUID4 is generated.
    The chosen id is:
      - Bound to structlog contextvars so every log line during the
        request carries it (the merge_contextvars processor is already
        in the configured chain; see engine.observability.logging).
      - Echoed back on the response as `X-Request-Id` for client-side
        correlation.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming else str(uuid.uuid4())

        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
