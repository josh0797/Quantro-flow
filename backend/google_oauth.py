"""
Google OAuth 2.0 + Gmail / Calendar sync helpers (Phase 7e).

This module isolates everything Google-specific so server.py only deals
with high-level intents:

    1. ``build_authorization_url(state, scopes)`` — generates the URL
       the frontend redirects the user to.
    2. ``exchange_code_for_tokens(code)`` — completes the OAuth flow and
       returns plaintext credentials we can persist (encrypted).
    3. ``load_credentials(workspace_id)`` — fetches stored tokens for a
       workspace, decrypts them, refreshes if expired, and returns a
       google-auth ``Credentials`` object ready to call APIs.
    4. ``fetch_recent_gmail(creds, limit)`` and
       ``fetch_upcoming_calendar(creds, days)`` — the actual data calls.

Why everything lives here (and not in server.py):

* Keeps the dependency surface (google-auth-oauthlib + googleapiclient)
  contained — server.py keeps its tight FastAPI footprint.
* Token encryption and refresh logic is non-trivial; centralising it
  prevents the typical "token saved without rotation" bug.
* Easy to swap the persistence layer later (e.g. move tokens to a
  Supabase table) without touching the route handlers.

Token at-rest encryption uses Fernet (symmetric, AES-128-CBC + HMAC).
The key lives in ``GOOGLE_TOKENS_ENCRYPTION_KEY`` and MUST NOT change
between deploys; rotating it would invalidate every saved refresh
token. If we ever need rotation, add a versioned prefix and a fallback
decrypt path.
"""
from __future__ import annotations

import os
import warnings
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# ─── Configuration ────────────────────────────────────────────────────
GOOGLE_CLIENT_ID = (os.environ.get("GOOGLE_CLIENT_ID") or "").strip()
GOOGLE_CLIENT_SECRET = (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip()
# We default to <REACT_APP_BACKEND_URL>/api/integrations/google/callback
# but allow an override via GOOGLE_OAUTH_REDIRECT_URI for staging/prod.
GOOGLE_OAUTH_REDIRECT_URI = (os.environ.get("GOOGLE_OAUTH_REDIRECT_URI") or "").strip()

# Frontend URL we bounce the user back to after the callback finishes.
# We resolve this lazily off the request when possible so the same
# backend can serve multiple environments.
DEFAULT_FRONTEND_RETURN_PATH = "/welcome/inbox"

# Scopes — keep in lock-step with the playbook from the user.
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

_TOKEN_URI = "https://oauth2.googleapis.com/token"
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_REVOKE_URI = "https://oauth2.googleapis.com/revoke"


def missing_required_scopes(granted_scopes: Optional[List[str]]) -> List[str]:
    """Diff what Google actually granted against ``GOOGLE_SCOPES`` (what
    we asked for). Returns the subset of required scopes the user did
    NOT grant — e.g. because they unchecked a permission on the Google
    consent screen. An empty list means the connection is fully usable;
    a non-empty list means the caller must treat the workspace as not
    connected and prompt for re-authorization.

    Used right after the OAuth callback (and again whenever we read a
    stored integration doc) so we never silently trust a partial grant."""
    granted = set(granted_scopes or [])
    return [s for s in GOOGLE_SCOPES if s not in granted]

_ENCRYPTION_KEY = (os.environ.get("GOOGLE_TOKENS_ENCRYPTION_KEY") or "").encode()


def config_status() -> Dict[str, bool]:
    """Granular OAuth readiness diagnostic.

    SECURITY: this function returns ONLY booleans — never the actual
    client_id/secret/key values. Safe to expose through an authenticated
    API response (e.g. GET /api/integrations/google/status) so an admin
    can tell exactly which piece of config is missing in a given
    deployment (preview vs. production often have different env vars
    set) without ever leaking a secret over the wire.
    """
    backend_public_url = (os.environ.get("BACKEND_PUBLIC_URL") or "").strip()
    return {
        "client_id_configured": bool(GOOGLE_CLIENT_ID),
        "client_secret_configured": bool(GOOGLE_CLIENT_SECRET),
        "encryption_key_configured": bool(_ENCRYPTION_KEY),
        "backend_public_url_configured": bool(backend_public_url),
        # True if resolve_redirect_uri() can produce a URI without
        # needing to fall back to the incoming request's own host.
        "redirect_uri_configured": bool(GOOGLE_OAUTH_REDIRECT_URI or backend_public_url),
    }


def is_oauth_configured() -> bool:
    """True iff the deploy has a usable client_id/secret/encryption-key
    triple. Kept as the single source of truth `config_status()` derives
    the aggregate `configured` flag from — never duplicate this check."""
    cfg = config_status()
    return bool(
        cfg["client_id_configured"]
        and cfg["client_secret_configured"]
        and cfg["encryption_key_configured"]
    )


def _fernet() -> Fernet:
    if not _ENCRYPTION_KEY:
        raise RuntimeError(
            "GOOGLE_TOKENS_ENCRYPTION_KEY is not set; refusing to en/decrypt"
        )
    return Fernet(_ENCRYPTION_KEY)


def encrypt_token(value: Optional[str]) -> Optional[str]:
    """Encrypt a token. Pass-through ``None`` so optional fields stay nullable."""
    if not value:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt_token(value: Optional[str]) -> Optional[str]:
    """Decrypt a token. Returns ``None`` if the input is empty or
    unrecoverable (e.g. the encryption key was rotated). Callers must
    treat ``None`` as "no token" and re-trigger the OAuth flow."""
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def _client_config() -> Dict[str, Any]:
    """Mirror the shape google-auth-oauthlib expects from a Web client."""
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
        }
    }


