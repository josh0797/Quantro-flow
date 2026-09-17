"""
Shared test fixtures. No real MongoDB is available in CI/dev sandboxes
for this task, so FakeAsyncCollection below is a tiny in-memory stand-in
implementing just the Motor calls this codebase's new modules use
(find_one, insert_one, update_one, delete_one, count_documents). It is
NOT a general Mongo emulator — do not extend it to cover query
operators the new tests don't need.
"""
from __future__ import annotations

import copy
import os
from typing import Any, Dict, List, Optional

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("INTEGRATIONS_ENCRYPTION_KEY", Fernet.generate_key().decode())


def _match(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for k, v in query.items():
        if isinstance(v, dict) and "$in" in v:
            if doc.get(k) not in v["$in"]:
                return False
        elif isinstance(v, dict) and "$gte" in v:
            if doc.get(k) is None or doc.get(k) < v["$gte"]:
                return False
        elif doc.get(k) != v:
            return False
    return True


class FakeAsyncCollection:
    def __init__(self):
        self._docs: List[Dict[str, Any]] = []

    async def find_one(self, query: Dict[str, Any], projection: Optional[Dict[str, int]] = None):
        for doc in self._docs:
            if _match(doc, query):
                return _project(copy.deepcopy(doc), projection)
        return None

    async def insert_one(self, doc: Dict[str, Any]):
        from pymongo.errors import DuplicateKeyError

        # Emulate a unique index on (workspace_id, action_id, idempotency_key)
        # when idempotency_key is present — the only uniqueness constraint
        # the new code relies on.
        if doc.get("idempotency_key"):
            for existing in self._docs:
                if (
                    existing.get("workspace_id") == doc.get("workspace_id")
                    and existing.get("action_id") == doc.get("action_id")
                    and existing.get("idempotency_key") == doc.get("idempotency_key")
                ):
                    raise DuplicateKeyError("duplicate idempotency_key")
        self._docs.append(copy.deepcopy(doc))
        return doc

    async def update_one(self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False):
        for doc in self._docs:
            if _match(doc, query):
                doc.update(update.get("$set", {}))
                for key in update.get("$unset", {}):
                    doc.pop(key, None)
                return
        if upsert:
            new_doc = dict(query)
            new_doc.update(update.get("$set", {}))
            self._docs.append(new_doc)


    async def find_one_and_update(self, query: Dict[str, Any], update: Dict[str, Any], projection: Optional[Dict[str, int]] = None, return_document=None):
        for doc in self._docs:
            if _match(doc, query):
                doc.update(update.get("$set", {}))
                for key in update.get("$unset", {}):
                    doc.pop(key, None)
                return _project(copy.deepcopy(doc), projection)
        return None

    async def delete_one(self, query: Dict[str, Any]):
        for i, doc in enumerate(self._docs):
            if _match(doc, query):
                del self._docs[i]
                return

    async def delete_many(self, query: Dict[str, Any]):
        self._docs = [d for d in self._docs if not _match(d, query)]

    async def count_documents(self, query: Dict[str, Any]) -> int:
        return sum(1 for d in self._docs if _match(d, query))

    def find(self, query: Dict[str, Any]):
        return _FakeCursor([d for d in self._docs if _match(d, query)])


class _FakeCursor:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = docs

    async def to_list(self, n: int):
        return copy.deepcopy(self._docs[:n])


def _project(doc: Dict[str, Any], projection: Optional[Dict[str, int]]):
    if not projection:
        return doc
    exclude = {k for k, v in projection.items() if v == 0}
    if exclude:
        return {k: v for k, v in doc.items() if k not in exclude}
    include = {k for k, v in projection.items() if v == 1}
    return {k: v for k, v in doc.items() if k in include}


@pytest.fixture
def fake_collection():
    return FakeAsyncCollection()
