"""
Quantro Connect — provider adapter contract.

A ProviderAdapter describes ONE external system (Google, Microsoft,
Facturapi, the internal Quantro provider, and — in the future — any
other system) in a shape the rest of the platform (Connect UI, Actions
registry, System Health) can reason about without knowing anything
provider-specific.

Design rules (do not violate these when adding a provider):
  * No UI logic here. No HTML/JSX/copy strings beyond short machine
    labels — localization and presentation belong to the frontend.
  * No direct FastAPI/Request coupling. Adapters are plain async
    Python objects constructed with whatever they need (a Mongo
    collection, a decrypt function, ...) injected via __init__. This
    keeps them independently unit-testable and avoids circular imports
    with server.py.
  * Adapters never raise raw provider exceptions up to the caller —
    they catch and translate into the ProviderError vocabulary
    (see errors.py) so the UI never has to parse Facturapi/Google/
    Microsoft-specific error shapes.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    CONNECTED_LIMITED = "connected_limited"
    REAUTHORIZATION_REQUIRED = "reauthorization_required"
    DISCONNECTED = "disconnected"
    CONFIGURATION_MISSING = "configuration_missing"
    ERROR = "error"


class AuthType(str, Enum):
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    NONE = "none"


@dataclass
class ProviderCapability:
    """One thing a provider can *do for the platform* at a data level
    (as opposed to an Action, which is a thing a user/agent can *trigger*).
    e.g. {"id": "gmail.read", "label": "Read Gmail"}."""
    id: str
    label: str


@dataclass
class ProviderAccount:
    """Client-safe identity of the connected account/org. Never put a
    secret or token in here — this dataclass is serialized straight to
    the API response."""
    id: Optional[str] = None
    label: Optional[str] = None
    email: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderStatus:
    provider_id: str
    status: ConnectionStatus
    account: Optional[ProviderAccount] = None
    capabilities: List[str] = field(default_factory=list)
    missing_scopes: List[str] = field(default_factory=list)
    actions_available: List[str] = field(default_factory=list)
    last_sync_at: Optional[str] = None
    auto_sync: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "account": {
                "id": self.account.id,
                "label": self.account.label,
                "email": self.account.email,
                **self.account.extra,
            } if self.account else None,
            "capabilities": self.capabilities,
            "missing_scopes": self.missing_scopes,
            "actions_available": self.actions_available,
            "last_sync_at": self.last_sync_at,
            "auto_sync": self.auto_sync,
            "error": self.error,
        }


class ProviderAdapter(abc.ABC):
    """Base class every provider adapter implements.

    Class-level metadata (provider_id/name/category/...) is declared as
    plain class attributes so the registry can list every provider's
    static shape without instantiating anything.
    """

    provider_id: str
    name: str
    category: str  # "productivity" | "fiscal" | "ai" | "crm" | "automation" | "internal"
    description: str = ""
    auth_type: AuthType = AuthType.NONE
    supports_sync: bool = False
    supports_webhooks: bool = False
    supports_test_mode: bool = False
    required_scopes: List[str] = []
    configuration_schema: Dict[str, Any] = {}

    @abc.abstractmethod
    async def get_status(self, workspace_id: str) -> ProviderStatus:
        ...

    async def connect(self, workspace_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Establish a connection. OAuth providers don't implement this
        (they use their existing /start + /callback redirect routes —
        see each adapter's docstring); API-key providers do."""
        raise NotImplementedError(f"{self.provider_id} does not support direct connect(); use its own connect route")

    @abc.abstractmethod
    async def disconnect(self, workspace_id: str) -> Dict[str, Any]:
        ...

    @abc.abstractmethod
    async def test_connection(self, workspace_id: str) -> Dict[str, Any]:
        ...

    async def sync(self, workspace_id: str) -> Dict[str, Any]:
        if not self.supports_sync:
            raise NotImplementedError(f"{self.provider_id} does not support sync()")
        raise NotImplementedError

    def get_capabilities(self) -> List[ProviderCapability]:
        return []

    def get_actions(self) -> List[str]:
        """Action IDs (from the Actions registry) this provider exposes.
        Kept as a plain list of ids — the Actions registry is the
        source of truth for the full Action definition."""
        return []
