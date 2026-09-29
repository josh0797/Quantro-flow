"""Calendar rows whose Mongo and Supabase copies disagree, across runbook
step 6b (every *_MONGO_MIRROR off).

Production (2026-09-29, step 6a): a Google sync logged
``MONGO_ONLY calendar: row only in Mongo (event_id=…)`` for 11 events while
the backfill dry run reported every calendar row ``same`` (day 1:
``matched_by_alt_key=41``). Two shapes of disagreement exist:

* **legacy provider** — same ``event_id``, but Supabase holds
  ``external_provider='internal'`` with the provider's id: konta
  20260919010000 set ``internal`` on every row without a provider (the
  shadows of synced events had lost their Google id), and the backfill's
  ``fill`` policy later filled ``external_event_id`` but kept the non-NULL
  ``internal``. The sync looks rows up by (workspace, provider, external id),
  misses them in Supabase and, while mirrored, finds them in Mongo — that is
  the MONGO_ONLY line, and the backfill matches them by the alt key
  (workspace, event_id) and reports them ``same``. With the mirror off the
  sync inserted a DUPLICATE per event and the stale copy never got another
  update.
* **event_id differs** — same external identity, different ``event_id``.
  Harmless: the sync resolves by identity and Supabase's id is the one every
  list (and so every client) has had since 6a.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pytest

import product_domain_store as pds
from fake_motor import FakeMotorCollection
from scripts import mongo_to_supabase as bf
from sb_rest import SupabaseStoreError
from storage_helpers import TripwireMongo, supabase_only

WS = "ws_a"
X = "gcal-abc123"
E = "88107986-c41c-4610-92b4-5b8e2527d6e1"      # same id in both stores (legacy-provider shape)
E_MONGO = "mongo-only-uuid"                      # Mongo's id of an event…
E_SB = "supabase-own-uuid"                       # …whose Supabase copy got its own uuid
T1 = "2026-09-30T15:00:00+00:00"
T2 = "2026-09-30T16:00:00+00:00"
SOURCE = {"google": "google_calendar", "microsoft": "outlook_calendar"}


def mongo_doc(event_id: str, ext: str = X, provider: str = "google", title: str = "Standup") -> Dict[str, Any]:
    return {"_id": f"65f1{abs(hash((event_id, ext))) % 10**20:020d}", "workspace_id": WS, "event_id": event_id,
            "external_provider": provider, "external_event_id": ext, "title": title, "description": "",
            "start_time": T1, "end_time": T2, "location": "", "attendees": [], "status": "confirmed",
            "source": SOURCE[provider], "external_url": "https://cal/x", "is_real": True,
            "is_simulation": False, "hidden_by_real": False}


def sb_row(event_id: str, provider: Optional[str], ext: Optional[str], title: str = "Standup",
           source: str = "google_calendar") -> Dict[str, Any]:
    return {"id": f"pk-{event_id}", "workspace_id": WS, "event_id": event_id, "external_provider": provider,
            "external_event_id": ext, "google_event_id": ext if source == "google_calendar" else None,
            "title": title, "description": "", "start_time": T1, "end_time": T2, "location": "",
            "attendees": [], "status": "confirmed", "source": source, "external_url": "https://cal/x",
            "is_real": True, "is_simulation": False, "hidden_by_real": False, "extra": {},
            "created_at": "2026-09-18T00:00:00+00:00", "updated_at": "2026-09-18T00:00:00+00:00"}


async def sync(cal: Any, title: str = "Standup", *, ext: str = X, provider: str = "google") -> Dict[str, Any]:
    """Exactly what POST /api/integrations/google/sync does per event."""
    now = datetime.now(timezone.utc)
    canonical = pds.canonical_calendar_write(
        workspace_id=WS, event_id=f"fresh-{title}", external_provider=provider, external_event_id=ext,
        title=title, description="", start_time=T1, end_time=T2, location="", attendees=[],
        status="confirmed", source=SOURCE[provider], external_url="https://cal/x", is_simulation=False,
        synced_at=now, updated_at=now, extra={"is_real": True},
    )
    return await pds.upsert_calendar_external_event(cal, workspace_id=WS, provider=provider,
                                                    external_event_id=ext, canonical=canonical, now=now)


def recorded(mongo: FakeMotorCollection) -> List[Dict[str, Any]]:
    queries: List[Dict[str, Any]] = []
    real = mongo.find_one

    async def find_one(query=None, projection=None, *a, **k):
        queries.append(dict(query or {}))
        return await real(query, projection, *a, **k)

    mongo.find_one = find_one  # type: ignore[method-assign]
    return queries


def rows(fake) -> List[tuple]:
    return sorted((r["event_id"], r["external_provider"], r["external_event_id"], r["title"])
                  for r in fake.rows["calendar_events"])


class Source:
    """Mongo calendar collection as the backfill streams it."""

    def __init__(self, docs: List[Dict[str, Any]]):
        self.docs = docs

    async def collection_names(self) -> List[str]:
        return ["calendar_events"]

    async def batches(self, name: str, size: int = 500):
        yield [dict(d) for d in self.docs]


def calendar_report(report: Dict[str, Any]) -> Dict[str, Any]:
    return next(d for d in report["datasets"] if d["dataset"] == "calendar_events")


# ── Q1: where the MONGO_ONLY line comes from ─────────────────────────────

@pytest.mark.asyncio
async def test_mongo_only_line_is_the_sync_identity_lookup_answered_by_the_mirror(monkeypatch, caplog):
    """6a (Supabase primary, mirror on). The sync's only read is
    find_calendar_event_for_external_sync → DualWriteCollection.find_one on
    (workspace_id, external_provider, external_event_id); when Supabase has no
    row for that identity the mirror answers and the line names the MONGO
    row's event_id — which Supabase may well have under another identity."""
    fake = supabase_only(monkeypatch, mirror=True)
    mongo = FakeMotorCollection("calendar_events")
    mongo.docs.append(mongo_doc(E))
    # Same event_id in Supabase, but an identity no lookup can tie to X.
    fake.rows["calendar_events"].append(sb_row(E, "google", "gcal-some-other-id"))
    queries = recorded(mongo)
    caplog.set_level(logging.WARNING, logger="quantro.product_domain.store")

    await sync(pds.wrap_calendar_col(mongo))

    assert queries == [{"workspace_id": WS, "external_provider": "google", "external_event_id": X}]
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("MONGO_ONLY calendar")]
    assert len(lines) == 1
    assert f"event_id={E}" in lines[0]
    assert "lookup on external_event_id,external_provider,workspace_id" in lines[0]
    assert any(r["event_id"] == E for r in fake.rows["calendar_events"])  # not "only in Mongo" by event_id


