"""The state runbook step 2 deploys: fly.toml [env] pins (docs / calendar /
integrations still Mongo-primary, every mirror on). Every startup job must
complete — review finding 7: the workspace-scoping repair called update_many
on the integrations_config facade, which had none.

(Lives in its own file, sorted after the msal/google tests, because booting
server.py installs import stubs for SDKs missing from a bare dev venv.)
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import httpx
import pytest

import _import_stubs
from fake_motor import FakeMotorClient
from storage_helpers import _variants, supabase_only

REPO = Path(__file__).resolve().parents[2]


def _fly_toml_env() -> dict:
    return tomllib.loads((REPO / "fly.toml").read_text())["env"]


@pytest.fixture
def pinned_server(monkeypatch):
    """server.py booted in the state runbook step 2 deploys: fly.toml [env]
    pins over a Supabase-configured machine with every mirror on."""
    _import_stubs.install()
    fake = supabase_only(monkeypatch, mirror=True)
    pins = _fly_toml_env()
    for k, v in pins.items():
        if k.startswith("QUANTRO_"):
            monkeypatch.setenv(k, v)
    import connect_store
    import mongo_legacy

    for mod in _variants(connect_store, [("server", "connect_store")]):
        monkeypatch.setattr(mod, "INTEGRATIONS_CONFIG_PRIMARY", pins["QUANTRO_INTEGRATIONS_CONFIG_PRIMARY"])
    client = FakeMotorClient()
    monkeypatch.setattr(mongo_legacy, "_get_client", lambda: client)
    monkeypatch.setattr(httpx, "AsyncClient", fake.async_client_factory(httpx.AsyncClient))
    import server

    return fake, client["quantro_os"], server


def test_fly_toml_pins_the_pre_cutover_routing():
    env = _fly_toml_env()
    assert env["QUANTRO_DOCS_PRIMARY"] == env["QUANTRO_CALENDAR_PRIMARY"] == "mongo"
    assert env["QUANTRO_INTEGRATIONS_CONFIG_PRIMARY"] == "mongo" and env["QUANTRO_MONGO_MIRROR"] == "1"


@pytest.mark.asyncio
async def test_startup_jobs_complete_under_the_fly_toml_pins(pinned_server):
    """Finding 7: backfill_workspace_scoping called update_many on the
    integrations_config facade, which had none → AttributeError on every
    boot, skipping business_profile / system_health scoping and the default
    workspace shell."""
    fake, mdb, server = pinned_server
    await mdb["integrations_config"].insert_one(
        {"integration_id": "legacy-1", "provider": "legacy_crm", "status": "connected", "config": {}})
    await mdb["business_profile"].insert_one({"profile_id": "default", "industry": "other"})
    await mdb["system_health_events"].insert_one({"event_id": "h1", "scope": "legacy"})

    outcome = await server.run_startup_jobs()
    assert all(v == "ok" for v in outcome.values()), outcome

    legacy = await mdb["integrations_config"].find_one({"integration_id": "legacy-1"})
    assert legacy["workspace_id"] == "default"
    assert any(r["provider"] == "legacy_crm" and r["workspace_id"] == "default"
               for r in fake.rows["integrations_config"])          # shadow kept in step
    assert (await mdb["business_profile"].find_one({"profile_id": "default"}))["workspace_id"] == "default"
    assert (await mdb["system_health_events"].find_one({"event_id": "h1"}))["workspace_id"] == "default"
    assert await mdb["workspaces"].find_one({"workspace_id": "default"})
    shadows = {(r["collection"], r["doc"].get("workspace_id")) for r in fake.rows["flow_documents"]}
    assert ("workspaces", "default") in shadows and ("business_profile", "default") in shadows


@pytest.mark.asyncio
async def test_one_failing_repair_does_not_skip_the_rest(pinned_server, monkeypatch):
    fake, mdb, server = pinned_server
    await mdb["business_profile"].insert_one({"profile_id": "default", "industry": "other"})

    async def boom(*_a, **_k):
        raise RuntimeError("integrations store down")

    monkeypatch.setattr(server.integrations_config_col, "update_many", boom)
    await server.backfill_workspace_scoping()
    assert (await mdb["business_profile"].find_one({"profile_id": "default"}))["workspace_id"] == "default"
    assert await mdb["workspaces"].find_one({"workspace_id": "default"})
