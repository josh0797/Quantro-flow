"""
Provider Registry — the backend's single source of truth for which
providers exist. The frontend's old INTEGRATION_MANIFEST (still used by
IntegrationsPanel.js for openai/crm/webhook) should NOT be extended for
new providers; register them here instead and let
GET /api/connect/providers describe them.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .base import ProviderAdapter

_REGISTRY: Dict[str, ProviderAdapter] = {}


def register_provider(adapter: ProviderAdapter) -> None:
    _REGISTRY[adapter.provider_id] = adapter


def get_provider(provider_id: str) -> Optional[ProviderAdapter]:
    return _REGISTRY.get(provider_id)


def list_providers() -> List[ProviderAdapter]:
    return list(_REGISTRY.values())


def clear_registry() -> None:
    """Test-only: reset the registry between test modules."""
    _REGISTRY.clear()
