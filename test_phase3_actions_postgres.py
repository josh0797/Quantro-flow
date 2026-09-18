#!/usr/bin/env python3
"""Phase 3 Actions Postgres unit tests — dual-write / primary flip / idempotency.

No live Mongo or Supabase. Uses httpx mocks + FakeAsyncCollection.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
# conftest lives under backend/tests
_TESTS = os.path.join(BACKEND, "tests")
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from conftest import FakeAsyncCollection  # noqa: E402


def _reload_store(**env):
    base = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-test",
        "QUANTRO_ACTIONS_PRIMARY": "mongo",
        "QUANTRO_MONGO_MIRROR": "1",
        "QUANTRO_ACTIONS_MONGO_MIRROR": "",
    }
    base.update(env)
    with patch.dict(os.environ, base, clear=False):
        # Clear empty dedicated mirror so store falls back to QUANTRO_MONGO_MIRROR
        if not base.get("QUANTRO_ACTIONS_MONGO_MIRROR"):
            os.environ.pop("QUANTRO_ACTIONS_MONGO_MIRROR", None)
        for mod in list(sys.modules):
            if mod == "actions.store" or mod.endswith(".store") and "actions" in mod:
                del sys.modules[mod]
        import actions.store as store
        importlib.reload(store)
        return store


class FakeResponse:
    def __init__(self, status_code: int, json_data=None, text: str = "", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text if text or json_data is None else ("" if json_data == [] else str(json_data))
        self.headers = headers or {}

    def json(self):
        return self._json


@pytest.fixture
def fake_mongo():
    return FakeAsyncCollection()


# ── flags ─────────────────────────────────────────────────────────────

def test_default_primary_is_mongo():
    store = _reload_store()
    assert store.ACTIONS_PRIMARY == "mongo"
    assert store.is_actions_dual_write_enabled() is True
    assert store.is_actions_mongo_write_enabled() is True
    assert store.actions_health()["escalation_rules"] == "deferred_mongo"


def test_flip_primary_supabase():
    store = _reload_store(QUANTRO_ACTIONS_PRIMARY="supabase")
    assert store.is_actions_supabase_primary() is True
    assert store.is_actions_mongo_write_enabled() is True  # mirror default on


def test_mirror_off_when_supabase_primary():
    store = _reload_store(
        QUANTRO_ACTIONS_PRIMARY="supabase",
        QUANTRO_ACTIONS_MONGO_MIRROR="0",
    )
    assert store.is_actions_mongo_write_enabled() is False


# ── dual-write executions (primary=mongo) ─────────────────────────────

@pytest.mark.asyncio
async def test_execution_insert_dual_writes_to_supabase(fake_mongo):
    store = _reload_store(QUANTRO_ACTIONS_PRIMARY="mongo")
    col = store.wrap_executions_col(fake_mongo)
    posted = []

    async def fake_request(method, path, **kwargs):
        if method == "POST":
            posted.append(kwargs.get("json"))
            return FakeResponse(201, [])
        return FakeResponse(200, [])

    with patch.object(store, "_sb_request", side_effect=fake_request):
        doc = {
            "execution_id": "e1",
            "workspace_id": "ws1",
            "action_id": "facturapi.invoice.create",
            "status": "running",
            "idempotency_key": "k1",
            "input": {"x": 1},
            "result_metadata": {},
            "started_at": datetime.now(timezone.utc),
        }
        await col.insert_one(doc)

    assert await fake_mongo.find_one({"execution_id": "e1"}) is not None
    assert len(posted) == 1
    assert posted[0]["execution_id"] == "e1"
    assert posted[0]["idempotency_key"] == "k1"


@pytest.mark.asyncio
async def test_graceful_degrade_when_table_missing(fake_mongo):
    store = _reload_store(QUANTRO_ACTIONS_PRIMARY="mongo")
    col = store.wrap_executions_col(fake_mongo)

    async def fake_request(method, path, **kwargs):
        return FakeResponse(
            404,
            text='{"code":"PGRST205","message":"Could not find the table"}',
        )

    with patch.object(store, "_sb_request", side_effect=fake_request):
        # _sb_request itself maps table-missing to None — simulate that
        with patch.object(store, "_sb_request", AsyncMock(return_value=None)):
            await col.insert_one({
                "execution_id": "e2",
                "workspace_id": "ws1",
                "action_id": "a",
                "status": "running",
                "input": {},
                "result_metadata": {},
            })
    assert await fake_mongo.find_one({"execution_id": "e2"}) is not None


# ── primary=supabase reads + idempotency claim ────────────────────────

@pytest.mark.asyncio
async def test_policy_read_primary_supabase(fake_mongo):
    store = _reload_store(QUANTRO_ACTIONS_PRIMARY="supabase")
    col = store.wrap_automation_policies_col(fake_mongo)

    async def fake_request(method, path, **kwargs):
        assert "automation_policies" in path
        return FakeResponse(200, [{
            "policy_id": "p1",
            "workspace_id": "ws1",
            "enabled": True,
            "scope": "action",
            "action_id": "facturapi.invoice.create",
            "mode": "auto_run",
            "extra": {},
        }])

    with patch.object(store, "_sb_request", side_effect=fake_request):
        doc = await col.find_one({
            "workspace_id": "ws1",
            "enabled": True,
            "scope": "action",
            "action_id": "facturapi.invoice.create",
        })
    assert doc["mode"] == "auto_run"
    assert doc["policy_id"] == "p1"
    # Mongo not consulted when SB hits
    assert fake_mongo._docs == []


@pytest.mark.asyncio
async def test_concurrent_idempotency_via_store_mongo_primary(fake_mongo):
    """Existing hardening semantics still hold through the dual-write wrapper."""
    from actions.base import ActionDefinition, ActionResult, RiskLevel
    from actions.executor import ActionExecutor
    from actions.policy_engine import PolicyEngine
    from actions.policy_gate import PolicyGate
    from actions import registry

    store = _reload_store(QUANTRO_ACTIONS_PRIMARY="mongo")
    executions = store.wrap_executions_col(fake_mongo)
    policies = store.wrap_automation_policies_col(FakeAsyncCollection())
    action_policies = store.wrap_action_policies_col(FakeAsyncCollection())

    registry.clear_registry()
    calls = []

    async def handler(ctx, input):
        await asyncio.sleep(0.02)
        calls.append(1)
        return ActionResult(status="succeeded", result_metadata={"n": len(calls)})

    registry.register_action(ActionDefinition(
        action_id="facturapi.invoice.create", provider="facturapi", name="T",
        description="", input_schema={"value": {"type": "string", "required": True}},
        risk_level=RiskLevel.HIGH, handler=handler, idempotent=True, minimum_role="leader",
    ))

    async def is_sim(_):
        return False

    engine = PolicyEngine(
        automation_policies_col=policies,
        action_policies_col=action_policies,
        action_executions_col=executions,
        is_simulation_mode_fn=is_sim,
    )
    executor = ActionExecutor(executions, PolicyGate(engine), None, deps={})

    async def fake_request(method, path, **kwargs):
        if method == "POST":
            return FakeResponse(201, [])
        if method == "PATCH":
            return FakeResponse(200, [])
        return FakeResponse(200, [])

    with patch.object(store, "_sb_request", side_effect=fake_request):
        async def one():
            return await executor.execute(
                workspace_id="ws1", action_id="facturapi.invoice.create",
                input={"value": "inv"}, idempotency_key="same-key",
                skip_policy_gate=True, actor_role="leader",
            )
        results = await asyncio.gather(*[one() for _ in range(10)])

    assert len(calls) == 1
    assert len({r["execution_id"] for r in results}) == 1
    registry.clear_registry()


@pytest.mark.asyncio
async def test_approve_same_id_via_store(fake_mongo):
    from actions.base import ActionDefinition, ActionResult, RiskLevel
    from actions.executor import ActionExecutor
    from actions.policy_engine import PolicyEngine
    from actions.policy_gate import PolicyGate
    from actions import registry

    store = _reload_store(QUANTRO_ACTIONS_PRIMARY="mongo")
    executions = store.wrap_executions_col(fake_mongo)
    policies = store.wrap_automation_policies_col(FakeAsyncCollection())
    action_policies = store.wrap_action_policies_col(FakeAsyncCollection())

    registry.clear_registry()
    calls = []

    async def handler(ctx, input):
        calls.append(1)
        return ActionResult(status="succeeded")

    registry.register_action(ActionDefinition(
        action_id="facturapi.invoice.create", provider="facturapi", name="T",
        description="", input_schema={"value": {"type": "string", "required": True}},
        risk_level=RiskLevel.HIGH, handler=handler, idempotent=True, minimum_role="leader",
    ))

    async def is_sim(_):
        return False

    engine = PolicyEngine(
        automation_policies_col=policies,
        action_policies_col=action_policies,
        action_executions_col=executions,
        is_simulation_mode_fn=is_sim,
    )
    executor = ActionExecutor(executions, PolicyGate(engine), None, deps={})

    async def fake_request(method, path, **kwargs):
        return FakeResponse(200 if method != "POST" else 201, [])

    with patch.object(store, "_sb_request", side_effect=fake_request):
        pending = await executor.execute(
            workspace_id="ws1", action_id="facturapi.invoice.create",
            input={"value": "x"}, actor_role="leader",
        )
        assert pending["status"] == "pending_approval"
        approved = await executor.approve("ws1", pending["execution_id"], "leader-1")

    assert approved["execution_id"] == pending["execution_id"]
    assert approved["status"] == "succeeded"
    assert len(calls) == 1
    registry.clear_registry()


@pytest.mark.asyncio
async def test_supabase_primary_insert_duplicate_raises(fake_mongo):
    from pymongo.errors import DuplicateKeyError

    store = _reload_store(QUANTRO_ACTIONS_PRIMARY="supabase")
    col = store.wrap_executions_col(fake_mongo)

    async def fake_request(method, path, **kwargs):
        if method == "POST":
            return FakeResponse(409, text='{"code":"23505"}')
        return FakeResponse(200, [])

    with patch.object(store, "_sb_request", side_effect=fake_request):
        with pytest.raises(DuplicateKeyError):
            await col.insert_one({
                "execution_id": "e3",
                "workspace_id": "ws1",
                "action_id": "a",
                "status": "running",
                "idempotency_key": "dup",
                "input": {},
                "result_metadata": {},
            })


@pytest.mark.asyncio
async def test_supabase_primary_find_one_and_update_claim(fake_mongo):
    store = _reload_store(QUANTRO_ACTIONS_PRIMARY="supabase", QUANTRO_ACTIONS_MONGO_MIRROR="0")
    col = store.wrap_executions_col(fake_mongo)

    async def fake_request(method, path, **kwargs):
        if method == "PATCH":
            return FakeResponse(200, [{
                "execution_id": "e9",
                "workspace_id": "ws1",
                "action_id": "a",
                "status": "approved",
                "approved_by": "u1",
                "input": {},
                "result_metadata": {},
            }])
        return FakeResponse(200, [])

    with patch.object(store, "_sb_request", side_effect=fake_request):
        claimed = await col.find_one_and_update(
            {"execution_id": "e9", "workspace_id": "ws1", "status": "pending_approval"},
            {"$set": {"status": "approved", "approved_by": "u1"}},
            projection={"_id": 0},
        )
    assert claimed["status"] == "approved"
    assert claimed["approved_by"] == "u1"


def test_partial_unique_semantics_documented_in_mapper():
    """Mapper keeps null idempotency_key as null (partial unique allows multiples)."""
    store = _reload_store()
    row = store.execution_mongo_to_sb({
        "execution_id": "e",
        "workspace_id": "w",
        "action_id": "a",
        "status": "running",
        "idempotency_key": None,
        "input": {},
    })
    assert row["idempotency_key"] is None