def resolve_redirect_uri(request_base_url: Optional[str] = None) -> str:
    """Pick the redirect URI Google will call back to.

    Priority order (highest wins):
      1. ``GOOGLE_OAUTH_REDIRECT_URI`` env var — explicit, provider-specific
         override. Use this if Google's registered callback ever needs to
         diverge from the shared backend domain.
      2. ``BACKEND_PUBLIC_URL`` — the single source of truth for "what is
         our production backend's public domain" (e.g.
         ``https://quantro-os.emergent.host`` or a custom
         ``https://api.quantroflow.online``). Shared with Microsoft so
         both providers always agree on the canonical domain without
         duplicating it in two env vars.
      3. The request base URL (FastAPI gives us scheme+host) — dev/preview
         fallback only; never rely on this in production because a proxy
         or preview subdomain could differ from what's registered with
         Google.
      4. ``REACT_APP_BACKEND_URL`` — legacy fallback (frontend/.env, often
         mirrored into backend/.env on Emergent's preview environments).
    """
    if GOOGLE_OAUTH_REDIRECT_URI:
        return GOOGLE_OAUTH_REDIRECT_URI
    backend_public_url = (os.environ.get("BACKEND_PUBLIC_URL") or "").strip()
    if backend_public_url:
        return backend_public_url.rstrip("/") + "/api/integrations/google/callback"
    if request_base_url:
        return request_base_url.rstrip("/") + "/api/integrations/google/callback"
    backend_url = (os.environ.get("REACT_APP_BACKEND_URL") or "").strip()
    if backend_url:
        return backend_url.rstrip("/") + "/api/integrations/google/callback"
    raise RuntimeError(
        "Cannot resolve redirect URI: set GOOGLE_OAUTH_REDIRECT_URI, "
        "BACKEND_PUBLIC_URL, or REACT_APP_BACKEND_URL, or pass "
        "request_base_url explicitly."
    )


def build_authorization_url(state: str, redirect_uri: str) -> str:
    """Compose the URL the frontend opens for user consent.

    ``access_type='offline'`` + ``prompt='consent'`` are MANDATORY — they
    are the difference between getting a refresh token (and thus being
    able to sync forever) and getting only a 1-hour access token.
    """
    flow = Flow.from_client_config(
        _client_config(), scopes=GOOGLE_SCOPES, redirect_uri=redirect_uri
    )
    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
        state=state,
    )
    return url


def exchange_code_for_tokens(
    code: str, redirect_uri: str
) -> Tuple[Credentials, Dict[str, Any]]:
    """Exchange the ``code`` Google sent us for tokens + user info.

    Returns ``(credentials, profile)`` where ``profile`` includes the
    user's email/sub so the caller can persist account identity. We
    suppress the noisy "scope changed" warning Google emits when it
    re-orders the scopes.
    """
    flow = Flow.from_client_config(
        _client_config(), scopes=GOOGLE_SCOPES, redirect_uri=redirect_uri
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        flow.fetch_token(code=code)
    creds = flow.credentials

    # Pull the OIDC ID token so we know which Google account just authed.
    profile: Dict[str, Any] = {}
    try:
        oauth2 = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        info = oauth2.userinfo().get().execute()
        profile = {
            "email": info.get("email"),
            "name": info.get("name"),
            "picture": info.get("picture"),
            "google_user_id": info.get("id"),
        }
    except Exception:  # noqa: BLE001 — userinfo is optional, never block flow
        profile = {}

    return creds, profile


def credentials_from_tokens(
    access_token: str,
    refresh_token: Optional[str],
    expires_at: Optional[datetime],
    scopes: Optional[List[str]] = None,
) -> Credentials:
    """Hydrate a google-auth ``Credentials`` from our stored fields."""
    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=_TOKEN_URI,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=scopes or GOOGLE_SCOPES,
        expiry=(
            expires_at.replace(tzinfo=None)
            if expires_at and expires_at.tzinfo
            else expires_at
        ),
    )


