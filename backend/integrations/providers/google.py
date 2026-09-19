"""
Google Workspace adapter — wraps the existing google_oauth.py module and
provider_secrets_store (Supabase primary with Mongo fallback/mirror).

Does NOT reimplement OAuth: connecting/reauthorizing still happens through
GET /api/integrations/google/start + /callback. sync/disconnect delegate to
functions injected from server.py.
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

# Base (read) scopes expected after first connect.
BASE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]


class GoogleAdapter(ProviderAdapter):
    provider_id = "google"
    name = "Google Workspace"
    category = "productivity"
    description = "Gmail + Calendar. Read-only by default; Actions can request write access incrementally."
    auth_type = AuthType.OAUTH2
    supports_sync = True
    supports_webhooks = False
    supports_test_mode = False
    required_scopes = list(BASE_SCOPES)
    # Write scopes an Action may request incrementally — never asked for
    # up front at first connect.
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
        secrets_store=None,
    ):
        self.col = col
        self.goog = goog_module
        self._sync_fn = sync_fn
        self._disconnect_fn = disconnect_fn
        self._secrets_store = secrets_store

    async def _load_doc(self, workspace_id: str, projection: Optional[Dict[str, int]] = None) -> Optional[Dict[str, Any]]:
        """Prefer provider_secrets_store (SB primary + Mongo fallback)."""
        if self._secrets_store is not None:
            return await self._secrets_store.get_connection(
                provider="google",
                workspace_id=workspace_id,
                mongo_col=self.col,
                projection=projection,
            )
        return await self.col.find_one({"workspace_id": workspace_id}, projection)

    async def get_status(self, workspace_id: str) -> ProviderStatus:
        if not self.goog.is_oauth_configured():
            return ProviderStatus(provider_id=self.provider_id, status=ConnectionStatus.CONFIGURATION_MISSING)

        doc = await self._load_doc(workspace_id, {"_id": 0})
        if not doc:
            return ProviderStatus(provider_id=self.provider_id, status=ConnectionStatus.DISCONNECTED)

        stored_scopes = list(doc.get("scopes") or [])
        granted = set(stored_scopes)
        missing_base = [s for s in BASE_SCOPES if s not in granted]
        missing_action = [s for s in self.action_scopes.values() if s not in granted]

        # Explicit flag from callback wins when base scopes are incomplete.
        reauth_flag = doc.get("reauthorization_required")
        if missing_base or (reauth_flag is True and missing_base):
            status = ConnectionStatus.REAUTHORIZATION_REQUIRED
            missing_scopes = missing_base
        elif missing_action:
            # Base-only (or base + partial action) → Connected Limited.
            # Not CONNECTED and not REAUTHORIZATION_REQUIRED.
            status = ConnectionStatus.CONNECTED_LIMITED
            missing_scopes = missing_action
        else:
            status = ConnectionStatus.CONNECTED
            missing_scopes = []

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
        doc = await self._load_doc(workspace_id)
        if not doc:
            return {"success": False, "message": "Google is not connected for this workspace"}
        stored_scopes = set(doc.get("scopes") or [])
        missing_base = [s for s in BASE_SCOPES if s not in stored_scopes]
        if missing_base or doc.get("reauthorization_required"):
            return {"success": False, "message": "Reauthorization required — missing base scopes"}
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
