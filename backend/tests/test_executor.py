"""
ActionExecutor — the single execution path every caller funnels
through. Covers: idempotency (no double-run on repeat key, per the
task spec calling out Facturapi invoice creation by name), the
pending_approval -> approve() flow, Simulation Mode forcing a
`simulated` result without ever invoking the real handler logic, and a
handler exception landing as a `failed` execution record rather than
raising past the caller (batch/auto callers depend on this).
"""
import pytest

from actions.base import ActionContext, ActionDefinition, ActionResult, RiskLevel
from actions.executor import ActionExecutor
from actions.policy_gate import PolicyGate
from errors import QuantroError


def make_executor(fake_collection, is_simulation=False, audit_log=None):
    from actions.policy_engine import PolicyEngine
    async def is_simulation_mode(workspace_id):
        return is_simulation
    engine = PolicyEngine(
        automation_policies_col=fake_collection,
        action_policies_col=fake_collection,
        action_executions_col=fake_collection,
        is_simulation_mode_fn=is_simulation_mode,
    )
    gate = PolicyGate(engine)

    async def log_audit(event_type, description, workspace_id=None, metadata=None):
        if audit_log is not None:
            audit_log.append((event_type, metadata))

    return ActionExecutor(fake_collection, gate, log_audit, deps={"counter": {"n": 0}})


def register(monkeypatch, action_id, risk, handler):
    from actions import registry
    definition = ActionDefinition(
        action_id=action_id, provider="test", name="Test", description="",
        input_schema={"value": {"type": "string", "required": True}}, risk_level=risk, handler=handler,
        idempotent=True,
    )
    registry.register_action(definition)
    return definition


@pytest.fixture(autouse=True)
def _clear_registry():
    from actions import registry
    registry.clear_registry()
    yield
    registry.clear_registry()


async def test_unknown_action_raises_before_touching_the_db(fake_collection, monkeypatch):
    executor = make_executor(fake_collection)
    with pytest.raises(QuantroError) as exc:
        await executor.execute(workspace_id="ws1", action_id="nope.does.not.exist", input={})
    assert exc.value.code == "invalid_input"
    assert await fake_collection.count_documents({}) == 0


async def test_missing_required_field_raises_invalid_input(fake_collection, monkeypatch):
    async def handler(ctx, input):
        return ActionResult(status="succeeded")
    register(monkeypatch, "test.action", RiskLevel.LOW, handler)
    executor = make_executor(fake_collection)
    with pytest.raises(QuantroError) as exc:
        await executor.execute(workspace_id="ws1", action_id="test.action", input={})
    assert exc.value.code == "invalid_input"


async def test_low_risk_action_succeeds_immediately(fake_collection, monkeypatch):
    calls = []

    async def handler(ctx, input):
        calls.append(input)
        return ActionResult(status="succeeded", result_metadata={"echo": input["value"]})
    register(monkeypatch, "test.action", RiskLevel.LOW, handler)
    executor = make_executor(fake_collection)

    result = await executor.execute(workspace_id="ws1", action_id="test.action", input={"value": "hi"}, actor_role="member")
    assert result["status"] == "succeeded"
    assert result["result_metadata"]["echo"] == "hi"
    assert len(calls) == 1


async def test_idempotency_key_prevents_double_execution(fake_collection, monkeypatch):
    calls = []

    async def handler(ctx, input):
        calls.append(1)
        return ActionResult(status="succeeded", result_metadata={"count": len(calls)})
    register(monkeypatch, "facturapi.invoice.create", RiskLevel.HIGH, handler)
    executor = make_executor(fake_collection)

    first = await executor.execute(
        workspace_id="ws1", action_id="facturapi.invoice.create", input={"value": "inv-1"},
        idempotency_key="idem-1", skip_policy_gate=True,
    )
    second = await executor.execute(
        workspace_id="ws1", action_id="facturapi.invoice.create", input={"value": "inv-1"},
        idempotency_key="idem-1", skip_policy_gate=True,
    )
    assert len(calls) == 1, "handler must run exactly once for a repeated idempotency_key"
    assert first["execution_id"] == second["execution_id"]
    assert second["result_metadata"]["count"] == 1


