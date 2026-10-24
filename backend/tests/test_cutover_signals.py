"""Cutover observability (review finding 5) + integrations facade parity (7).

Rows that only Mongo has, writes that degraded to Mongo and mirror failures
log a greppable WARNING tag (``MONGO_ONLY`` / ``STORE_DRIFT``). Flow
configures no logging, so INFO would never reach ``fly logs``.
(Server-level startup under the fly.toml pins: test_startup_pinned_state.py.)
"""
from __future__ import annotations

import logging

import pytest

import storage_flags
from fake_motor import FakeMotorCollection
from storage_helpers import supabase_only

EMAIL = "secret-person@example.com"


def tagged(caplog, tag: str):
    return [r for r in caplog.records if r.levelno >= logging.WARNING and tag in r.getMessage()]


@pytest.mark.asyncio
async def test_doc_store_row_only_in_mongo_is_a_warning_with_ids_only(monkeypatch, caplog):
    import doc_store

    supabase_only(monkeypatch, mirror=True)   # 6a: docs on Supabase, Mongo mirrored
    mongo = FakeMotorCollection("workspace_members")
    await mongo.insert_one({"workspace_id": "ws", "user_id": "u9", "email": EMAIL})
    members = doc_store.FlowDocCollection("workspace_members", mongo)
    caplog.set_level(logging.WARNING)

    assert (await members.find_one({"user_id": "nobody"})) is None
    assert tagged(caplog, storage_flags.MONGO_ONLY) == []          # a miss in both is not a signal

    assert (await members.find_one({"user_id": "u9"}))["user_id"] == "u9"
    (rec,) = tagged(caplog, storage_flags.MONGO_ONLY)
    assert mongo.docs[0]["_id"] in rec.getMessage() and EMAIL not in rec.getMessage()


@pytest.mark.asyncio
async def test_product_and_inbox_signals(monkeypatch, caplog):
    import inbox_store
    import product_domain_store as pds

    fake = supabase_only(monkeypatch, mirror=True)
    caplog.set_level(logging.WARNING)

    contacts_mongo = FakeMotorCollection("contacts")
    await contacts_mongo.insert_one({"workspace_id": "ws", "contact_id": "c-legacy", "email": EMAIL})
    contacts = pds.wrap_contacts_col(contacts_mongo)
    assert (await contacts.find_one({"workspace_id": "ws", "contact_id": "c-legacy"}))["contact_id"] == "c-legacy"
    assert any("c-legacy" in r.getMessage() for r in tagged(caplog, storage_flags.MONGO_ONLY))

    # Mirror delete fails → Mongo keeps a row Supabase deleted: STORE_DRIFT.
    await contacts.insert_one({"workspace_id": "ws", "contact_id": "c1", "is_simulation": False})

    async def boom(*_a, **_k):
        raise RuntimeError("mongo down")

    monkeypatch.setattr(contacts_mongo, "delete_one", boom)
    await contacts.delete_one({"workspace_id": "ws", "contact_id": "c1"})
    assert tagged(caplog, storage_flags.STORE_DRIFT)

    # Supabase insert degrades to Mongo: MONGO_ONLY.
    caplog.clear()
    fake.drop_table("inbox_items")
    inbox = inbox_store.wrap_inbox_col(FakeMotorCollection("inbox_items"))
    await inbox.insert_one({"inbox_id": "i1", "workspace_id": "ws", "from_email": EMAIL, "body": "hi"})
    recs = tagged(caplog, storage_flags.MONGO_ONLY)
    assert recs and all(EMAIL not in r.getMessage() for r in recs)


