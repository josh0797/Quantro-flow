"""scripts/fix_activity_workspace.py — re-attributes activity rows that leaked
into workspace "default", quarantines what it cannot resolve, never deletes,
prints ids/counts only, and stays safe with the Mongo → Supabase backfill at
every point of the cutover (docs/mongo-exit-runbook.md)."""
from __future__ import annotations

import dataclasses
import json
from typing import Any, Dict, List

import pytest

from fake_motor import FakeMotorClient
from scripts import fix_activity_workspace as fix
from scripts import mongo_to_supabase as bf
from storage_helpers import TripwireMongo, supabase_only
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
    assert dict(report.decisions) == {"keep": 4, "reattribute": 6, "quarantine": 3}
    assert dict(report.reattributed_to) == {"ws_a": 3, "ws_b": 3}
    assert report.moves == {"supabase": 9, "mongo": 9}
    assert report.default_workspace_members == 2
    assert report.scanned["supabase"] == 13 and report.scanned["mongo"] == 13     # O1 (ws_a) not scanned
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
    assert dict(again.decisions) == {"keep": 4, "unattributed": 3}
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
    assert report.decisions["reattribute"] == 1 and report.decisions["restore"] == 1
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
    assert report.reasons["duplicate_of_reattributed_row"] == 1
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
    assert report.flags["activity_mongo_copy"] is False and "mongo" not in report.moves
    assert db.log == []
    for eid, (*_x, ws, _sim) in LEAKED.items():
        assert [r["workspace_id"] for r in _sb(fake, eid)] == [ws]


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
