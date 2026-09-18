#!/usr/bin/env python3
"""Phase 6.1 inbox_items dual-write unit tests.

No live Mongo or Supabase. Uses httpx mocks + FakeAsyncCollection.
"""
from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
_TESTS = os.path.join(BACKEND, "tests")
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from conftest import FakeAsyncCollection  # noqa: E402


def _reload_store(**env):
    base = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-test",
        "QUANTRO_INBOX_PRIMARY": "mongo",
        "QUANTRO_MONGO_MIRROR": "1",
        "QUANTRO_INBOX_MONGO_MIRROR": "",
    }
    base.update(env)
    with patch.dict(os.environ, base, clear=False):
        if not base.get("QUANTRO_INBOX_MONGO_MIRROR"):
            os.environ.pop("QUANTRO_INBOX_MONGO_MIRROR", None)
        for mod in list(sys.modules):
            if mod == "inbox_store" or mod.endswith("inbox_store"):
                del sys.modules[mod]
        import inbox_store as store
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
    assert store.INBOX_PRIMARY == "mongo"
    assert store.is_inbox_dual_write_enabled() is True
    assert store.is_inbox_mongo_write_enabled() is True
    assert "activity_events" in store.inbox_health()["next_domains"]


def test_flip_primary_supabase():
    store = _reload_store(QUANTRO_INBOX_PRIMARY="supabase")
    assert store.is_inbox_supabase_primary() is True
    assert store.is_inbox_mongo_write_enabled() is True


def test_mirror_off_when_supabase_primary():
    store = _reload_store(
        QUANTRO_INBOX_PRIMARY="supabase",
        QUANTRO_INBOX_MONGO_MIRROR="0",
    )
    assert store.is_inbox_mongo_write_enabled() is False


# ── mappers ───────────────────────────────────────────────────────────

def test_mapper_seed_and_sync_fields():
    store = _reload_store()
    seed = {
        "inbox_id": "i1",
        "workspace_id": "ws1",
        "from_email": "a@b.com",
        "from_name": "A",
        "subject": "Hi",
        "body": "secret body",
        "ai_intent": {"intent": "follow_up"},
        "is_simulation": True,
        "hidden_by_real": False,
    }
    row = store.inbox_mongo_to_sb(seed)
    assert row["inbox_id"] == "i1"
    assert row["from_email"] == "a@b.com"
    assert row["ai_intent"]["intent"] == "follow_up"
    assert "id" not in row  # PG uuid separate

    sync = {
        "id": "sync-uuid",
        "workspace_id": "ws1",
        "gmail_id": "g1",
        "from_address": "boss@co.com",
        "preview": "snippet",
        "label_ids": ["INBOX"],
        "is_real": True,
        "is_simulation": False,
    }
    row2 = store.inbox_mongo_to_sb(sync)
    assert row2["inbox_id"] == "sync-uuid"
    assert row2["from_address"] == "boss@co.com"
    assert row2["gmail_id"] == "g1"
    assert row2["label_ids"] == ["INBOX"]

    back = store.inbox_sb_to_mongo({**row2, "id": "pg-uuid"})
    assert "id" not in back or back.get("id") == "sync-uuid"
    assert back["inbox_id"] == "sync-uuid"


def test_ne_true_filter_uses_not_is_true():
    store = _reload_store()
    params = store._mongo_filter_to_params({
        "workspace_id": "ws1",
        "is_simulation": {"$ne": True},
        "hidden_by_real": {"$ne": True},
    })
    assert params["is_simulation"] == "not.is.true"
    assert params["hidden_by_real"] == "not.is.true"
    assert params["workspace_id"] == "eq.ws1"


# ── dual-write (primary=mongo) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_dual_writes_to_supabase(fake_mongo):
    store = _reload_store(QUANTRO_INBOX_PRIMARY="mongo")
    col = store.wrap_inbox_col(fake_mongo)
    posted: List[Dict[str, Any]] = []

    async def fake_request(method, path, **kwargs):
        if method == "POST":
            posted.append(kwargs.get("json"))
            assert "on_conflict=workspace_id,gmail_id" in path or "on_conflict=workspace_id,inbox_id" in path
            return FakeResponse(201, [])
        return FakeResponse(200, [])

    with patch.object(store, "_sb_request", side_effect=fake_request):
        now = datetime.now(timezone.utc)
        await col.update_one(
            {"workspace_id": "ws1", "gmail_id": "gm1"},
            {
                "$set": {
                    "workspace_id": "ws1",
                    "source": "gmail",
                    "gmail_id": "gm1",
                    "from_address": "boss@co.com",
                    "subject": "Q3",
                    "preview": "hi",
                    "is_real": True,
                    "is_simulation": False,
                    "synced_at": now,
                },
                "$setOnInsert": {
                    "id": "app-id-1",
                    "status": "new",
                    "priority": "medium",
                    "created_at": now,
                },
            },
            upsert=True,
        )

    mongo_doc = await fake_mongo.find_one({"gmail_id": "gm1"})
    assert mongo_doc is not None
    assert mongo_doc.get("from_address") == "boss@co.com"
    assert len(posted) == 1
    assert posted[0]["inbox_id"] == "app-id-1"
    assert posted[0]["gmail_id"] == "gm1"
    assert posted[0]["from_address"] == "boss@co.com"
    assert "body" not in posted[0] or posted[0].get("body") is None


