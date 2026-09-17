"""
Normalized error vocabulary shared by Quantro Connect and Quantro Actions.

The UI must never have to parse a raw Facturapi/Google/Microsoft error
message to decide what to render — every provider- or action-facing
failure gets translated into one of these codes before it leaves the
backend. Raw provider text (if any) goes in `provider_detail`, which is
already redacted (see integrations/secrets.py:redact_error_text) and is
meant for a collapsed "details" section, not the headline.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException

ERROR_CODES = {
    "provider_not_connected",
    "provider_unavailable",
    "configuration_missing",
    "permission_missing",
    "reauthorization_required",
    "invalid_credentials",
    "rate_limited",
    "invalid_input",
    "approval_required",
    "action_blocked",
    "simulation_only",
    "duplicate_execution",
    "provider_error",
}

_STATUS_BY_CODE = {
    "provider_not_connected": 400,
    "provider_unavailable": 503,
    "configuration_missing": 503,
    "permission_missing": 403,
    "reauthorization_required": 403,
    "invalid_credentials": 401,
    "rate_limited": 429,
    "invalid_input": 422,
    "approval_required": 202,
    "action_blocked": 403,
    "simulation_only": 200,
    "duplicate_execution": 200,
    "provider_error": 502,
}


class QuantroError(Exception):
    """Raised anywhere in the Connect/Actions stack; a single FastAPI
    exception handler (see server.py) turns this into a normalized JSON
    body. Never construct this with a raw provider exception's text —
    pass it through redact_error_text() first."""

    def __init__(self, code: str, message: str, *, extra: Optional[Dict[str, Any]] = None):
        if code not in ERROR_CODES:
            raise ValueError(f"Unknown QuantroError code: {code}")
        self.code = code
        self.message = message
        self.extra = extra or {}
        super().__init__(message)

    def to_http_exception(self) -> HTTPException:
        return HTTPException(
            status_code=_STATUS_BY_CODE.get(self.code, 400),
            detail={"error": self.code, "message": self.message, **self.extra},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.code, "message": self.message, **self.extra}
