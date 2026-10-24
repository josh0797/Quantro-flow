"""scripts/fix_activity_workspace.py — re-attributes activity rows (and
template-generated content items) that leaked into workspace "default",
quarantines what it cannot resolve, never touches an event written after the
fix, never deletes, records provenance on every moved row, prints ids/counts
only, and stays safe with the Mongo → Supabase backfill at every point of the
cutover (docs/mongo-exit-runbook.md)."""
from __future__ import annotations

import dataclasses
import json
from typing import Any, Dict, List

import httpx
import pytest

import _import_stubs
from fake_motor import FakeMotorClient
from scripts import fix_activity_workspace as fix
from scripts import mongo_to_supabase as bf
from storage_helpers import TripwireMongo, supabase_only
from test_activity_workspace import Client, _tenants, app  # noqa: F401  (app: pytest fixture)
from test_mongo_to_supabase_backfill import PINS

SECRET = "SECRET-SUBJECT from victim@corp.example"
Q = fix.QUARANTINE_WORKSPACE_ID


@pytest.fixture
def cutover(monkeypatch):
    """Production at runbook steps 3-6a: docs/calendar/integrations still
    Mongo-primary (fly.toml pins), the rest Supabase-primary, every mirror on."""
    fake = supabase_only(monkeypatch, mirror=True)
    for flag in PINS:
        monkeypatch.setenv(flag, "mongo")
    client = FakeMotorClient()
    db = client["quantro_os"]
    return fake, client, db, fix.Stores.build(db)


def _event(eid: str, ws: str, event_type: str, related_type: Any, related_id: Any) -> Dict[str, Any]:
    return {"event_id": eid, "workspace_id": ws, "event_type": event_type, "title": SECRET,
            "description": f"{SECRET} — AI summary", "related_id": related_id, "related_type": related_type,
            "timestamp": "2026-09-20T10:00:00+00:00", "is_simulation": True}   # default's mode at write time


LEAKED = {  # event_id → (event_type, related_type, related_id, expected workspace, expected is_simulation)
    "L1-inbox": ("ai", "inbox", "in-a", "ws_a", False),
    "L2-contact": ("crm", "contact", "c-b", "ws_b", True),
    "L3-agent": ("onboarding", "agent", "ag-a", "ws_a", False),
    "L4-policy": ("system", "policy", "p-b", "ws_b", True),       # no flag on policies → ws_b's mode
    "L5-calendar": ("calendar", "calendar", "ev-a", "ws_a", False),
    "L6-profile": ("system", "profile", "ws_b", "ws_b", True),
    "L7-batch": ("ai", "inbox", None, Q, True),                    # Batch triage complete
    "L8-sim": ("system", "system", "simulation", Q, True),
    "L9-gone": ("inbox", "inbox", "in-deleted", Q, True),          # entity deleted since
}
KEPT = {
    "K1-own": ("ai", "inbox", "in-default"),
    "K2-seed": ("system", None, None),
    "K3-integration": ("system", "integration", "gmail"),
    "K4-profile": ("system", "profile", "default"),
}


async def _seed(stores: fix.Stores) -> None:
    for ws, sim in (("default", True), ("ws_a", False), ("ws_b", True)):
        await stores.workspaces.insert_one({"workspace_id": ws, "name": ws})
        await stores.business_profile.insert_one({"workspace_id": ws, "simulation_mode": sim})
    for user in ("u1", "u2"):
        await stores.members.insert_one({"workspace_id": "default", "user_id": user, "role": "owner"})
    await stores.members.insert_one({"workspace_id": "ws_a", "user_id": "u3", "role": "owner"})
    await stores.inbox.insert_one({"inbox_id": "in-a", "workspace_id": "ws_a", "subject": SECRET, "is_simulation": False})
    await stores.inbox.insert_one({"inbox_id": "in-default", "workspace_id": "default", "is_simulation": True})
    await stores.contacts.insert_one({"contact_id": "c-b", "workspace_id": "ws_b", "name": "Victim", "is_simulation": True})
    await stores.agents.insert_one({"agent_id": "ag-a", "workspace_id": "ws_a", "name": "Hire", "is_simulation": False})
    await stores.policies.insert_one({"policy_id": "p-b", "workspace_id": "ws_b", "intent": "booking", "enabled": True})
    await stores.calendar.insert_one({"event_id": "ev-a", "workspace_id": "ws_a", "title": SECRET,
                                      "external_provider": "internal", "is_simulation": False})
    # Through the app's dual-write facade, exactly as log_activity wrote them.
    for eid, (etype, rtype, rid, _ws, _sim) in LEAKED.items():
        await stores.activity.insert_one(_event(eid, "default", etype, rtype, rid))
    for eid, (etype, rtype, rid) in KEPT.items():
        await stores.activity.insert_one(_event(eid, "default", etype, rtype, rid))
    await stores.activity.insert_one({**_event("O1-other", "ws_a", "crm", "contact", "c-x"), "is_simulation": False})


