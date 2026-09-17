"""
Quantro Actions — the contract every Action (a thing Quantro can *do*
through a connected provider) implements. See registry.py for how
Actions are registered and executor.py for the one execution path
every caller (manual execute, the migrated inbox auto-execute, batch
approve, ...) funnels through.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionStatus(str, Enum):
    SUGGESTED = "suggested"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SIMULATED = "simulated"


@dataclass
class ActionContext:
    """Everything a handler needs, injected once by server.py at
    startup via ActionExecutor(deps=...) rather than imported — keeps
    handlers unit-testable without a running FastAPI app or real Mongo."""
    workspace_id: str
    requested_by: Optional[str]
    source: str
    dry_run: bool
    deps: Dict[str, Any]

    def dep(self, key: str) -> Any:
        if key not in self.deps:
            raise RuntimeError(f"ActionContext missing required dependency: {key}")
        return self.deps[key]


@dataclass
class ActionResult:
    status: str  # one of ExecutionStatus, but handlers only ever return succeeded/failed/simulated
    result_metadata: Dict[str, Any] = field(default_factory=dict)
    provider_request_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message_sanitized: Optional[str] = None


ActionHandler = Callable[[ActionContext, Dict[str, Any]], Awaitable[ActionResult]]


@dataclass
class ActionDefinition:
    action_id: str  # "<provider>.<resource>.<verb>"
    provider: str
    name: str
    description: str
    input_schema: Dict[str, Any]  # {field: {"type": ..., "required": bool}}
    risk_level: RiskLevel
    handler: ActionHandler
    required_capabilities: List[str] = field(default_factory=list)
    required_scopes: List[str] = field(default_factory=list)
    supports_dry_run: bool = True
    idempotent: bool = False

    def validate_input(self, payload: Dict[str, Any]) -> List[str]:
        """Returns a list of validation error strings (empty = valid).
        Deliberately simple — a required-field + type check, not a full
        JSON-schema engine. Actions with genuinely complex nested input
        (Facturapi invoices) validate further inside their own handler."""
        errors: List[str] = []
        for field_name, spec in self.input_schema.items():
            if spec.get("required") and field_name not in payload:
                errors.append(f"Missing required field: {field_name}")
                continue
            if field_name in payload and spec.get("type"):
                expected = spec["type"]
                value = payload[field_name]
                if expected == "string" and not isinstance(value, str):
                    errors.append(f"{field_name} must be a string")
                elif expected == "number" and not isinstance(value, (int, float)):
                    errors.append(f"{field_name} must be a number")
                elif expected == "array" and not isinstance(value, list):
                    errors.append(f"{field_name} must be an array")
                elif expected == "object" and not isinstance(value, dict):
                    errors.append(f"{field_name} must be an object")
        return errors
