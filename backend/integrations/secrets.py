"""
Central secret encryption + redaction for Quantro Connect.

Before this module, generic integrations (openai/crm/webhook — see
`/api/integrations/{provider}` in server.py) stored whatever the
frontend sent inside `config` AS PLAINTEXT, and `GET /api/integrations`
returned that same `config` straight back to the browser. That is a
real, live secret-exposure bug (found during the Phase 0 audit of this
task), not a hypothetical one — every new secret write from this
module onward is encrypted at rest, and every read redacts known
secret fields before serialization.

Key resolution order:
  1. INTEGRATIONS_ENCRYPTION_KEY — dedicated key for this layer.
  2. GOOGLE_TOKENS_ENCRYPTION_KEY — the key google_oauth.py/
     microsoft_oauth.py already use. Falling back to it means a
     deployment that only ever set up Google OAuth still gets secret
     encryption for Facturapi/etc. for free, but production should set
     its own INTEGRATIONS_ENCRYPTION_KEY (a single shared key across
     unrelated secret domains is a compatibility bridge, not the
     target state).
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

# Field names that must NEVER be returned to a browser, logged, put in
# an audit-log metadata blob, or embedded in an exception message.
SECRET_FIELD_NAMES = {
    "api_key",
    "secret_key",
    "access_token",
    "refresh_token",
    "client_secret",
    "webhook_token",
    "private_key",
    "password",
}


def _resolve_key() -> bytes:
    key = (os.environ.get("INTEGRATIONS_ENCRYPTION_KEY") or "").strip()
    if key:
        return key.encode()
    fallback = (os.environ.get("GOOGLE_TOKENS_ENCRYPTION_KEY") or "").strip()
    return fallback.encode()


def is_encryption_configured() -> bool:
    return bool(_resolve_key())


def using_dedicated_key() -> bool:
    """True if INTEGRATIONS_ENCRYPTION_KEY is set (not falling back to
    the Google/Microsoft token key). Surfaced in System Health so an
    operator knows to set a dedicated key before going to production."""
    return bool((os.environ.get("INTEGRATIONS_ENCRYPTION_KEY") or "").strip())


def _fernet() -> Fernet:
    key = _resolve_key()
    if not key:
        raise RuntimeError(
            "No encryption key configured. Set INTEGRATIONS_ENCRYPTION_KEY "
            "(preferred) or GOOGLE_TOKENS_ENCRYPTION_KEY."
        )
    return Fernet(key)


def encrypt_secret(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def redact_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a client-safe copy of a provider config dict: every known
    secret field becomes a boolean `has_<field>` flag instead of the
    value itself. Unknown/non-secret fields pass through unchanged so
    the UI can still show e.g. a selected model or base_url."""
    if not config:
        return {}
    out: Dict[str, Any] = {}
    for k, v in config.items():
        if k in SECRET_FIELD_NAMES:
            out[f"has_{k}"] = bool(v)
        else:
            out[k] = v
    return out


def encrypt_config_secrets(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Encrypt every known secret field in-place (returns a new dict).
    Non-secret fields pass through unchanged. Call this right before
    persisting a provider config; call redact_config() right before
    returning one."""
    if not config:
        return {}
    out: Dict[str, Any] = {}
    for k, v in config.items():
        if k in SECRET_FIELD_NAMES and isinstance(v, str) and v:
            out[k] = encrypt_secret(v)
        else:
            out[k] = v
    return out


def decrypt_config_secrets(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Server-side-only counterpart to encrypt_config_secrets() — used
    when an adapter needs the real value to call a provider API. Never
    pass the result of this function into an API response."""
    if not config:
        return {}
    out: Dict[str, Any] = {}
    for k, v in config.items():
        if k in SECRET_FIELD_NAMES and isinstance(v, str) and v:
            out[k] = decrypt_secret(v)
        else:
            out[k] = v
    return out


# ── Error text redaction ────────────────────────────────────────────
# A provider SDK/HTTP client exception can embed the request body,
# headers, or URL (which may carry a key as a query param) in its
# str(). We never forward that verbatim into a log line, audit entry,
# or HTTP response — only a scrubbed version.
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9\-_.~+/]+=*", re.IGNORECASE)
_SK_KEY_RE = re.compile(r"\b(sk|pk|rk)_(test|live)_[A-Za-z0-9]{6,}\b")
_QUERY_SECRET_RE = re.compile(
    r"(?i)\b(key|token|secret|password|api_key)=([^&\s]+)"
)
_LONG_TOKENish_RE = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")


def redact_error_text(text: Optional[str], max_len: int = 300) -> str:
    """Best-effort scrub of a provider exception's text before it's
    ever logged or shown to a user. Not a substitute for not logging
    secrets in the first place — this is a last line of defense."""
    if not text:
        return ""
    scrubbed = _BEARER_RE.sub("Bearer [redacted]", text)
    scrubbed = _SK_KEY_RE.sub("[redacted-key]", scrubbed)
    scrubbed = _QUERY_SECRET_RE.sub(lambda m: f"{m.group(1)}=[redacted]", scrubbed)
    scrubbed = _LONG_TOKENish_RE.sub("[redacted]", scrubbed)
    return scrubbed[:max_len]