def _sb(fake, eid: str) -> List[Dict[str, Any]]:
    return [r for r in fake.rows["activity_events"] if r["event_id"] == eid]


def _mongo(db, eid: str) -> List[Dict[str, Any]]:
    return [d for d in db["activity_events"].docs if d["event_id"] == eid]


def _writes(fake) -> List[Any]:
    return [c for c in fake.calls if c[0] != "GET"]


def _by(report: Dict[str, Any], name: str) -> Dict[str, Any]:
    return next(d for d in report["datasets"] if d["dataset"] == name)


# ── plan / apply ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_plans_every_case_and_writes_nothing(cutover):
    fake, _client, db, stores = cutover
    await _seed(stores)
    writes, mongo_before = _writes(fake), json.dumps(db["activity_events"].docs, default=str)

    report = await fix.run(stores, apply=False)

    assert report.errors == 0 and fix.exit_code(report) == 0
    act = report.activity
    assert dict(act.decisions) == {"keep": 4, "reattribute": 6, "quarantine": 3}
    assert dict(act.reattributed_to) == {"ws_a": 3, "ws_b": 3}
    assert act.moves == {"supabase": 9, "mongo": 9}
    assert report.default_workspace_members == 2
    assert act.scanned["supabase"] == 13 and act.scanned["mongo"] == 13     # O1 (ws_a) not scanned
    assert not report.content.moves
    assert fix.exit_code(report, verify=True) == 1
    assert _writes(fake) == writes                                             # read-only
    assert json.dumps(db["activity_events"].docs, default=str) == mongo_before
    text = fix.render(report) + json.dumps(report.as_dict(), default=str)
    assert "SECRET" not in text and "victim@" not in text and "Victim" not in text
    assert "L1-inbox -> ws_a (related_inbox)" in text


@pytest.mark.asyncio
async def test_apply_moves_supabase_and_mongo_copies_idempotently_and_never_deletes(cutover):
    fake, _client, db, stores = cutover
    await _seed(stores)
    n_sb, n_mongo = len(fake.rows["activity_events"]), len(db["activity_events"].docs)

    report = await fix.run(stores, apply=True)
    assert fix.exit_code(report) == 0, fix.render(report)
    assert report.applied == 9 and report.remaining_moves == 0

    for eid, (_t, _rt, _rid, ws, sim) in LEAKED.items():
        (row,) = _sb(fake, eid)
        (doc,) = _mongo(db, eid)
        assert (row["workspace_id"], doc["workspace_id"]) == (ws, ws), eid
        assert row["is_simulation"] is sim and doc["is_simulation"] is sim, eid
    for eid in KEPT:
        assert [r["workspace_id"] for r in _sb(fake, eid)] == ["default"]
        assert [d["workspace_id"] for d in _mongo(db, eid)] == ["default"]
    assert [r["workspace_id"] for r in _sb(fake, "O1-other")] == ["ws_a"]
    # Never deletes; titles untouched.
    assert (len(fake.rows["activity_events"]), len(db["activity_events"].docs)) == (n_sb, n_mongo)
    assert not [c for c in fake.calls if c[0] == "DELETE"]
    assert all(r["title"] == SECRET for r in fake.rows["activity_events"])

    again = await fix.run(stores, apply=False)
    assert fix.exit_code(again, verify=True) == 0, fix.render(again, verify=True)
    assert dict(again.activity.decisions) == {"keep": 4, "unattributed": 3}
    writes = _writes(fake)
    second = await fix.run(stores, apply=True)
    assert second.applied == 0 and _writes(fake) == writes


# ── R5: cutover safety with the backfill ────────────────────────────────

