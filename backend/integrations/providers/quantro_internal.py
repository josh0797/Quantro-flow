"""
Quantro Internal adapter — represents Quantro's own data (contacts,
calendar, onboarding, follow-ups) as a "provider" so it shows up
consistently in Connect/Actions alongside external systems. There is
nothing to connect/disconnect/test — it's always available for any
workspace with valid auth, which is exactly what get_status() reports.
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..base import AuthType, ConnectionStatus, ProviderAccount, ProviderAdapter, ProviderStatus


class QuantroInternalAdapter(ProviderAdapter):
    provider_id = "quantro_internal"
    name = "Quantro Internal"
    category = "internal"
    description = "Quantro's own CRM, calendar and workflow primitives."
    auth_type = AuthType.NONE
    supports_sync = False
    supports_webhooks = False
    supports_test_mode = False

    async def get_status(self, workspace_id: str) -> ProviderStatus:
        return ProviderStatus(
            provider_id=self.provider_id,
            status=ConnectionStatus.CONNECTED,
            account=ProviderAccount(label="This workspace"),
            capabilities=["crm.write", "calendar.write", "onboarding.write"],
            actions_available=self.get_actions(),
        )

    async def disconnect(self, workspace_id: str) -> Dict[str, Any]:
        raise NotImplementedError("quantro_internal cannot be disconnected")

    async def test_connection(self, workspace_id: str) -> Dict[str, Any]:
        return {"success": True, "message": "Always available"}

    def get_actions(self) -> List[str]:
        # Exactly the 6 legacy execute_action_for_item() action_types,
        # migrated 1:1 — see actions/handlers/quantro_internal.py.
        return [
            "quantro.calendar.event.create",
            "quantro.crm.contact.create",
            "quantro.onboarding.start",
            "quantro.followup.send",
            "quantro.review.flag",
            "quantro.inbox.ignore",
        ]
