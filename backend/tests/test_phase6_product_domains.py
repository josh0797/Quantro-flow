"""Phase 6.2–6.3 product domain dual-write unit tests."""
import os
import pytest

os.environ.setdefault("QUANTRO_ACTIVITY_PRIMARY", "mongo")
os.environ.setdefault("QUANTRO_CONTENT_PRIMARY", "mongo")
os.environ.setdefault("QUANTRO_CONTACTS_PRIMARY", "mongo")
os.environ.setdefault("QUANTRO_CALENDAR_PRIMARY", "mongo")


def test_domain_configs_unique_tables():
    from product_domain_store import (
        ACTIVITY_CFG, CONTENT_ITEMS_CFG, CONTENT_TEMPLATES_CFG,
        CONTACTS_CFG, CALENDAR_CFG, product_domains_health,
    )
    tables = {c.table for c in (ACTIVITY_CFG, CONTENT_ITEMS_CFG, CONTENT_TEMPLATES_CFG, CONTACTS_CFG, CALENDAR_CFG)}
    assert len(tables) == 5
    h = product_domains_health()
    assert h["activity"]["activity_primary"] == "mongo"
    assert h["contacts"]["contacts_primary"] == "mongo"


def test_mongo_to_sb_maps_ids():
    from product_domain_store import CONTACTS_CFG, CALENDAR_CFG, ACTIVITY_CFG, mongo_to_sb
    c = mongo_to_sb(CONTACTS_CFG, {
        "contact_id": "c1", "workspace_id": "ws", "name": "Ada", "email": "a@b.co",
        "_id": "mongo", "extra": "drop-me",
    })
    assert c["contact_id"] == "c1" and "extra" not in c and "_id" not in c
    a = mongo_to_sb(ACTIVITY_CFG, {"event_id": "e1", "workspace_id": "ws", "title": "Hi", "timestamp": None})
    assert a["event_id"] == "e1"
    cal = mongo_to_sb(CALENDAR_CFG, {
        "event_id": "ev", "workspace_id": "ws", "attendees": ["x"], "hidden_by_real": False,
    })
    assert cal["attendees"] == ["x"]


@pytest.mark.asyncio
async def test_wrap_insert_one_mongo_only(monkeypatch):
    from product_domain_store import wrap_contacts_col, DualWriteCollection
    class FakeCol:
        def __init__(self):
            self.docs = []
        async def insert_one(self, doc):
            self.docs.append(doc)
            class R: inserted_id = "x"
            return R()
        async def find_one(self, *a, **k):
            return self.docs[0] if self.docs else None
        async def count_documents(self, q):
            return len(self.docs)
    col = FakeCol()
    wrapped = wrap_contacts_col(col)
    assert isinstance(wrapped, DualWriteCollection)
    await wrapped.insert_one({"contact_id": "c1", "workspace_id": "ws", "name": "Ada"})
    assert col.docs[0]["contact_id"] == "c1"