async def _gate(fake, client) -> Dict[str, Any]:
    """Runbook gate before 6b: backfill --apply then --verify (exit 0)."""
    source = bf.MongoSource("unused", "quantro_os", client=client)
    applied = await bf.run(source, fake.request, apply=True)
    assert bf.exit_code(applied) == 0, bf.render(applied)
    verify = await bf.run(source, fake.request, apply=False)
    assert bf.exit_code(verify, verify=True) == 0, bf.render(verify, verify=True)
    return applied


def _no_leak_left(fake) -> None:
    default_ids = {r["event_id"] for r in fake.rows["activity_events"] if r["workspace_id"] == "default"}
    assert default_ids == set(KEPT)
    counts: Dict[str, int] = {}
    for r in fake.rows["activity_events"]:
        counts[r["event_id"]] = counts.get(r["event_id"], 0) + 1
    assert set(counts.values()) == {1}      # no second copy of any event


@pytest.mark.asyncio
async def test_backfill_gate_after_remediation_reinserts_nothing(cutover):
    fake, client, _db, stores = cutover
    await _seed(stores)
    assert fix.exit_code(await fix.run(stores, apply=True)) == 0
    applied = await _gate(fake, client)
    act = _by(applied, "activity_events")
    assert (act["insert"], act["update"], act["error"]) == (0, 0, 0), act
    _no_leak_left(fake)


@pytest.mark.asyncio
async def test_remediation_between_backfill_apply_and_verify(cutover):
    """Order on the day: backfill --apply, remediation, backfill --verify."""
    fake, client, _db, stores = cutover
    await _seed(stores)
    source = bf.MongoSource("unused", "quantro_os", client=client)
    assert bf.exit_code(await bf.run(source, fake.request, apply=True)) == 0
    assert fix.exit_code(await fix.run(stores, apply=True)) == 0
    verify = await bf.run(source, fake.request, apply=False)
    assert bf.exit_code(verify, verify=True) == 0, bf.render(verify, verify=True)
    _no_leak_left(fake)


@pytest.mark.asyncio
async def test_stale_mirror_copy_is_never_reinserted_under_default(cutover):
    """A Mongo mirror write that fails during the remediation (STORE_DRIFT)
    leaves the Mongo copy under "default". The backfill must not copy it back
    into Supabase: it matches activity rows by event_id too."""
    fake, client, db, stores = cutover
    await _seed(stores)
    mongo_activity = db["activity_events"]

    async def mirror_down(*_a, **_k):
        raise RuntimeError("mongo mirror unavailable")

    mongo_activity.update_one = mirror_down          # instance attribute shadows the method
    try:
        report = await fix.run(stores, apply=True)
    finally:
        del mongo_activity.update_one

    assert report.applied == 9 and report.errors == 0
    assert report.remaining_moves == 9                  # the stale Mongo copies — re-run --apply repairs them
    assert fix.exit_code(report) == 1
    assert {d["workspace_id"] for eid in LEAKED for d in _mongo(db, eid)} == {"default"}
    assert all(_sb(fake, eid)[0]["workspace_id"] == ws for eid, (*_x, ws, _s) in LEAKED.items())

    # Without the event_id alt key the backfill WOULD re-insert all nine.
    spec = next(s for s in bf.typed_specs() if s.dataset == "activity_events")
    naive = await bf.backfill_typed(bf.Supabase(fake.request, apply=False),
                                    bf.MongoSource("unused", "quantro_os", client=client),
                                    dataclasses.replace(spec, alt_keys=()), "fill")
    assert naive.insert == 9

    applied = await _gate(fake, client)
    act = _by(applied, "activity_events")
    assert (act["insert"], act["update"]) == (0, 0) and act["notes"].get("matched_by_alt_key") == 9
    _no_leak_left(fake)

    # And the next remediation run repairs the Mongo copies.
    fixed = await fix.run(stores, apply=True)
    assert fix.exit_code(fixed) == 0 and fixed.remaining_moves == 0
    assert {d["workspace_id"] for eid in LEAKED for d in _mongo(db, eid)} == {ws for *_x, ws, _s in LEAKED.values()}