@pytest.mark.asyncio
async def test_legacy_provider_rows_no_longer_reach_the_mirror(monkeypatch, caplog):
    """The production shape: Supabase (internal, X, E) vs Mongo (google, X, E).
    Supabase now resolves it itself and repairs it in place; before, the
    lookup fell through to Mongo (MONGO_ONLY) and a changed event hit a 409
    on Supabase, so the UI (served from Supabase since 6a) kept the old
    title/time while only Mongo got Google's change."""
    fake = supabase_only(monkeypatch, mirror=True)
    mongo = FakeMotorCollection("calendar_events")
    mongo.docs.append(mongo_doc(E))
    fake.rows["calendar_events"].append(sb_row(E, "internal", X))
    queries = recorded(mongo)
    caplog.set_level(logging.WARNING, logger="quantro.product_domain.store")
    cal = pds.wrap_calendar_col(mongo)

    assert (await sync(cal, "Renamed")) == {"event_id": E, "outcome": "updated"}

    assert queries == []
    assert not [r for r in caplog.records if "MONGO_ONLY" in r.getMessage() or "409" in r.getMessage()]
    assert rows(fake) == [(E, "google", X, "Renamed")]
    (m,) = mongo.docs
    assert (m["event_id"], m["external_provider"], m["title"]) == (E, "google", "Renamed")  # mirror kept in step


