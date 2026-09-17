"""
PolicyGate — the gate a standalone Action call goes through. These
tests are the executable version of the task spec's Risk Levels
section: low/medium auto-execute, high/critical need an explicit
workspace override, Simulation Mode always wins regardless of risk.
"""
import pytest

from actions.base import ActionDefinition, RiskLevel
from actions.policy_gate import PolicyGate


def make_action(risk: RiskLevel, action_id: str = "test.action") -> ActionDefinition:
    async def handler(ctx, input):  # pragma: no cover - not invoked by these tests
        raise AssertionError("handler should not run in policy_gate tests")
    return ActionDefinition(
        action_id=action_id, provider="test", name="Test", description="",
        input_schema={}, risk_level=risk, handler=handler,
    )


@pytest.mark.parametrize("risk", [RiskLevel.LOW, RiskLevel.MEDIUM])
async def test_low_medium_risk_auto_executes(fake_collection, risk):
    async def not_simulation(workspace_id):
        return False
    gate = PolicyGate(fake_collection, fake_collection, not_simulation)
    decision = await gate.evaluate("ws1", make_action(risk))
    assert decision.outcome == "execute"


async def test_simulation_mode_always_wins_even_for_low_risk(fake_collection):
    async def is_simulation(workspace_id):
        return True
    gate = PolicyGate(fake_collection, fake_collection, is_simulation)
    decision = await gate.evaluate("ws1", make_action(RiskLevel.LOW))
    assert decision.outcome == "simulate"


async def test_high_risk_requires_approval_by_default(fake_collection):
    async def not_simulation(workspace_id):
        return False
    gate = PolicyGate(fake_collection, fake_collection, not_simulation)
    decision = await gate.evaluate("ws1", make_action(RiskLevel.HIGH, "facturapi.invoice.create"))
    assert decision.outcome == "pending_approval"


async def test_high_risk_with_explicit_override_auto_executes(fake_collection):
    async def not_simulation(workspace_id):
        return False
    await fake_collection.insert_one({
        "workspace_id": "ws1", "action_id": "facturapi.invoice.create", "auto_approve": True,
    })
    gate = PolicyGate(fake_collection, fake_collection, not_simulation)
    decision = await gate.evaluate("ws1", make_action(RiskLevel.HIGH, "facturapi.invoice.create"))
    assert decision.outcome == "execute"


async def test_high_risk_override_does_not_leak_to_other_workspaces(fake_collection):
    async def not_simulation(workspace_id):
        return False
    await fake_collection.insert_one({
        "workspace_id": "ws1", "action_id": "facturapi.invoice.create", "auto_approve": True,
    })
    gate = PolicyGate(fake_collection, fake_collection, not_simulation)
    decision = await gate.evaluate("ws2", make_action(RiskLevel.HIGH, "facturapi.invoice.create"))
    assert decision.outcome == "pending_approval"


async def test_daily_limit_falls_back_to_approval_once_reached(fake_collection):
    async def not_simulation(workspace_id):
        return False
    await fake_collection.insert_one({
        "workspace_id": "ws1", "action_id": "facturapi.invoice.create", "auto_approve": True, "daily_limit": 1,
    })
    from datetime import datetime, timezone
    await fake_collection.insert_one({
        "workspace_id": "ws1", "action_id": "facturapi.invoice.create", "status": "succeeded",
        "started_at": datetime.now(timezone.utc),
    })
    gate = PolicyGate(fake_collection, fake_collection, not_simulation)
    decision = await gate.evaluate("ws1", make_action(RiskLevel.HIGH, "facturapi.invoice.create"))
    assert decision.outcome == "pending_approval"
    assert "Daily limit" in decision.reason