@pytest.mark.asyncio
async def test_mongo_only_leaked_row_is_fixed_before_the_first_backfill(cutover):
    """A leaked row whose Supabase write had degraded (MONGO_ONLY) exists only
    in Mongo: the remediation moves the Mongo copy, the backfill then inserts
    it under the right workspace."""
    fake, client, db, stores = cutover
    await _seed(stores)
    await db["activity_events"].insert_one(_event("M1-mongo-only", "default", "ai", "inbox", "in-a"))
    assert _sb(fake, "M1-mongo-only") == []

    report = await fix.run(stores, apply=True)
    assert fix.exit_code(report) == 0, fix.render(report)
    assert [d["workspace_id"] for d in _mongo(db, "M1-mongo-only")] == ["ws_a"]

    applied = await _gate(fake, client)
    assert _by(applied, "activity_events")["insert_ids"] == ["M1-mongo-only"]
    assert [(r["workspace_id"], r["is_simulation"]) for r in _sb(fake, "M1-mongo-only")] == [("ws_a", False)]
    _no_leak_left(fake)


@pytest.mark.asyncio
async def test_quarantine_is_reversible_when_the_entity_turns_up(cutover):
    fake, _client, _db, stores = cutover
    await _seed(stores)
    await stores.activity.insert_one(_event("L10-late", "default", "inbox", "inbox", "in-late-default"))
    await fix.run(stores, apply=True)
    assert _sb(fake, "L9-gone")[0]["workspace_id"] == Q and _sb(fake, "L10-late")[0]["workspace_id"] == Q

    # The entities show up later (e.g. copied by the backfill).
    await stores.inbox.insert_one({"inbox_id": "in-deleted", "workspace_id": "ws_b", "is_simulation": False})
    await stores.inbox.insert_one({"inbox_id": "in-late-default", "workspace_id": "default", "is_simulation": True})
    report = await fix.run(stores, apply=True)
    assert report.activity.decisions["reattribute"] == 1 and report.activity.decisions["restore"] == 1
    assert [(r["workspace_id"], r["is_simulation"]) for r in _sb(fake, "L9-gone")] == [("ws_b", False)]
    assert [r["workspace_id"] for r in _sb(fake, "L10-late")] == ["default"]


@pytest.mark.asyncio
async def test_supabase_duplicate_is_quarantined_instead_of_conflicting(cutover):
    """A second copy already under "default" next to the re-attributed row
    (unique (workspace_id, event_id)) is hidden, not a 409."""
    fake, _client, _db, stores = cutover
    await _seed(stores)
    await fix.run(stores, apply=True)
    await stores.activity.insert_one(_event("L1-inbox", "default", "ai", "inbox", "in-a"))   # re-leaked copy
    report = await fix.run(stores, apply=True)
    assert fix.exit_code(report) == 0, fix.render(report)
    assert report.activity.reasons["duplicate_of_reattributed_row"] == 1
    assert sorted(r["workspace_id"] for r in _sb(fake, "L1-inbox")) == sorted(["ws_a", Q])


class _TripwireDB:
    def __init__(self):
        self.log: List[Any] = []

    def __getitem__(self, name: str) -> TripwireMongo:
        return TripwireMongo(name, self.log)


@pytest.mark.asyncio
async def test_after_mirrors_off_only_supabase_is_touched(monkeypatch):
    """Runbook 6b and later: Supabase only, Mongo never touched."""
    fake = supabase_only(monkeypatch, mirror=False)
    db = _TripwireDB()
    stores = fix.Stores.build(db)
    await _seed(stores)
    report = await fix.run(stores, apply=True)
    assert fix.exit_code(report) == 0, fix.render(report)
    assert report.flags["activity_events"]["mongo_copy"] is False and "mongo" not in report.activity.moves
    assert db.log == []
    for eid, (*_x, ws, _sim) in LEAKED.items():
        assert [r["workspace_id"] for r in _sb(fake, eid)] == [ws]


# ── rows written after the fix are never touched ────────────────────────

@pytest.fixture
def fixed_log_activity(cutover, monkeypatch):
    """The real, fixed server.log_activity, writing through the script's stores."""
    _fake, _client, _db, stores = cutover
    _import_stubs.install()
    import server

    monkeypatch.setattr(server, "activity_col", stores.activity)
    monkeypatch.setattr(server, "business_profile_col", stores.business_profile)
    assert server.ACTIVITY_WORKSPACE_EXPLICIT == fix.WRITTEN_AFTER_FIX
    return server.log_activity