# ── why the backfill said "same" — and now repairs it ────────────────────

@pytest.mark.asyncio
async def test_backfill_fill_repairs_the_migration_inferred_provider(monkeypatch):
    fake = supabase_only(monkeypatch, mirror=True)          # 6a: calendar primary supabase → policy fill
    fake.rows["calendar_events"] += [
        sb_row(E, "internal", X),                            # fill already filled the id, kept 'internal'
        sb_row("e-null", "internal", None),                  # straight out of 20260919010000
        sb_row("e-int", "internal", None, title="Manual", source="manual"),   # a genuine internal event
    ]
    source = Source([
        mongo_doc(E),
        mongo_doc("e-null", ext="gcal-null"),
        {**mongo_doc("e-int", title="Manual"), "external_provider": "internal", "external_event_id": None,
         "source": "manual", "is_real": None},
    ])

    dry = await bf.run(source, fake.request, apply=False, only={"calendar_events"})
    d = calendar_report(dry)
    assert d["policy"] == "fill"
    # Before this fix: update=1 (e-null) and E reported "same" — the gate passed with E still broken.
    assert (d["insert"], d["update"], d["error"]) == (0, 2, 0)
    assert d["notes"]["matched_by_alt_key"] == 2
    assert sorted(d["alt_key_ids"]) == [E, "e-null"]
    assert f"matched_by_alt_key: {E}" in bf.render(dry)
    assert "alt_key_unresolved" not in d["notes"] and "REVIEW" not in bf.render(dry)   # the apply fixes them
    assert bf.exit_code(dry, verify=True) == 1

    applied = await bf.run(source, fake.request, apply=True, only={"calendar_events"})
    assert bf.exit_code(applied) == 0, bf.render(applied)
    assert rows(fake) == [
        (E, "google", X, "Standup"),
        ("e-int", "internal", None, "Manual"),
        ("e-null", "google", "gcal-null", "Standup"),
    ]
    again = await bf.run(source, fake.request, apply=False, only={"calendar_events"})
    assert bf.exit_code(again, verify=True) == 0, bf.render(again, verify=True)
    assert "matched_by_alt_key" not in calendar_report(again)["notes"]


@pytest.mark.asyncio
async def test_verify_fails_while_supabase_holds_an_event_under_another_identity(monkeypatch):
    """A shape the backfill cannot decide (Supabase: another provider id under
    the same event_id) is reported ``same`` by fill — the gate must not pass
    on it, since the sync would insert that event again after 6b."""
    fake = supabase_only(monkeypatch, mirror=True)
    fake.rows["calendar_events"].append(sb_row(E, "google", "gcal-some-other-id"))
    source = Source([mongo_doc(E)])

    applied = await bf.run(source, fake.request, apply=True, only={"calendar_events"})
    d = calendar_report(applied)
    assert (d["insert"], d["update"], d["same"]) == (0, 0, 1) and d["notes"]["alt_key_unresolved"] == 1
    assert rows(fake) == [(E, "google", "gcal-some-other-id", "Standup")]   # fill never overwrites it
    verify = await bf.run(source, fake.request, apply=False, only={"calendar_events"})
    assert bf.exit_code(verify, verify=True) == 1
    text = bf.render(verify, verify=True)
    assert f"matched_by_alt_key: {E}" in text and "REVIEW: calendar_events has 1 row(s)" in text


# ── Q2: after 6b (mirror off, Mongo never touched) ───────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["google", "microsoft"])
async def test_6b_resync_of_a_legacy_provider_row_updates_it_in_place(monkeypatch, provider):
    """(a) no duplicate, (b) no error, (c) Google's change is applied, and the
    row keeps its event_id. Before the fix: a second row with a fresh uuid,
    the change landed there, the original stayed stale and listed twice."""
    fake = supabase_only(monkeypatch)
    fake.rows["calendar_events"].append(sb_row(E, "internal", X, source=SOURCE[provider]))
    cal = pds.wrap_calendar_col(TripwireMongo("calendar_events"))

    assert await sync(cal, provider=provider) == {"event_id": E, "outcome": "updated"}   # identity repaired
    assert rows(fake) == [(E, provider, X, "Standup")]
    assert (await sync(cal, provider=provider))["outcome"] == "unchanged"
    assert await sync(cal, "Moved to 5pm", provider=provider) == {"event_id": E, "outcome": "updated"}
    assert rows(fake) == [(E, provider, X, "Moved to 5pm")]


