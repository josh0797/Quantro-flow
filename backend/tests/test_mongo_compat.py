"""Mongo query/update semantics used to evaluate filters PostgREST cannot."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import mongo_compat as mc


def test_equality_null_and_missing():
    assert mc.match({"a": None}, {"a": None})
    assert mc.match({}, {"a": None})
    assert not mc.match({"a": 1}, {"a": None})
    assert mc.match({"tags": ["x", "y"]}, {"tags": "x"})  # array contains
    assert mc.match({"tags": ["x", "y"]}, {"tags": ["x", "y"]})


def test_ne_matches_missing_like_mongo():
    live = {"workspace_id": "ws", "is_simulation": {"$ne": True}, "hidden_by_real": {"$ne": True}}
    assert mc.match({"workspace_id": "ws", "is_simulation": False}, live)
    assert mc.match({"workspace_id": "ws"}, live)
    assert not mc.match({"workspace_id": "ws", "hidden_by_real": True}, live)
    assert not mc.match({"workspace_id": "ws", "is_simulation": True}, live)


def test_bool_is_not_int():
    assert not mc.match({"a": 1}, {"a": True})
    assert not mc.match({"a": True}, {"a": 1})


def test_in_nin_exists_or_and():
    doc = {"category": "lead", "priority": "low", "n": 3}
    q = {"$or": [{"category": {"$in": ["opportunity", "lead"]}}, {"priority": {"$in": ["high"]}}]}
    assert mc.match(doc, q)
    assert not mc.match(doc, {"category": {"$nin": ["lead"]}})
    assert mc.match(doc, {"missing": {"$nin": ["x"]}})
    assert mc.match(doc, {"n": {"$exists": True}, "zz": {"$exists": False}})
    assert mc.match(doc, {"$and": [{"n": {"$gt": 2}}, {"n": {"$lte": 3}}]})
    assert mc.match(doc, {"$nor": [{"n": 4}]})


def test_datetime_comparisons_mix_naive_and_aware():
    now = datetime.now(timezone.utc)
    naive_past = (now - timedelta(hours=2)).replace(tzinfo=None)
    assert mc.match({"t": naive_past}, {"t": {"$lt": now}})
    assert mc.match({"t": now}, {"t": {"$gte": naive_past}})
    # Different types never compare (Mongo semantics) instead of raising.
    assert not mc.match({"t": "2026-01-01"}, {"t": {"$gt": now}})


def test_dotted_paths_through_arrays_and_regex():
    doc = {"accepted_by": [{"user_id": "u1"}, {"user_id": "u2"}], "name": "Sarah Chen"}
    assert mc.match(doc, {"accepted_by.user_id": "u2"})
    assert mc.match(doc, {"name": {"$regex": "^sarah", "$options": "i"}})
    assert mc.match(doc, {"accepted_by": {"$elemMatch": {"user_id": "u1"}}})
    assert mc.match(doc, {"accepted_by": {"$size": 2}})


def test_unknown_operator_raises():
    with pytest.raises(ValueError):
        mc.match({"a": 1}, {"a": {"$where": "1"}})
    with pytest.raises(ValueError):
        mc.apply_update({}, {"$bit": {"a": 1}})


def test_update_operators():
    doc = {"_id": "x", "used_count": 0, "accepted_by": [], "revoked": True, "role": "agent"}
    out = mc.apply_update(doc, {
        "$inc": {"used_count": 1},
        "$push": {"accepted_by": {"user_id": "u1"}},
        "$set": {"revoked": False, "meta.a": 1},
        "$unset": {"role": ""},
    })
    assert out == {"_id": "x", "used_count": 1, "accepted_by": [{"user_id": "u1"}], "revoked": False, "meta": {"a": 1}}
    assert doc["used_count"] == 0  # input untouched
    out2 = mc.apply_update(out, {"$addToSet": {"tags": {"$each": ["a", "a", "b"]}}, "$pull": {"accepted_by": {"user_id": "u1"}}})
    assert out2["tags"] == ["a", "b"] and out2["accepted_by"] == []


def test_set_on_insert_only_on_insert():
    upd = {"$set": {"status": "synced"}, "$setOnInsert": {"status_first": "new", "created_at": 1}}
    assert mc.apply_update({"a": 1}, upd) == {"a": 1, "status": "synced"}
    seeded = mc.apply_update(mc.seed_from_query({"workspace_id": "ws", "gmail_id": "g", "x": {"$ne": 1}}), upd, is_insert=True)
    assert seeded == {"workspace_id": "ws", "gmail_id": "g", "status": "synced", "status_first": "new", "created_at": 1}


def test_projection_and_sort():
    docs = [
        {"_id": "1", "t": datetime(2026, 1, 2, tzinfo=timezone.utc), "n": 1},
        {"_id": "2", "t": None, "n": 2},
        {"_id": "3", "t": datetime(2026, 1, 3, tzinfo=timezone.utc), "n": 3},
    ]
    assert [d["_id"] for d in mc.sort_docs(docs, [("t", -1)])] == ["3", "1", "2"]  # null last desc
    assert [d["_id"] for d in mc.sort_docs(docs, [("t", 1)])] == ["2", "1", "3"]   # null first asc
    assert mc.project(docs[0], {"_id": 0, "n": 1}) == {"n": 1}
    assert mc.project(docs[0], {"n": 1}) == {"n": 1, "_id": "1"}
    assert mc.project(docs[0], {"_id": 0}) == {"t": docs[0]["t"], "n": 1}
    assert mc.normalize_sort([("a", -1), ("b", 1)]) == [("a", -1), ("b", 1)]
    assert mc.normalize_sort("a", -1) == [("a", -1)]


def test_json_codec_round_trips_types():
    naive = datetime(2026, 9, 28, 12, 0, 0, 123000)
    aware = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    value = {"a": naive, "b": [aware, {"c": float("nan")}], "d": b"\x00\x01", "e": None}
    back = mc.from_json(mc.to_json(value))
    assert back["a"] == naive and back["a"].tzinfo is None
    assert back["b"][0] == aware
    assert back["d"] == b"\x00\x01"
    assert back["b"][1]["c"] != back["b"][1]["c"]  # nan
    import json
    json.dumps(mc.to_json(value))  # always serializable


def test_duplicate_key_error_is_pymongos_when_available():
    try:
        from pymongo.errors import DuplicateKeyError
    except Exception:  # pragma: no cover
        pytest.skip("pymongo not installed")
    assert mc.DuplicateKeyError is DuplicateKeyError
