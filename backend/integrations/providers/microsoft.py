"""
Microsoft 365 adapter — wraps microsoft_oauth.py + microsoft_integrations_col.
Same non-reimplementation rule as google.py: sync/disconnect delegate to
functions injected from server.py.

Unlike Google, the existing Microsoft integration doc doesn't track
missing_scopes/reauthorization_required yet (see Phase 0 audit — MS
status was previously a bare boolean). We derive a best-effort limited
state from the stored `scopes` list without changing the callback's
persisted schema, so this stays additive.
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

SyncFn = Callable[[str], Awaitable[Dict[str, Any]]]
DisconnectFn = Callable[[str], Awaitable[Dict[str, Any]]]


class MicrosoftAdapter(ProviderAdapter):
    provider_id = "microsoft"
    name = "Microsoft 365"
    category = "productivity"
    description = "Outlook Mail + Calendar. Read-only by default."
    auth_type = AuthType.OAUTH2
    supports_sync = True
    supports_webhooks = False
    supports_test_mode = False
    required_scopes = ["Mail.Read", "Calendars.Read"]
    # NOTE: full incremental consent for these requires adding them to
    # microsoft_oauth.MS_SCOPES so the next /start round-trip requests
    # them — MSAL/Graph don't support requesting *only* the delta like
    # Google's incremental-auth pattern. Tracked as a follow-up; actions
    # below correctly report reauthorization_required in the meantime
    # rather than silently failing or granting themselves access.
    action_scopes = {
        "microsoft.mail.send": "Mail.Send",
        "microsoft.calendar.event.create": "Calendars.ReadWrite",
    }

    def __init__(self, col, msoa_module, sync_fn: SyncFn, disconnect_fn: DisconnectFn):
        self.col = col
        self.msoa = msoa_module
        self._sync_fn = sync_fn
        self._disconnect_fn = disconnect_fn

    async def get_status(self, workspace_id: str) -> ProviderStatus:
        if not self.msoa.is_oauth_configured():
            return ProviderStatus(provider_id=self.provider_id, status=ConnectionStatus.CONFIGURATION_MISSING)

        doc = await self.col.find_one({"workspace_id": workspace_id}, {"_id": 0})
        if not doc:
            return ProviderStatus(provider_id=self.provider_id, status=ConnectionStatus.DISCONNECTED)

        stored_scopes = set(doc.get("scopes") or [])
        missing_action_scopes = [
            s for s in self.action_scopes.values() if s not in stored_scopes
        ]
        status = ConnectionStatus.CONNECTED_LIMITED if missing_action_scopes else ConnectionStatus.CONNECTED

        return ProviderStatus(
            provider_id=self.provider_id,
            status=status,
            account=ProviderAccount(email=doc.get("account_email"), label=doc.get("account_name")),
            capabilities=["mail.read", "calendar.read"],
            missing_scopes=missing_action_scopes,
            actions_available=self.get_actions(),
            last_sync_at=_iso(doc.get("last_sync_at")),
            auto_sync=not bool(doc.get("auto_sync_paused")),
            error=doc.get("last_sync_error"),
        )

    async def disconnect(self, workspace_id: str) -> Dict[str, Any]:
        return await self._disconnect_fn(workspace_id)

    async def test_connection(self, workspace_id: str) -> Dict[str, Any]:
        doc = await self.col.find_one({"workspace_id": workspace_id})
        if not doc:
            return {"success": False, "message": "Microsoft is not connected for this workspace"}
        return {"success": True, "message": f"Connected as {doc.get('account_email') or 'unknown account'}"}

    async def sync(self, workspace_id: str) -> Dict[str, Any]:
        return await self._sync_fn(workspace_id)

    def get_capabilities(self):
        return [
            ProviderCapability(id="mail.read", label="Read Outlook Mail"),
            ProviderCapability(id="calendar.read", label="Read Outlook Calendar"),
        ]

    def get_actions(self):
        return ["microsoft.mail.send", "microsoft.calendar.event.create"]


def _iso(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
