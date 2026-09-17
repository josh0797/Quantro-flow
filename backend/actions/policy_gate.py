"""
Policy Gate — decides whether an Action runs immediately, waits for
approval, or is forced into simulation. Does NOT reimplement Automation
Policies/Escalation Rules (those already exist for the intent-driven
inbox flow — see evaluate_policy_for_item()/evaluate_advanced_escalation()
in server.py); this gate is what a *standalone* Action call (one not
already vetted by that intent flow) goes through.

Design:
  * Simulation Mode always wins — a workspace in Simulation Mode never
    lets a real side effect through this gate, full stop.
  * low/medium risk actions auto-execute.
  * high/critical risk actions require approval UNLESS the workspace
    has an explicit `action_policies` document whitelisting that exact
    action_id for auto-approval (optionally capped by a daily_limit).
    This is the "policy explícita del workspace" the task spec requires
    before any high-risk action (e.g. emitir un CFDI) can auto-run.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

from .base import ActionDefinition, RiskLevel

IsSimulationModeFn = Callable[[str], Awaitable[bool]]


@dataclass
class PolicyDecision:
    outcome: str  # "execute" | "pending_approval" | "simulate"
    reason: str


class PolicyGate:
    def __init__(self, action_policies_col, action_executions_col, is_simulation_mode_fn: IsSimulationModeFn):
        self.action_policies_col = action_policies_col
        self.action_executions_col = action_executions_col
        self._is_simulation_mode = is_simulation_mode_fn

    async def evaluate(self, workspace_id: str, action_def: ActionDefinition) -> PolicyDecision:
        if await self._is_simulation_mode(workspace_id):
            return PolicyDecision("simulate", "Simulation Mode is active for this workspace")

        if action_def.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM):
            return PolicyDecision("execute", f"risk level '{action_def.risk_level.value}' auto-executes by default")

        override = await self.action_policies_col.find_one(
            {"workspace_id": workspace_id, "action_id": action_def.action_id}
        )
        if override and override.get("auto_approve"):
            daily_limit = override.get("daily_limit")
            if daily_limit is not None:
                count = await self._count_today(workspace_id, action_def.action_id)
                if count >= daily_limit:
                    return PolicyDecision(
                        "pending_approval",
                        f"Daily limit of {daily_limit} reached for {action_def.action_id}",
                    )
            return PolicyDecision(
                "execute",
                f"workspace policy explicitly auto-approves {action_def.action_id}",
            )

        return PolicyDecision(
            "pending_approval",
            f"'{action_def.risk_level.value}'-risk actions require approval by default",
        )

    async def _count_today(self, workspace_id: str, action_id: str) -> int:
        start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return await self.action_executions_col.count_documents({
            "workspace_id": workspace_id,
            "action_id": action_id,
            "status": {"$in": ["succeeded", "simulated"]},
            "started_at": {"$gte": start_of_day},
        })
