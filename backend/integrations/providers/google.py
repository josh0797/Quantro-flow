"""
Google Workspace adapter — wraps the existing google_oauth.py module and
google_integrations_col. Does NOT reimplement OAuth: connecting/
reauthorizing still happens through the existing
GET /api/integrations/google/start + /callback routes (top-level
redirect flow — an adapter method can't drive a browser redirect), and
this adapter's `sync`/`disconnect` delegate to the exact same functions
server.py's legacy routes already use, passed in via the constructor so
there is only ever one implementation of "how Google sync/disconnect
works".
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

from ..base import (
    AuthType,
    ConnectionStatus,
    ProviderAccount,
    ProviderAdapter,
    ProviderCapability,
    ProviderStatus,
)
from ..secrets import redact_error_text

SyncFn = Callable[[str], Awaitable[Dict[str, Any]]]
DisconnectFn = Callable[[str], Awaitable[Dict[str, Any]]]


class GoogleAdapter(ProviderAdapter):
    provider_id = "google"
    name = "Google Workspace"
    category = "productivity"
    description = "Gmail + Calendar. Read-only by default; Actions can request write access incrementally."
    auth_type = AuthType.OAUTH2
    supports_sync = True
    supports_webhooks = False
    supports_test_mode = False
    required_scopes = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/calendar.readonly",
    ]
    # Write scopes an Action may request incrementally — never asked for
    # up front at first connect (see google_oauth_actions.incremental_auth_url).
    action_scopes = {
        "google.gmail.send": "https://www.googleapis.com/auth/gmail.send",
        "google.calendar.event.create": "https://www.googleapis.com/auth/calendar.events",
    }

    def __init__(
        self,
        col,
        goog_module,
        sync_fn: SyncFn,
        disconnect_fn: DisconnectFn,
    ):
        self.col = col
        self.goog = goog_module
        self._sync_fn = sync_fn
        self._disconnect_fn = disconnect_fn

    async def get_status(self, workspace_id: str) -> ProviderStatus:
        if not self.goog.is_oauth_configured():
            return ProviderStatus(provider_id=self.provider_id, status=ConnectionStatus.CONFIGURATION_MISSING)

        doc = await self.col.find_one({"workspace_id": workspace_id}, {"_id": 0})
        if not doc:
            return ProviderStatus(provider_id=self.provider_id, status=ConnectionStatus.DISCONNECTED)

        stored_scopes = doc.get("scopes") or []
        missing_scopes = doc.get("missing_scopes")
        if missing_scopes is None:
            missing_scopes = self.goog.missing_required_scopes(stored_scopes)
        reauth_required = doc.get("reauthorization_required")
        if reauth_required is None:
            reauth_required = bool(missing_scopes)

        if reauth_required:
            status = ConnectionStatus.REAUTHORIZATION_REQUIRED
        elif missing_scopes:
            # Base scopes present, but an *action* scope (write) is
            # missing — connected, just limited for Actions.
            status = ConnectionStatus.CONNECTED_LIMITED
        else:
            status = ConnectionStatus.CONNECTED

        return ProviderStatus(
            provider_id=self.provider_id,
            status=status,
            account=ProviderAccount(email=doc.get("account_email"), label=doc.get("account_name")),
            capabilities=["gmail.read", "calendar.read"],
            missing_scopes=missing_scopes,
            actions_available=self.get_actions(),
            last_sync_at=_iso(doc.get("last_sync_at")),
            auto_sync=not bool(doc.get("auto_sync_paused")),
            error=redact_error_text(doc.get("last_sync_error")) if doc.get("last_sync_error") else None,
        )

    async def disconnect(self, workspace_id: str) -> Dict[str, Any]:
        return await self._disconnect_fn(workspace_id)

    async def test_connection(self, workspace_id: str) -> Dict[str, Any]:
        doc = await self.col.find_one({"workspace_id": workspace_id})
        if not doc:
            return {"success": False, "message": "Google is not connected for this workspace"}
        if doc.get("reauthorization_required"):
            return {"success": False, "message": "Reauthorization required — missing scopes"}
        return {"success": True, "message": f"Connected as {doc.get('account_email') or 'unknown account'}"}

    async def sync(self, workspace_id: str) -> Dict[str, Any]:
        return await self._sync_fn(workspace_id)

    def get_capabilities(self):
        return [
            ProviderCapability(id="gmail.read", label="Read Gmail"),
            ProviderCapability(id="calendar.read", label="Read Calendar"),
        ]

    def get_actions(self):
        return ["google.gmail.send", "google.calendar.event.create"]


def _iso(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