@pytest.mark.asyncio
async def test_6b_resync_when_the_event_ids_differ_is_safe(monkeypatch):
    """Same identity, Supabase has its own uuid: the sync resolves by identity
    (no duplicate, no error, updates applied) and keeps Supabase's id; only
    Mongo's id — which no list has returned since 6a — is unknown."""
    fake = supabase_only(monkeypatch)
    fake.rows["calendar_events"].append(sb_row(E_SB, "google", X))
    cal = pds.wrap_calendar_col(TripwireMongo("calendar_events"))

    assert await sync(cal) == {"event_id": E_SB, "outcome": "unchanged"}
    assert await sync(cal, "Renamed") == {"event_id": E_SB, "outcome": "updated"}
    assert rows(fake) == [(E_SB, "google", X, "Renamed")]
    assert (await cal.delete_one({"event_id": E_MONGO, "workspace_id": WS})).deleted_count == 0
    assert (await cal.delete_one({"event_id": E_SB, "workspace_id": WS})).deleted_count == 1


@pytest.mark.asyncio
async def test_6b_supabase_read_failure_fails_the_sync_instead_of_inserting(monkeypatch):
    fake = supabase_only(monkeypatch)
    fake.drop_table("calendar_events")
    cal = pds.wrap_calendar_col(TripwireMongo("calendar_events"))
    with pytest.raises(SupabaseStoreError):
        await sync(cal)


@pytest.fixture
def app_6b(monkeypatch):
    import _import_stubs
    _import_stubs.install()
    fake = supabase_only(monkeypatch)                         # every mirror off
    monkeypatch.setenv("MONGO_URL", "mongodb://tripwire.invalid:27017")
    import mongo_legacy
    import server

    def no_connect():
        raise AssertionError("Mongo client requested after 6b")

    monkeypatch.setattr(mongo_legacy, "_get_client", no_connect)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", fake.async_client_factory(real_async_client))
    yield fake, server, real_async_client
    server.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_6b_google_sync_route_then_list_and_delete_by_the_listed_id(app_6b, monkeypatch):
    """(d) End to end through the real routes: POST /api/integrations/google/sync,
    GET /api/calendar, DELETE /api/calendar/{event_id} — the ids a client gets
    from the list open/delete exactly one row, and no event is listed twice."""
    fake, server, RealAsyncClient = app_6b
    await server.workspaces_col.insert_one({"workspace_id": WS, "name": "A", "owner_user_id": "u1", "claimed": True})
    await server.workspace_members_col.insert_one({"workspace_id": WS, "user_id": "u1", "role": "owner"})
    fake.rows["calendar_events"] += [sb_row(E, "internal", X), sb_row(E_SB, "google", "gcal-2")]

    feed = [
        {"gcal_id": X, "title": "Standup (moved)", "description": "", "location": "", "start_iso": T1,
         "end_iso": T2, "attendees": [], "html_link": "https://cal/x", "status": "confirmed"},
        {"gcal_id": "gcal-2", "title": "Review (renamed)", "description": "", "location": "", "start_iso": T1,
         "end_iso": T2, "attendees": [], "html_link": "https://cal/x", "status": "confirmed"},
    ]

    async def creds(_ws):
        return object(), {"workspace_id": WS}

    monkeypatch.setattr(server, "_load_google_credentials", creds)
    monkeypatch.setattr(server.goog, "fetch_recent_gmail", lambda *_a, **_k: [])
    monkeypatch.setattr(server.goog, "fetch_upcoming_calendar", lambda *_a, **_k: feed)
    user = server.User(user_id="u1", email="o@example.com", name="O", current_workspace_id=WS, access_token="t")
    server.app.dependency_overrides[server.get_current_user] = lambda: user

    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=True)
    headers = {"X-Workspace-Id": WS, "Authorization": "Bearer t"}
    async with RealAsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(2):                                   # a re-sync must not add rows either
            r = await client.post("/api/integrations/google/sync", headers=headers)
            assert r.status_code == 200, r.text
            assert r.json()["counts"]["events"] == 2
        listed = (await client.get("/api/calendar", headers=headers)).json()
        assert sorted((e["event_id"], e["title"]) for e in listed) == [
            (E, "Standup (moved)"), (E_SB, "Review (renamed)"),
        ]
        assert (await client.delete(f"/api/calendar/{E_MONGO}", headers=headers)).status_code == 404
        for e in listed:
            assert (await client.delete(f"/api/calendar/{e['event_id']}", headers=headers)).status_code == 200
    assert fake.rows["calendar_events"] == []


