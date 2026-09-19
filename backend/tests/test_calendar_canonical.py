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


@pytest.mark.asyncio
async def test_calendar_on_conflict_external_vs_internal():
    from product_domain_store import calendar_on_conflict

    assert calendar_on_conflict({"external_event_id": "g1", "event_id": "e1"}) == (
        "workspace_id,external_provider,external_event_id"
    )
    assert calendar_on_conflict({"external_event_id": None, "event_id": "e1"}) == "workspace_id,event_id"
    assert calendar_on_conflict({"event_id": "e1"}) == "workspace_id,event_id"


@pytest.mark.asyncio
async def test_sb_upsert_uses_external_conflict_and_preserves_event_id(monkeypatch):
    """Google first sync insert; second sync same external_event_id keeps event_id."""
    from product_domain_store import DualWriteCollection, CALENDAR_CFG, canonical_calendar_write
    import product_domain_store as pds

    posts = []
    existing_row = None

    class FakeResp:
        def __init__(self, status_code=201, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload
            self.text = text

        def json(self):
            return self._payload

    async def fake_sb_request(method, path, **kwargs):
        nonlocal existing_row
        if method == "GET":
            if existing_row:
                return FakeResp(200, [existing_row])
            return FakeResp(200, [])
        if method == "POST":
            posts.append({"path": path, "json": kwargs.get("json")})
            existing_row = dict(kwargs.get("json") or {})
            return FakeResp(201)
        return FakeResp(200)

    monkeypatch.setattr(pds, "_sb_request", fake_sb_request)
    monkeypatch.setattr(pds, "_is_sb_configured", lambda: True)
    monkeypatch.setenv("QUANTRO_CALENDAR_PRIMARY", "mongo")

    class FakeMongo:
        async def insert_one(self, doc):
            return doc

        async def update_one(self, *a, **k):
            class R:
                matched_count = 1
                modified_count = 1
                upserted_id = None
            return R()

    store = DualWriteCollection(FakeMongo(), CALENDAR_CFG)
    c1 = canonical_calendar_write(
        workspace_id="ws1", event_id="evt-first", external_provider="google",
        external_event_id="gcal-xyz", title="A", source="google_calendar",
    )
    assert await store._sb_upsert_doc(c1) is True
    assert "on_conflict=workspace_id,external_provider,external_event_id" in posts[0]["path"]
    assert posts[0]["json"]["event_id"] == "evt-first"

    c2 = canonical_calendar_write(
        workspace_id="ws1", event_id="evt-SECOND-NEW-UUID", external_provider="google",
        external_event_id="gcal-xyz", title="A2", source="google_calendar",
    )
    assert await store._sb_upsert_doc(c2) is True
    assert posts[1]["json"]["event_id"] == "evt-first"  # preserved
    assert posts[1]["json"]["title"] == "A2"


@pytest.mark.asyncio
async def test_sb_upsert_internal_uses_event_id_conflict(monkeypatch):
    from product_domain_store import DualWriteCollection, CALENDAR_CFG, canonical_calendar_write
    import product_domain_store as pds

    posts = []

    class FakeResp:
        status_code = 201
        text = ""

        def json(self):
            return []

    async def fake_sb_request(method, path, **kwargs):
        if method == "POST":
            posts.append(path)
        return FakeResp()

    monkeypatch.setattr(pds, "_sb_request", fake_sb_request)
    monkeypatch.setattr(pds, "_is_sb_configured", lambda: True)

    class FakeMongo:
        async def insert_one(self, doc):
            return doc

    store = DualWriteCollection(FakeMongo(), CALENDAR_CFG)
    doc = canonical_calendar_write(
        workspace_id="ws1", event_id="int-1", external_provider="internal",
        title="Standup", source="manual",
    )
    await store._sb_upsert_doc(doc)
    assert "on_conflict=workspace_id,event_id" in posts[0]


@pytest.mark.asyncio
async def test_legacy_gcal_id_sync_updates_same_row_no_duplicate():
    from product_domain_store import (
        wrap_calendar_col, canonical_calendar_write, upsert_calendar_external_event,
    )
    from datetime import datetime, timezone

    class FakeCol:
        def __init__(self):
            self._docs = [
                {
                    "_id": "mongo1",
                    "workspace_id": "ws1",
                    "id": "legacy-evt-1",
                    "gcal_id": "gcal-legacy",
                    "title": "Old",
                    "start": "2026-01-01T00:00:00Z",
                }
            ]

        async def find_one(self, query, projection=None):
            for d in self._docs:
                if all(d.get(k) == v for k, v in query.items()):
                    return dict(d)
            return None

        async def update_one(self, query, update, upsert=False):
            for d in self._docs:
                if all(d.get(k) == v for k, v in query.items() if not str(k).startswith("$")):
                    d.update(update.get("$set", {}))
                    class R:
                        matched_count = 1
                        modified_count = 1
                        upserted_id = None
                    return R()
            if upsert:
                nd = dict(query)
                nd.update(update.get("$setOnInsert", {}))
                nd.update(update.get("$set", {}))
                self._docs.append(nd)
            class R:
                matched_count = 0
                modified_count = 0
                upserted_id = None
            return R()

    raw = FakeCol()
    wrapped = wrap_calendar_col(raw)
    now = datetime.now(timezone.utc)
    canonical = canonical_calendar_write(
        workspace_id="ws1", event_id="should-not-win",
        external_provider="google", external_event_id="gcal-legacy",
        title="New Title", source="google_calendar", synced_at=now, updated_at=now,
    )
    eid = await upsert_calendar_external_event(
        wrapped, workspace_id="ws1", provider="google",
        external_event_id="gcal-legacy", canonical=canonical, now=now,
    )
    assert eid == "legacy-evt-1"
    assert len(raw._docs) == 1
    assert raw._docs[0]["external_event_id"] == "gcal-legacy"
    assert raw._docs[0]["external_provider"] == "google"
    assert raw._docs[0]["title"] == "New Title"
    assert raw._docs[0].get("gcal_id") == "gcal-legacy"  # not deleted

    # Repeated sync still one row, same event_id
    canonical2 = canonical_calendar_write(
        workspace_id="ws1", event_id="another-uuid",
        external_provider="google", external_event_id="gcal-legacy",
        title="Newer", source="google_calendar", synced_at=now, updated_at=now,
    )
    eid2 = await upsert_calendar_external_event(
        wrapped, workspace_id="ws1", provider="google",
        external_event_id="gcal-legacy", canonical=canonical2, now=now,
    )
    assert eid2 == "legacy-evt-1"
    assert len(raw._docs) == 1
    assert raw._docs[0]["title"] == "Newer"


@pytest.mark.asyncio
async def test_legacy_ms_id_sync_updates_same_row_no_duplicate():
    from product_domain_store import (
        wrap_calendar_col, canonical_calendar_write, upsert_calendar_external_event,
    )
    from datetime import datetime, timezone

    class FakeCol:
        def __init__(self):
            self._docs = [
                {
                    "_id": "mongo-ms",
                    "workspace_id": "ws1",
                    "event_id": "ms-legacy-evt",
                    "ms_id": "ms-legacy",
                    "title": "Old MS",
                }
            ]

        async def find_one(self, query, projection=None):
            for d in self._docs:
                if all(d.get(k) == v for k, v in query.items()):
                    return dict(d)
            return None

        async def update_one(self, query, update, upsert=False):
            for d in self._docs:
                if all(d.get(k) == v for k, v in query.items() if not str(k).startswith("$")):
                    d.update(update.get("$set", {}))
                    class R:
                        matched_count = 1
                        modified_count = 1
                        upserted_id = None
                    return R()
            class R:
                matched_count = 0
                modified_count = 0
                upserted_id = None
            return R()

    raw = FakeCol()
    wrapped = wrap_calendar_col(raw)
    now = datetime.now(timezone.utc)
    canonical = canonical_calendar_write(
        workspace_id="ws1", event_id="new-uuid",
        external_provider="microsoft", external_event_id="ms-legacy",
        title="Updated MS", source="outlook_calendar", synced_at=now,
    )
    eid = await upsert_calendar_external_event(
        wrapped, workspace_id="ws1", provider="microsoft",
        external_event_id="ms-legacy", canonical=canonical, now=now,
    )
    assert eid == "ms-legacy-evt"
    assert len(raw._docs) == 1
    assert raw._docs[0]["ms_id"] == "ms-legacy"
    assert raw._docs[0]["external_event_id"] == "ms-legacy"

    eid2 = await upsert_calendar_external_event(
        wrapped, workspace_id="ws1", provider="microsoft",
        external_event_id="ms-legacy",
        canonical=canonical_calendar_write(
            workspace_id="ws1", event_id="uuid-2", external_provider="microsoft",
            external_event_id="ms-legacy", title="Again", source="outlook_calendar",
        ),
        now=now,
    )
    assert eid2 == "ms-legacy-evt"
    assert len(raw._docs) == 1


@pytest.mark.asyncio
async def test_google_first_sync_insert_then_second_updates_same_event_id():
    from product_domain_store import (
        wrap_calendar_col, canonical_calendar_write, upsert_calendar_external_event,
    )
    from datetime import datetime, timezone

    class FakeCol:
        def __init__(self):
            self._docs = []

        async def find_one(self, query, projection=None):
            for d in self._docs:
                if all(d.get(k) == v for k, v in query.items()):
                    return dict(d)
            return None

        async def update_one(self, query, update, upsert=False):
            for d in self._docs:
                if all(d.get(k) == v for k, v in query.items()):
                    d.update(update.get("$set", {}))
                    class R:
                        matched_count = 1
                        modified_count = 1
                        upserted_id = None
                    return R()
            if upsert:
                nd = dict(query)
                nd.update(update.get("$setOnInsert", {}))
                nd.update(update.get("$set", {}))
                self._docs.append(nd)
                class R:
                    matched_count = 0
                    modified_count = 0
                    upserted_id = nd.get("event_id")
                return R()
            class R:
                matched_count = 0
                modified_count = 0
                upserted_id = None
            return R()

    raw = FakeCol()
    wrapped = wrap_calendar_col(raw)
    now = datetime.now(timezone.utc)
    eid1 = await upsert_calendar_external_event(
        wrapped, workspace_id="ws", provider="google", external_event_id="g1",
        canonical=canonical_calendar_write(
            workspace_id="ws", event_id="e-a", external_provider="google",
            external_event_id="g1", title="T1", source="google_calendar",
        ),
        now=now,
    )
    eid2 = await upsert_calendar_external_event(
        wrapped, workspace_id="ws", provider="google", external_event_id="g1",
        canonical=canonical_calendar_write(
            workspace_id="ws", event_id="e-b", external_provider="google",
            external_event_id="g1", title="T2", source="google_calendar",
        ),
        now=now,
    )
    assert eid1 == eid2 == "e-a"
    assert len(raw._docs) == 1
    assert raw._docs[0]["title"] == "T2"
