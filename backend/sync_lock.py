"""Atomic Mongo sync lease for provider autosync.

Keyed by ``provider:workspace_id``. Acquire only when the lock document is
missing or ``expires_at <= now``. Lease expires by time if the process dies.
Optional TTL index on ``expires_at`` is operational only — correctness comes
from the atomic acquire predicate + ``QUANTRO_SYNC_LOCK_WINDOW_SECONDS``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional


async def acquire_sync_lock_lease(
    lock_col: Any,
    *,
    provider: str,
    workspace_id: str,
    window_seconds: int,
    owner_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Atomically acquire a sync lease for ``provider:workspace_id``.

    Uses ``find_one_and_update`` when the lease is missing-or-expired, then
    ``insert_one`` if absent. Concurrent callers: exactly one wins.
    """
    from pymongo import ReturnDocument
    from pymongo.errors import DuplicateKeyError

    key = f"{provider}:{workspace_id}"
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    expires_at = now_dt + timedelta(seconds=int(window_seconds))
    fields = {
        "provider": provider,
        "workspace_id": workspace_id,
        "locked_at": now_dt,
        "expires_at": expires_at,
    }
    if owner_id:
        fields["owner_id"] = owner_id

    query = {
        "_id": key,
        "$or": [
            {"expires_at": {"$exists": False}},
            {"expires_at": None},
            {"expires_at": {"$lte": now_dt}},
        ],
    }

    try:
        try:
            doc = await lock_col.find_one_and_update(
                query,
                {"$set": fields},
                return_document=ReturnDocument.AFTER,
            )
        except TypeError:
            doc = await lock_col.find_one_and_update(query, {"$set": fields})
        if doc is not None:
            return True
    except Exception:  # noqa: BLE001
        pass

    try:
        await lock_col.insert_one({"_id": key, **fields})
        return True
    except DuplicateKeyError:
        return False
    except Exception:  # noqa: BLE001
        return False