@pytest.mark.asyncio
async def test_insert_many_seed_dual_write(fake_mongo):
    store = _reload_store(QUANTRO_INBOX_PRIMARY="mongo")
    col = store.wrap_inbox_col(fake_mongo)
    posted = []

    async def fake_request(method, path, **kwargs):
        if method == "POST":
            posted.append(kwargs.get("json"))
            return FakeResponse(201, [])
        return FakeResponse(200, [])

    docs = [
        {
            "inbox_id": "seed1",
            "workspace_id": "default",
            "from_email": "sarah@x.com",
            "from_name": "Sarah Chen",
            "subject": "Viewing",
            "body": "please do not log this body in bulk",
            "is_simulation": True,
            "status": "new",
            "read": False,
        }
    ]
    with patch.object(store, "_sb_request", side_effect=fake_request):
        # FakeAsyncCollection has no insert_many — store falls back to loop via hasattr
        # Add a minimal insert_many on the fake for this test path.
        async def _insert_many(items):
            for d in items:
                await fake_mongo.insert_one(d)
            return items

        fake_mongo.insert_many = _insert_many  # type: ignore[attr-defined]
        await col.insert_many(docs)

    assert await fake_mongo.find_one({"inbox_id": "seed1"}) is not None
    assert len(posted) == 1
    assert posted[0]["from_email"] == "sarah@x.com"
    assert posted[0]["body"] == "please do not log this body in bulk"


@pytest.mark.asyncio
async def test_hidden_by_real_update_many_dual_write(fake_mongo):
    store = _reload_store(QUANTRO_INBOX_PRIMARY="mongo")
    col = store.wrap_inbox_col(fake_mongo)
    await fake_mongo.insert_one({
        "inbox_id": "demo1",
        "workspace_id": "ws1",
        "is_simulation": True,
        "from_name": "Sarah Chen",
    })
    await fake_mongo.insert_one({
        "inbox_id": "real1",
        "workspace_id": "ws1",
        "is_simulation": False,
        "is_real": True,
    })

    patches = []

    async def fake_request(method, path, **kwargs):
        if method == "PATCH":
            patches.append({"params": kwargs.get("params"), "json": kwargs.get("json")})
            return FakeResponse(204, [])
        return FakeResponse(200, [])

    with patch.object(store, "_sb_request", side_effect=fake_request):
        await col.update_many(
            {"workspace_id": "ws1", "is_simulation": True},
            {"$set": {"hidden_by_real": True}},
        )

    demo = await fake_mongo.find_one({"inbox_id": "demo1"})
    real = await fake_mongo.find_one({"inbox_id": "real1"})
    assert demo["hidden_by_real"] is True
    assert real.get("hidden_by_real") is not True
    assert len(patches) == 1
    assert patches[0]["json"]["hidden_by_real"] is True
    assert patches[0]["params"]["is_simulation"] == "eq.true"


@pytest.mark.asyncio
async def test_graceful_degrade_when_table_missing(fake_mongo):
    store = _reload_store(QUANTRO_INBOX_PRIMARY="mongo")
    col = store.wrap_inbox_col(fake_mongo)
    with patch.object(store, "_sb_request", AsyncMock(return_value=None)):
        await col.insert_one({
            "inbox_id": "i2",
            "workspace_id": "ws1",
            "from_email": "x@y.com",
            "subject": "ok",
        })
    assert await fake_mongo.find_one({"inbox_id": "i2"}) is not None


# ── primary=supabase reads ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_primary_supabase(fake_mongo):
    store = _reload_store(QUANTRO_INBOX_PRIMARY="supabase")
    col = store.wrap_inbox_col(fake_mongo)

    async def fake_request(method, path, **kwargs):
        assert "inbox_items" in path
        return FakeResponse(200, [{
            "id": "pg-uuid",
            "inbox_id": "i9",
            "workspace_id": "ws1",
            "from_email": "a@b.com",
            "subject": "Hello",
            "hidden_by_real": False,
            "is_simulation": False,
            "ai_intent": {"intent": "follow_up"},
        }])

    with patch.object(store, "_sb_request", side_effect=fake_request):
        doc = await col.find_one({"workspace_id": "ws1", "inbox_id": "i9"})
    assert doc["subject"] == "Hello"
    assert doc["inbox_id"] == "i9"
    assert doc["ai_intent"]["intent"] == "follow_up"
    assert fake_mongo._docs == []


@pytest.mark.asyncio
async def test_list_preserves_hidden_by_real_filter_semantics():
    """Live mode filter still excludes hidden_by_real=True (mongo primary)."""
    store = _reload_store(QUANTRO_INBOX_PRIMARY="mongo")
    fake = FakeAsyncCollection()
    col = store.wrap_inbox_col(fake)
    await fake.insert_one({
        "inbox_id": "demo", "workspace_id": "ws", "is_simulation": True, "hidden_by_real": True,
    })
    await fake.insert_one({
        "inbox_id": "real", "workspace_id": "ws", "is_simulation": False, "is_real": True,
    })
    await fake.insert_one({
        "inbox_id": "live_unhidden", "workspace_id": "ws", "is_simulation": False,
    })

    mode = {
        "workspace_id": "ws",
        "is_simulation": {"$ne": True},
        "hidden_by_real": {"$ne": True},
    }
    rows = await col.find(mode).sort("received_at", -1).to_list(100)
    ids = {r["inbox_id"] for r in rows}
    assert "demo" not in ids
    assert "real" in ids
    assert "live_unhidden" in ids
