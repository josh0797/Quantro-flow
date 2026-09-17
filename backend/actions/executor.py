"""
ActionExecutor — the ONE path every Action execution goes through,
whatever triggered it: a direct POST /api/actions/{id}/execute call,
the legacy inbox auto-execute/approve/batch-approve endpoints (via the
execute_action_for_item() compatibility shim in server.py), or the
Quantro Revenue-style autonomous-execution loops. There must never be
a second copy of "how do we run an action" anywhere else.

Contract: execute() raises QuantroError only for pre-flight failures
(unknown action, invalid input) — nothing was attempted, so the caller
gets a clean 4xx. Once an action_executions row exists (status=running),
every subsequent failure (policy, handler, provider) is captured INTO
that row (status=failed) and returned normally, never raised — so
batch/auto callers never need a try/except around a single item's
execution breaking a whole batch.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from pymongo.errors import DuplicateKeyError

from errors import QuantroError
from integrations.secrets import redact_error_text
from .base import ActionContext, ExecutionStatus
from .policy_gate import PolicyDecision, PolicyGate
from .registry import get_action

LogAuditFn = Callable[..., Awaitable[None]]


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
        input: Dict[str, Any],  # noqa: A002 — matches the spec's payload field name
        requested_by: Optional[str] = None,
        source: str = "manual",
        idempotency_key: Optional[str] = None,
        dry_run: bool = False,
        skip_policy_gate: bool = False,
        confidence: Optional[float] = None,
    ) -> Dict[str, Any]:
        action_def = get_action(action_id)
        if not action_def:
            raise QuantroError("invalid_input", f"Unknown action: {action_id}")

        errors = action_def.validate_input(input)
        if errors:
            raise QuantroError("invalid_input", "; ".join(errors), extra={"fields": errors})

        if idempotency_key:
            existing = await self.executions_col.find_one({
                "workspace_id": workspace_id, "action_id": action_id, "idempotency_key": idempotency_key,
                "status": {"$in": [ExecutionStatus.SUCCEEDED.value, ExecutionStatus.SIMULATED.value]},
            }, {"_id": 0})
            if existing:
                return existing

        execution_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        base_doc = {
            "execution_id": execution_id,
            "workspace_id": workspace_id,
            "action_id": action_id,
            "provider": action_def.provider,
            "requested_by": requested_by,
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

        if dry_run:
            decision = PolicyDecision("simulate", "explicit dry_run requested")
        elif skip_policy_gate:
            decision = PolicyDecision("execute", "policy already evaluated by caller")
        else:
            decision = await self.policy_gate.evaluate(workspace_id, action_def)

        await self.executions_col.update_one(
            {"execution_id": execution_id}, {"$set": {"policy_decision": decision.reason}}
        )

        if decision.outcome == "pending_approval":
            await self.executions_col.update_one(
                {"execution_id": execution_id},
                {"$set": {"status": ExecutionStatus.PENDING_APPROVAL.value}},
            )
            await self._audit("action.pending_approval", action_def, workspace_id, execution_id)
            return await self._get(execution_id)

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
        except Exception as exc:  # noqa: BLE001 — never let a handler bug break the caller
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

    async def approve(self, workspace_id: str, execution_id: str, approver_user_id: Optional[str]) -> Dict[str, Any]:
        doc = await self.executions_col.find_one({"execution_id": execution_id, "workspace_id": workspace_id})
        if not doc:
            raise QuantroError("invalid_input", "Unknown execution")
        if doc["status"] != ExecutionStatus.PENDING_APPROVAL.value:
            raise QuantroError("invalid_input", f"Execution is not pending approval (status={doc['status']})")

        await self.executions_col.update_one(
            {"execution_id": execution_id},
            {"$set": {"status": ExecutionStatus.APPROVED.value, "approved_by": approver_user_id}},
        )
        await self._audit("action.approved", get_action(doc["action_id"]), workspace_id, execution_id)

        # Re-run through execute() with the gate bypassed (already approved
        # by a human) — same idempotency_key so a repeat click can't double-run it.
        return await self.execute(
            workspace_id=workspace_id,
            action_id=doc["action_id"],
            input=doc["input"],
            requested_by=doc.get("requested_by"),
            source=doc.get("source", "manual"),
            idempotency_key=doc.get("idempotency_key") or execution_id,
            skip_policy_gate=True,
        )

    async def cancel(self, workspace_id: str, execution_id: str) -> Dict[str, Any]:
        doc = await self.executions_col.find_one({"execution_id": execution_id, "workspace_id": workspace_id})
        if not doc:
            raise QuantroError("invalid_input", "Unknown execution")
        if doc["status"] not in (ExecutionStatus.PENDING_APPROVAL.value, ExecutionStatus.SUGGESTED.value):
            raise QuantroError("invalid_input", f"Cannot cancel an execution with status={doc['status']}")
        await self.executions_col.update_one(
            {"execution_id": execution_id}, {"$set": {"status": ExecutionStatus.CANCELLED.value, "completed_at": datetime.now(timezone.utc)}}
        )
        await self._audit("action.cancelled", get_action(doc["action_id"]), workspace_id, execution_id)
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
