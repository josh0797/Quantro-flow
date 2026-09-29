"""In-memory Motor stand-in (client → database → collection) built on
mongo_compat's matcher/updater. Enough of the API for server.py's startup
jobs under the fly.toml pins and for the backfill's streaming reader.

``cursor.to_list(None)`` on a collection marked ``stream_only`` raises, so a
test can prove a reader never materializes a whole collection.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

import mongo_compat as mc


class WholeCollectionLoad(AssertionError):
    pass


class FakeMotorCursor:
    def __init__(self, col: "FakeMotorCollection", query: Dict[str, Any], projection: Optional[Dict[str, Any]],
                 sort: Any = None, skip: int = 0, limit: int = 0):
        self._col = col
        self._query = query
        self._projection = projection
        self._sort = mc.normalize_sort(sort) if sort else []
        self._skip = skip
        self._limit = limit
        self._iter = None
        self.batch_size_set: Optional[int] = None

    def sort(self, key_or_list: Any, direction: Optional[int] = None) -> "FakeMotorCursor":
        self._sort = mc.normalize_sort(key_or_list, direction)
        return self

    def skip(self, n: int) -> "FakeMotorCursor":
        self._skip = n
        return self

    def limit(self, n: int) -> "FakeMotorCursor":
        self._limit = n
        return self

    def batch_size(self, n: int) -> "FakeMotorCursor":
        self.batch_size_set = n
        return self

    def _rows(self) -> List[Dict[str, Any]]:
        rows = [copy.deepcopy(d) for d in self._col.docs if mc.match(d, self._query)]
        if self._sort:
            rows = mc.sort_docs(rows, self._sort)
        if self._skip:
            rows = rows[self._skip:]
        if self._limit:
            rows = rows[: self._limit]
        return [mc.project(r, self._projection) for r in rows]

    async def to_list(self, length: Optional[int] = None) -> List[Dict[str, Any]]:
        if self._col.stream_only and not length:
            raise WholeCollectionLoad(f"to_list(None) on {self._col.name}")
        rows = self._rows()
        return rows[:length] if length else rows

    def __aiter__(self):
        self._col.streamed += 1
        self._iter = iter(self._rows())
        return self

    async def __anext__(self) -> Dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class FakeMotorCollection:
    def __init__(self, name: str):
        self.name = name
        self.docs: List[Dict[str, Any]] = []
        self.stream_only = False
        self.streamed = 0

    # reads
    def find(self, query: Optional[Dict[str, Any]] = None, projection: Optional[Dict[str, Any]] = None,
             *_: Any, sort: Any = None, skip: int = 0, limit: int = 0, **__: Any) -> FakeMotorCursor:
        return FakeMotorCursor(self, query or {}, projection, sort=sort, skip=skip, limit=limit)

    async def find_one(self, query: Optional[Dict[str, Any]] = None, projection: Optional[Dict[str, Any]] = None,
                       *_: Any, sort: Any = None, **__: Any) -> Optional[Dict[str, Any]]:
        rows = FakeMotorCursor(self, query or {}, projection, sort=sort, limit=1)._rows()
        return rows[0] if rows else None

    async def count_documents(self, query: Optional[Dict[str, Any]] = None, **_: Any) -> int:
        return sum(1 for d in self.docs if mc.match(d, query or {}))

    # writes
    async def insert_one(self, doc: Dict[str, Any], *_: Any, **__: Any) -> mc.InsertOneResult:
        if doc.get("_id") is None:
            doc["_id"] = mc.new_object_id()   # Motor mutates the caller's dict too
        if any(d.get("_id") == doc["_id"] for d in self.docs):
            raise mc.DuplicateKeyError(f"duplicate _id in {self.name}")
        self.docs.append(copy.deepcopy(doc))
        return mc.InsertOneResult(doc["_id"])

    async def insert_many(self, docs: List[Dict[str, Any]], *_: Any, **__: Any) -> mc.InsertManyResult:
        return mc.InsertManyResult([(await self.insert_one(d)).inserted_id for d in docs])

    async def _update(self, query: Dict[str, Any], update: Dict[str, Any], *, upsert: bool, many: bool) -> mc.UpdateResult:
        matched = modified = 0
        for i, d in enumerate(self.docs):
            if not mc.match(d, query):
                continue
            matched += 1
            new = mc.apply_update(d, update)
            if new != d:
                modified += 1
                self.docs[i] = new
            if not many:
                break
        if matched or not upsert:
            return mc.UpdateResult(matched, modified)
        new = mc.apply_update(mc.seed_from_query(query), update, is_insert=True)
        new.setdefault("_id", mc.new_object_id())
        self.docs.append(new)
        return mc.UpdateResult(0, 0, new["_id"])

    async def update_one(self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False, **_: Any):
        return await self._update(query, update, upsert=upsert, many=False)

    async def update_many(self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False, **_: Any):
        return await self._update(query, update, upsert=upsert, many=True)

    async def replace_one(self, query: Dict[str, Any], replacement: Dict[str, Any], upsert: bool = False, **_: Any):
        return await self._update(query, replacement, upsert=upsert, many=False)

    async def find_one_and_update(self, query: Dict[str, Any], update: Dict[str, Any],
                                  projection: Optional[Dict[str, Any]] = None, return_document: Any = False,
                                  upsert: bool = False, sort: Any = None, **_: Any):
        before = await self.find_one(query, sort=sort)
        res = await self._update({"_id": before["_id"]} if before else query, update, upsert=upsert, many=False)
        if before is None and res.upserted_id is None:
            return None
        after = await self.find_one({"_id": before["_id"] if before else res.upserted_id})
        return mc.project(after if return_document else before, projection)

    async def find_one_and_delete(self, query: Dict[str, Any], projection: Optional[Dict[str, Any]] = None, **_: Any):
        doc = await self.find_one(query)
        if doc is not None:
            self.docs = [d for d in self.docs if d.get("_id") != doc["_id"]]
        return mc.project(doc, projection)

    async def delete_one(self, query: Dict[str, Any], **_: Any) -> mc.DeleteResult:
        for i, d in enumerate(self.docs):
            if mc.match(d, query):
                del self.docs[i]
                return mc.DeleteResult(1)
        return mc.DeleteResult(0)

    async def delete_many(self, query: Dict[str, Any], **_: Any) -> mc.DeleteResult:
        before = len(self.docs)
        self.docs = [d for d in self.docs if not mc.match(d, query)]
        return mc.DeleteResult(before - len(self.docs))

    async def create_index(self, *_: Any, **__: Any) -> str:
        return "idx"


class FakeMotorDatabase:
    def __init__(self):
        self.collections: Dict[str, FakeMotorCollection] = {}

    def __getitem__(self, name: str) -> FakeMotorCollection:
        return self.collections.setdefault(name, FakeMotorCollection(name))

    async def list_collection_names(self) -> List[str]:
        return [n for n, c in self.collections.items() if c.docs]


class FakeMotorClient:
    def __init__(self):
        self.databases: Dict[str, FakeMotorDatabase] = {}
        self.closed = False

    def __getitem__(self, name: str) -> FakeMotorDatabase:
        return self.databases.setdefault(name, FakeMotorDatabase())

    def close(self) -> None:
        self.closed = True