@pytest.mark.asyncio
async def test_integrations_facade_update_many_and_delete_supabase_primary(monkeypatch):
    import connect_store

    fake = supabase_only(monkeypatch, mirror=True)
    mongo = FakeMotorCollection("integrations_config")
    col = connect_store.IntegrationsConfigCollection(mongo)
    for p in ("a", "b"):
        await col.insert_one({"integration_id": p, "workspace_id": "ws", "provider": p, "status": "disconnected",
                              "config": {}})
    res = await col.update_many({"workspace_id": "ws"}, {"$set": {"status": "connected"}})
    assert res.matched_count == 2
    assert {r["status"] for r in fake.rows["integrations_config"]} == {"connected"}
    assert {d["status"] for d in mongo.docs} == {"connected"}              # mirror replayed
    assert (await col.delete_one({"workspace_id": "ws", "provider": "a"})).deleted_count == 1
    assert [r["provider"] for r in fake.rows["integrations_config"]] == ["b"]
    assert [d["provider"] for d in mongo.docs] == ["b"]


@pytest.mark.asyncio
async def test_new_code_tolerates_the_old_partial_indexes(monkeypatch, caplog):
    """Runbook order (finding 4): the Flow deploy lands BEFORE konta's
    index migration. On the old PARTIAL gmail/ms indexes the sync upsert
    gets 42P10; with the mirror on the new code must degrade to Mongo
    (tagged), never raise, and never touch an existing Supabase row's
    identity or triage state."""
    from datetime import datetime, timezone

    import inbox_store

    fake = supabase_only(monkeypatch, mirror=True)
    spec = fake.specs["inbox_items"]
    spec.uniques = [u for u in spec.uniques if u not in (("workspace_id", "gmail_id"), ("workspace_id", "ms_id"))]
    spec.partial_uniques = [("workspace_id", "gmail_id"), ("workspace_id", "ms_id")]
    caplog.set_level(logging.WARNING)
    mongo = FakeMotorCollection("inbox_items")
    inbox = inbox_store.wrap_inbox_col(mongo)
    now = datetime.now(timezone.utc)

    async def sync(subject):
        return await inbox.update_one(
            {"workspace_id": "ws", "gmail_id": "g1"},
            {"$set": {"workspace_id": "ws", "source": "gmail", "gmail_id": "g1", "subject": subject,
                      "is_real": True, "is_simulation": False, "synced_at": now},
             "$setOnInsert": {"id": f"app-{subject}", "status": "new", "priority": "medium", "created_at": now}},
            upsert=True,
        )

    await sync("one")
    assert fake.rows["inbox_items"] == []                       # 42P10: nothing in Supabase…
    assert [d["subject"] for d in mongo.docs] == ["one"]        # …but kept in Mongo
    assert tagged(caplog, storage_flags.MONGO_ONLY)
    await mongo.update_one({"gmail_id": "g1"}, {"$set": {"status": "processed"}})
    await sync("two")
    (doc,) = mongo.docs
    assert doc["id"] == "app-one" and doc["status"] == "processed" and doc["subject"] == "two"


def test_runbook_flag_dump_never_prints_secrets():
    """Finding 6: step 0 used `env | grep ^QUANTRO_`, which also prints
    QUANTRO_OS_SERVICE_TOKEN. The pattern must match every storage flag and
    no other QUANTRO_* variable the code reads."""
    import re
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    runbook = (backend.parent / "docs" / "mongo-exit-runbook.md").read_text()
    assert not re.search(r"grep \^QUANTRO_[ |'\"]", runbook)
    (line,) = [l for l in runbook.splitlines() if "storage flags only" in l]
    pattern = re.compile(re.search(r"grep -E '([^']+)'", line).group(1))

    flags = {"QUANTRO_DB_PRIMARY", "QUANTRO_MONGO_MIRROR"}
    for names in storage_flags.DOMAIN_FLAGS.values():
        flags |= {n for n in names.values() if n}
    used = set()
    for path in backend.rglob("*.py"):
        if ".venv" in path.parts or "tests" in path.parts:
            continue
        used |= set(re.findall(r"QUANTRO_[A-Z_]+[A-Z]", path.read_text()))
    assert "QUANTRO_OS_SERVICE_TOKEN" in used
    assert all(pattern.match(f"{name}=x") for name in flags), flags
    leaks = sorted(n for n in used - flags if pattern.match(f"{n}=x"))
    assert leaks == []