async def _default_members_work(log_activity) -> List[str]:
    """What the default workspace's own members write after the deploy —
    shapes the script would otherwise quarantine or re-attribute."""
    written = [
        await log_activity("ai", "Batch triage complete", "Processed 3 message(s)", None, "inbox", workspace_id="default"),
        await log_activity("system", "Batch approval complete", "Approved 2", None, "inbox", workspace_id="default"),
        await log_activity("content", "Content generated", "AI generated 2 content item(s)", None, "content",
                           workspace_id="default"),
        await log_activity("system", "Simulation data generated", "Sandbox ready", "simulation", "system",
                           workspace_id="default"),
        # Entity deleted since.
        await log_activity("calendar", "Event created", "New event: Standup", "ev-deleted-since", "calendar",
                           workspace_id="default"),
        # related_id of ANOTHER workspace's item (caller-supplied input, e.g.
        # quantro.review.flag through the Actions API): the event still
        # belongs to the caller's workspace and must never be moved into ws_a.
        await log_activity("inbox", "Flagged for review (manual)", "INJECTED text for ws_a's feed", "in-a", "inbox",
                           workspace_id="default"),
    ]
    return [e["event_id"] for e in written]


@pytest.mark.asyncio
async def test_events_written_after_the_fix_are_never_moved(cutover, fixed_log_activity):
    """Findings 1/2/6: every later run (the gate is >= 24 h after the deploy)
    must leave the default workspace's own post-fix events where they are,
    while still repairing the pre-fix rows."""
    fake, _client, db, stores = cutover
    await _seed(stores)
    assert fix.exit_code(await fix.run(stores, apply=True)) == 0          # today's step 4b
    own = await _default_members_work(fixed_log_activity)

    verify = await fix.run(stores, apply=False)                           # the gate's step 4b
    assert fix.exit_code(verify, verify=True) == 0, fix.render(verify, verify=True)
    assert verify.activity.scanned["supabase_written_after_fix"] == len(own)
    assert verify.activity.scanned["mongo_written_after_fix"] == len(own)
    report = await fix.run(stores, apply=True)
    assert fix.exit_code(report) == 0 and report.applied == 0, fix.render(report)
    for eid in own:
        assert [r["workspace_id"] for r in _sb(fake, eid)] == ["default"], eid
        assert [d["workspace_id"] for d in _mongo(db, eid)] == ["default"], eid
        assert _sb(fake, eid)[0]["extra"][fix.WRITTEN_AFTER_FIX] is True
    assert not [r for r in fake.rows["activity_events"] if "INJECTED" in r["description"] and r["workspace_id"] == "ws_a"]
    # The pre-fix rows were repaired all the same.
    assert [r["workspace_id"] for r in _sb(fake, "L1-inbox")] == ["ws_a"]


@pytest.mark.asyncio
async def test_gate_before_6b_is_stable_while_default_members_work(cutover, fixed_log_activity):
    """The gate: backfill --apply, 4b --apply, (default members keep working),
    4b --verify and backfill --verify all exit 0 — the gate does not flap."""
    fake, client, _db, stores = cutover
    await _seed(stores)
    source = bf.MongoSource("unused", "quantro_os", client=client)
    assert bf.exit_code(await bf.run(source, fake.request, apply=True)) == 0
    assert fix.exit_code(await fix.run(stores, apply=True)) == 0
    await _default_members_work(fixed_log_activity)

    verify = await fix.run(stores, apply=False)
    assert fix.exit_code(verify, verify=True) == 0, fix.render(verify, verify=True)
    bf_verify = await bf.run(source, fake.request, apply=False)
    assert bf.exit_code(bf_verify, verify=True) == 0, bf.render(bf_verify, verify=True)


@pytest.mark.asyncio
async def test_default_owner_keeps_their_feed_after_using_the_fixed_endpoints(app):  # noqa: F811
    """End to end on the real app: the default workspace's owner generates a
    sandbox, triages and generates content; the repair moves nothing."""
    fake, server, RealAsyncClient = app
    await _tenants(server)
    await server.inbox_col.insert_one({"workspace_id": "default", "inbox_id": "d-own", "from_name": "Own Lead",
                                       "from_email": "lead@own.example", "subject": "own", "body": "b",
                                       "status": "new", "is_simulation": True})
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=True)
    async with RealAsyncClient(transport=transport, base_url="http://test") as http:
        c = Client(server, http)
        d = lambda method, url, **kw: c.call("u-default", "default", method, url, **kw)  # noqa: E731
        assert (await d("POST", "/api/simulation/generate")).status_code == 200
        assert (await d("POST", "/api/inbox/batch-analyze", json={"inbox_ids": ["d-own"]})).status_code == 200
        assert (await d("POST", "/api/content/generate", json={"prompt": "launch", "type": "social_post"})).status_code == 200
        before = {e["title"] for e in (await d("GET", "/api/activity", params={"limit": 100})).json()}
        assert {"Simulation data generated", "Batch triage complete", "Content generated"} <= before

        stores = fix.Stores.build(server.db)
        verify = await fix.run(stores, apply=False)
        assert fix.exit_code(verify, verify=True) == 0, fix.render(verify, verify=True)
        applied = await fix.run(stores, apply=True)
        assert fix.exit_code(applied) == 0 and applied.applied == 0, fix.render(applied)
        after = {e["title"] for e in (await d("GET", "/api/activity", params={"limit": 100})).json()}
    assert after == before
    assert not [r for r in fake.rows["activity_events"] if r["workspace_id"] == fix.QUARANTINE_WORKSPACE_ID]


