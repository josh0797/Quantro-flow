"""Sentry error tracking for the Quantro Flow API (Sentry project `quantro-flow-api`).

Activated by the SENTRY_DSN Fly secret; without it ``init_sentry()`` is a
no-op and the SDK is never initialised (no network, no patching).

Privacy policy (mirrors konta docs/observability/sentry.md):
  * send_default_pii=False, include_local_variables=False (frame locals can
    hold tokens / customer rows), request bodies never attached.
  * before_send / before_breadcrumb scrub: Authorization, cookies, API keys,
    tokens, secrets, passwords, Supabase JWTs, Bearer values, provider keys
    (sk-/sk_live_/whsec_/xox*/ghp_/AIza…), emails, RFC/CURP, card numbers.
  * User context is reduced to ``{"id": ...}``.
  * release = SENTRY_RELEASE | GIT_SHA | FLY_IMAGE_REF; environment =
    SENTRY_ENVIRONMENT | ENVIRONMENT | ENV | production-on-Fly.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("quantro.observability")

FILTERED = "[Filtered]"

SENSITIVE_KEY = re.compile(
    r"(authorization|cookie|passw(or)?d|secret|token|api[-_]?key|apikey|service[-_]?role|"
    r"private[-_]?key|signature|session|credential|jwt|bearer|(?:^|[-_])otp(?:$|[-_])|"
    r"refresh|access[-_]?key|client[-_]?secret|dsn|encryption[-_]?key|fernet)",
    re.IGNORECASE,
)

_PASSTHROUGH_KEYS = {
    "event_id", "timestamp", "start_timestamp", "release", "environment", "platform",
    "level", "logger", "type", "mechanism", "handled", "sdk", "stacktrace", "frames",
    "trace_id", "span_id", "parent_span_id", "op", "status", "fingerprint",
    "transaction", "category", "lineno", "colno", "in_app", "status_code", "method",
    "module", "filename", "abs_path", "function",
}
_ID_KEY = re.compile(r"(^id$|_id$)")

_VALUE_PATTERNS = [
    # JWT (Supabase anon/service/user tokens)
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[JWT]"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9\-._~+/]{12,}=*"), r"\1[TOKEN]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "[API_KEY]"),
    (re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{8,}"), "[API_KEY]"),
    (re.compile(r"\bwhsec_[A-Za-z0-9+/=]{16,}"), "[API_KEY]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "[API_KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "[API_KEY]"),
    (re.compile(r"\bAIza[A-Za-z0-9_-]{30,}"), "[API_KEY]"),
    (re.compile(r"\bgAAAA[A-Za-z0-9_-]{40,}={0,2}"), "[FERNET]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"), "[EMAIL]"),
    # CURP before RFC (a CURP starts with an RFC-shaped prefix)
    (re.compile(r"(?i)(?<![A-Z0-9])[A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}[A-Z0-9]\d(?![A-Z0-9])"), "[CURP]"),
    (re.compile(r"(?i)(?<![A-Z0-9&Ñ])[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}(?![A-Z0-9&Ñ])"), "[RFC]"),
]
_DIGIT_RUN = re.compile(r"(?<![\d.])(?:\d[ -]?){13,19}(?!\d)")
_CLABE = re.compile(r"(?<!\d)\d{18}(?!\d)")
_MAX_STRING = 8000


def _luhn(digits: str) -> bool:
    total, double = 0, False
    for ch in reversed(digits):
        n = ord(ch) - 48
        if double:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        double = not double
    return total % 10 == 0


def _card(match: "re.Match[str]") -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if 13 <= len(digits) <= 19 and _luhn(digits):
        return "[CARD]"
    return match.group(0)


def scrub_text(value: str) -> str:
    if not isinstance(value, str) or not value:
        return value
    out = value[:_MAX_STRING]
    for pattern, repl in _VALUE_PATTERNS:
        out = pattern.sub(repl, out)
    out = _CLABE.sub("[CLABE]", out)
    out = _DIGIT_RUN.sub(_card, out)
    return out


def scrub_value(value: Any, key: str = "", depth: int = 0) -> Any:
    if key and SENSITIVE_KEY.search(key):
        return FILTERED
    if key and (key in _PASSTHROUGH_KEYS or _ID_KEY.search(key)):
        return value
    if isinstance(value, str):
        return scrub_text(value)
    if depth > 12:
        return "[Truncated]"
    if isinstance(value, dict):
        return {k: scrub_value(v, str(k), depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub_value(v, "", depth + 1) for v in value]
    return value


def _scrub_query_string(qs: Any) -> Any:
    if isinstance(qs, str):
        parts = []
        for pair in qs.split("&"):
            name, sep, val = pair.partition("=")
            if SENSITIVE_KEY.search(name) or name.lower() in {"code", "state", "key", "sig", "hmac", "email"}:
                parts.append(f"{name}{sep}{FILTERED}" if sep else name)
            else:
                parts.append(f"{name}{sep}{scrub_text(val)}" if sep else scrub_text(name))
        return "&".join(parts)
    return scrub_value(qs)


def scrub_event(event: Dict[str, Any], hint: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Sentry ``before_send``: never raises; on failure sends a stub, not raw data."""
    try:
        if isinstance(event.get("message"), str):
            event["message"] = scrub_text(event["message"])
        if isinstance(event.get("logentry"), dict):
            event["logentry"] = scrub_value(event["logentry"])
        for exc in (event.get("exception") or {}).get("values") or []:
            if isinstance(exc.get("value"), str):
                exc["value"] = scrub_text(exc["value"])
            # Belt and braces: include_local_variables=False, but drop any vars anyway.
            for frame in ((exc.get("stacktrace") or {}).get("frames") or []):
                frame.pop("vars", None)
        req = event.get("request")
        if isinstance(req, dict):
            req.pop("cookies", None)
            req.pop("data", None)
            req.pop("env", None)
            if isinstance(req.get("url"), str):
                req["url"] = scrub_text(req["url"].split("#", 1)[0])
            if "query_string" in req:
                req["query_string"] = _scrub_query_string(req["query_string"])
            headers = req.get("headers")
            if isinstance(headers, dict):
                req["headers"] = {
                    k: (FILTERED if SENSITIVE_KEY.search(str(k)) else scrub_text(str(v)))
                    for k, v in headers.items()
                }
        user = event.get("user")
        if isinstance(user, dict):
            if user.get("id") is not None:
                event["user"] = {"id": user["id"]}
            else:
                event.pop("user", None)
        crumbs = event.get("breadcrumbs")
        if isinstance(crumbs, dict) and isinstance(crumbs.get("values"), list):
            crumbs["values"] = [scrub_breadcrumb(b) for b in crumbs["values"]]
        elif isinstance(crumbs, list):
            event["breadcrumbs"] = [scrub_breadcrumb(b) for b in crumbs]
        for field in ("extra", "contexts", "tags"):
            if isinstance(event.get(field), dict):
                event[field] = scrub_value(event[field])
        return event
    except Exception:  # pragma: no cover - defensive
        return {"event_id": event.get("event_id"), "message": FILTERED, "level": "error"}


