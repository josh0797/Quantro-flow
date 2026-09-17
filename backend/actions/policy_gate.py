"""
Policy Gate for standalone Actions — thin adapter over the Unified
PolicyEngine. Does NOT maintain a second independent rule brain.

Inbox intent automation still uses evaluate_policy_for_item() in
server.py; both share PolicyEngine outcome vocabulary and Simulation
Mode precedence via PolicyEngine.evaluate_inbox_action().
"""
from __future__ import annotations

from typing import Optional

from .base import ActionDefinition
from .policy_engine import PolicyDecision, PolicyEngine


class PolicyGate:
    """Backward-compatible façade used by ActionExecutor."""

    def __init__(self, engine: PolicyEngine):
        self.engine = engine

    async def evaluate(
        self,
        workspace_id: str,
        action_def: ActionDefinition,
        *,
        actor_role: Optional[str] = None,
        source: str = "manual",
        dry_run: bool = False,
        confidence: Optional[float] = None,
        skip_rbac: bool = False,
    ) -> PolicyDecision:
        return await self.engine.evaluate_action(
            workspace_id=workspace_id,
            action_def=action_def,
            actor_role=actor_role,
            source=source,
            dry_run=dry_run,
            confidence=confidence,
            skip_rbac=skip_rbac,
        )
