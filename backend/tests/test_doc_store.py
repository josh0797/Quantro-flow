"""flow_documents facade: Mongo semantics on Supabase, and the transition modes."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

import doc_store
from storage_helpers import TripwireMongo, supabase_only


@pytest.fixture
def sb(monkeypatch):
    return supabase_only(monkeypatch)


def col(name: str) -> doc_store.FlowDocCollection:
    return doc_store.FlowDocCollection(name, TripwireMongo(name))


@pytest.mark.asyncio
async def test_crud_and_queries_supabase_only(sb):
    users = col("users")
    doc = {"user_id": "u1", "email": "a@example.com", "created_at": datetime(2026, 1, 1, 12, 0)}
    res = await users.insert_one(doc)
    assert doc["_id"] == res.inserted_id and len(res.inserted_id) == 24  # Motor-style mutation, ObjectId shape
    await users.insert_one({"user_id": "u2", "email": "b@example.com"})

    got = await users.find_one({"user_id": "u1"}, {"_id": 0})
    assert got == {"user_id": "u1", "email": "a@example.com", "created_at": datetime(2026, 1, 1, 12, 0)}
    assert got["created_at"].tzinfo is None  # datetime type round-trips exactly
    assert await users.find_one({"email": "a@example.com", "user_id": {"$ne": "u1"}}) is None
    assert await users.count_documents({}) == 2
    assert await users.count_documents({"user_id": {"$in": ["u1", "u9"]}}) == 1
    listed = await users.find({"user_id": {"$in": ["u1", "u2"]}}, {"_id": 0, "user_id": 1}).sort("user_id", -1).to_list(10)
    assert listed == [{"user_id": "u2"}, {"user_id": "u1"}]
    # Only the users collection is visible through this facade.
    await col("workspaces").insert_one({"workspace_id": "default"})
    assert await users.count_documents({}) == 2


@pytest.mark.asyncio
async def test_update_operators_upsert_and_results(sb):
    invites = col("workspace_invites")
    await invites.insert_one({"workspace_id": "ws", "token": "t1", "used_count": 0, "accepted_by": [], "revoked": True})
    res = await invites.update_one(
        {"token": "t1"},
        {"$inc": {"used_count": 1}, "$push": {"accepted_by": {"user_id": "u1"}}, "$set": {"revoked": False}},
    )
    assert (res.matched_count, res.modified_count) == (1, 1)
    inv = await invites.find_one({"token": "t1"})
    assert inv["used_count"] == 1 and inv["accepted_by"] == [{"user_id": "u1"}] and inv["revoked"] is False

    none = await invites.update_one({"token": "nope"}, {"$set": {"x": 1}})
    assert none.matched_count == 0

    members = col("workspace_members")
    up = await members.update_one(
        {"workspace_id": "ws", "user_id": "u1"},
        {"$set": {"role": "owner"}, "$setOnInsert": {"joined_at": "2026-01-01"}},
        upsert=True,
    )
    assert up.upserted_id and up.matched_count == 0
    again = await members.update_one(
        {"workspace_id": "ws", "user_id": "u1"},
        {"$set": {"role": "owner"}, "$setOnInsert": {"joined_at": "CHANGED"}},
        upsert=True,
    )
    assert (again.matched_count, again.modified_count, again.upserted_id) == (1, 0, None)
    m = await members.find_one({"workspace_id": "ws", "user_id": "u1"}, {"_id": 0})
    assert m == {"workspace_id": "ws", "user_id": "u1", "role": "owner", "joined_at": "2026-01-01"}

    many = await members.update_many({"role": "owner"}, {"$set": {"role": "leader"}})
    assert many.modified_count == 1
    assert (await members.delete_many({"workspace_id": "ws"})).deleted_count == 1
    assert await members.count_documents({}) == 0


@pytest.mark.asyncio
async def test_find_one_and_update_before_after_and_sort_kwargs(sb):
    health = col("system_health_events")
    base = datetime(2026, 9, 1, tzinfo=timezone.utc)
    for i in range(60):
        await health.insert_one({"scope": "integrations", "checked_at": base + timedelta(minutes=i), "repair_count": i % 2})
    latest = await health.find_one({"scope": "integrations"}, sort=[("checked_at", -1)], projection={"_id": 0})
    assert latest["checked_at"] == base + timedelta(minutes=59)
    old = await health.find({}, {"_id": 1}).sort("checked_at", -1).skip(50).to_list(1000)
    assert len(old) == 10
    await health.delete_many({"_id": {"$in": [e["_id"] for e in old]}})
    assert await health.count_documents({}) == 50
    assert await health.count_documents({"repair_count": {"$gt": 0}}) == 25

    locks = col("workspace_invites")
    await locks.insert_one({"token": "a", "status": "pending"})
    before = await locks.find_one_and_update({"token": "a", "status": "pending"}, {"$set": {"status": "approved"}})
    assert before["status"] == "pending"
    after = await locks.find_one_and_update({"token": "a"}, {"$set": {"status": "done"}}, return_document=True)
    assert after["status"] == "done"
    assert await locks.find_one_and_update({"token": "a", "status": "pending"}, {"$set": {"status": "x"}}) is None


@pytest.mark.asyncio
async def test_async_iteration(sb):
    ws = col("workspaces")
    for i in range(3):
        await ws.insert_one({"workspace_id": f"ws{i}"})
    seen = [w["workspace_id"] async for w in ws.find({}, {"_id": 0, "workspace_id": 1})]
    assert seen == ["ws0", "ws1", "ws2"]  # natural (insertion) order


@pytest.mark.asyncio
async def test_optimistic_concurrency_retries_lost_update(sb, monkeypatch):
    """A concurrent write between read and write must not be overwritten."""
    invites = col("workspace_invites")
    await invites.insert_one({"token": "t", "used_count": 0})
    real_replace = doc_store.FlowDocCollection._sb_replace
    state = {"raced": False}

    async def racing_replace(self, doc, expected):
        if not state["raced"]:
            state["raced"] = True
            # Someone else increments first (bumps updated_at).
            row = sb.rows["flow_documents"][0]
            row["doc"] = {**row["doc"], "used_count": 1}
            row["updated_at"] = datetime.now(timezone.utc).isoformat() + "x"
        return await real_replace(self, doc, expected)

    monkeypatch.setattr(doc_store.FlowDocCollection, "_sb_replace", racing_replace)
    await invites.update_one({"token": "t"}, {"$inc": {"used_count": 1}})
    assert (await invites.find_one({"token": "t"}))["used_count"] == 2


@pytest.mark.asyncio
async def test_supabase_error_raises_without_mirror(sb, monkeypatch):
    import sb_rest

    async def down(*a, **k):
        return None

    monkeypatch.setattr(doc_store, "_sb_request", down)
    with pytest.raises(sb_rest.SupabaseStoreError):
        await col("users").find_one({"user_id": "u1"})
    with pytest.raises(sb_rest.SupabaseStoreError):
        await col("users").insert_one({"user_id": "u1"})


class FakeMongo:
    """Minimal Motor-like collection with ObjectId-ish _ids (shadow tests)."""

    def __init__(self):
        from mongo_compat import match, apply_update, new_object_id

        self._match, self._apply, self._new = match, apply_update, new_object_id
        self.docs: List[Dict[str, Any]] = []

    async def insert_one(self, doc):
        doc.setdefault("_id", self._new())
        self.docs.append(copy.deepcopy(doc))

        class R:
            inserted_id = doc["_id"]
        return R()

    def find(self, query=None, projection=None):
        rows = [copy.deepcopy(d) for d in self.docs if self._match(d, query or {})]

        class C:
            async def to_list(self, n=None):
                return rows if not n else rows[:n]
        return C()

    async def find_one(self, query, projection=None):
        rows = await self.find(query).to_list(1)
        return rows[0] if rows else None

    async def update_one(self, query, update, upsert=False):
        for i, d in enumerate(self.docs):
            if self._match(d, query):
                self.docs[i] = self._apply(d, update)

                class R:
                    matched_count = 1
                    modified_count = 1
                    upserted_id = None
                return R()

        class N:
            matched_count = 0
            modified_count = 0
            upserted_id = None
        return N()

    async def replace_one(self, query, body, upsert=False):
        self.docs = [d for d in self.docs if not self._match(d, query)]
        self.docs.append({"_id": query["_id"], **body})

    async def delete_many(self, query):
        self.docs = [d for d in self.docs if not self._match(d, query)]


@pytest.mark.asyncio
async def test_mongo_primary_shadows_every_write_to_supabase(monkeypatch):
    fake = supabase_only(monkeypatch)
    monkeypatch.setenv("QUANTRO_DOCS_PRIMARY", "mongo")  # step 1 of the runbook
    mongo = FakeMongo()
    agents = doc_store.FlowDocCollection("agents", mongo)
    await agents.insert_one({"agent_id": "a1", "workspace_id": "ws", "status": "onboarding"})
    await agents.update_one({"agent_id": "a1"}, {"$set": {"status": "active"}})
    rows = fake.rows["flow_documents"]
    assert len(rows) == 1 and rows[0]["doc"]["status"] == "active"
    assert rows[0]["doc_id"] == mongo.docs[0]["_id"] and rows[0]["workspace_id"] == "ws"
    # Reads still come from Mongo.
    assert (await agents.find_one({"agent_id": "a1"}))["status"] == "active"


@pytest.mark.asyncio
async def test_supabase_primary_with_mirror_replays_writes_to_mongo(monkeypatch):
    supabase_only(monkeypatch, mirror=True)
    mongo = FakeMongo()
    rules = doc_store.FlowDocCollection("escalation_rules", mongo)
    await rules.insert_one({"rule_id": "r1", "workspace_id": "ws", "enabled": True})
    await rules.update_one({"rule_id": "r1"}, {"$set": {"enabled": False}})
    assert mongo.docs[0]["enabled"] is False
    # Supabase miss falls back to the mirror (pre-backfill rows).
    mongo.docs.append({"_id": "65f000000000000000000001", "rule_id": "legacy", "workspace_id": "ws"})
    assert (await rules.find_one({"rule_id": "legacy"}))["rule_id"] == "legacy"
    await rules.delete_one({"rule_id": "r1"})
    assert [d["rule_id"] for d in mongo.docs] == ["legacy"]
