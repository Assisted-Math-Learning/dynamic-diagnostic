"""
Per-tenant shared-secret authentication (spec section 5.1).

Every request body carries a `tenant_id`. The engine maintains a server-side
map of {tenant_id: expected_token} loaded from TENANT_TOKENS_JSON at startup.
The `X-Internal-Service-Token` header must match the expected token for the
request's tenant_id. Mismatch returns 401 INVALID_TENANT_TOKEN.

The map is constructed at app construction time and stored on app.state.
The verify function is called explicitly by each route handler.
"""

from typing import Mapping, Optional

from engine.api.errors import InvalidTenantTokenError

TOKEN_HEADER = "X-Internal-Service-Token"


def verify_tenant_token(
    *,
    header_token: Optional[str],
    tenant_id: str,
    tenant_tokens: Mapping[str, str],
) -> None:
    """Verify that the header token matches the expected token for the tenant.

    Raises:
        InvalidTenantTokenError if the token is missing, the tenant is
        unknown, or the token does not match.
    """
    if not header_token:
        raise InvalidTenantTokenError(
            "missing or empty X-Internal-Service-Token header"
        )
    expected = tenant_tokens.get(tenant_id)
    if expected is None:
        # We intentionally return the same error code regardless of whether
        # the tenant is unknown or the token is wrong. This avoids leaking
        # which tenants are registered.
        raise InvalidTenantTokenError("invalid X-Internal-Service-Token")
    if not _constant_time_eq(header_token, expected):
        raise InvalidTenantTokenError("invalid X-Internal-Service-Token")


def _constant_time_eq(a: str, b: str) -> bool:
    """Constant-time string comparison to avoid timing-based token leakage."""
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0
