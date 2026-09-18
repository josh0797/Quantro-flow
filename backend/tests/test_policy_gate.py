"""
PolicyGate / PolicyEngine — unified decision surface for standalone Actions.
"""
import pytest

from actions.base import ActionDefinition, RiskLevel
from actions.policy_engine import PolicyEngine
from actions.policy_gate import PolicyGate


def make_action(risk: RiskLevel, action_id: str = "test.action", provider: str = "test", minimum_role=None) -> ActionDefinition:
    async def handler(ctx, input):  # pragma: no cover
        raise AssertionError("handler should not run in policy_gate tests")
    return ActionDefinition(
        action_id=action_id, provider=provider, name="Test", description="",
        input_schema={}, risk_level=risk, handler=handler, minimum_role=minimum_role,
    )


def make_gate(fake_collection, is_simulation=False, automation_col=None):
    async def sim_fn(workspace_id):
        return is_simulation
    engine = PolicyEngine(
        automation_policies_col=automation_col if automation_col is not None else fake_collection,
        action_policies_col=fake_collection,
        action_executions_col=fake_collection,
        is_simulation_mode_fn=sim_fn,
    )
    return PolicyGate(engine)


@pytest.mark.parametrize("risk", [RiskLevel.LOW, RiskLevel.MEDIUM])
async def test_low_medium_risk_auto_executes_with_sufficient_role(fake_collection, risk):
    gate = make_gate(fake_collection)
    decision = await gate.evaluate("ws1", make_action(risk), actor_role="member")
    assert decision.outcome == "execute"


async def test_simulation_mode_always_wins_even_for_low_risk(fake_collection):
    gate = make_gate(fake_collection, is_simulation=True)
    decision = await gate.evaluate("ws1", make_action(RiskLevel.LOW), actor_role="owner")
    assert decision.outcome == "simulate"


async def test_high_risk_requires_approval_by_default(fake_collection):
    gate = make_gate(fake_collection)
    decision = await gate.evaluate("ws1", make_action(RiskLevel.HIGH, "facturapi.invoice.create"), actor_role="leader")
    assert decision.outcome == "pending_approval"


async def test_high_risk_with_explicit_override_auto_executes(fake_collection):
    await fake_collection.insert_one({
        "workspace_id": "ws1", "action_id": "facturapi.invoice.create", "auto_approve": True,
    })
    gate = make_gate(fake_collection)
    decision = await gate.evaluate("ws1", make_action(RiskLevel.HIGH, "facturapi.invoice.create"), actor_role="leader")
    assert decision.outcome == "execute"


async def test_high_risk_override_does_not_leak_to_other_workspaces(fake_collection):
    await fake_collection.insert_one({
        "workspace_id": "ws1", "action_id": "facturapi.invoice.create", "auto_approve": True,
    })
    gate = make_gate(fake_collection)
    decision = await gate.evaluate("ws2", make_action(RiskLevel.HIGH, "facturapi.invoice.create"), actor_role="leader")
    assert decision.outcome == "pending_approval"


async def test_daily_limit_falls_back_to_approval_once_reached(fake_collection):
    await fake_collection.insert_one({
        "workspace_id": "ws1", "action_id": "facturapi.invoice.create", "auto_approve": True, "daily_limit": 1,
    })
    from datetime import datetime, timezone
    await fake_collection.insert_one({
        "workspace_id": "ws1", "action_id": "facturapi.invoice.create", "status": "succeeded",
        "started_at": datetime.now(timezone.utc),
    })
    gate = make_gate(fake_collection)
    decision = await gate.evaluate("ws1", make_action(RiskLevel.HIGH, "facturapi.invoice.create"), actor_role="leader")
    assert decision.outcome == "pending_approval"
    assert "Daily limit" in decision.reason


async def test_member_blocked_from_medium_external_by_default(fake_collection):
    gate = make_gate(fake_collection)
    action = make_action(RiskLevel.MEDIUM, "google.gmail.send", provider="google", minimum_role="leader")
    decision = await gate.evaluate("ws1", action, actor_role="member")
    assert decision.outcome == "block"
    assert decision.required_role == "leader"


async def test_ai_source_without_actor_role_blocked(fake_collection):
    gate = make_gate(fake_collection)
    decision = await gate.evaluate("ws1", make_action(RiskLevel.LOW), source="ai", actor_role=None)
    assert decision.outcome == "block"


async def test_automation_policy_scope_action_require_approval(fake_collection):
    await fake_collection.insert_one({
        "workspace_id": "ws1", "enabled": True, "scope": "action",
        "action_id": "quantro.crm.contact.create", "mode": "require_approval", "policy_id": "p1",
    })
    gate = make_gate(fake_collection)
    decision = await gate.evaluate(
        "ws1", make_action(RiskLevel.LOW, "quantro.crm.contact.create"), actor_role="member",
    )
    assert decision.outcome == "pending_approval"
    assert decision.matched_policy == "p1"


async def test_inbox_adapter_preserves_escalation_vocabulary(fake_collection):
    gate = make_gate(fake_collection)
    d = await gate.engine.evaluate_inbox_action(
        workspace_id="ws1", resolved_action="escalate", intent="complaint", confidence=0.4, policy_id="inbox-1",
    )
    assert d.outcome == "escalate"
    assert d.matched_policy == "inbox-1"
