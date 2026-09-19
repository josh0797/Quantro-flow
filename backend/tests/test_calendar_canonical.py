"""Calendar canonical model — mapping, dual-write shape, dedup key."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

os.environ.setdefault("QUANTRO_CALENDAR_PRIMARY", "mongo")


def test_normalize_legacy_google_shape():
    from product_domain_store import normalize_calendar_doc, mongo_to_sb, CALENDAR_CFG

    doc = {
        "id": "legacy-1",
        "workspace_id": "ws1",
        "gcal_id": "gcal-abc",
        "title": "Meet",
        "start": "2026-09-19T10:00:00Z",
        "end": "2026-09-19T11:00:00Z",
        "html_link": "https://calendar.google.com/event?eid=1",
        "source": "google_calendar",
        "attendees": ["a@b.co"],
    }
    n = normalize_calendar_doc(doc)
    assert n["event_id"] == "legacy-1"
    assert n["external_event_id"] == "gcal-abc"
    assert n["external_provider"] == "google"
    assert n["start_time"] == "2026-09-19T10:00:00Z"
    assert n["end_time"] == "2026-09-19T11:00:00Z"
    assert n["external_url"].startswith("https://calendar.google.com")
    sb = mongo_to_sb(CALENDAR_CFG, doc)
    assert sb["external_event_id"] == "gcal-abc"
    assert sb["start_time"].startswith("2026-09-19")
    assert "gcal_id" not in sb
    assert "start" not in sb


def test_normalize_legacy_microsoft_shape():
    from product_domain_store import normalize_calendar_doc

    n = normalize_calendar_doc({
        "workspace_id": "ws1",
        "event_id": "e1",
        "ms_id": "ms-99",
        "start": "2026-01-01T00:00:00Z",
        "end": "2026-01-01T01:00:00Z",
        "html_link": "https://outlook.office.com/x",
        "source": "outlook_calendar",
    })
    assert n["external_provider"] == "microsoft"
    assert n["external_event_id"] == "ms-99"
    assert n["external_url"].startswith("https://outlook")


def test_canonical_internal_write():
    from product_domain_store import canonical_calendar_write, mongo_to_sb, CALENDAR_CFG

    doc = canonical_calendar_write(
        workspace_id="ws1",
        event_id="ev-int",
        external_provider="internal",
        title="Standup",
        start_time="2026-09-20T15:00:00Z",
        end_time="2026-09-20T15:30:00Z",
        source="manual",
    )
    assert doc["external_provider"] == "internal"
    assert doc["external_event_id"] is None
    sb = mongo_to_sb(CALENDAR_CFG, doc)
    assert sb["event_id"] == "ev-int"
    assert sb["external_provider"] == "internal"


def test_normalize_calendar_query_remaps_legacy():
    from product_domain_store import normalize_calendar_query

    q = normalize_calendar_query({"workspace_id": "ws", "gcal_id": "g1"})
    assert q["external_event_id"] == "g1"
    assert q["external_provider"] == "google"
    assert "gcal_id" not in q
    q2 = normalize_calendar_query({"workspace_id": "ws", "ms_id": "m1"})
    assert q2["external_provider"] == "microsoft"


@pytest.mark.asyncio
async def test_calendar_upsert_dedup_key_shape():
    """New sync writes use (workspace_id, external_provider, external_event_id)."""
    from product_domain_store import wrap_calendar_col, canonical_calendar_write

    class FakeCol:
        def __init__(self):
            self.ops = []

        async def update_one(self, query, update, upsert=False):
            self.ops.append({"query": query, "update": update, "upsert": upsert})
            class R:
                matched_count = 1
                modified_count = 1
                upserted_id = None
            return R()

    col = FakeCol()
    wrapped = wrap_calendar_col(col)
    now = datetime.now(timezone.utc)
    canonical = canonical_calendar_write(
        workspace_id="ws1",
        event_id="e1",
        external_provider="google",
        external_event_id="gcal-1",
        title="T",
        start_time=now,
        end_time=now,
        source="google_calendar",
        synced_at=now,
    )
    await wrapped.update_one(
        {"workspace_id": "ws1", "external_provider": "google", "external_event_id": "gcal-1"},
        {"$set": {k: v for k, v in canonical.items() if k != "event_id"}, "$setOnInsert": {"event_id": "e1"}},
        upsert=True,
    )
    assert col.ops[0]["query"]["external_event_id"] == "gcal-1"
    assert col.ops[0]["query"]["external_provider"] == "google"
    assert col.ops[0]["update"]["$set"]["start_time"] is not None
    assert "gcal_id" not in col.ops[0]["update"]["$set"] or col.ops[0]["update"]["$set"].get("external_event_id") == "gcal-1"


@pytest.mark.asyncio
async def test_duplicate_external_same_query_no_second_insert_key():
    """Two upserts with same external id share the same conflict key."""
    from product_domain_store import wrap_calendar_col, canonical_calendar_write

    class FakeCol:
        def __init__(self):
            self.keys = []

        async def update_one(self, query, update, upsert=False):
            self.keys.append((query.get("workspace_id"), query.get("external_provider"), query.get("external_event_id")))
            class R:
                matched_count = 1
                modified_count = 1
                upserted_id = None
            return R()

    wrapped = wrap_calendar_col(FakeCol())
    for _ in range(2):
        c = canonical_calendar_write(
            workspace_id="ws", event_id="x", external_provider="microsoft",
            external_event_id="ms-dup", title="D", source="outlook_calendar",
        )
        await wrapped.update_one(
            {"workspace_id": "ws", "external_provider": "microsoft", "external_event_id": "ms-dup"},
            {"$set": c},
            upsert=True,
        )
    assert wrapped._mongo.keys[0] == wrapped._mongo.keys[1]
