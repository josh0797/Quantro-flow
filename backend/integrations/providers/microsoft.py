"""
Microsoft 365 adapter — wraps microsoft_oauth.py + provider_secrets_store
(Supabase primary with Mongo fallback/mirror). Same non-reimplementation
rule as google.py: sync/disconnect delegate to functions injected from server.py.
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

BASE_SCOPES = ["Mail.Read", "Calendars.Read"]


class MicrosoftAdapter(ProviderAdapter):
    provider_id = "microsoft"
    name = "Microsoft 365"
    category = "productivity"
    description = "Outlook Mail + Calendar. Read-only by default; Actions request write scopes via Grant."
    auth_type = AuthType.OAUTH2
    supports_sync = True
    supports_webhooks = False
    supports_test_mode = False
    required_scopes = list(BASE_SCOPES)
    action_scopes = {
        "microsoft.mail.send": "Mail.Send",
        "microsoft.calendar.event.create": "Calendars.ReadWrite",
    }

    def __init__(
        self,
        col,
        msoa_module,
        sync_fn: SyncFn,
        disconnect_fn: DisconnectFn,
        secrets_store=None,
    ):
        self.col = col
        self.msoa = msoa_module
        self._sync_fn = sync_fn
        self._disconnect_fn = disconnect_fn
        self._secrets_store = secrets_store

    async def _load_doc(self, workspace_id: str, projection: Optional[Dict[str, int]] = None) -> Optional[Dict[str, Any]]:
        if self._secrets_store is not None:
            return await self._secrets_store.get_connection(
                provider="microsoft",
                workspace_id=workspace_id,
                mongo_col=self.col,
                projection=projection,
            )
        return await self.col.find_one({"workspace_id": workspace_id}, projection)

    async def get_status(self, workspace_id: str) -> ProviderStatus:
        if not self.msoa.is_oauth_configured():
            return ProviderStatus(provider_id=self.provider_id, status=ConnectionStatus.CONFIGURATION_MISSING)

        doc = await self._load_doc(workspace_id, {"_id": 0})
        if not doc:
            return ProviderStatus(provider_id=self.provider_id, status=ConnectionStatus.DISCONNECTED)

        stored_scopes = set(doc.get("scopes") or [])
        # Graph sometimes returns scope URIs; normalize bare names.
        normalized = set()
        for s in stored_scopes:
            if not s:
                continue
            normalized.add(s.split("/")[-1] if "/" in s else s)

        missing_base = [s for s in BASE_SCOPES if s not in normalized and s not in stored_scopes]
        missing_action = [
            s for s in self.action_scopes.values()
            if s not in normalized and s not in stored_scopes
        ]

        if missing_base or doc.get("reauthorization_required"):
            status = ConnectionStatus.REAUTHORIZATION_REQUIRED
            missing_scopes = missing_base or list(doc.get("missing_scopes") or [])
        elif missing_action:
            status = ConnectionStatus.CONNECTED_LIMITED
            missing_scopes = missing_action
        else:
            status = ConnectionStatus.CONNECTED
            missing_scopes = []

        return ProviderStatus(
            provider_id=self.provider_id,
            status=status,
            account=ProviderAccount(email=doc.get("account_email"), label=doc.get("account_name")),
            capabilities=["mail.read", "calendar.read"],
            missing_scopes=missing_scopes,
            actions_available=self.get_actions(),
            last_sync_at=_iso(doc.get("last_sync_at")),
            auto_sync=not bool(doc.get("auto_sync_paused")),
            error=doc.get("last_sync_error"),
        )

    async def disconnect(self, workspace_id: str) -> Dict[str, Any]:
        return await self._disconnect_fn(workspace_id)

    async def test_connection(self, workspace_id: str) -> Dict[str, Any]:
        doc = await self._load_doc(workspace_id)
        if not doc:
            return {"success": False, "message": "Microsoft is not connected for this workspace"}
        stored = set(doc.get("scopes") or [])
        missing_base = [s for s in BASE_SCOPES if s not in stored]
        if missing_base:
            return {"success": False, "message": "Reauthorization required — missing base scopes"}
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
