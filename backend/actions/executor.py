"""
ActionExecutor — the ONE path every Action execution goes through.

Key invariants (audit hardening):
  1. Idempotency: first insert with (workspace, action, idempotency_key)
     atomically claims the key; concurrent callers return that execution
     and NEVER re-run the handler.
  2. Approval continues the SAME execution_id (pending_approval → approved
     → running → succeeded|failed|simulated).
  3. Simulation Mode always wins — including between pending and approve.
  4. RBAC + Unified PolicyEngine decide before the handler runs.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from pymongo.errors import DuplicateKeyError

from errors import QuantroError
from integrations.secrets import redact_error_text
from .base import ActionContext, ExecutionStatus
from .policy_engine import PolicyDecision
from .policy_gate import PolicyGate
from .registry import get_action

LogAuditFn = Callable[..., Awaitable[None]]

# Statuses that mean "this idempotency key is already claimed — do not run again"
_CLAIMED_STATUSES = {
    ExecutionStatus.RUNNING.value,
    ExecutionStatus.PENDING_APPROVAL.value,
    ExecutionStatus.APPROVED.value,
    ExecutionStatus.SUCCEEDED.value,
    ExecutionStatus.SIMULATED.value,
    ExecutionStatus.FAILED.value,
    ExecutionStatus.SUGGESTED.value,
}


class ActionExecutor:
    def __init__(self, executions_col, policy_gate: PolicyGate, log_audit_fn: Optional[LogAuditFn], deps: Dict[str, Any]):
        self.executions_col = executions_col
        self.policy_gate = policy_gate
        self.log_audit = log_audit_fn
        self.deps = deps

    async def execute(
        self,
        *,
        workspace_id: str,
        action_id: str,
        input: Dict[str, Any],  # noqa: A002
        requested_by: Optional[str] = None,
        source: str = "manual",
        idempotency_key: Optional[str] = None,
        dry_run: bool = False,
        skip_policy_gate: bool = False,
        confidence: Optional[float] = None,
        actor_role: Optional[str] = None,
        skip_rbac: bool = False,
    ) -> Dict[str, Any]:
        action_def = get_action(action_id)
        if not action_def:
            raise QuantroError("invalid_input", f"Unknown action: {action_id}")

        errors = action_def.validate_input(input)
        if errors:
            raise QuantroError("invalid_input", "; ".join(errors), extra={"fields": errors})

        if idempotency_key:
            existing = await self.executions_col.find_one({
                "workspace_id": workspace_id,
                "action_id": action_id,
                "idempotency_key": idempotency_key,
            }, {"_id": 0})
            if existing and existing.get("status") in _CLAIMED_STATUSES:
                return existing

        execution_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        base_doc = {
            "execution_id": execution_id,
            "workspace_id": workspace_id,
            "action_id": action_id,
            "provider": action_def.provider,
            "requested_by": requested_by,
            "actor_role": actor_role,
            "source": source,
            "input": input,
            "status": ExecutionStatus.RUNNING.value,
            "risk_level": action_def.risk_level.value,
            "policy_decision": None,
            "confidence": confidence,
            "idempotency_key": idempotency_key,
            "started_at": now,
            "completed_at": None,
            "provider_request_id": None,
            "result_metadata": {},
            "error_code": None,
            "error_message_sanitized": None,
            "approved_by": None,
            "approved_at": None,
        }

        if idempotency_key:
            try:
                await self.executions_col.insert_one(dict(base_doc))
            except DuplicateKeyError:
                existing = await self.executions_col.find_one({
                    "workspace_id": workspace_id, "action_id": action_id, "idempotency_key": idempotency_key,
                }, {"_id": 0})
                if existing:
                    return existing
                raise QuantroError("duplicate_execution", "This action is already running with this idempotency key")
        else:
            await self.executions_col.insert_one(dict(base_doc))

        return await self._run_execution(
            execution_id=execution_id,
            action_def=action_def,
            input=input,
            workspace_id=workspace_id,
            requested_by=requested_by,
            source=source,
            dry_run=dry_run,
            skip_policy_gate=skip_policy_gate,
            confidence=confidence,
            actor_role=actor_role,
            skip_rbac=skip_rbac,
            already_approved=False,
        )

    async def approve(self, workspace_id: str, execution_id: str, approver_user_id: Optional[str]) -> Dict[str, Any]:
        # Atomic claim: only one approver transitions pending_approval → approved
        claimed = await self._claim_approval(workspace_id, execution_id, approver_user_id)
        if claimed is None:
            doc = await self.executions_col.find_one({"execution_id": execution_id, "workspace_id": workspace_id}, {"_id": 0})
            if not doc:
                raise QuantroError("invalid_input", "Unknown execution")
            if doc["status"] == ExecutionStatus.CANCELLED.value:
                raise QuantroError("invalid_input", "Cannot approve a cancelled execution")
            # Already claimed / finished — return without re-running handler
            if doc["status"] in (
                ExecutionStatus.SUCCEEDED.value,
                ExecutionStatus.SIMULATED.value,
                ExecutionStatus.FAILED.value,
                ExecutionStatus.RUNNING.value,
                ExecutionStatus.APPROVED.value,
            ):
                return doc
            raise QuantroError("invalid_input", f"Execution is not pending approval (status={doc['status']})")

        action_def = get_action(claimed["action_id"])
        await self._audit("action.approved", action_def, workspace_id, execution_id)

        return await self._run_execution(
            execution_id=execution_id,
            action_def=action_def,
            input=claimed.get("input") or {},
            workspace_id=workspace_id,
            requested_by=claimed.get("requested_by"),
            source=claimed.get("source", "manual"),
            dry_run=False,
            skip_policy_gate=True,  # human already approved — do not re-gate
            confidence=claimed.get("confidence"),
            actor_role=claimed.get("actor_role"),
            skip_rbac=True,
            already_approved=True,
        )

    async def cancel(self, workspace_id: str, execution_id: str) -> Dict[str, Any]:
        doc = await self.executions_col.find_one({"execution_id": execution_id, "workspace_id": workspace_id})
        if not doc:
            raise QuantroError("invalid_input", "Unknown execution")
        if doc["status"] not in (ExecutionStatus.PENDING_APPROVAL.value, ExecutionStatus.SUGGESTED.value):
            raise QuantroError("invalid_input", f"Cannot cancel an execution with status={doc['status']}")
        await self.executions_col.update_one(
            {"execution_id": execution_id},
            {"$set": {"status": ExecutionStatus.CANCELLED.value, "completed_at": datetime.now(timezone.utc)}},
        )
        await self._audit("action.cancelled", get_action(doc["action_id"]), workspace_id, execution_id)
        return await self._get(execution_id)

    async def _claim_approval(self, workspace_id: str, execution_id: str, approver_user_id: Optional[str]):
        now = datetime.now(timezone.utc)
        # Prefer find_one_and_update when available (Motor / Fake)
        if hasattr(self.executions_col, "find_one_and_update"):
            return await self.executions_col.find_one_and_update(
                {
                    "execution_id": execution_id,
                    "workspace_id": workspace_id,
                    "status": ExecutionStatus.PENDING_APPROVAL.value,
                },
                {"$set": {
                    "status": ExecutionStatus.APPROVED.value,
                    "approved_by": approver_user_id,
                    "approved_at": now,
                }},
                projection={"_id": 0},
            )
        # Fallback for minimal fakes
        doc = await self.executions_col.find_one({
            "execution_id": execution_id,
            "workspace_id": workspace_id,
            "status": ExecutionStatus.PENDING_APPROVAL.value,
        }, {"_id": 0})
        if not doc:
            return None
        await self.executions_col.update_one(
            {"execution_id": execution_id, "status": ExecutionStatus.PENDING_APPROVAL.value},
            {"$set": {"status": ExecutionStatus.APPROVED.value, "approved_by": approver_user_id, "approved_at": now}},
        )
        doc["status"] = ExecutionStatus.APPROVED.value
        doc["approved_by"] = approver_user_id
        doc["approved_at"] = now
        return doc

    async def _run_execution(
        self,
        *,
        execution_id: str,
        action_def,
        input: Dict[str, Any],
        workspace_id: str,
        requested_by: Optional[str],
        source: str,
        dry_run: bool,
        skip_policy_gate: bool,
        confidence: Optional[float],
        actor_role: Optional[str],
        skip_rbac: bool,
        already_approved: bool,
    ) -> Dict[str, Any]:
        if dry_run:
            decision = PolicyDecision("simulate", "explicit dry_run requested")
        elif skip_policy_gate and already_approved:
            # Re-check Simulation Mode — always wins even after human approval
            decision = await self.policy_gate.evaluate(
                workspace_id, action_def, actor_role=actor_role, source=source,
                dry_run=False, confidence=confidence, skip_rbac=True,
            )
            if decision.outcome != "simulate":
                decision = PolicyDecision("execute", "human-approved; policy gate skipped")
        elif skip_policy_gate:
            decision = PolicyDecision("execute", "policy already evaluated by caller")
        else:
            decision = await self.policy_gate.evaluate(
                workspace_id, action_def,
                actor_role=actor_role, source=source, dry_run=dry_run,
                confidence=confidence, skip_rbac=skip_rbac,
            )

        await self.executions_col.update_one(
            {"execution_id": execution_id},
            {"$set": {"policy_decision": decision.reason}},
        )

        if decision.outcome == "block":
            update = {
                "status": ExecutionStatus.FAILED.value,
                "completed_at": datetime.now(timezone.utc),
                "error_code": "action_blocked",
                "error_message_sanitized": decision.reason,
                "result_metadata": {"required_role": decision.required_role},
            }
            await self.executions_col.update_one({"execution_id": execution_id}, {"$set": update})
            await self._audit("action.blocked", action_def, workspace_id, execution_id)
            return await self._get(execution_id)

        if decision.outcome == "escalate":
            await self.executions_col.update_one(
                {"execution_id": execution_id},
                {"$set": {"status": ExecutionStatus.PENDING_APPROVAL.value, "policy_decision": decision.reason}},
            )
            await self._audit("action.pending_approval", action_def, workspace_id, execution_id)
            return await self._get(execution_id)

        if decision.outcome == "pending_approval":
            await self.executions_col.update_one(
                {"execution_id": execution_id},
                {"$set": {"status": ExecutionStatus.PENDING_APPROVAL.value}},
            )
            await self._audit("action.pending_approval", action_def, workspace_id, execution_id)
            return await self._get(execution_id)

        # Ensure status is running (approve path may be sitting on approved)
        await self.executions_col.update_one(
            {"execution_id": execution_id},
            {"$set": {"status": ExecutionStatus.RUNNING.value}},
        )

        ctx = ActionContext(
            workspace_id=workspace_id,
            requested_by=requested_by,
            source=source,
            dry_run=(decision.outcome == "simulate"),
            deps=self.deps,
        )

        try:
            result = await action_def.handler(ctx, input)
            final_status = result.status
            update: Dict[str, Any] = {
                "status": final_status,
                "completed_at": datetime.now(timezone.utc),
                "result_metadata": result.result_metadata,
                "provider_request_id": result.provider_request_id,
            }
            if final_status == ExecutionStatus.FAILED.value:
                update["error_code"] = result.error_code
                update["error_message_sanitized"] = result.error_message_sanitized
        except QuantroError as exc:
            update = {
                "status": ExecutionStatus.FAILED.value,
                "completed_at": datetime.now(timezone.utc),
                "error_code": exc.code,
                "error_message_sanitized": redact_error_text(exc.message),
            }
        except Exception as exc:  # noqa: BLE001
            update = {
                "status": ExecutionStatus.FAILED.value,
                "completed_at": datetime.now(timezone.utc),
                "error_code": "provider_error",
                "error_message_sanitized": redact_error_text(str(exc)),
            }

        await self.executions_col.update_one({"execution_id": execution_id}, {"$set": update})
        event = {
            ExecutionStatus.SUCCEEDED.value: "action.executed",
            ExecutionStatus.SIMULATED.value: "action.simulated",
            ExecutionStatus.FAILED.value: "action.failed",
        }.get(update["status"], "action.executed")
        await self._audit(event, action_def, workspace_id, execution_id)
        return await self._get(execution_id)

    async def _get(self, execution_id: str) -> Dict[str, Any]:
        doc = await self.executions_col.find_one({"execution_id": execution_id}, {"_id": 0})
        return doc or {}

    async def _audit(self, event_type: str, action_def, workspace_id: str, execution_id: str) -> None:
        if not self.log_audit:
            return
        try:
            await self.log_audit(
                event_type,
                f"{event_type} — {action_def.action_id if action_def else 'unknown'}",
                workspace_id=workspace_id,
                metadata={
                    "action_id": action_def.action_id if action_def else None,
                    "provider": action_def.provider if action_def else None,
                    "execution_id": execution_id,
                },
            )
        except Exception:  # noqa: BLE001
            pass
