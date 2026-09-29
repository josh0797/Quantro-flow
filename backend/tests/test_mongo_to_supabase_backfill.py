"""scripts/mongo_to_supabase.py — idempotent, never deletes, dry-run by
default, primary-aware, prints ids/counts only."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import pytest

from scripts import mongo_to_supabase as bf
from storage_helpers import supabase_only

T0 = datetime(2026, 9, 1, 12, 0)  # naive, like Motor returns


class FakeSource:
    """Streams like MongoSource.batches (tiny batches so every test crosses
    batch boundaries); ``docs`` is kept for ad-hoc probes."""

    def __init__(self, data: Dict[str, List[Dict[str, Any]]], batch: int = 2):
        self.data = copy.deepcopy(data)
        self.reads: List[str] = []
        self.batch = batch
        self.max_batch = 0

    async def collection_names(self) -> List[str]:
        return sorted(self.data)

    async def batches(self, name: str, size: int = 500):
        self.reads.append(name)
        docs = copy.deepcopy(self.data.get(name, []))
        step = min(size, self.batch)
        for i in range(0, len(docs), step):
            chunk = docs[i:i + step]
            self.max_batch = max(self.max_batch, len(chunk))
            yield chunk

    async def docs(self, name: str) -> List[Dict[str, Any]]:
        self.reads.append(name)
        return copy.deepcopy(self.data.get(name, []))


def oid(n: int) -> str:
    return f"65f1{n:020x}"


SECRET_BODY = "CONFIDENTIAL-EMAIL-BODY"
TOKEN = "gAAAAABsecretcipher" + "x" * 60


def mongo_fixture() -> Dict[str, List[Dict[str, Any]]]:
    return {
        "users": [
            {"_id": oid(1), "user_id": "u1", "email": "owner@example.com", "name": "Owner",
             "current_workspace_id": "default", "created_at": T0, "last_login_at": T0},
        ],
        "workspaces": [
            {"_id": oid(2), "workspace_id": "default", "name": "Quantro", "owner_user_id": "u1", "org_id": "org-1", "claimed": True},
            {"_id": oid(3), "workspace_id": "ws_a", "name": "A", "owner_user_id": "u1", "claimed": True},
        ],
        "workspace_members": [{"_id": oid(4), "workspace_id": "ws_a", "user_id": "u1", "role": "owner", "joined_at": T0}],
        "workspace_invites": [{"_id": oid(5), "workspace_id": "ws_a", "token": "tok", "max_uses": 3, "used_count": 1,
                               "accepted_by": [{"user_id": "u2", "at": T0}]}],
        "audit_log": [{"_id": oid(6), "event_id": "ev1", "event_type": "workspace.created", "workspace_id": "ws_a",
                       "timestamp": T0, "metadata": {}}],
        "business_profile": [{"_id": oid(7), "profile_id": "default", "industry": "other", "simulation_mode": False}],  # no workspace_id
        "agents": [{"_id": oid(8), "agent_id": "a1", "name": "James", "status": "onboarding", "created_at": T0}],
        "onboarding_tasks": [{"_id": oid(9), "task_id": "t1", "agent_id": "a1", "status": "pending", "workspace_id": "ws_a"}],
        "escalation_rules": [{"_id": oid(10), "rule_id": "r1", "workspace_id": "ws_a", "name": "Urgent", "enabled": True}],
        "calendar_events": [
            {"_id": oid(11), "workspace_id": "ws_a", "id": "legacy-evt", "gcal_id": "g-1", "title": "Synced",
             "start": "2026-09-02T10:00:00Z", "html_link": "https://cal/x", "is_real": True, "is_simulation": False,
             "source": "google_calendar"},
            {"_id": oid(12), "workspace_id": "ws_a", "event_id": "int-1", "title": "Internal", "external_provider": "internal"},
        ],
        "integrations_config": [
            {"_id": oid(13), "integration_id": "i-old", "workspace_id": "ws_a", "provider": "openai", "status": "disconnected",
             "config": {}, "updated_at": T0},
            {"_id": oid(14), "integration_id": "i-new", "workspace_id": "ws_a", "provider": "openai", "status": "connected",
             "config": {"api_key": "sk-plaintext-legacy", "model": "gpt-4"}, "updated_at": T0 + timedelta(days=1)},
        ],
        "inbox_items": [
            {"_id": oid(15), "workspace_id": "ws_a", "id": "app-g1", "gmail_id": "gm1", "from_address": "boss@co.com",
             "subject": "Q3", "preview": SECRET_BODY, "is_real": True, "is_simulation": False, "status": "new",
             "received_at": "2026-09-02T09:00:00+00:00"},
            {"_id": oid(16), "workspace_id": "ws_a", "inbox_id": "seed1", "from_email": "sarah@x.com", "body": SECRET_BODY,
             "status": "new", "policy_action": "escalate", "escalation": {"rule": "Urgent"}, "auto_executed": False},
        ],
        "contacts": [{"_id": oid(17), "workspace_id": "ws_a", "contact_id": "c1", "name": "Ada", "status": "active",
                      "last_contact": T0, "is_simulation": True, "hidden_by_real": True}],
        "content_templates": [{"_id": oid(18), "workspace_id": "ws_a", "template_id": "tpl1", "name": "Welcome",
                               "template_type": "email", "body_template": "Dear {{contact_name}}", "variables": ["contact_name"]}],
        "automation_policies": [{"_id": oid(19), "workspace_id": "ws_a", "policy_id": "p1", "intent": "booking",
                                 "action": "auto_run", "enabled": True, "created_at": T0}],
        "google_integrations": [{"_id": oid(20), "workspace_id": "ws_a", "access_token": TOKEN, "refresh_token": TOKEN,
                                 "account_email": "boss@co.com", "scopes": ["a"], "connected": True,
                                 "last_calendar_sync_metrics": {"inserted": 1}}],
        "facturapi_webhook_events": [{"_id": oid(21), "event_id": "evt_1", "workspace_id": "ws_a", "connection_id": "c",
                                      "event_type": "invoice.status_updated", "signature_valid": True,
                                      "received_at": T0, "payload_summary": {"id": "inv_1"}}],
        "google_oauth_state": [{"_id": oid(22), "state": "s"}],
        "mystery_collection": [{"_id": oid(23)}],
    }


PINS = ("QUANTRO_DOCS_PRIMARY", "QUANTRO_CALENDAR_PRIMARY", "QUANTRO_INTEGRATIONS_CONFIG_PRIMARY")


@pytest.fixture
def env(monkeypatch):
    # Production state at runbook steps 3-5 (fly.toml pins): these three
    # domains are still Mongo-primary, everything else already
    # Supabase-primary, and every Mongo mirror is on.
    fake = supabase_only(monkeypatch, mirror=True)
    for flag in PINS:
        monkeypatch.setenv(flag, "mongo")
    return fake


def by(report: Dict[str, Any], name: str) -> Dict[str, Any]:
    return next(d for d in report["datasets"] if d["dataset"] == name)


def snapshot(fake) -> Dict[str, List[Dict[str, Any]]]:
    return copy.deepcopy({t: rows for t, rows in fake.rows.items()})


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(env):
    fake = env
    report = await bf.run(FakeSource(mongo_fixture()), fake.request, apply=False)
    assert report["mode"] == "dry_run" and report["preflight"] == {}
    assert all(not rows for rows in fake.rows.values())
    assert by(report, "users")["insert"] == 1
    assert by(report, "integrations_config")["notes"]["mongo_duplicates"] == 1
    assert "mystery_collection" in report["unknown_collections"]
    assert "google_oauth_state" in report["not_migrated"]
    assert not [m for m, path in fake.calls if m != "GET"]


@pytest.mark.asyncio
async def test_apply_then_rerun_is_idempotent_and_never_deletes(env):
    fake = env
    # A Supabase-only row (written after the flip / by the app) must survive.
    fake.rows["contacts"].append({"id": "keep", "workspace_id": "ws_a", "contact_id": "sb-only", "is_simulation": False,
                                  "hidden_by_real": False, "extra": {}, "created_at": "2026-09-01T00:00:00+00:00",
                                  "updated_at": "2026-09-01T00:00:00+00:00"})
    source = FakeSource(mongo_fixture())
    first = await bf.run(source, fake.request, apply=True)
    assert bf.exit_code(first) == 0, bf.render(first)
    after_first = snapshot(fake)
    writes_before = [c for c in fake.calls if c[0] != "GET"]

    second = await bf.run(source, fake.request, apply=True)
    assert bf.exit_code(second, verify=True) == 0, bf.render(second, verify=True)
    for d in second["datasets"]:
        assert (d["insert"], d["update"], d["error"]) == (0, 0, 0), d
    # The re-run wrote nothing at all and the data is byte-for-byte the same.
    assert [c for c in fake.calls if c[0] != "GET"] == writes_before
    assert snapshot(fake) == after_first
    assert any(r["contact_id"] == "sb-only" for r in fake.rows["contacts"])
    assert not [c for c in fake.calls if c[0] == "DELETE"]


@pytest.mark.asyncio
async def test_what_lands_in_supabase(env):
    fake = env
    report = await bf.run(FakeSource(mongo_fixture()), fake.request, apply=True)
    assert bf.exit_code(report) == 0, bf.render(report)
    docs = {(r["collection"], r["doc_id"]): r for r in fake.rows["flow_documents"]}
    # doc_id = Mongo _id, datetimes typed, legacy defaults applied.
    user = docs[("users", oid(1))]
    assert user["doc"]["created_at"] == {"$date": T0.isoformat()}
    # Row created_at = the ObjectId's creation time (keeps Mongo's natural order).
    assert user["created_at"] == datetime.fromtimestamp(int(oid(1)[:8], 16), tz=timezone.utc).isoformat()
    assert docs[("business_profile", oid(7))]["workspace_id"] == "default"
    assert docs[("agents", oid(8))]["doc"]["is_simulation"] is True
    assert docs[("workspace_invites", oid(5))]["doc"]["accepted_by"][0]["user_id"] == "u2"
    # Calendar legacy doc normalized onto the canonical columns.
    cal = {r["event_id"]: r for r in fake.rows["calendar_events"]}
    assert cal["legacy-evt"]["external_provider"] == "google" and cal["legacy-evt"]["external_event_id"] == "g-1"
    assert cal["legacy-evt"]["external_url"] == "https://cal/x" and cal["legacy-evt"]["is_real"] is True
    # integrations_config: newest duplicate wins, plaintext secret encrypted.
    (ic,) = fake.rows["integrations_config"]
    assert ic["integration_id"] == "i-new" and ic["status"] == "connected"
    assert ic["secrets_enc"]["api_key"].startswith("gAAAAA") and "sk-plaintext-legacy" not in str(fake.rows)
    # Inbox: Mongo-only Gmail row inserted; policy fields kept.
    inbox = {r["inbox_id"]: r for r in fake.rows["inbox_items"]}
    assert inbox["app-g1"]["gmail_id"] == "gm1"
    assert inbox["seed1"]["policy_action"] == "escalate" and inbox["seed1"]["escalation"] == {"rule": "Urgent"}
    # Contacts: simulation extras + hidden flag.
    (c,) = fake.rows["contacts"]
    assert c["hidden_by_real"] is True and c["extra"]["status"] == "active"
    # Templates: editor fields.
    assert fake.rows["content_templates"][0]["body_template"] == "Dear {{contact_name}}"
    # Provider connection: ciphertext columns + non-secret extras in meta.
    (pc,) = fake.rows["provider_connections"]
    assert pc["access_token_enc"] == TOKEN and pc["meta"]["last_calendar_sync_metrics"] == {"inserted": 1}
    assert fake.rows["webhook_events"][0]["event_id"] == "evt_1"


@pytest.mark.asyncio
async def test_fill_policy_never_overwrites_supabase_primary_rows(env):
    fake = env
    fake.rows["inbox_items"].append({
        "id": "pk1", "workspace_id": "ws_a", "inbox_id": "seed1", "status": "processed", "read": True,
        "policy_action": None, "extra": {}, "created_at": "2026-09-01T00:00:00+00:00", "updated_at": "2026-09-01T00:00:00+00:00",
    })
    # Stale shadow of a Mongo-primary calendar row: Mongo wins there.
    fake.rows["calendar_events"].append({
        "id": "pk2", "workspace_id": "ws_a", "event_id": "int-1", "title": "STALE", "external_provider": "internal",
        "is_simulation": False, "hidden_by_real": False, "extra": {},
        "created_at": "2026-09-01T00:00:00+00:00", "updated_at": "2026-09-01T00:00:00+00:00",
    })
    report = await bf.run(FakeSource(mongo_fixture()), fake.request, apply=True)
    assert by(report, "inbox_items")["policy"] == "fill"
    assert by(report, "calendar_events")["policy"] == "mongo_wins"
    row = next(r for r in fake.rows["inbox_items"] if r["inbox_id"] == "seed1")
    assert row["status"] == "processed"            # Supabase value kept
    assert row["policy_action"] == "escalate"      # missing value filled from Mongo
    cal = next(r for r in fake.rows["calendar_events"] if r["event_id"] == "int-1")
    assert cal["title"] == "Internal"


@pytest.mark.asyncio
async def test_token_less_supabase_row_is_repaired(env):
    fake = env
    fake.rows["provider_connections"].append({
        "id": "pc1", "workspace_id": "ws_a", "provider": "google", "access_token_enc": None, "refresh_token_enc": None,
        "scopes": [], "missing_scopes": [], "connected": False, "reauthorization_required": False,
        "auto_sync_paused": False, "meta": {}, "last_sync_at": "2026-09-27T00:00:00+00:00",
        "created_at": "2026-09-01T00:00:00+00:00", "updated_at": "2026-09-27T00:00:00+00:00",
    })
    report = await bf.run(FakeSource(mongo_fixture()), fake.request, apply=True, only={"google_integrations"})
    d = by(report, "google_integrations")
    assert d["update"] == 1 and d["notes"].get("token_less_row_repaired") == 1
    assert fake.rows["provider_connections"][0]["access_token_enc"] == TOKEN


@pytest.mark.asyncio
async def test_output_has_counts_and_ids_but_no_bodies_or_secrets(env):
    fake = env
    report = await bf.run(FakeSource(mongo_fixture()), fake.request, apply=False)
    text = bf.render(report) + str(report)
    for secret in (SECRET_BODY, TOKEN, "sk-plaintext-legacy", "owner@example.com", "boss@co.com", "sarah@x.com"):
        assert secret not in text


@pytest.mark.asyncio
async def test_preflight_blocks_apply_when_migration_missing(env):
    fake = env
    fake.drop_table("flow_documents")  # konta migration not applied
    report = await bf.run(FakeSource(mongo_fixture()), fake.request, apply=True)
    assert report.get("aborted") and "flow_documents" in report["preflight"]
    assert bf.exit_code(report) == 2
    assert not [m for m, _ in fake.calls if m in ("POST", "PATCH", "DELETE")]


def test_cli_requires_fly_env(monkeypatch, capsys):
    for k in ("MONGO_URL", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert bf.main([]) == 2
    assert "missing env" in capsys.readouterr().err


# ── review findings (2026-09-28) ───────────────────────────────────────

MIRRORS_OFF = {  # runbook step 6b
    "QUANTRO_MONGO_MIRROR": "0", "QUANTRO_DOCS_MONGO_MIRROR": "0", "QUANTRO_CALENDAR_MONGO_MIRROR": "0",
    "QUANTRO_ACTIONS_MONGO_MIRROR": "0", "QUANTRO_INBOX_MONGO_MIRROR": "0", "QUANTRO_ACTIVITY_MONGO_MIRROR": "0",
    "QUANTRO_CONTACTS_MONGO_MIRROR": "0", "QUANTRO_CONTENT_MONGO_MIRROR": "0",
}


def stale_mongo() -> Dict[str, List[Dict[str, Any]]]:
    return {
        "workspace_members": [{"_id": oid(4), "workspace_id": "ws_a", "user_id": "removed_user", "role": "member"}],
        "content_templates": [{"_id": oid(18), "workspace_id": "ws_a", "template_id": "tpl1", "name": "Welcome",
                               "template_type": "email", "body_template": "OLD body", "status": "active"}],
        "contacts": [{"_id": oid(17), "workspace_id": "ws_a", "contact_id": "c_deleted", "name": "Deleted",
                      "is_simulation": False}],
        "inbox_items": [{"_id": oid(16), "workspace_id": "ws_a", "inbox_id": "i1", "status": "new",
                         "policy_action": "escalate", "is_simulation": False}],
        "microsoft_integrations": [{"_id": oid(30), "workspace_id": "ws_a", "access_token": TOKEN,
                                    "refresh_token": TOKEN, "account_email": "u@x.com", "connected": True}],
    }


def _flip(monkeypatch, *, primaries: bool = True, mirrors_off: bool = False) -> None:
    if primaries:  # 6a
        for flag in PINS:
            monkeypatch.setenv(flag, "supabase")
    if mirrors_off:  # 6b
        for k, v in MIRRORS_OFF.items():
            monkeypatch.setenv(k, v)


@pytest.mark.asyncio
async def test_apply_after_6b_is_refused_and_restores_nothing(env, monkeypatch):
    """Finding 1: re-running --apply once Mongo stopped being written would
    resurrect a removed member, a deleted contact and a disconnected mailbox
    (with its tokens) and revert edits. It must refuse and write nothing."""
    fake = env
    first = await bf.run(FakeSource(stale_mongo()), fake.request, apply=True)   # normal cutover (mirrors on)
    assert bf.exit_code(first) == 0, bf.render(first)
    _flip(monkeypatch, mirrors_off=True)
    # After 6b users act in Supabase only.
    fake.rows["flow_documents"] = [r for r in fake.rows["flow_documents"] if r["collection"] != "workspace_members"]
    fake.rows["contacts"] = []
    fake.rows["provider_connections"] = []                  # Microsoft disconnected
    for r in fake.rows["content_templates"]:
        r["body_template"] = "NEW body"
    for r in fake.rows["inbox_items"]:
        r["policy_action"] = "auto_run"
    before = snapshot(fake)
    writes = [c for c in fake.calls if c[0] != "GET"]

    report = await bf.run(FakeSource(stale_mongo()), fake.request, apply=True)
    assert bf.exit_code(report) == 2
    assert "no longer mirrored" in report["aborted"]
    assert set(report["stale_mongo"]) == {"content", "contacts", "docs", "inbox", "secrets"}
    assert [c for c in fake.calls if c[0] != "GET"] == writes      # nothing written
    assert snapshot(fake) == before
    assert "ABORTED" in bf.render(report)

    # A dry run still works (read-only) and says the numbers are against a stale copy.
    dry = await bf.run(FakeSource(stale_mongo()), fake.request, apply=False)
    assert "stale" in bf.render(dry)
    assert snapshot(fake) == before


@pytest.mark.asyncio
async def test_stale_refusal_is_per_domain_and_overridable(env, monkeypatch):
    fake = env
    monkeypatch.setenv("QUANTRO_INBOX_MONGO_MIRROR", "0")   # only inbox stopped mirroring
    blocked = await bf.run(FakeSource(stale_mongo()), fake.request, apply=True)
    assert bf.exit_code(blocked) == 2 and blocked["stale_mongo"] == ["inbox"]
    ok = await bf.run(FakeSource(stale_mongo()), fake.request, apply=True, only={"contacts"})
    assert bf.exit_code(ok) == 0 and [r["contact_id"] for r in fake.rows["contacts"]] == ["c_deleted"]
    forced = await bf.run(FakeSource(stale_mongo()), fake.request, apply=True, allow_stale_mongo=True)
    assert bf.exit_code(forced) == 0 and forced["allow_stale_mongo"] is True
    assert fake.rows["inbox_items"]


@pytest.mark.asyncio
async def test_template_content_items_take_their_templates_workspace_never_default(env):
    """Until the workspace fixes, POST /api/templates/{id}/generate stored the
    item without workspace_id (the startup repair re-tagged it "default"),
    although the template was loaded scoped to the caller. The legacy rule
    would copy other tenants' drafts into the default workspace; the item
    takes its template's workspace instead, or the quarantine workspace when
    the template is gone — never "default"."""
    fake = env
    fake.rows["content_templates"].append({
        "id": "tpl-sb-pk", "workspace_id": "ws_c", "template_id": "tpl-sb", "name": "SB", "is_default": False,
        "is_simulation": False, "hidden_by_real": False, "extra": {},
        "created_at": "2026-09-01T00:00:00+00:00", "updated_at": "2026-09-01T00:00:00+00:00",
    })

    def item(n: int, cid: str, tpl: str, **kw: Any) -> Dict[str, Any]:
        return {"_id": oid(n), "content_id": cid, "type": "email_draft", "title": "ACME offer - Jane Victim",
                "content": {"body": SECRET_BODY}, "created_by": "ai_template", "template_id": tpl, **kw}

    data = {
        "content_templates": [
            {"_id": oid(90), "workspace_id": "ws_a", "template_id": "tpl1", "name": "Welcome"},
            {"_id": oid(91), "workspace_id": "default", "template_id": "tpl-d", "name": "Own"},
        ],
        "content_items": [
            item(92, "untagged", "tpl1"),
            item(93, "retagged", "tpl1", workspace_id="default", is_simulation=True),
            item(94, "sb-template", "tpl-sb"),
            item(95, "own", "tpl-d", workspace_id="default", is_simulation=True),
            item(96, "orphan", "tpl-gone"),
            item(97, "own-orphan", "tpl-gone", workspace_id="default", is_simulation=True),
            item(98, "explicit", "tpl1", workspace_id="ws_b", is_simulation=False),
        ],
    }
    source = FakeSource(data)
    report = await bf.run(source, fake.request, apply=True)
    assert bf.exit_code(report) == 0, bf.render(report)
    rows = {r["content_id"]: r["workspace_id"] for r in fake.rows["content_items"]}
    assert rows == {"untagged": "ws_a", "retagged": "ws_a", "sb-template": "ws_c", "own": "default",
                    "orphan": bf.QUARANTINE_WORKSPACE_ID, "own-orphan": "default", "explicit": "ws_b"}
    notes = by(report, "content_items")["notes"]
    assert notes["workspace_from_template"] == 3 and notes["workspace_unattributed"] == 1
    assert SECRET_BODY not in bf.render(report)
    verify = await bf.run(source, fake.request, apply=False)
    assert bf.exit_code(verify, verify=True) == 0, bf.render(verify, verify=True)


@pytest.mark.asyncio
async def test_fill_takes_new_columns_only_while_they_hold_the_default(env):
    """Finding 1 (second half): under ``fill`` a column the migration added
    comes from Mongo only while Supabase still holds its default; a value
    the app has written is never reverted to a stale Mongo copy."""
    fake = env
    common = {"workspace_id": "ws_a", "is_simulation": False, "extra": {},
              "created_at": "2026-09-01T00:00:00+00:00", "updated_at": "2026-09-01T00:00:00+00:00"}
    fake.rows["content_templates"].append({**common, "id": "t1", "template_id": "tpl1", "name": "Welcome",
                                           "is_default": False, "hidden_by_real": False,
                                           "body_template": "NEW body"})     # app-written
    fake.rows["contacts"].append({**common, "id": "k1", "contact_id": "c1", "hidden_by_real": False})  # default
    mongo = {
        "content_templates": [{"_id": oid(18), "workspace_id": "ws_a", "template_id": "tpl1", "name": "Welcome",
                               "body_template": "OLD body"}],
        "contacts": [{"_id": oid(17), "workspace_id": "ws_a", "contact_id": "c1", "is_simulation": False,
                      "hidden_by_real": True}],
    }
    report = await bf.run(FakeSource(mongo), fake.request, apply=True)
    assert bf.exit_code(report) == 0, bf.render(report)
    assert fake.rows["content_templates"][0]["body_template"] == "NEW body"
    assert fake.rows["contacts"][0]["hidden_by_real"] is True


@pytest.mark.asyncio
async def test_verify_converges_on_rows_with_an_updated_at_trigger(env):
    """Finding 3: an existing integrations_config shadow row (trigger-stamped
    updated_at) must reach insert=0 update=0 after one --apply."""
    fake = env
    await fake.request("POST", "/rest/v1/integrations_config?on_conflict=workspace_id,provider",
                       json={"workspace_id": "ws_a", "provider": "crm", "status": "disconnected"},
                       prefer="resolution=merge-duplicates,return=minimal")
    mongo = {"integrations_config": [
        {"_id": oid(14), "integration_id": "i-1", "workspace_id": "ws_a", "provider": "crm",
         "status": "connected", "config": {"model": "x"}, "created_at": T0, "updated_at": T0},
    ]}
    applied = await bf.run(FakeSource(mongo), fake.request, apply=True)
    assert by(applied, "integrations_config")["update"] == 1
    verify = await bf.run(FakeSource(mongo), fake.request, apply=False)
    d = by(verify, "integrations_config")
    assert (d["insert"], d["update"]) == (0, 0), d
    assert bf.exit_code(verify, verify=True) == 0
    (row,) = fake.rows["integrations_config"]
    assert row["status"] == "connected" and row["integration_id"] == "i-1"


@pytest.mark.asyncio
async def test_supabase_only_access_rows_are_reported_and_block_verify_while_mongo_primary(env):
    """Finding 1 (related case): a member removed in Mongo whose shadow delete
    failed still grants access from Supabase after the flip. The backfill never
    deletes, so it must surface the row and fail --verify."""
    fake = env
    fake.rows["flow_documents"].append({
        "collection": "workspace_members", "doc_id": oid(99), "workspace_id": "ws_a",
        "doc": {"workspace_id": "ws_a", "user_id": "removed_user", "role": "member"},
        "created_at": "2026-09-01T00:00:00+00:00", "updated_at": "2026-09-01T00:00:00+00:00",
    })
    fake.rows["provider_connections"].append({
        "id": "pc9", "workspace_id": "ws_b", "provider": "google", "scopes": [], "missing_scopes": [],
        "connected": True, "reauthorization_required": False, "auto_sync_paused": False, "meta": {},
        "created_at": "2026-09-01T00:00:00+00:00", "updated_at": "2026-09-01T00:00:00+00:00",
    })
    source = FakeSource(mongo_fixture())
    await bf.run(source, fake.request, apply=True)
    report = await bf.run(source, fake.request, apply=False)
    members = by(report, "workspace_members")
    assert members["supabase_only"] == 1 and members["supabase_only_ids"] == [oid(99)]
    google = by(report, "google_integrations")
    assert google["supabase_only_ids"] == ["ws_b:google"] and google["policy"] == "fill"
    assert bf.exit_code(report, verify=True) == 1          # members: stale shadow under mongo_wins
    text = bf.render(report, verify=True)
    assert "REVIEW: workspace_members" in text and "removed_user" not in text
    assert any(r["doc_id"] == oid(99) for r in fake.rows["flow_documents"])   # never deleted
    # Once reviewed (deleted by hand), verify passes; a Supabase-primary
    # dataset's Supabase-only row is legitimate and never blocks it.
    fake.rows["flow_documents"] = [r for r in fake.rows["flow_documents"] if r["doc_id"] != oid(99)]
    assert bf.exit_code(await bf.run(source, fake.request, apply=False), verify=True) == 0


class _Recorder:
    def __init__(self, fake):
        self.fake = fake
        self.gets: List[Tuple[str, Dict[str, Any]]] = []

    async def request(self, method, path, **kw):
        if method == "GET":
            self.gets.append((path, dict(kw.get("params") or {})))
        return await self.fake.request(method, path, **kw)


@pytest.mark.asyncio
async def test_memory_is_bounded_mongo_streamed_and_supabase_indexed(env):
    """Finding 8: never hold a whole Mongo collection or a whole Supabase
    table of full rows; results are identical to the unbatched behaviour."""
    fake = env
    many = {
        "contacts": [{"_id": oid(1000 + i), "workspace_id": "ws_a", "contact_id": f"c{i}", "name": f"N{i}",
                      "is_simulation": False} for i in range(25)],
        "users": [{"_id": oid(2000 + i), "user_id": f"u{i}", "email": f"u{i}@x.com"} for i in range(25)],
    }
    # A third of them already in Supabase (to exercise the per-batch lookups).
    pre = await bf.run(FakeSource({k: v[:8] for k, v in many.items()}), fake.request, apply=True)
    assert bf.exit_code(pre) == 0
    rec = _Recorder(fake)
    source = FakeSource(many, batch=4)
    report = await bf.run(source, rec.request, apply=True)
    assert bf.exit_code(report) == 0, bf.render(report)
    assert by(report, "contacts")["insert"] == 17 and by(report, "contacts")["same"] == 8
    assert by(report, "users")["insert"] == 17 and by(report, "users")["same"] == 8
    assert source.max_batch <= 4
    data_gets = [(path, p) for path, p in rec.gets if p.get("limit") != "0"]    # skip preflight probes
    full_row_reads = [
        (path, p) for path, p in data_gets
        if p.get("select") == "*" and not any(str(v).startswith("in.(") for v in p.values())
    ]
    assert full_row_reads == []
    assert all(len(p.get("id", p.get("doc_id", "in.()")).split(",")) <= bf.FETCH_CHUNK
               for _path, p in data_gets if "id" in p or "doc_id" in p)
    assert len(fake.rows["contacts"]) == 25


@pytest.mark.asyncio
async def test_mongo_source_streams_with_a_cursor():
    from fake_motor import FakeMotorClient

    client = FakeMotorClient()
    col = client["quantro_os"]["contacts"]
    for i in range(7):
        await col.insert_one({"contact_id": f"c{i}"})
    col.stream_only = True        # to_list(None) would raise
    src = bf.MongoSource("unused", "quantro_os", client=client)
    sizes = [len(b) async for b in src.batches("contacts", size=3)]
    assert sizes == [3, 3, 1] and col.streamed == 1
    assert await src.collection_names() == ["contacts"]
    src.close()
    assert client.closed
