"""
ConnectService — the single object server.py talks to for every
provider-agnostic Connect operation. Endpoints stay tiny (auth +
workspace resolution + call one of these methods); all provider-
specific behavior lives in the adapters via the registry.
"""
from __future__ import annotations

from typing import Any, Dict, List

from errors import QuantroError
from .registry import get_provider, list_providers


class ConnectService:
    async def list_providers(self, workspace_id: str) -> List[Dict[str, Any]]:
        out = []
        for adapter in list_providers():
            status = await adapter.get_status(workspace_id)
            out.append(_describe(adapter, status))
        return out

    async def list_connections(self, workspace_id: str) -> List[Dict[str, Any]]:
        """Only providers that are actually connected (in any state other
        than disconnected/configuration_missing) — for a "your active
        tools" summary view distinct from the full catalog."""
        all_providers = await self.list_providers(workspace_id)
        return [p for p in all_providers if p["status"] not in ("disconnected", "configuration_missing")]

    async def get_provider(self, workspace_id: str, provider_id: str) -> Dict[str, Any]:
        adapter = get_provider(provider_id)
        if not adapter:
            raise QuantroError("invalid_input", f"Unknown provider: {provider_id}")
        status = await adapter.get_status(workspace_id)
        return _describe(adapter, status)

    async def test_connection(self, workspace_id: str, provider_id: str) -> Dict[str, Any]:
        adapter = get_provider(provider_id)
        if not adapter:
            raise QuantroError("invalid_input", f"Unknown provider: {provider_id}")
        return await adapter.test_connection(workspace_id)

    async def sync(self, workspace_id: str, provider_id: str) -> Dict[str, Any]:
        adapter = get_provider(provider_id)
        if not adapter:
            raise QuantroError("invalid_input", f"Unknown provider: {provider_id}")
        if not adapter.supports_sync:
            raise QuantroError("invalid_input", f"{provider_id} does not support sync")
        return await adapter.sync(workspace_id)

    async def disconnect(self, workspace_id: str, provider_id: str) -> Dict[str, Any]:
        adapter = get_provider(provider_id)
        if not adapter:
            raise QuantroError("invalid_input", f"Unknown provider: {provider_id}")
        return await adapter.disconnect(workspace_id)


def _describe(adapter, status) -> Dict[str, Any]:
    d = status.to_dict()
    d["provider_id"] = adapter.provider_id
    d["name"] = adapter.name
    d["category"] = adapter.category
    d["description"] = adapter.description
    d["auth_type"] = adapter.auth_type.value
    d["supports_sync"] = adapter.supports_sync
    d["supports_webhooks"] = adapter.supports_webhooks
    d["supports_test_mode"] = adapter.supports_test_mode
    d["configuration_schema"] = adapter.configuration_schema
    return d
