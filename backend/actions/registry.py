from __future__ import annotations

from typing import Dict, List, Optional

from .base import ActionDefinition

_REGISTRY: Dict[str, ActionDefinition] = {}


def register_action(definition: ActionDefinition) -> None:
    _REGISTRY[definition.action_id] = definition


def get_action(action_id: str) -> Optional[ActionDefinition]:
    return _REGISTRY.get(action_id)


def list_actions(
    provider: Optional[str] = None,
    category: Optional[str] = None,  # reserved for future use; providers double as categories today
) -> List[ActionDefinition]:
    out = list(_REGISTRY.values())
    if provider:
        out = [a for a in out if a.provider == provider]
    return out


def clear_registry() -> None:
    """Test-only: reset between test modules."""
    _REGISTRY.clear()
