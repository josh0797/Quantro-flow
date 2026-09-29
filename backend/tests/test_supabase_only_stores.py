"""Typed stores with every flag on Supabase and no mirror: correct Mongo
semantics, nothing dropped, and Mongo never touched (tripwire)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import connect_store
import inbox_store
import product_domain_store as pds
import provider_secrets_store as pss
from actions import store as actions_store
from mongo_compat import DuplicateKeyError
from storage_helpers import TripwireMongo, supabase_only


@pytest.fixture
def sb(monkeypatch):
    return supabase_only(monkeypatch)


LIVE = {"workspace_id": "ws", "is_simulation": {"$ne": True}, "hidden_by_real": {"$ne": True}}


@pytest.mark.asyncio
async def test_inbox_sync_upsert_honours_set_on_insert(sb):
    inbox = inbox_store.wrap_inbox_col(TripwireMongo("inbox_items"))
    now = datetime.now(timezone.utc)

    async def sync(subject):
        return await inbox.update_one(
            {"workspace_id": "ws", "gmail_id": "g1"},
            {
                "$set": {"workspace_id": "ws", "source": "gmail", "gmail_id": "g1", "subject": subject,
                         "from_address": "boss@co.com", "preview": "hi", "received_at": now.isoformat(),
                         "is_real": True, "is_simulation": False, "synced_at": now},
                "$setOnInsert": {"id": f"app-{subject}", "status": "new", "priority": "medium", "created_at": now},
            },
            upsert=True,
        )

    first = await sync("one")
    assert first.upserted_id == "app-one"
    await inbox.update_one({"inbox_id": "app-one"}, {"$set": {"status": "processed", "policy_action": "auto_run",
                                                             "escalation": {"rule": "r"}, "auto_executed": True,
                                                             "execution_results": [{"type": "x"}]}})
    second = await sync("two")
    assert second.matched_count == 1
    rows = sb.rows["inbox_items"]
    assert len(rows) == 1
    # Re-sync must not reset the app id or the triage state.
    assert rows[0]["inbox_id"] == "app-one" and rows[0]["status"] == "processed" and rows[0]["subject"] == "two"
    item = await inbox.find_one({"workspace_id": "ws", "inbox_id": "app-one"})
    assert item["policy_action"] == "auto_run" and item["escalation"] == {"rule": "r"}
    assert item["execution_results"] == [{"type": "x"}] and item["id"] == "app-one"


@pytest.mark.asyncio
async def test_inbox_lists_counts_and_residual_filters(sb):
    inbox = inbox_store.wrap_inbox_col(TripwireMongo("inbox_items"))
    base = datetime(2026, 9, 1, tzinfo=timezone.utc)
    await inbox.insert_many([
        {"inbox_id": "demo", "workspace_id": "ws", "is_simulation": True, "hidden_by_real": True, "received_at": base},
        {"inbox_id": "real", "workspace_id": "ws", "is_simulation": False, "received_at": base + timedelta(hours=1)},
        {"inbox_id": "nulls", "workspace_id": "ws", "received_at": None, "category": "lead", "priority": "low"},
        {"inbox_id": "sim", "workspace_id": "ws", "is_simulation": True, "priority": "high"},
    ])
    rows = await inbox.find(LIVE).sort("received_at", -1).to_list(100)
    assert [r["inbox_id"] for r in rows] == ["real", "nulls"]  # NULL last on desc, like Mongo
    assert await inbox.count_documents(LIVE) == 2
    opp = await inbox.count_documents({"workspace_id": "ws", "$or": [
        {"category": {"$in": ["opportunity", "lead"]}}, {"priority": {"$in": ["high", "urgent"]}}]})
    assert opp == 2  # category lives in `extra`, evaluated in Python
    res = await inbox.update_many({"workspace_id": "ws", "is_simulation": True}, {"$set": {"hidden_by_real": True}})
    assert res.matched_count == 2
    res = await inbox.update_many({"workspace_id": "ws", "is_simulation": True}, {"$unset": {"hidden_by_real": ""}})
    assert all(r.get("hidden_by_real") is None for r in sb.rows["inbox_items"] if r["inbox_id"] in ("demo", "sim"))
    deleted = await inbox.delete_many({"workspace_id": "ws", "category": "lead"})
    assert deleted.deleted_count == 1


@pytest.mark.asyncio
async def test_contacts_keep_extra_fields_and_live_filter(sb):
    contacts = pds.wrap_contacts_col(TripwireMongo("contacts"))
    last = datetime(2026, 9, 2, 10, 0)
    await contacts.insert_one({"contact_id": "c1", "workspace_id": "ws", "name": "Ada", "status": "active",
                               "last_contact": last, "is_simulation": True})
    await contacts.insert_one({"contact_id": "c2", "workspace_id": "ws", "name": "Bo", "is_simulation": False})
    c1 = await contacts.find_one({"contact_id": "c1"})
    assert c1["status"] == "active" and c1["last_contact"] == last
    live = await contacts.find(LIVE).sort("updated_at", -1).to_list(100)
    assert [c["contact_id"] for c in live] == ["c2"]
    assert await contacts.count_documents({"is_simulation": True, "workspace_id": "ws"}) == 1


@pytest.mark.asyncio
async def test_calendar_external_sync_and_disconnect_supabase_only(sb):
    cal = pds.wrap_calendar_col(TripwireMongo("calendar_events"))
    now = datetime.now(timezone.utc)

    async def sync(event_id, title):
        canonical = pds.canonical_calendar_write(
            workspace_id="ws", event_id=event_id, external_provider="google", external_event_id="gcal-1",
            title=title, start_time=now.isoformat(), end_time=now.isoformat(), source="google_calendar",
            synced_at=now, updated_at=now, extra={"is_real": True},
        )
        return await pds.upsert_calendar_external_event(
            cal, workspace_id="ws", provider="google", external_event_id="gcal-1", canonical=canonical, now=now,
        )

    r1 = await sync("e-first", "A")
    r2 = await sync("e-second", "B")
    r3 = await sync("e-third", "B")
    assert r1 == {"event_id": "e-first", "outcome": "inserted"}
    assert r2 == {"event_id": "e-first", "outcome": "updated"}
    assert r3["outcome"] == "unchanged"
    rows = sb.rows["calendar_events"]
    assert len(rows) == 1 and rows[0]["title"] == "B" and rows[0]["is_real"] is True

    await cal.insert_one({"event_id": "demo", "workspace_id": "ws", "is_simulation": True, "title": "Demo"})
    await cal.update_many({"workspace_id": "ws", "is_simulation": True}, {"$set": {"hidden_by_real": True}})
    # Disconnect: un-hide ($unset on a NOT NULL column → default) and wipe synced rows.
    await cal.update_many({"workspace_id": "ws", "is_simulation": True}, {"$unset": {"hidden_by_real": ""}})
    res = await cal.delete_many({"workspace_id": "ws", "is_real": True, "source": "google_calendar"})
    assert res.deleted_count == 1
    assert [r["event_id"] for r in sb.rows["calendar_events"]] == ["demo"]
    assert sb.rows["calendar_events"][0]["hidden_by_real"] is False


@pytest.mark.asyncio
async def test_template_editor_fields_round_trip(sb):
    tpl = pds.wrap_content_templates_col(TripwireMongo("content_templates"))
    await tpl.insert_one({
        "workspace_id": "ws", "template_id": "t1", "name": "Welcome", "category": "welcome",
        "template_type": "email", "subject_template": "Hi {{contact_name}}", "body_template": "Dear {{contact_name}}",
        "variables": ["contact_name"], "tags": ["onboarding"], "status": "active", "created_by": "system",
        "created_at": datetime.now(timezone.utc),
    })
    t = await tpl.find_one({"workspace_id": "ws", "template_id": "t1"})
    assert t["body_template"] == "Dear {{contact_name}}" and t["variables"] == ["contact_name"]
    res = await tpl.update_one({"workspace_id": "ws", "template_id": "t1"}, {"$set": {"body_template": "New"}})
    assert res.matched_count == 1
    assert (await tpl.update_one({"workspace_id": "ws", "template_id": "zz"}, {"$set": {"name": "x"}})).matched_count == 0


@pytest.mark.asyncio
async def test_policy_update_returns_matched_count_and_idempotency(sb):
    policies = actions_store.wrap_automation_policies_col(TripwireMongo("automation_policies"))
    await policies.insert_one({"workspace_id": "ws", "policy_id": "p1", "intent": "booking", "action": "auto_run",
                               "enabled": True, "created_at": datetime.now(timezone.utc), "custom": 1})
    res = await policies.update_one({"workspace_id": "ws", "policy_id": "p1"}, {"$set": {"action": "escalate"}})
    assert res.matched_count == 1  # PUT /api/policies/{id} used to 500 here
    missing = await policies.update_one({"workspace_id": "ws", "policy_id": "nope"}, {"$set": {"action": "x"}})
    assert missing.matched_count == 0
    p = await policies.find_one({"workspace_id": "ws", "intent": "booking", "enabled": True})
    assert p["action"] == "escalate" and p["custom"] == 1

    execs = actions_store.wrap_executions_col(TripwireMongo("action_executions"))
    doc = {"execution_id": "e1", "workspace_id": "ws", "action_id": "a", "status": "pending_approval",
           "idempotency_key": "k", "input": {}, "result_metadata": {}, "started_at": datetime.now(timezone.utc)}
    await execs.insert_one(dict(doc))
    with pytest.raises(DuplicateKeyError):
        await execs.insert_one({**doc, "execution_id": "e2"})
    claim = {"execution_id": "e1", "workspace_id": "ws", "status": "pending_approval"}
    won = await execs.find_one_and_update(claim, {"$set": {"status": "approved"}}, projection={"_id": 0})
    lost = await execs.find_one_and_update(claim, {"$set": {"status": "approved"}}, projection={"_id": 0})
    assert won["status"] == "approved" and lost is None
    assert await execs.count_documents({"workspace_id": "ws", "started_at": {"$gte": datetime.now(timezone.utc) - timedelta(days=1)}}) == 1


@pytest.mark.asyncio
async def test_integrations_config_keeps_ciphertext_only(sb):
    from integrations import secrets as integration_secrets

    cfg = connect_store.IntegrationsConfigCollection(TripwireMongo("integrations_config"))
    await cfg.insert_one({"integration_id": "i1", "workspace_id": "ws", "provider": "openai", "status": "disconnected",
                          "config": {}, "created_at": datetime.now(timezone.utc), "legacy_flag": True})
    assert await cfg.count_documents({"workspace_id": "ws"}) == 1
    enc = integration_secrets.encrypt_secret("sk-live-secret")
    res = await connect_store.update_integrations_config(
        workspace_id="ws", provider="openai", mongo_col=cfg,
        fields={"status": "connected", "config": {"api_key": enc, "model": "gpt-4"}},
    )
    assert res.matched_count == 1
    row = sb.rows["integrations_config"][0]
    assert row["secrets_enc"] == {"api_key": enc} and "api_key" not in row["config"]
    assert "sk-live-secret" not in str(sb.rows)
    doc = await connect_store.get_integrations_config(workspace_id="ws", provider="openai", mongo_col=cfg)
    assert doc["config"]["api_key"] == enc and doc["integration_id"] == "i1" and doc["legacy_flag"] is True
    # Unknown provider: 404 path, and no row is created.
    none = await connect_store.update_integrations_config(
        workspace_id="ws", provider="evil", mongo_col=cfg, fields={"status": "connected"})
    assert none.matched_count == 0 and len(sb.rows["integrations_config"]) == 1


@pytest.mark.asyncio
async def test_oauth_state_keeps_requested_scopes_and_connections_are_sb_only(sb):
    state_col = TripwireMongo("microsoft_oauth_state")
    await pss.put_oauth_state(
        provider="microsoft", mongo_col=state_col, state="st", user_id="u", workspace_id="ws",
        return_to="/connect", redirect_uri="https://x/cb", requested_scopes=["Mail.Send", "Mail.Read"],
    )
    doc = await pss.consume_oauth_state(provider="microsoft", mongo_col=state_col, state="st")
    assert doc["requested_scopes"] == ["Mail.Send", "Mail.Read"]
    assert await pss.consume_oauth_state(provider="microsoft", mongo_col=state_col, state="st") is None

    conn_col = TripwireMongo("google_integrations")
    assert await pss.get_connection(provider="google", workspace_id="ws", mongo_col=conn_col) is None
    await pss.upsert_connection(provider="google", workspace_id="ws", mongo_col=conn_col, fields={
        "access_token": "gAAAAA-cipher", "refresh_token": "gAAAAA-r", "scopes": ["a"], "connected": True,
        "last_calendar_sync_metrics": {"inserted": 2}, "refresh_token_plain": "never-stored",
    })
    await pss.patch_connection(provider="google", workspace_id="ws", mongo_col=conn_col,
                               fields={"last_sync_at": datetime.now(timezone.utc)})
    got = await pss.get_connection(provider="google", workspace_id="ws", mongo_col=conn_col)
    assert got["access_token"] == "gAAAAA-cipher" and got["last_calendar_sync_metrics"] == {"inserted": 2}
    assert "never-stored" not in str(sb.rows["provider_connections"])
    assert await pss.list_autosync_workspace_ids(provider="google", mongo_col=conn_col) == ["ws"]


@pytest.mark.asyncio
async def test_sync_lock_lease_is_exclusive(sb):
    from sync_lock import acquire_sync_lock_lease_supabase

    now = datetime.now(timezone.utc)
    assert await acquire_sync_lock_lease_supabase(provider="google", workspace_id="ws", window_seconds=300, now=now)
    assert not await acquire_sync_lock_lease_supabase(provider="google", workspace_id="ws", window_seconds=300, now=now)
    later = now + timedelta(seconds=301)
    assert await acquire_sync_lock_lease_supabase(provider="google", workspace_id="ws", window_seconds=300, now=later)
    assert not await acquire_sync_lock_lease_supabase(provider="google", workspace_id="ws", window_seconds=300, now=later)