async def test_high_risk_action_waits_for_approval_then_runs_on_approve(fake_collection, monkeypatch):
    calls = []

    async def handler(ctx, input):
        calls.append(1)
        return ActionResult(status="succeeded")
    register(monkeypatch, "facturapi.invoice.create", RiskLevel.HIGH, handler)
    executor = make_executor(fake_collection)

    pending = await executor.execute(workspace_id="ws1", action_id="facturapi.invoice.create", input={"value": "x"}, actor_role="leader")
    assert pending["status"] == "pending_approval"
    assert len(calls) == 0, "handler must not run before approval"

    approved = await executor.approve("ws1", pending["execution_id"], approver_user_id="u1")
    assert approved["status"] == "succeeded"
    assert approved["execution_id"] == pending["execution_id"], "approve must continue the same execution"
    assert len(calls) == 1


async def test_approve_on_already_executed_returns_same_record_without_rerun(fake_collection, monkeypatch):
    calls = []
    async def handler(ctx, input):
        calls.append(1)
        return ActionResult(status="succeeded")
    register(monkeypatch, "test.action", RiskLevel.LOW, handler)
    executor = make_executor(fake_collection)
    done = await executor.execute(workspace_id="ws1", action_id="test.action", input={"value": "x"}, actor_role="member")
    again = await executor.approve("ws1", done["execution_id"], approver_user_id="u1")
    assert again["execution_id"] == done["execution_id"]
    assert again["status"] == "succeeded"
    assert len(calls) == 1


async def test_simulation_mode_forces_simulated_status_and_dry_run_context(fake_collection, monkeypatch):
    seen_dry_run = []

    async def handler(ctx: ActionContext, input):
        seen_dry_run.append(ctx.dry_run)
        if ctx.dry_run:
            return ActionResult(status="simulated", result_metadata={"predicted": True})
        raise AssertionError("handler should have short-circuited on dry_run")
    register(monkeypatch, "google.gmail.send", RiskLevel.MEDIUM, handler)
    executor = make_executor(fake_collection, is_simulation=True)

    result = await executor.execute(workspace_id="ws1", action_id="google.gmail.send", input={"value": "hi"})
    assert result["status"] == "simulated"
    assert seen_dry_run == [True]


async def test_handler_exception_is_captured_as_failed_not_raised(fake_collection, monkeypatch):
    # A generic long token, not shaped like any real vendor's key format
    # (no sk_/pk_/rk_ prefix) — just needs to be 32+ chars to exercise
    # redact_error_text()'s generic long-token pattern.
    leaked_marker = "LEAKED-TOKEN-abcDEF123456789012345678"
    async def handler(ctx, input):
        raise RuntimeError(f"boom: {leaked_marker}")
    register(monkeypatch, "test.action", RiskLevel.LOW, handler)
    executor = make_executor(fake_collection)

    result = await executor.execute(workspace_id="ws1", action_id="test.action", input={"value": "x"})
    assert result["status"] == "failed"
    assert result["error_code"] == "provider_error"
    assert leaked_marker not in result["error_message_sanitized"]


async def test_quantro_error_from_handler_maps_its_own_code(fake_collection, monkeypatch):
    async def handler(ctx, input):
        raise QuantroError("reauthorization_required", "need more scopes")
    register(monkeypatch, "google.gmail.send", RiskLevel.MEDIUM, handler)
    executor = make_executor(fake_collection)

    result = await executor.execute(workspace_id="ws1", action_id="google.gmail.send", input={"value": "x"})
    assert result["status"] == "failed"
    assert result["error_code"] == "reauthorization_required"
