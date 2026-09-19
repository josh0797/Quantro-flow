"""Atomic sync lock lease — concurrency + expiry re-acquire."""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from pymongo.errors import DuplicateKeyError


class AtomicLockCollection:
    """In-memory lock collection with asyncio mutual exclusion so concurrent
    gather() callers exercise the same race windows as multi-instance Mongo."""

    def __init__(self):
        self._docs: Dict[Any, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def find_one_and_update(self, query, update, return_document=None, upsert=False):
        async with self._lock:
            await asyncio.sleep(0)
            for _id, doc in list(self._docs.items()):
                if _match_lock(doc, query):
                    doc.update(update.get("$set", {}))
                    return copy.deepcopy(doc)
            return None

    async def insert_one(self, doc):
        async with self._lock:
            await asyncio.sleep(0)
            _id = doc.get("_id")
            if _id in self._docs:
                raise DuplicateKeyError("E11000 duplicate key")
            self._docs[_id] = copy.deepcopy(doc)
            return doc

    async def find_one(self, query, projection=None):
        async with self._lock:
            for doc in self._docs.values():
                if _match_lock(doc, query):
                    return copy.deepcopy(doc)
            return None


def _match_lock(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for k, v in query.items():
        if k == "$or":
            if not any(_match_lock(doc, clause) for clause in v):
                return False
        elif isinstance(v, dict) and "$lte" in v:
            if doc.get(k) is None or doc.get(k) > v["$lte"]:
                return False
        elif isinstance(v, dict) and "$exists" in v:
            exists = k in doc
            if bool(v["$exists"]) != exists:
                return False
        elif doc.get(k) != v:
            return False
    return True


@pytest.mark.asyncio
async def test_n_simultaneous_acquires_exactly_one_wins():
    # Import without booting full FastAPI app: load the helper via exec of the
    # function source is brittle; import server module pieces carefully.
    import importlib
    import sys
    import os

    # Minimal env so server import side-effects are quiet where possible.
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "quantro_test_lock")
    os.environ.setdefault("INTEGRATIONS_ENCRYPTION_KEY", "x" * 44)

    # Import acquire_sync_lock_lease from server — may pull heavy deps.
    from sync_lock import acquire_sync_lock_lease

    col = AtomicLockCollection()
    n = 20
    results = await asyncio.gather(
        *[
            acquire_sync_lock_lease(
                col,
                provider="google",
                workspace_id="ws-lock",
                window_seconds=300,
                owner_id=f"owner-{i}",
            )
            for i in range(n)
        ]
    )
    assert sum(1 for r in results if r) == 1
    assert sum(1 for r in results if not r) == n - 1
    assert len(col._docs) == 1
    lease = next(iter(col._docs.values()))
    assert lease["provider"] == "google"
    assert lease["workspace_id"] == "ws-lock"
    assert "expires_at" in lease
    assert "locked_at" in lease


@pytest.mark.asyncio
async def test_expired_lease_is_re_acquirable():
    from sync_lock import acquire_sync_lock_lease

    col = AtomicLockCollection()
    now = datetime.now(timezone.utc)
    assert await acquire_sync_lock_lease(
        col, provider="microsoft", workspace_id="ws2", window_seconds=60, now=now,
    )
    # Force expiry
    key = "microsoft:ws2"
    col._docs[key]["expires_at"] = now - timedelta(seconds=1)
    col._docs[key]["locked_at"] = now - timedelta(seconds=120)

    later = now + timedelta(seconds=5)
    assert await acquire_sync_lock_lease(
        col, provider="microsoft", workspace_id="ws2", window_seconds=60, now=later,
        owner_id="reclaimer",
    )
    assert col._docs[key]["owner_id"] == "reclaimer"
    assert col._docs[key]["expires_at"] > later

    # Still held — second acquire fails
    assert not await acquire_sync_lock_lease(
        col, provider="microsoft", workspace_id="ws2", window_seconds=60, now=later,
    )
