"""
Critical hardening coverage: simulation isolation, concurrent idempotency,
same-execution approval, RBAC, unified policy engine.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from actions.base import ActionContext, ActionDefinition, ActionResult, RiskLevel
from actions.executor import ActionExecutor
from actions.handlers import quantro_internal
from actions.policy_engine import PolicyEngine
from actions.policy_gate import PolicyGate
from actions import registry
from errors import QuantroError


@pytest.fixture(autouse=True)
def _clear_registry():
    registry.clear_registry()
    yield
    registry.clear_registry()


def make_executor(fake_collection, is_simulation=False, deps=None):
    async def is_simulation_mode(workspace_id):
        return is_simulation
    engine = PolicyEngine(
        automation_policies_col=fake_collection,
        action_policies_col=fake_collection,
        action_executions_col=fake_collection,
        is_simulation_mode_fn=is_simulation_mode,
    )
    return ActionExecutor(fake_collection, PolicyGate(engine), None, deps=deps or {})


def register(action_id, risk, handler, minimum_role=None, provider="test"):
    definition = ActionDefinition(
        action_id=action_id, provider=provider, name="T", description="",
        input_schema={"value": {"type": "string", "required": True}},
        risk_level=risk, handler=handler, idempotent=True, minimum_role=minimum_role,
    )
    registry.register_action(definition)
    return definition


# ─── Simulation isolation ─────────────────────────────────────────────

async def test_internal_contact_create_simulation_tags_sandbox(fake_collection):
    contacts = type(fake_collection)()
    activity = []

    async def log_activity(*a, **k):
        activity.append((a, k))

    ctx = ActionContext(workspace_id="ws1", requested_by="u", source="manual", dry_run=True, deps={
        "contacts_col": contacts, "log_activity": log_activity,
    })
    result = await quantro_internal.crm_contact_create(ctx, {"name": "Ada", "email": "a@x.com"})
    assert result.status == "simulated"
    doc = await contacts.find_one({})
    assert doc["is_simulation"] is True


async def test_internal_calendar_and_onboarding_simulation_tags(fake_collection):
    calendar = type(fake_collection)()
    agents = type(fake_collection)()
    onboarding = type(fake_collection)()

    async def log_activity(*a, **k):
        return None

    ctx = ActionContext(workspace_id="ws1", requested_by="u", source="manual", dry_run=True, deps={
        "calendar_col": calendar, "agents_col": agents, "onboarding_col": onboarding, "log_activity": log_activity,
    })
    ev = await quantro_internal.calendar_event_create(ctx, {"title": "Sync"})
    assert ev.status == "simulated"
    assert (await calendar.find_one({}))["is_simulation"] is True

    ob = await quantro_internal.onboarding_start(ctx, {"name": "Bob", "email": "b@x.com"})
    assert ob.status == "simulated"
    agent = await agents.find_one({})
    assert agent["is_simulation"] is True
    assert await onboarding.count_documents({"is_simulation": True}) == 5


async def test_internal_live_mode_is_simulation_false(fake_collection):
    contacts = type(fake_collection)()

    async def log_activity(*a, **k):
        return None

    ctx = ActionContext(workspace_id="ws1", requested_by="u", source="manual", dry_run=False, deps={
        "contacts_col": contacts, "log_activity": log_activity,
    })
    result = await quantro_internal.crm_contact_create(ctx, {"name": "Live"})
    assert result.status == "succeeded"
    assert (await contacts.find_one({}))["is_simulation"] is False


async def test_external_handlers_respect_dry_run(fake_collection):
    from actions.handlers import google as google_handlers
    from actions.handlers import microsoft as microsoft_handlers
    from actions.handlers import facturapi as facturapi_handlers

    # dry_run short-circuits before any provider deps are touched
    ctx = ActionContext(workspace_id="ws1", requested_by="u", source="manual", dry_run=True, deps={})
    g = await google_handlers.gmail_send(ctx, {"to": "a@b.com", "subject": "hi", "body": "x"})
    assert g.status == "simulated"
    gc = await google_handlers.calendar_event_create(ctx, {"title": "t", "start_time": "1", "end_time": "2"})
    assert gc.status == "simulated"
    m = await microsoft_handlers.mail_send(ctx, {"to": "a@b.com", "subject": "hi", "body": "x"})
    assert m.status == "simulated"
    mc = await microsoft_handlers.calendar_event_create(ctx, {"title": "t", "start_time": "1", "end_time": "2"})
    assert mc.status == "simulated"
    f = await facturapi_handlers.invoice_create(ctx, {"customer": {}, "items": [], "payment_form": "01", "use": "G03"})
    assert f.status == "simulated"


# ─── Concurrent idempotency ───────────────────────────────────────────

async def test_concurrent_idempotency_handler_runs_once(fake_collection, monkeypatch):
    calls = []

    async def handler(ctx, input):
        await asyncio.sleep(0.02)
        calls.append(1)
        return ActionResult(status="succeeded", result_metadata={"n": len(calls)})

    register("facturapi.invoice.create", RiskLevel.HIGH, handler, minimum_role="leader", provider="facturapi")
    executor = make_executor(fake_collection)

    async def one():
        return await executor.execute(
            workspace_id="ws1", action_id="facturapi.invoice.create", input={"value": "inv"},
            idempotency_key="same-key", skip_policy_gate=True, actor_role="leader",
        )

    results = await asyncio.gather(*[one() for _ in range(10)])
    assert len(calls) == 1
    ids = {r["execution_id"] for r in results}
    assert len(ids) == 1


async def test_concurrent_gmail_idempotency_mocked(fake_collection):
    calls = []

    async def handler(ctx, input):
        calls.append(1)
        return ActionResult(status="succeeded")

    register("google.gmail.send", RiskLevel.MEDIUM, handler, minimum_role="leader", provider="google")
    executor = make_executor(fake_collection)

    async def one():
        return await executor.execute(
            workspace_id="ws1", action_id="google.gmail.send", input={"value": "x"},
            idempotency_key="mail-1", skip_policy_gate=True, actor_role="leader",
        )

    await asyncio.gather(*[one() for _ in range(10)])
    assert len(calls) == 1


# ─── Approval same execution_id ───────────────────────────────────────

async def test_approve_keeps_same_execution_id(fake_collection):
    calls = []

    async def handler(ctx, input):
        calls.append(1)
        return ActionResult(status="succeeded")

    register("facturapi.invoice.create", RiskLevel.HIGH, handler, minimum_role="leader", provider="facturapi")
    executor = make_executor(fake_collection)
    pending = await executor.execute(
        workspace_id="ws1", action_id="facturapi.invoice.create", input={"value": "x"}, actor_role="leader",
    )
    assert pending["status"] == "pending_approval"
    approved = await executor.approve("ws1", pending["execution_id"], "leader-1")
    assert approved["execution_id"] == pending["execution_id"]
    assert approved["status"] == "succeeded"
    assert len(calls) == 1


async def test_double_approve_does_not_rerun_handler(fake_collection):
    calls = []

    async def handler(ctx, input):
        calls.append(1)
        return ActionResult(status="succeeded")

    register("facturapi.invoice.create", RiskLevel.HIGH, handler, minimum_role="leader", provider="facturapi")
    executor = make_executor(fake_collection)
    pending = await executor.execute(
        workspace_id="ws1", action_id="facturapi.invoice.create", input={"value": "x"}, actor_role="leader",
    )
    await executor.approve("ws1", pending["execution_id"], "u1")
    again = await executor.approve("ws1", pending["execution_id"], "u2")
    assert again["status"] == "succeeded"
    assert len(calls) == 1


async def test_concurrent_approve_handler_once(fake_collection):
    calls = []

    async def handler(ctx, input):
        await asyncio.sleep(0.01)
        calls.append(1)
        return ActionResult(status="succeeded")

    register("facturapi.invoice.create", RiskLevel.HIGH, handler, minimum_role="leader", provider="facturapi")
    executor = make_executor(fake_collection)
    pending = await executor.execute(
        workspace_id="ws1", action_id="facturapi.invoice.create", input={"value": "x"}, actor_role="leader",
    )

    async def appr():
        return await executor.approve("ws1", pending["execution_id"], "u")

    await asyncio.gather(*[appr() for _ in range(8)])
    assert len(calls) == 1


async def test_cancelled_cannot_be_approved(fake_collection):
    async def handler(ctx, input):
        return ActionResult(status="succeeded")

    register("facturapi.invoice.create", RiskLevel.HIGH, handler, minimum_role="leader", provider="facturapi")
    executor = make_executor(fake_collection)
    pending = await executor.execute(
        workspace_id="ws1", action_id="facturapi.invoice.create", input={"value": "x"}, actor_role="leader",
    )
    await executor.cancel("ws1", pending["execution_id"])
    with pytest.raises(QuantroError):
        await executor.approve("ws1", pending["execution_id"], "u1")


async def test_simulation_between_pending_and_approve_forces_simulated(fake_collection):
    calls = []
    sim_flag = {"on": False}

    async def handler(ctx, input):
        calls.append(ctx.dry_run)
        return ActionResult(status="simulated" if ctx.dry_run else "succeeded")

    register("facturapi.invoice.create", RiskLevel.HIGH, handler, minimum_role="leader", provider="facturapi")

    async def is_simulation_mode(workspace_id):
        return sim_flag["on"]

    engine = PolicyEngine(
        automation_policies_col=fake_collection,
        action_policies_col=fake_collection,
        action_executions_col=fake_collection,
        is_simulation_mode_fn=is_simulation_mode,
    )
    executor = ActionExecutor(fake_collection, PolicyGate(engine), None, deps={})

    pending = await executor.execute(
        workspace_id="ws1", action_id="facturapi.invoice.create", input={"value": "x"}, actor_role="leader",
    )
    assert pending["status"] == "pending_approval"
    sim_flag["on"] = True
    result = await executor.approve("ws1", pending["execution_id"], "u1")
    assert result["execution_id"] == pending["execution_id"]
    assert result["status"] == "simulated"
    assert calls == [True]


# ─── RBAC ─────────────────────────────────────────────────────────────

async def test_member_cannot_execute_gmail_send(fake_collection):
    async def handler(ctx, input):
        raise AssertionError("must not run")

    register("google.gmail.send", RiskLevel.MEDIUM, handler, minimum_role="leader", provider="google")
    executor = make_executor(fake_collection)
    result = await executor.execute(
        workspace_id="ws1", action_id="google.gmail.send", input={"value": "x"}, actor_role="member",
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "action_blocked"


async def test_leader_can_reach_gmail_send(fake_collection):
    async def handler(ctx, input):
        return ActionResult(status="succeeded")

    register("google.gmail.send", RiskLevel.MEDIUM, handler, minimum_role="leader", provider="google")
    executor = make_executor(fake_collection)
    result = await executor.execute(
        workspace_id="ws1", action_id="google.gmail.send", input={"value": "x"}, actor_role="leader",
    )
    assert result["status"] == "succeeded"