def scrub_breadcrumb(crumb: Dict[str, Any], hint: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not isinstance(crumb, dict):
        return crumb
    out = dict(crumb)
    if isinstance(out.get("message"), str):
        out["message"] = scrub_text(out["message"])
    data = out.get("data")
    if isinstance(data, dict):
        clean = {}
        for k, v in data.items():
            if k in {"body", "request_body", "response_body"}:
                continue
            if k in {"url", "http.query"} and isinstance(v, str):
                clean[k] = _scrub_query_string(v) if k == "http.query" else scrub_text(v.split("?", 1)[0])
                continue
            clean[k] = scrub_value(v, str(k))
        out["data"] = clean
    return out


def resolve_environment(env: Optional[Dict[str, str]] = None) -> str:
    e = os.environ if env is None else env
    explicit = (e.get("SENTRY_ENVIRONMENT") or e.get("ENVIRONMENT") or e.get("ENV") or "").strip()
    if explicit:
        return explicit
    return "production" if e.get("FLY_APP_NAME") else "development"


def resolve_release(env: Optional[Dict[str, str]] = None) -> Optional[str]:
    e = os.environ if env is None else env
    for name in ("SENTRY_RELEASE", "GIT_SHA", "FLY_IMAGE_REF"):
        val = (e.get(name) or "").strip()
        if val:
            return val
    return None


def _traces_rate(env: Dict[str, str]) -> float:
    try:
        rate = float(env.get("SENTRY_TRACES_SAMPLE_RATE", "0.05"))
    except ValueError:
        return 0.05
    return rate if 0.0 <= rate <= 1.0 else 0.05


def init_sentry(env: Optional[Dict[str, str]] = None) -> bool:
    """Initialise Sentry when SENTRY_DSN is set. Returns True when initialised."""
    e = dict(os.environ) if env is None else env
    dsn = (e.get("SENTRY_DSN") or "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber
    except Exception as exc:  # pragma: no cover - dependency missing
        logger.warning("SENTRY_DSN set but sentry-sdk unavailable: %s", exc)
        return False

    denylist = list(DEFAULT_DENYLIST) + [
        "apikey", "api_key", "x-api-key", "service_role", "supabase_service_role_key",
        "refresh_token", "access_token", "id_token", "client_secret", "encryption_key",
        "stripe-signature", "x-internal-secret",
    ]
    sentry_sdk.init(
        dsn=dsn,
        environment=resolve_environment(e),
        release=resolve_release(e),
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        traces_sample_rate=_traces_rate(e),
        event_scrubber=EventScrubber(denylist=denylist, recursive=True),
        before_send=scrub_event,
        before_breadcrumb=scrub_breadcrumb,
        integrations=[
            StarletteIntegration(failed_request_status_codes={*range(500, 600)}),
            FastApiIntegration(failed_request_status_codes={*range(500, 600)}),
        ],
    )
    sentry_sdk.set_tag("service", "quantro-flow-api")
    return True
