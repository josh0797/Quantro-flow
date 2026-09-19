"""
Microsoft Graph (Outlook Mail + Calendar) OAuth helpers — Phase 7e.2.

Mirrors ``google_oauth.py`` 1:1 in shape so the rest of the backend can
treat both providers symmetrically. Uses MSAL for the OAuth dance and
plain httpx for the actual Graph API calls (the ``msgraph`` SDK is
heavy and async-incompatible with our motor stack).

Why ``common`` tenant?

* Quantro Flow is a SaaS that needs to accept both consumer accounts
  (outlook.com, hotmail.com, live.com) and work/school accounts. The
  ``common`` endpoint multiplexes both. Customers who later need a
  single-tenant Azure deployment can override ``MS_TENANT_ID`` in env.

Token encryption reuses the same Fernet key (``GOOGLE_TOKENS_ENCRYPTION_KEY``)
because rotating a single key is simpler than juggling per-provider
keys, and Fernet is symmetric anyway.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
from cryptography.fernet import Fernet, InvalidToken
import msal


# ─── Configuration ────────────────────────────────────────────────────
MS_CLIENT_ID = (os.environ.get("MS_CLIENT_ID") or "").strip()
MS_CLIENT_SECRET = (os.environ.get("MS_CLIENT_SECRET") or "").strip()
# 'common' lets both personal + work/school accounts sign in.
# Customers wanting tenant lock-down can set MS_TENANT_ID=<their_tenant>.
MS_TENANT_ID = (os.environ.get("MS_TENANT_ID") or "common").strip()
MS_OAUTH_REDIRECT_URI = (os.environ.get("MS_OAUTH_REDIRECT_URI") or "").strip()

# Same scope set as the Google integration, mapped to Graph permissions.
# offline_access is REQUIRED for refresh tokens — otherwise we can only
# stay live for the access_token lifetime (~1h).
MS_SCOPES = [
    "openid",
    "profile",
    "email",
    "offline_access",
    "Mail.Read",
    "Calendars.Read",
    "User.Read",
]

_AUTHORITY = f"https://login.microsoftonline.com/{MS_TENANT_ID}"
_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

_ENCRYPTION_KEY = (os.environ.get("GOOGLE_TOKENS_ENCRYPTION_KEY") or "").encode()


def is_oauth_configured() -> bool:
    return bool(MS_CLIENT_ID and MS_CLIENT_SECRET and _ENCRYPTION_KEY)


def _fernet() -> Fernet:
    if not _ENCRYPTION_KEY:
        raise RuntimeError("GOOGLE_TOKENS_ENCRYPTION_KEY is not set")
    return Fernet(_ENCRYPTION_KEY)


def encrypt_token(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt_token(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def resolve_redirect_uri(request_base_url: Optional[str] = None) -> str:
    """Mirrors google_oauth.resolve_redirect_uri's priority order:
    MS_OAUTH_REDIRECT_URI override > BACKEND_PUBLIC_URL (shared source of
    truth with Google) > request base URL (dev fallback) >
    REACT_APP_BACKEND_URL (legacy fallback)."""
    if MS_OAUTH_REDIRECT_URI:
        return MS_OAUTH_REDIRECT_URI
    backend_public_url = (os.environ.get("BACKEND_PUBLIC_URL") or "").strip()
    if backend_public_url:
        return backend_public_url.rstrip("/") + "/api/integrations/microsoft/callback"
    if request_base_url:
        return request_base_url.rstrip("/") + "/api/integrations/microsoft/callback"
    backend_url = (os.environ.get("REACT_APP_BACKEND_URL") or "").strip()
    if backend_url:
        return backend_url.rstrip("/") + "/api/integrations/microsoft/callback"
    raise RuntimeError(
        "Cannot resolve redirect URI: set MS_OAUTH_REDIRECT_URI, "
        "BACKEND_PUBLIC_URL, or REACT_APP_BACKEND_URL."
    )


def _msal_client() -> msal.ConfidentialClientApplication:
    """One MSAL app per call — MSAL is cheap to construct and we don't
    want long-lived globals leaking tokens. We strip the OIDC scopes
    from MS_SCOPES when MSAL asks us for them; MSAL adds them itself."""
    return msal.ConfidentialClientApplication(
        client_id=MS_CLIENT_ID,
        client_credential=MS_CLIENT_SECRET,
        authority=_AUTHORITY,
    )


def _graph_scopes() -> List[str]:
    """MSAL's `scopes` argument expects only the Graph permissions —
    it adds openid/profile/email/offline_access automatically. Passing
    them explicitly causes a 'Reserved scopes' error."""
    return [s for s in MS_SCOPES if s not in {"openid", "profile", "email", "offline_access"}]


def build_authorization_url(
    state: str,
    redirect_uri: str,
    scopes: Optional[List[str]] = None,
) -> str:
    """Initial connect uses read/base Graph scopes only.

    Pass ``scopes`` explicitly for incremental consent (base + action writes).
    """
    app = _msal_client()
    return app.get_authorization_request_url(
        scopes=list(scopes) if scopes is not None else _graph_scopes(),
        state=state,
        redirect_uri=redirect_uri,
        prompt="select_account",  # let multi-account users pick deliberately
    )


def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    scopes: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Returns (token_payload, profile). ``token_payload`` has
    ``access_token``, ``refresh_token``, ``expires_in`` and the granted
    ``scope`` string. ``profile`` is a best-effort /me lookup.

    ``scopes`` must match the authorization request (incremental consent
    stores the requested set in OAuth state and passes it here).
    """
    app = _msal_client()
    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=list(scopes) if scopes is not None else _graph_scopes(),
        redirect_uri=redirect_uri,
    )
    if "error" in result:
        raise RuntimeError(f"MSAL error: {result.get('error')} - {result.get('error_description')}")

    profile: Dict[str, Any] = {}
    access_token = result.get("access_token")
    if access_token:
        try:
            with httpx.Client(timeout=8.0) as cx:
                r = cx.get(
                    f"{_GRAPH_BASE}/me",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if r.status_code == 200:
                me = r.json()
                profile = {
                    "email": me.get("mail") or me.get("userPrincipalName"),
                    "name": me.get("displayName"),
                    "ms_user_id": me.get("id"),
                }
        except Exception:  # noqa: BLE001
            profile = {}

    return result, profile


def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    """Exchange a refresh token for a new access token. MSAL handles
    rotation if the IdP returns a new refresh token."""
    app = _msal_client()
    result = app.acquire_token_by_refresh_token(
        refresh_token=refresh_token, scopes=_graph_scopes(),
    )
    if "error" in result:
        raise RuntimeError(f"MSAL refresh error: {result.get('error_description')}")
    return result


def maybe_refresh_dict(stored: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """If ``stored`` represents an expired token, return a freshened
    payload (to persist + use). Otherwise return None.
    Caller is responsible for re-encrypting and saving."""
    expiry = stored.get("expires_at")
    if isinstance(expiry, datetime):
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < expiry - timedelta(seconds=60):
            return None
    if not stored.get("refresh_token_plain"):
        return None
    fresh = refresh_access_token(stored["refresh_token_plain"])
    return fresh


# ─── Data fetchers ────────────────────────────────────────────────────
def fetch_recent_outlook(access_token: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Pull ``limit`` most recent inbox messages, normalised to match
    the shape of fetch_recent_gmail() so the rest of the app doesn't
    have to branch on provider."""
    params = {
        "$top": str(min(limit, 50)),
        "$select": "id,conversationId,subject,from,bodyPreview,receivedDateTime,categories",
        "$orderby": "receivedDateTime desc",
    }
    with httpx.Client(timeout=15.0) as cx:
        r = cx.get(
            f"{_GRAPH_BASE}/me/mailFolders/Inbox/messages",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )
    r.raise_for_status()
    items = (r.json() or {}).get("value", []) or []
    out: List[Dict[str, Any]] = []
    for m in items:
        from_obj = (m.get("from") or {}).get("emailAddress") or {}
        out.append({
            "ms_id": m.get("id"),
            "thread_id": m.get("conversationId"),
            "subject": m.get("subject") or "(sin asunto)",
            "from_name": from_obj.get("name") or "",
            "from_address": from_obj.get("address") or "",
            "snippet": m.get("bodyPreview") or "",
            "date_iso": m.get("receivedDateTime"),
            "categories": m.get("categories") or [],
        })
    return out


def fetch_upcoming_outlook_events(access_token: str, days: int = 30) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    # Outlook calendarView requires explicit start/end window query.
    params = {
        "startDateTime": now.isoformat(),
        "endDateTime": end.isoformat(),
        "$top": "100",
        "$orderby": "start/dateTime",
        "$select": "id,subject,bodyPreview,location,start,end,attendees,webLink,showAs",
    }
    with httpx.Client(timeout=15.0) as cx:
        r = cx.get(
            f"{_GRAPH_BASE}/me/calendarView",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Prefer": 'outlook.timezone="UTC"',
            },
            params=params,
        )
    r.raise_for_status()
    items = (r.json() or {}).get("value", []) or []
    out: List[Dict[str, Any]] = []
    for ev in items:
        start = (ev.get("start") or {}).get("dateTime")
        end_at = (ev.get("end") or {}).get("dateTime")
        location = ((ev.get("location") or {}).get("displayName")) or ""
        attendees = [
            {"email": (a.get("emailAddress") or {}).get("address"),
             "response": (a.get("status") or {}).get("response")}
            for a in (ev.get("attendees") or [])
            if (a.get("emailAddress") or {}).get("address")
        ]
        out.append({
            "ms_id": ev.get("id"),
            "title": ev.get("subject") or "(sin título)",
            "description": ev.get("bodyPreview") or "",
            "location": location,
            "start_iso": start,
            "end_iso": end_at,
            "attendees": attendees,
            "html_link": ev.get("webLink"),
            "status": ev.get("showAs"),
        })
    return out


# ─── Quantro Actions — incremental write-scope authorization ──────────
# Mirrors google_oauth.py's ACTION_SCOPES. NOTE (see module docstring on
# MS_SCOPES): Graph/MSAL don't support Google-style incremental consent
# — requesting these requires adding them to MS_SCOPES and having the
# user re-run /api/integrations/microsoft/start, which re-prompts for
# the full scope set. Handlers below correctly report
# reauthorization_required rather than silently failing in the
# meantime; wiring the actual re-consent UX is a follow-up.
ACTION_SCOPES = {
    "microsoft.mail.send": "Mail.Send",
    "microsoft.calendar.event.create": "Calendars.ReadWrite",
}


def missing_base_scopes(granted_scopes: Optional[List[str]]) -> List[str]:
    """Diff granted scopes against read-only MS base Graph permissions."""
    granted = set()
    for s in granted_scopes or []:
        if not s:
            continue
        granted.add(s.split("/")[-1] if "/" in s else s)
    base = [s for s in MS_SCOPES if s not in {"openid", "profile", "email", "offline_access"}]
    return [s for s in base if s not in granted]


def scopes_for_incremental(additional_scopes: List[str]) -> List[str]:
    """Base Graph scopes plus action write scopes (Mail.Send / Calendars.ReadWrite)."""
    scopes = list(_graph_scopes())
    for s in additional_scopes or []:
        bare = s.split("/")[-1] if "/" in s else s
        if bare and bare not in scopes:
            scopes.append(bare)
    return scopes


def build_incremental_authorization_url(
    state: str, redirect_uri: str, additional_scopes: List[str]
) -> str:
    """Request base Graph scopes PLUS action write scopes (Connected Limited → Grant).

    MSAL re-requests the union so previously granted refresh tokens remain
    usable after the user consents to Mail.Send / Calendars.ReadWrite.
    Do NOT put write scopes in the initial MS_SCOPES connect set.
    Caller must persist ``scopes_for_incremental(additional_scopes)`` in OAuth
    state and pass that same list to ``exchange_code_for_tokens``.
    """
    scopes = scopes_for_incremental(additional_scopes)
    app = _msal_client()
    return app.get_authorization_request_url(
        scopes=scopes,
        state=state,
        redirect_uri=redirect_uri,
        prompt="consent",
    )


def send_mail(access_token: str, to: str, subject: str, body: str) -> None:
    """Send a plain-text email via Microsoft Graph. Requires Mail.Send
    — callers MUST verify it's present in stored scopes first (see
    actions/handlers/microsoft.py)."""
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        }
    }
    with httpx.Client(timeout=15.0) as cx:
        r = cx.post(
            f"{_GRAPH_BASE}/me/sendMail",
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload,
        )
    r.raise_for_status()


def create_calendar_event(
    access_token: str, subject: str, start_iso: str, end_iso: str,
    description: str = "", location: str = "", attendees: Optional[List[str]] = None,
) -> str:
    """Create a real Outlook Calendar event. Requires Calendars.ReadWrite
    — see send_mail()'s docstring for the same scope-check rule."""
    payload: Dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": "Text", "content": description},
        "start": {"dateTime": start_iso, "timeZone": "UTC"},
        "end": {"dateTime": end_iso, "timeZone": "UTC"},
        "location": {"displayName": location},
    }
    if attendees:
        payload["attendees"] = [{"emailAddress": {"address": a}, "type": "required"} for a in attendees]
    with httpx.Client(timeout=15.0) as cx:
        r = cx.post(
            f"{_GRAPH_BASE}/me/events",
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload,
        )
    r.raise_for_status()
    return r.json().get("id")


def revoke_token(_token: str) -> bool:
    """Microsoft does not expose a public revoke endpoint for personal
    accounts. The closest action is admin-level tenant-wide revocation
    via PATCH /users/{id}/revokeSignInSessions, which requires
    privileged scopes we don't have. We return True so the caller's
    cleanup path stays uniform with Google's behaviour — the local
    delete still happens, and the next access attempt with a stale
    token will fail naturally."""
    return True