# ── gate before 6b: Supabase rows no sync could keep ─────────────────────
# Before these fixes the gate (--verify + the runbook's SQL check) passed on
# every shape below, and 6b then listed the event twice with one copy frozen.

LIVE = {"workspace_id": WS, "is_simulation": {"$ne": True}, "hidden_by_real": {"$ne": True}}   # live-mode list
GOOGLE_DISCONNECT = {"workspace_id": WS, "is_real": True, "source": "google_calendar"}         # server.py


def sql_legacy_provider(fake) -> int:
    """Runbook gate, read-only query 1 (expected 0)."""
    return sum(1 for r in fake.rows["calendar_events"]
               if r.get("external_event_id") is not None
               and (r.get("external_provider") or "internal") == "internal")


def sql_no_external_id(fake) -> int:
    """Runbook gate, read-only query 2 (expected 0)."""
    return sum(1 for r in fake.rows["calendar_events"]
               if r.get("source") in ("google_calendar", "outlook_calendar")
               and r.get("is_simulation") is False and r.get("external_event_id") is None)


def legacy_gcal_doc(event_id: str, title: str) -> Dict[str, Any]:
    """A pre-canonical Mongo doc of a synced Google event (``id`` + ``gcal_id``)."""
    return {"_id": "65f100000000000000000011", "workspace_id": WS, "id": event_id, "gcal_id": X,
            "source": "google_calendar", "title": title, "start": T1, "end": T2, "attendees": [],
            "status": "confirmed", "is_real": True, "is_simulation": False,
            "synced_at": "2026-09-18T00:00:00+00:00"}


def mirrors_off(monkeypatch, fake) -> Tuple[Any, Any]:
    """Runbook 6b over the same Supabase rows: every mirror off, Mongo a
    tripwire. Returns (the 6b fake, the calendar collection)."""
    fake6b = supabase_only(monkeypatch)
    fake6b.rows["calendar_events"] = [dict(r) for r in fake.rows["calendar_events"]]
    return fake6b, pds.wrap_calendar_col(TripwireMongo("calendar_events"))


async def gate(source: Source, fake) -> Dict[str, Any]:
    """Runbook step 4 (--apply) then step 5 (--verify): the verify report."""
    applied = await bf.run(source, fake.request, apply=True, only={"calendar_events"})
    assert bf.exit_code(applied) == 0, bf.render(applied)
    return await bf.run(source, fake.request, apply=False, only={"calendar_events"})


E_LEG, E_CAN = "e-legacy-doc", "e-canonical-doc"