@pytest.mark.asyncio
async def test_entity_without_a_workspace_is_unresolved_not_default(cutover):
    """An entity that has no workspace_id was written by the same bug class:
    its event is quarantined, not kept in "default"."""
    fake, _client, db, stores = cutover
    await _seed(stores)
    await db["inbox_items"].insert_one({"inbox_id": "in-untagged", "subject": SECRET})   # Mongo only, no workspace
    await stores.activity.insert_one(_event("L11-untagged", "default", "ai", "inbox", "in-untagged"))
    report = await fix.run(stores, apply=True)
    assert fix.exit_code(report) == 0, fix.render(report)
    assert report.activity.reasons["related_entity_without_workspace"] == 1
    assert [r["workspace_id"] for r in _sb(fake, "L11-untagged")] == [Q]


# ── template-generated content (findings 4 and 5) ───────────────────────

TPL_TITLE = "ACME renewal offer - Jane Victim"


async def _template_seed(stores: fix.Stores) -> None:
    for ws, sim in (("default", True), ("ws_a", False)):
        await stores.workspaces.insert_one({"workspace_id": ws, "name": ws})
        await stores.business_profile.insert_one({"workspace_id": ws, "simulation_mode": sim})
    await stores.templates.insert_one({"template_id": "tpl-a", "workspace_id": "ws_a", "name": "ACME renewal offer",
                                       "template_type": "email", "body_template": "Hi {{contact_name}}"})
    await stores.templates.insert_one({"template_id": "tpl-d", "workspace_id": "default", "name": "Own template",
                                       "template_type": "email", "body_template": "Hi"})


def _tpl_item(cid: str, template_id: str, ws: Any) -> Dict[str, Any]:
    """What POST /api/templates/{id}/generate stored before the fixes: no
    workspace_id (``ws`` models the startup re-tag to "default")."""
    item = {"content_id": cid, "type": "email_draft", "title": TPL_TITLE, "status": "draft",
            "content": {"subject": "Renewal", "body": "Dear Jane, ... ACME pricing ..."},
            "created_by": "ai_template", "template_id": template_id, "created_at": "2026-09-20T10:00:00+00:00"}
    if ws is not None:
        item.update(workspace_id=ws, is_simulation=True)     # startup repairs: "default" + sandbox flag
    return item


def _content(fake, cid: str) -> List[str]:
    return sorted(r["workspace_id"] for r in fake.rows["content_items"] if r["content_id"] == cid)


@pytest.mark.asyncio
@pytest.mark.parametrize("item_ws,template_id,event_ws,item_target", [
    (None, "tpl-a", "ws_a", "ws_a"),                 # untagged item (Mongo only)
    ("default", "tpl-a", "ws_a", "ws_a"),            # startup re-tagged item
    (None, "tpl-gone", Q, Q),                        # template deleted since: unattributable
    (None, "tpl-d", "default", "default"),           # the default workspace's own item
], ids=["untagged_item", "startup_retagged_item", "template_gone", "template_in_default"])
async def test_content_from_template_rows_follow_the_template(cutover, item_ws, template_id, event_ws, item_target):
    """Finding 4: the "Content from template" row and its item go to the
    template's workspace — never kept in "default" because the item itself
    was put there by the same bug class."""
    fake, client, db, stores = cutover
    await _template_seed(stores)
    await db["content_items"].insert_one(_tpl_item("ci-a", template_id, item_ws))
    await stores.activity.insert_one(_event("L-tpl", "default", "content", "content", "ci-a"))

    report = await fix.run(stores, apply=True)
    assert fix.exit_code(report) == 0, fix.render(report)
    assert [r["workspace_id"] for r in _sb(fake, "L-tpl")] == [event_ws], fix.render(report)
    assert [d.get("workspace_id") for d in db["content_items"].docs] == [item_target]
    assert TPL_TITLE not in fix.render(report) + json.dumps(report.as_dict(), default=str)

    # The backfill then copies the item into its workspace only.
    await _gate(fake, client)
    assert _content(fake, "ci-a") == [item_target]