def maybe_refresh(creds: Credentials) -> bool:
    """Refresh the access token in place if it's expired. Returns True
    if a refresh actually happened, so the caller can re-encrypt and
    persist the new pair."""
    expiry = creds.expiry
    if expiry is None:
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) < expiry - timedelta(seconds=60):
        return False
    if not creds.refresh_token:
        # Without a refresh token we can't recover; caller must re-auth.
        return False
    creds.refresh(GoogleRequest())
    return True


# ─── Data fetchers ────────────────────────────────────────────────────
def _decode_email_address(raw: Optional[str]) -> Tuple[str, str]:
    """Split 'Name <addr@x.com>' into (name, addr). Defensive against
    malformed headers — we never raise, we degrade."""
    if not raw:
        return ("", "")
    raw = raw.strip()
    if "<" in raw and ">" in raw:
        name = raw.split("<", 1)[0].strip().strip('"')
        addr = raw.split("<", 1)[1].split(">", 1)[0].strip()
        return (name, addr)
    return ("", raw)


def fetch_recent_gmail(creds: Credentials, limit: int = 50) -> List[Dict[str, Any]]:
    """Return the user's most recent inbox messages, normalised into the
    shape the rest of the app expects (subject, from, snippet, date)."""
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    list_resp = (
        service.users()
        .messages()
        .list(userId="me", maxResults=limit, labelIds=["INBOX"])
        .execute()
    )
    msgs = list_resp.get("messages", []) or []
    out: List[Dict[str, Any]] = []
    for m in msgs:
        try:
            full = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=m["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )
        except HttpError:
            continue
        headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
        from_name, from_addr = _decode_email_address(headers.get("From"))
        # Internal date is ms since epoch.
        ts_ms = int(full.get("internalDate") or 0)
        ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc) if ts_ms else None
        out.append(
            {
                "gmail_id": full.get("id"),
                "thread_id": full.get("threadId"),
                "subject": headers.get("Subject") or "(sin asunto)",
                "from_name": from_name,
                "from_address": from_addr,
                "snippet": full.get("snippet") or "",
                "date_iso": ts.isoformat() if ts else None,
                "label_ids": full.get("labelIds") or [],
            }
        )
    return out


def fetch_upcoming_calendar(creds: Credentials, days: int = 30) -> List[Dict[str, Any]]:
    """Return upcoming calendar events for the next ``days`` days."""
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    now = datetime.now(timezone.utc)
    time_max = now + timedelta(days=days)
    events_resp = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=100,
        )
        .execute()
    )
    raw_events = events_resp.get("items", []) or []
    out: List[Dict[str, Any]] = []
    for ev in raw_events:
        start = (ev.get("start") or {}).get("dateTime") or (ev.get("start") or {}).get("date")
        end = (ev.get("end") or {}).get("dateTime") or (ev.get("end") or {}).get("date")
        attendees = [
            {"email": a.get("email"), "response": a.get("responseStatus")}
            for a in (ev.get("attendees") or [])
            if a.get("email")
        ]
        out.append(
            {
                "gcal_id": ev.get("id"),
                "title": ev.get("summary") or "(sin título)",
                "description": ev.get("description") or "",
                "location": ev.get("location") or "",
                "start_iso": start,
                "end_iso": end,
                "attendees": attendees,
                "html_link": ev.get("htmlLink"),
                "status": ev.get("status"),
            }
        )
    return out


def revoke_token(refresh_or_access_token: str) -> bool:
    """Best-effort token revocation. Google accepts either token; we hit
    the revoke endpoint and trust the 200/400 response. Returns True if
    Google acknowledged the revoke (or said the token was already
    invalid — both are 'we're done')."""
    import httpx

    try:
        resp = httpx.post(
            _REVOKE_URI,
            data={"token": refresh_or_access_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=5.0,
        )
        return resp.status_code in (200, 400)
    except Exception:  # noqa: BLE001
        return False