@pytest.mark.asyncio
async def test_backfill_fills_the_supabase_copy_of_an_older_mongo_duplicate(monkeypatch):
    """Mongo holds one Google event twice — the legacy gcal_id doc (E_LEG)
    and the canonical doc beside it (E_CAN, newer) — and Supabase only
    E_LEG's copy, still without the Google id. Pass 1 keeps E_CAN; the
    backfill used to INSERT it next to E_LEG's copy, which nothing reported
    (external id NULL: no alt match, no SQL hit), so 6b listed the event
    twice and a Google disconnect left the stale copy (its is_real NULL)."""
    fake = supabase_only(monkeypatch, mirror=True)
    fake.rows["calendar_events"].append(
        {**sb_row(E_LEG, "internal", None, title="Standup (old title)"), "is_real": None})
    source = Source([legacy_gcal_doc(E_LEG, "Standup (old title)"),
                     {**mongo_doc(E_CAN), "_id": "65f100000000000000000012", "updated_at": T1}])

    dry = await bf.run(source, fake.request, apply=False, only={"calendar_events"})
    d = calendar_report(dry)
    assert (d["insert"], d["update"], d["error"]) == (0, 1, 0)
    assert d["notes"]["mongo_duplicates"] == 1 and d["notes"]["matched_by_older_duplicate"] == 1
    assert d["alt_key_ids"] == [E_CAN] and not d["review_ids"]

    verify = await gate(source, fake)
    assert bf.exit_code(verify, verify=True) == 0, bf.render(verify, verify=True)
    assert rows(fake) == [(E_LEG, "google", X, "Standup (old title)")]   # one row; Supabase's id kept
    assert (sql_legacy_provider(fake), sql_no_external_id(fake)) == (0, 0)

    fake6b, cal = mirrors_off(monkeypatch, fake)
    assert await sync(cal, "Standup (moved)") == {"event_id": E_LEG, "outcome": "updated"}
    listed = await cal.find(dict(LIVE)).to_list(100)
    assert [(e["event_id"], e["title"]) for e in listed] == [(E_LEG, "Standup (moved)")]
    await cal.delete_many(dict(GOOGLE_DISCONNECT))
    assert fake6b.rows["calendar_events"] == []


@pytest.mark.asyncio
async def test_verify_fails_on_an_older_mongo_duplicates_copy_beside_the_synced_row(monkeypatch):
    """Same Mongo pair, but Supabase also holds E_CAN (a 6a sync inserted it:
    it could not find E_LEG's copy, which has no Google id). The backfill
    never deletes, so the gate must fail and name the copy."""
    fake = supabase_only(monkeypatch, mirror=True)
    fake.rows["calendar_events"] += [
        {**sb_row(E_LEG, "internal", None, title="Standup (old title)"), "is_real": None},
        sb_row(E_CAN, "google", X),
    ]
    source = Source([legacy_gcal_doc(E_LEG, "Standup (old title)"),
                     {**mongo_doc(E_CAN), "_id": "65f100000000000000000012", "updated_at": T1}])

    verify = await gate(source, fake)
    d = calendar_report(verify)
    assert (d["insert"], d["update"]) == (0, 0)
    assert d["notes"]["duplicate_shadow"] == 1 and "no_external_id" not in d["notes"]   # reported once
    assert d["review_ids"] == [f"{E_LEG} (duplicate_shadow of {E_CAN})"]
    assert bf.exit_code(verify, verify=True) == 1
    text = bf.render(verify, verify=True)
    assert "REVIEW: calendar_events has 1 row(s) that duplicate an event" in text and "(duplicate_shadow)" in text
    assert sql_no_external_id(fake) == 1                       # the runbook's SQL query sees it too

    # The runbook's remedy (delete the copy by hand) clears the gate.
    fake.rows["calendar_events"] = [r for r in fake.rows["calendar_events"] if r["event_id"] != E_LEG]
    again = await bf.run(source, fake.request, apply=False, only={"calendar_events"})
    assert bf.exit_code(again, verify=True) == 0, bf.render(again, verify=True)


@pytest.mark.asyncio
async def test_backfill_fills_a_legacy_provider_row_whose_event_id_differs_from_mongo(monkeypatch):
    """Supabase (internal, X, e-old), Mongo (google, X, e-new): the key and
    the event_id alt key both miss. The backfill used to insert e-new beside
    e-old (an ordinary ``insert``, --verify exit 0) and the sync, which takes
    the exact identity first, never repaired e-old: listed twice, one frozen."""
    fake = supabase_only(monkeypatch, mirror=True)
    fake.rows["calendar_events"].append(sb_row("e-old", "internal", X))
    source = Source([mongo_doc("e-new")])

    dry = await bf.run(source, fake.request, apply=False, only={"calendar_events"})
    d = calendar_report(dry)
    assert (d["insert"], d["update"]) == (0, 1) and d["alt_key_ids"] == ["e-new"]

    verify = await gate(source, fake)
    assert bf.exit_code(verify, verify=True) == 0, bf.render(verify, verify=True)
    assert rows(fake) == [("e-old", "google", X, "Standup")]
    assert sql_legacy_provider(fake) == 0

    fake6b, cal = mirrors_off(monkeypatch, fake)
    for title in ("Standup (moved)", "Standup (moved again)"):
        assert (await sync(cal, title))["event_id"] == "e-old"
    assert rows(fake6b) == [("e-old", "google", X, "Standup (moved again)")]


