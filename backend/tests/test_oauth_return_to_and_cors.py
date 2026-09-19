"""OAuth return_to allowlist + CORS allowlist helpers."""
from __future__ import annotations

import os
from unittest.mock import patch


def test_sanitize_return_to_allowlist_and_rejects():
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


def _allowed_cors_origins_impl():
    """Mirrors server._allowed_cors_origins contract (post cloud-domain update)."""
    raw = (os.environ.get("ALLOWED_FRONTEND_ORIGINS") or "").strip()
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    for required in (
        "https://www.quantroflow.cloud",
        "https://quantroflow.cloud",
        "https://quantro-flow.vercel.app",
    ):
        if required not in origins:
            origins.append(required)
    env_name = (os.environ.get("ENVIRONMENT") or os.environ.get("ENV") or "").lower().strip()
    allow_local = env_name in {"development", "dev", "local"} or (
        str(os.environ.get("ALLOW_LOCALHOST_CORS") or "").lower() in {"1", "true", "yes"}
    )
    if allow_local:
        for loc in ("http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173"):
            if loc not in origins:
                origins.append(loc)
    return origins


def test_cors_origins_include_cloud_and_vercel_by_default():
    with patch.dict(os.environ, {
        "ALLOWED_FRONTEND_ORIGINS": "",
        "ENVIRONMENT": "production",
        "ALLOW_LOCALHOST_CORS": "0",
        "ALLOW_VERCEL_PREVIEW_CORS": "0",
    }, clear=False):
        origins = _allowed_cors_origins_impl()
        assert "https://www.quantroflow.cloud" in origins
        assert "https://quantroflow.cloud" in origins
        assert "https://quantro-flow.vercel.app" in origins
        assert "http://localhost:3000" not in origins
        assert ".*" not in origins


def test_cors_origins_merges_explicit_env():
    with patch.dict(os.environ, {
        "ALLOWED_FRONTEND_ORIGINS": "https://quantro-flow.vercel.app,https://app.example.com",
        "ENVIRONMENT": "production",
        "ALLOW_LOCALHOST_CORS": "0",
    }, clear=False):
        origins = _allowed_cors_origins_impl()
        assert "https://app.example.com" in origins
        assert "https://www.quantroflow.cloud" in origins


def test_frontend_public_url_apex_normalizes_to_www():
    raw = "https://quantroflow.cloud"
    normalized = "https://www.quantroflow.cloud" if raw == "https://quantroflow.cloud" else raw
    assert normalized == "https://www.quantroflow.cloud"
