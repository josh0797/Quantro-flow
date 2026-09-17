"""
Unified Policy Engine — single decision surface for Inbox automation and
standalone Quantro Actions.

Outcomes: execute | pending_approval | block | simulate | escalate

Source of truth (preferred):
  automation_policies documents with optional scope="action" (and action_id /
  provider). Legacy action_policies (auto_approve / daily_limit) are still
  read for backward compatibility during migration.

Inbox intent policies continue to use evaluate_policy_for_item() in server.py;
this engine exposes evaluate_inbox_action() as a thin reusable adapter so both
paths share the same outcome vocabulary and Simulation Mode precedence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from .base import ActionDefinition, RiskLevel
from .rbac import normalize_role, role_at_least

IsSimulationModeFn = Callable[[str], Awaitable[bool]]


@dataclass
class PolicyDecision:
    outcome: str  # execute | pending_approval | block | simulate | escalate
    reason: str
    matched_policy: Optional[str] = None
    daily_limit: Optional[int] = None
    required_role: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


class PolicyEngine:
    def __init__(
        self,
        *,
        automation_policies_col,
        action_policies_col,
        action_executions_col,
        is_simulation_mode_fn: IsSimulationModeFn,
        escalation_col=None,
    ):
        self.automation_policies_col = automation_policies_col
        self.action_policies_col = action_policies_col
        self.action_executions_col = action_executions_col
        self.escalation_col = escalation_col
        self._is_simulation_mode = is_simulation_mode_fn

    async def evaluate_action(
        self,
        *,
        workspace_id: str,
        action_def: ActionDefinition,
        actor_role: Optional[str] = None,
        source: str = "manual",
        dry_run: bool = False,
        confidence: Optional[float] = None,
        skip_rbac: bool = False,
    ) -> PolicyDecision:
        if dry_run or await self._is_simulation_mode(workspace_id):
            return PolicyDecision("simulate", "Simulation Mode is active for this workspace")

        min_role = action_def.minimum_role or self._default_minimum_role(action_def)
        # Autonomous / AI sources cannot assume authorization without an actor role
        # unless an explicit policy later elevates (skip_rbac only for trusted shims).
        if not skip_rbac:
            if source in ("auto", "ai", "agent") and actor_role is None:
                return PolicyDecision(
                    "block",
                    f"Autonomous source '{source}' is not authorized without an effective actor role",
                    required_role=min_role,
                )
            if actor_role is not None and not role_at_least(actor_role, min_role):
                return PolicyDecision(
                    "block",
                    f"Requires role '{min_role}' (actor has '{normalize_role(actor_role)}')",
                    required_role=min_role,
                )

        # Prefer automation_policies with scope=action
        scoped = await self._find_action_scope_policy(workspace_id, action_def)
        if scoped:
            return await self._decision_from_scoped_policy(workspace_id, action_def, scoped)

        # Compat: legacy action_policies auto_approve for high/critical
        if action_def.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
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
                            matched_policy=override.get("policy_id") or "action_policies",
                            daily_limit=daily_limit,
                        )
                return PolicyDecision(
                    "execute",
                    f"workspace policy explicitly auto-approves {action_def.action_id}",
                    matched_policy=override.get("policy_id") or "action_policies",
                )
            return PolicyDecision(
                "pending_approval",
                f"'{action_def.risk_level.value}'-risk actions require approval by default",
                required_role=min_role,
            )

        # Medium/low: risk alone does NOT authorize — RBAC already applied.
        # Optional automation policy may still force approval.
        return PolicyDecision(
            "execute",
            f"risk '{action_def.risk_level.value}' with sufficient role may execute",
            required_role=min_role,
        )

    async def evaluate_inbox_action(
        self,
        *,
        workspace_id: str,
        resolved_action: str,
        intent: Optional[str] = None,
        confidence: Optional[float] = None,
        policy_id: Optional[str] = None,
    ) -> PolicyDecision:
        """Map inbox policy vocabulary onto the shared outcome set."""
        if await self._is_simulation_mode(workspace_id):
            return PolicyDecision("simulate", "Simulation Mode is active for this workspace", matched_policy=policy_id)
        mapping = {
            "auto_run": "execute",
            "require_approval": "pending_approval",
            "manual_review": "pending_approval",
            "escalate": "escalate",
            "block": "block",
            "simulate": "simulate",
        }
        outcome = mapping.get(resolved_action, "pending_approval")
        return PolicyDecision(
            outcome,
            f"Inbox policy '{intent or 'unknown'}' → {resolved_action}",
            matched_policy=policy_id,
            extra={"confidence": confidence, "inbox_action": resolved_action},
        )

    def _default_minimum_role(self, action_def: ActionDefinition) -> str:
        if action_def.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            return "leader"
        if action_def.provider in ("google", "microsoft", "facturapi") and action_def.risk_level == RiskLevel.MEDIUM:
            return "leader"
        if action_def.provider == "facturapi" and action_def.action_id.endswith(".create"):
            return "leader"
        # read/list and internal low-risk writes
        if action_def.action_id.endswith(".get") or action_def.action_id.endswith(".list"):
            return "member"
        return "member"

    async def _find_action_scope_policy(self, workspace_id: str, action_def: ActionDefinition):
        if self.automation_policies_col is None:
            return None
        # Prefer exact action_id match with scope=action
        doc = await self.automation_policies_col.find_one({
            "workspace_id": workspace_id,
            "enabled": True,
            "scope": "action",
            "action_id": action_def.action_id,
        })
        if doc:
            return doc
        return await self.automation_policies_col.find_one({
            "workspace_id": workspace_id,
            "enabled": True,
            "scope": "action",
            "provider": action_def.provider,
            "action_id": {"$exists": False},
        })

    async def _decision_from_scoped_policy(self, workspace_id, action_def, scoped) -> PolicyDecision:
        mode = (scoped.get("mode") or scoped.get("high_action") or "require_approval").lower()
        min_role = scoped.get("minimum_role") or action_def.minimum_role or self._default_minimum_role(action_def)
        daily_limit = scoped.get("daily_limit")
        policy_id = scoped.get("policy_id")
        if mode in ("block", "deny"):
            return PolicyDecision("block", f"automation policy blocks {action_def.action_id}", matched_policy=policy_id, required_role=min_role)
        if mode in ("simulate", "simulation"):
            return PolicyDecision("simulate", f"automation policy forces simulation for {action_def.action_id}", matched_policy=policy_id)
        if mode in ("require_approval", "pending_approval", "manual_review"):
            return PolicyDecision("pending_approval", f"automation policy requires approval for {action_def.action_id}", matched_policy=policy_id, required_role=min_role)
        if mode in ("auto_run", "execute", "auto_approve"):
            if daily_limit is not None:
                count = await self._count_today(workspace_id, action_def.action_id)
                if count >= daily_limit:
                    return PolicyDecision(
                        "pending_approval",
                        f"Daily limit of {daily_limit} reached for {action_def.action_id}",
                        matched_policy=policy_id,
                        daily_limit=daily_limit,
                    )
            return PolicyDecision("execute", f"automation policy auto-executes {action_def.action_id}", matched_policy=policy_id)
        if mode == "escalate":
            return PolicyDecision("escalate", f"automation policy escalates {action_def.action_id}", matched_policy=policy_id)
        return PolicyDecision("pending_approval", f"Unknown policy mode '{mode}' — defaulting to approval", matched_policy=policy_id)

    async def _count_today(self, workspace_id: str, action_id: str) -> int:
        start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return await self.action_executions_col.count_documents({
            "workspace_id": workspace_id,
            "action_id": action_id,
            "status": {"$in": ["succeeded", "simulated"]},
            "started_at": {"$gte": start_of_day},
        })