@pytest.mark.asyncio
async def test_a_legacy_provider_row_beside_the_synced_row_fails_verify_and_logs_store_drift(monkeypatch, caplog):
    """Both rows already in Supabase: the sync updates the exact one, the
    legacy one can never take the identity (unique index). The runbook used
    to say such a leftover 'does not block 6b: the sync repairs it'."""
    fake = supabase_only(monkeypatch, mirror=True)
    fake.rows["calendar_events"] += [sb_row("e-old", "internal", X), sb_row("e-new", "google", X)]
    source = Source([mongo_doc("e-new")])

    verify = await gate(source, fake)
    d = calendar_report(verify)
    assert d["review_ids"] == ["e-old (duplicate_shadow of e-new)"]
    assert bf.exit_code(verify, verify=True) == 1 and sql_legacy_provider(fake) == 1

    fake6b, cal = mirrors_off(monkeypatch, fake)
    caplog.set_level(logging.WARNING, logger="quantro.product_domain.store")
    assert await sync(cal, "Renamed") == {"event_id": "e-new", "outcome": "updated"}
    assert rows(fake6b) == [("e-new", "google", X, "Renamed"), ("e-old", "internal", X, "Standup")]
    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("STORE_DRIFT calendar")]
    assert "event_id=e-new" in line and "duplicate event_id=e-old" in line and "Renamed" not in line


@pytest.mark.asyncio
async def test_verify_fails_on_calendar_rows_no_sync_can_keep(monkeypatch):
    """Rows the sync can never reach, with or without a Mongo copy (e.g. a
    shadow a Mongo-primary Google disconnect did not delete: is_real NULL).
    --verify and the runbook's two SQL queries agree; demo and internal rows
    are fine."""
    fake = supabase_only(monkeypatch, mirror=True)
    fake.rows["calendar_events"] += [
        sb_row("e-legacy", "internal", "gcal-gone"),                                  # no Mongo copy
        {**sb_row("e-orphan", "internal", None), "is_real": None},                   # no Mongo copy
        {**sb_row("e-demo", "internal", None), "is_simulation": True},              # demo seed
        sb_row("e-manual", "internal", None, title="Manual", source="manual"),       # internal event
        sb_row("e-ok", "google", "gcal-ok"),
    ]
    # A Mongo doc of a synced source without any provider id: inserted, and just as unreachable.
    source = Source([{**mongo_doc("e-mongo-orphan"), "external_provider": None, "external_event_id": None}])

    applied = await bf.run(source, fake.request, apply=True, only={"calendar_events"})
    assert calendar_report(applied)["insert"] == 1 and bf.exit_code(applied) == 0
    verify = await bf.run(source, fake.request, apply=False, only={"calendar_events"})
    d = calendar_report(verify)
    assert (d["insert"], d["update"]) == (0, 0)
    assert (d["notes"]["legacy_provider"], d["notes"]["no_external_id"]) == (1, 2)
    assert sorted(d["review_ids"]) == ["e-legacy (legacy_provider)", "e-mongo-orphan (no_external_id)",
                                       "e-orphan (no_external_id)"]
    assert bf.exit_code(verify, verify=True) == 1
    text = bf.render(verify, verify=True)
    assert "(legacy_provider)." in text and "(no_external_id)." in text
    assert (sql_legacy_provider(fake), sql_no_external_id(fake)) == (1, 2)
