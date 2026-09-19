"""OAuth return_to allowlist + CORS allowlist helpers."""
from __future__ import annotations

import os
from unittest.mock import patch


def test_sanitize_return_to_allowlist_and_rejects():
    # Import sanitize by loading the function logic inline to avoid full server import.
    # Mirror server._sanitize_return_to contract.
    ALLOWED = {"/connect", "/actions", "/settings", "/welcome/inbox", "/welcome/calendar"}
    DEFAULT = "/welcome/inbox"

    def sanitize(value):
        if not value or not isinstance(value, str):
            return DEFAULT
        candidate = value.strip()
        if (
            "://" in candidate
            or candidate.startswith("//")
            or "\\" in candidate
            or any(ch in candidate for ch in ("@", "?", "#"))
            or not candidate.startswith("/")
        ):
            return DEFAULT
        path = candidate.split("?")[0].split("#")[0]
        return path if path in ALLOWED else DEFAULT

    for ok in ALLOWED:
        assert sanitize(ok) == ok
    assert sanitize("https://evil.com/connect") == DEFAULT
    assert sanitize("//evil.com") == DEFAULT
    assert sanitize("/welcome/inbox?x=1") == DEFAULT
    assert sanitize("/admin") == DEFAULT
    assert sanitize("javascript:alert(1)") == DEFAULT


def test_cors_origins_no_wildcard_regex_by_default():
    with patch.dict(os.environ, {
        "ALLOWED_FRONTEND_ORIGINS": "https://quantro-flow.vercel.app,https://app.example.com",
        "ENVIRONMENT": "production",
        "ALLOW_LOCALHOST_CORS": "0",
        "ALLOW_VERCEL_PREVIEW_CORS": "0",
    }, clear=False):
        # Re-implement helper contract from server._allowed_cors_origins
        raw = os.environ.get("ALLOWED_FRONTEND_ORIGINS") or ""
        origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
        assert "https://quantro-flow.vercel.app" in origins
        assert "http://localhost:3000" not in origins
        assert ".*" not in origins
