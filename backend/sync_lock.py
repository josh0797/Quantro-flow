"""Atomic sync lease for provider autosync (Supabase, or legacy Mongo).

Keyed by ``provider:workspace_id``. Acquire only when the lock row is
missing or ``expires_at <= now``. Lease expires by time if the process dies.
Correctness comes from the atomic acquire predicate +
``QUANTRO_SYNC_LOCK_WINDOW_SECONDS``.

* ``acquire_sync_lock_lease_supabase`` — ``public.flow_sync_locks``: one
  conditional ``UPDATE … WHERE expires_at <= now`` (takes over an expired
  lease), else ``INSERT … ON CONFLICT DO NOTHING`` (first lease). Postgres
  row locking makes exactly one concurrent caller win either step.
* ``acquire_sync_lock_lease`` — legacy Mongo ``sync_locks`` collection
  (used while ``QUANTRO_DOCS_PRIMARY=mongo``).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

SYNC_LOCKS_TABLE = "flow_sync_locks"


async def acquire_sync_lock_lease_supabase(
    *,
    provider: str,
    workspace_id: str,
    window_seconds: int,
    owner_id: Optional[str] = None,
    now: Optional[datetime] = None,
    requester: Optional[Callable[..., Awaitable[Any]]] = None,
) -> bool:
    """Atomically acquire a sync lease in ``flow_sync_locks``.

    Raises ``sb_rest.SupabaseStoreError`` when Supabase cannot be reached
    (the caller decides whether to fall back to an in-process lock).
    """
    import sb_rest

    req = requester or sb_rest.request
    key = f"{provider}:{workspace_id}"
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    expires_at = now_dt + timedelta(seconds=int(window_seconds))
    fields = {
        "provider": provider,
        "workspace_id": workspace_id,
        "owner_id": owner_id,
        "locked_at": sb_rest.iso(now_dt),
        "expires_at": sb_rest.iso(expires_at),
    }

    # 1) Take over an expired lease (single conditional UPDATE).
    resp = await req(
        "PATCH", f"/rest/v1/{SYNC_LOCKS_TABLE}",
        json=fields,
        params={
            "lock_key": f"eq.{key}",
            "expires_at": f"lte.{sb_rest.iso(now_dt)}",
            "select": "lock_key",
        },
        prefer="return=representation",
    )
    if resp is None or resp.status_code >= 400:
        raise sb_rest.SupabaseStoreError(
            f"sync lock update failed: {sb_rest.short_error(resp)}", table=SYNC_LOCKS_TABLE,
        )
    if resp.json():
        return True

    # 2) First lease for this key; a live lease makes the insert a no-op.
    resp = await req(
        "POST", f"/rest/v1/{SYNC_LOCKS_TABLE}?on_conflict=lock_key",
        json={"lock_key": key, **fields},
        prefer="resolution=ignore-duplicates,return=representation",
    )
    if resp is None or resp.status_code >= 400:
        raise sb_rest.SupabaseStoreError(
            f"sync lock insert failed: {sb_rest.short_error(resp)}", table=SYNC_LOCKS_TABLE,
        )
    return bool(resp.json())


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
    from mongo_compat import DuplicateKeyError

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