@pytest.mark.asyncio
async def test_template_content_leaked_into_default_is_repaired_in_either_order(cutover):
    """Finding 5: tenant items already under "default" (an older backfill put
    a copy in Supabase, the startup repair re-tagged Mongo) and Mongo-only
    untagged ones end up in the template's workspace, whether 4b runs before
    or after the backfill's --apply; the gate converges and the default
    workspace's content list never shows them."""
    fake, client, db, stores = cutover
    await _template_seed(stores)
    await stores.content_items.insert_one(_tpl_item("ci-both", "tpl-a", "default"))   # Supabase + Mongo, "default"
    await db["content_items"].insert_one(_tpl_item("ci-mongo", "tpl-a", None))         # Mongo only, untagged
    await stores.content_items.insert_one({**_tpl_item("ci-own", "tpl-d", "default"), "title": "Own"})
    source = bf.MongoSource("unused", "quantro_os", client=client)

    # Backfill first (step 4): it resolves the template itself — nothing new
    # lands under "default" (the pre-existing Supabase copy is 4b's job).
    first = await bf.run(source, fake.request, apply=True)
    assert bf.exit_code(first) == 0, bf.render(first)
    assert _by(first, "content_items")["notes"]["workspace_from_template"] == 2
    assert _content(fake, "ci-mongo") == ["ws_a"]
    assert _content(fake, "ci-both") == ["default", "ws_a"]

    report = await fix.run(stores, apply=True)                                          # step 4b
    assert fix.exit_code(report) == 0, fix.render(report)
    assert report.content.reasons["duplicate_of_reattributed_row"] == 1
    assert _content(fake, "ci-both") == sorted([Q, "ws_a"])                             # stale copy hidden
    assert _content(fake, "ci-own") == ["default"]
    verify = await fix.run(stores, apply=False)
    assert fix.exit_code(verify, verify=True) == 0, fix.render(verify, verify=True)
    await _gate(fake, client)
    visible = await stores.content_items.find({"workspace_id": "default"}).to_list(None)
    assert [v["content_id"] for v in visible] == ["ci-own"]


@pytest.mark.asyncio
async def test_template_content_repaired_before_the_backfill_moves_both_copies(cutover):
    fake, client, db, stores = cutover
    await _template_seed(stores)
    await stores.content_items.insert_one(_tpl_item("ci-both", "tpl-a", "default"))
    await db["content_items"].insert_one(_tpl_item("ci-mongo", "tpl-a", None))

    dry = await fix.run(stores, apply=False)
    assert dict(dry.content.decisions) == {"reattribute": 2}
    assert dry.content.moves == {"supabase": 1, "mongo": 2}
    report = await fix.run(stores, apply=True)
    assert fix.exit_code(report) == 0, fix.render(report)
    assert {d["content_id"]: d["workspace_id"] for d in db["content_items"].docs} == {"ci-both": "ws_a", "ci-mongo": "ws_a"}
    assert _content(fake, "ci-both") == ["ws_a"]
    applied = await _gate(fake, client)
    assert _by(applied, "content_items")["insert_ids"] == ["ci-mongo"]
    assert _content(fake, "ci-mongo") == ["ws_a"] and _content(fake, "ci-both") == ["ws_a"]


