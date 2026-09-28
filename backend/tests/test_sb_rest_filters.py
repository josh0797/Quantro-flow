"""split_filter: pushed-down params + Python residual == pure Mongo semantics."""
from __future__ import annotations

import itertools
from datetime import datetime, timezone

import pytest

import mongo_compat as mc
import sb_rest
from fake_postgrest import FakePostgrest, TableSpec

COLS = ["id", "workspace_id", "status", "n", "flag", "ts", "extra"]


def test_translations():
    p, r = sb_rest.split_filter({"workspace_id": "ws", "flag": {"$ne": True}}, COLS)
    assert p == {"workspace_id": "eq.ws", "flag": "not.is.true"} and r == {}
    p, r = sb_rest.split_filter({"status": {"$ne": "a,b"}}, COLS)
    assert p == {"and": '(or(status.is.null,status.neq."a,b"))'} and r == {}
    p, _ = sb_rest.split_filter({"status": {"$in": ["x", None]}}, COLS)
    assert p == {"and": '(or(status.is.null,status.in.("x")))'}
    p, _ = sb_rest.split_filter({"n": {"$gte": 1, "$lt": 5}}, COLS)
    assert p == {"n": "gte.1", "and": "(n.lt.5)"}
    p, r = sb_rest.split_filter({"extra_field": 1, "a.b": 2, "$or": [{"n": 1}], "status": {"$regex": "x"}}, COLS)
    assert p == {} and set(r) == {"extra_field", "a.b", "$or", "status"}
    p, r = sb_rest.split_filter({"extra": {"k": 1}}, COLS, json_cols=["extra"])
    assert p == {} and r == {"extra": {"k": 1}}
    with pytest.raises(sb_rest.Impossible):
        sb_rest.split_filter({"status": {"$in": []}}, COLS)
    assert sb_rest.order_param([("ts", -1), ("n", 1)], COLS) == "ts.desc.nullslast,n.asc.nullsfirst"
    assert sb_rest.order_param([("nested.x", 1)], COLS) is None


DOCS = [
    {"id": "1", "workspace_id": "ws", "status": "new", "n": 1, "flag": True, "ts": "2026-09-01T00:00:00+00:00"},
    {"id": "2", "workspace_id": "ws", "status": None, "n": 2, "flag": False, "ts": None},
    {"id": "3", "workspace_id": "ws", "status": "a,b", "n": 3, "flag": None, "ts": "2026-09-03T00:00:00+00:00"},
    {"id": "4", "workspace_id": "other", "status": "new", "n": None, "flag": True, "ts": "2026-09-02T00:00:00+00:00"},
]

QUERIES = [
    {"workspace_id": "ws"},
    {"flag": {"$ne": True}},
    {"flag": {"$ne": False}},
    {"flag": True},
    {"status": {"$ne": "new"}},
    {"status": {"$ne": "a,b"}},
    {"status": None},
    {"status": {"$in": ["new", None]}},
    {"status": {"$nin": ["new"]}},
    {"status": {"$nin": ["new", None]}},
    {"status": {"$exists": False}},
    {"n": {"$gte": 2}},
    {"n": {"$gt": 1, "$lte": 3}},
    {"ts": {"$gte": datetime(2026, 9, 2, tzinfo=timezone.utc)}},
    {"$and": [{"workspace_id": "ws"}, {"n": {"$lt": 3}}]},
    {"$or": [{"status": "new"}, {"n": 3}]},
]


def _mongo_view(row):
    # Column NULL ≙ missing field (what the facades' row → doc mapping does).
    return {k: v for k, v in row.items() if v is not None}


@pytest.mark.asyncio
@pytest.mark.parametrize("query", QUERIES, ids=lambda q: str(q))
async def test_pushdown_plus_residual_equals_mongo(query):
    fake = FakePostgrest({"t": TableSpec(COLS)})
    fake.rows["t"] = [dict(d) for d in DOCS]
    params, residual = sb_rest.split_filter(query, COLS)
    resp = await fake.request("GET", "/rest/v1/t", params={**params, "select": "*"})
    assert resp.status_code == 200, resp.json()
    got = {r["id"] for r in resp.json() if mc.match(_mongo_view(r), residual)}
    ts_query = {k: v for k, v in query.items()}
    expected = {
        d["id"] for d in DOCS
        if mc.match({**_mongo_view(d), **({"ts": datetime.fromisoformat(d["ts"])} if d.get("ts") else {})}, ts_query)
    }
    assert got == expected