# ── provenance (finding 7) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_every_moved_row_keeps_its_provenance_in_both_stores(cutover):
    """The report lists at most 20 ids per bucket; the rows themselves say
    which events sat under "default" (no content, only workspace ids)."""
    fake, client, db, stores = cutover
    await _seed(stores)
    extra = [f"X{i:02d}-inbox" for i in range(25)]
    for eid in extra:
        await stores.activity.insert_one(_event(eid, "default", "ai", "inbox", "in-a"))
    moved = set(extra) | set(LEAKED)

    report = await fix.run(stores, apply=True)
    assert fix.exit_code(report) == 0, fix.render(report)
    assert len(report.activity.ids["reattribute"]) == fix.MAX_IDS_PRINTED < report.activity.decisions["reattribute"]
    for eid in moved:
        (row,) = _sb(fake, eid)
        (doc,) = _mongo(db, eid)
        prov = row["extra"][fix.PROVENANCE]
        assert prov["from"] == "default" and prov["to"] == row["workspace_id"] and prov["reason"], eid
        assert doc[fix.PROVENANCE] == prov, eid                  # the mirror copy says the same
    marked = {r["event_id"] for r in fake.rows["activity_events"] if fix.PROVENANCE in (r.get("extra") or {})}
    assert marked == moved                                       # kept rows carry nothing

    # A later move (the entity turns up) keeps where the row came from.
    await stores.inbox.insert_one({"inbox_id": "in-deleted", "workspace_id": "ws_b", "is_simulation": False})
    assert fix.exit_code(await fix.run(stores, apply=True)) == 0
    prov = _sb(fake, "L9-gone")[0]["extra"][fix.PROVENANCE]
    assert (prov["from"], prov["to"], prov["reason"]) == ("default", "ws_b", "related_inbox")
    await _gate(fake, client)                                    # the provenance field does not trip the backfill


# ── the owner's manual revert sticks (finding 8) ────────────────────────

def _owner_keeps_in_default(fake, eid: str, *, tag: bool = True) -> None:
    """The runbook's SQL: back to "default" (+ the review tag)."""
    for r in fake.rows["activity_events"]:
        if r["workspace_id"] == Q and r["event_id"] == eid:
            r["workspace_id"] = "default"
            if tag:
                r["extra"] = {**(r.get("extra") or {}), fix.REVIEW: fix.KEPT_DEFAULT}


@pytest.mark.asyncio
async def test_hand_restored_rows_stay_in_default_after_6b(monkeypatch):
    fake = supabase_only(monkeypatch, mirror=False)
    stores = fix.Stores.build(_TripwireDB())
    await _seed(stores)
    assert fix.exit_code(await fix.run(stores, apply=True)) == 0
    assert _sb(fake, "L8-sim")[0]["workspace_id"] == Q and _sb(fake, "L7-batch")[0]["workspace_id"] == Q

    _owner_keeps_in_default(fake, "L8-sim")
    verify = await fix.run(stores, apply=False)
    assert fix.exit_code(verify, verify=True) == 0, fix.render(verify, verify=True)
    assert verify.activity.reasons["kept_default_by_owner"] == 1
    again = await fix.run(stores, apply=True)
    assert again.applied == 0 and _sb(fake, "L8-sim")[0]["workspace_id"] == "default"

    # Without the tag the next run cannot tell the owner's decision apart
    # from a leaked row — the runbook's SQL always sets it.
    _owner_keeps_in_default(fake, "L7-batch", tag=False)
    assert fix.exit_code(await fix.run(stores, apply=False), verify=True) == 1


@pytest.mark.asyncio
async def test_hand_restore_while_mirrored_is_completed_by_the_next_apply(cutover):
    fake, client, db, stores = cutover
    await _seed(stores)
    assert fix.exit_code(await fix.run(stores, apply=True)) == 0
    _owner_keeps_in_default(fake, "L8-sim")                      # Supabase only; the Mongo copy is still in quarantine
    assert fix.exit_code(await fix.run(stores, apply=True)) == 0
    assert [d["workspace_id"] for d in _mongo(db, "L8-sim")] == ["default"]
    assert fix.exit_code(await fix.run(stores, apply=False), verify=True) == 0
    await _gate(fake, client)
    assert [r["workspace_id"] for r in _sb(fake, "L8-sim")] == ["default"]


# ── CLI ─────────────────────────────────────────────────────────────────

def test_cli_requires_fly_env(monkeypatch, capsys):
    for k in ("MONGO_URL", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert fix.main([]) == 2
    assert "missing env" in capsys.readouterr().err


def test_mongo_url_needed_only_while_a_flag_routes_to_mongo(monkeypatch):
    supabase_only(monkeypatch, mirror=True)
    monkeypatch.delenv("MONGO_URL", raising=False)
    assert fix._missing_env() == ["MONGO_URL"]
    supabase_only(monkeypatch, mirror=False)        # after 6b (every primary Supabase)
    assert fix._missing_env() == []


def test_verify_and_apply_are_exclusive():
    with pytest.raises(SystemExit):
        fix.main(["--apply", "--verify"])
