"""Phase 6.1 — inbox_items dual-write (Mongo ↔ Supabase).

Motor-like facade so ``server.py`` can keep ``inbox_col.find / update_one /
insert_many / update_many / count_documents`` call sites unchanged.

Flags
-----
``QUANTRO_INBOX_PRIMARY`` (default ``mongo``):
  * ``mongo``     — reads from Mongo; dual-write Supabase when configured.
  * ``supabase``  — reads from Supabase first (Mongo fallback); Mongo
                    writes gated by ``QUANTRO_INBOX_MONGO_MIRROR`` if set,
                    else ``QUANTRO_MONGO_MIRROR`` (default on).

Graceful degrade: missing tables / transport errors → log + keep Mongo.
Never log full email bodies in bulk (error snippets truncate ``body`` /
``preview``).

See docs/phase6-inbox-items.md.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

logger = logging.getLogger("quantro.inbox.store")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

_INBOX_PRIMARY_RAW = (os.environ.get("QUANTRO_INBOX_PRIMARY") or "mongo").lower().strip()
INBOX_PRIMARY = _INBOX_PRIMARY_RAW if _INBOX_PRIMARY_RAW in {"mongo", "supabase"} else "mongo"

_MIRROR_DEDICATED = os.environ.get("QUANTRO_INBOX_MONGO_MIRROR")
if _MIRROR_DEDICATED is None or _MIRROR_DEDICATED == "":
    _MIRROR_RAW = (os.environ.get("QUANTRO_MONGO_MIRROR") or "1").lower().strip()
else:
    _MIRROR_RAW = _MIRROR_DEDICATED.lower().strip()
MONGO_MIRROR = _MIRROR_RAW not in {"0", "false", "no", "off"}

TABLE_INBOX = "inbox_items"

# Columns that map 1:1 Mongo ↔ Postgres (plus jsonb / datetime handling).
_KNOWN_COLS = frozenset({
    "inbox_id", "workspace_id",
    "from_name", "from_email", "from_address",
    "subject", "body", "preview",
    "received_at", "read", "status",
    "ai_intent", "ai_suggested_action",
    "contact_id", "source",
    "gmail_id", "ms_id", "thread_id",
    "label_ids", "categories",
    "is_real", "is_simulation", "hidden_by_real",
    "priority", "synced_at",
    "created_at", "updated_at",
})
_DT_KEYS = frozenset({"received_at", "synced_at", "created_at", "updated_at"})
_JSON_KEYS = frozenset({"ai_intent", "ai_suggested_action", "label_ids", "categories"})
_SENSITIVE_LOG_KEYS = frozenset({"body", "preview"})


def _is_sb_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def is_inbox_supabase_primary() -> bool:
    return INBOX_PRIMARY == "supabase" and _is_sb_configured()


def is_inbox_dual_write_enabled() -> bool:
    return _is_sb_configured()


def is_inbox_mongo_write_enabled() -> bool:
    if not _is_sb_configured():
        return True
    if INBOX_PRIMARY != "supabase":
        return True
    return MONGO_MIRROR


def inbox_health() -> Dict[str, Any]:
    return {
        "inbox_primary": INBOX_PRIMARY,
        "supabase_configured": _is_sb_configured(),
        "dual_write": is_inbox_dual_write_enabled(),
        "mongo_write": is_inbox_mongo_write_enabled(),
        "mongo_mirror": MONGO_MIRROR,
        "next_domains": ["activity_events", "contacts", "calendar"],
    }


def _service_headers(prefer: Optional[str] = None) -> Optional[Dict[str, str]]:
    if not SUPABASE_SERVICE_ROLE_KEY:
        return None
    h = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def _table_missing(resp: Optional[httpx.Response]) -> bool:
    if resp is None:
        return False
    if resp.status_code == 404:
        return True
    text = (resp.text or "").lower()
    return resp.status_code in (400, 404) and (
        "could not find the table" in text
        or "pgrst205" in text
        or "does not exist" in text
    )


def _safe_err_text(text: str, limit: int = 200) -> str:
    """Truncate error bodies; never echo full email content."""
    if not text:
        return ""
    low = text.lower()
    if '"body"' in low or "preview" in low:
        return text[:80] + "…[truncated sensitive]"
    return text[:limit]


async def _sb_request(
    method: str,
    path: str,
    *,
    json: Optional[Any] = None,
    params: Optional[Dict[str, Any]] = None,
    prefer: Optional[str] = None,
) -> Optional[httpx.Response]:
    if not _is_sb_configured():
        return None
    headers = _service_headers(prefer)
    if not headers:
        return None
    url = f"{SUPABASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, url, headers=headers, json=json, params=params)
        if _table_missing(resp):
            logger.warning(
                "inbox.store: Supabase table missing for %s %s — "
                "apply migration 20260918200000_phase6_inbox_items.sql",
                method, path,
            )
            return None
        return resp
    except Exception as exc:  # noqa: BLE001
        logger.warning("inbox.store %s %s failed: %s", method, path, exc)
        return None


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    if isinstance(value, str):
        return value
    return str(value)


def _parse_dt(value: Any) -> Any:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


def _app_inbox_id(doc: Dict[str, Any]) -> Optional[str]:
    """Mongo seed uses inbox_id; Google/Outlook sync $setOnInsert uses id."""
    return doc.get("inbox_id") or doc.get("id")


def inbox_mongo_to_sb(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Map a Mongo inbox doc (or $set patch) to a Postgres row payload."""
    out: Dict[str, Any] = {}
    for k, v in doc.items():
        if k in {"_id", "id"} and k != "inbox_id":
            # Postgres uuid pk is separate; Mongo `id` is the app id for sync.
            continue
        if k not in _KNOWN_COLS:
            continue
        if k in _DT_KEYS:
            out[k] = _iso(v)
        elif k in _JSON_KEYS:
            out[k] = v  # None stays None for jsonb
        else:
            out[k] = v
    # Prefer explicit inbox_id; fall back to Mongo sync `id`.
    aid = _app_inbox_id(doc)
    if aid and "inbox_id" not in out:
        out["inbox_id"] = aid
    elif aid and not out.get("inbox_id"):
        out["inbox_id"] = aid
    return out


def inbox_sb_to_mongo(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return {}
    out = {k: v for k, v in row.items() if k not in {"id"}}  # drop PG uuid pk
    for k in _DT_KEYS:
        if k in out:
            out[k] = _parse_dt(out[k])
    # Keep `id` alias for sync-shaped docs that historically used `id`.
    if out.get("inbox_id") and "id" not in out:
        out["id"] = out["inbox_id"]
    return out


def _mongo_filter_to_params(query: Dict[str, Any], *, select: str = "*") -> Dict[str, str]:
    """Translate common Motor filters used by inbox routes to PostgREST.

    ``$ne: True`` on nullable bools uses ``not.is.true`` so missing/NULL
    rows match (Mongo semantics for hidden_by_real / is_simulation).
    """
    params: Dict[str, str] = {"select": select}
    for key, val in (query or {}).items():
        if key == "_id":
            continue
        # Map Mongo sync `id` lookups onto inbox_id column.
        col = "inbox_id" if key == "id" else key
        if isinstance(val, dict):
            if "$in" in val:
                items = ",".join(str(x) for x in val["$in"])
                params[col] = f"in.({items})"
            elif "$gte" in val:
                params[col] = f"gte.{_iso(val['$gte'])}"
            elif "$exists" in val:
                if val["$exists"] is False:
                    params[col] = "is.null"
            elif "$ne" in val:
                ne = val["$ne"]
                if isinstance(ne, bool):
                    # SQL NOT (col IS TRUE/FALSE) includes NULL — Mongo-like.
                    params[col] = f"not.is.{str(ne).lower()}"
                elif ne is None:
                    params[col] = "not.is.null"
                else:
                    params[col] = f"neq.{ne}"
            else:
                logger.debug("inbox.store: skipping unsupported filter %s=%s", key, val)
        elif val is None:
            params[col] = "is.null"
        elif isinstance(val, bool):
            params[col] = f"eq.{str(val).lower()}"
        else:
            params[col] = f"eq.{val}"
    return params


def _strip_pg_id(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return doc
    out = dict(doc)
    out.pop("_id", None)
    # Do not expose Postgres uuid as API `id` when we already alias inbox_id→id
    return out


def _project(doc: Optional[Dict[str, Any]], projection: Optional[Dict[str, int]]):
    if doc is None:
        return None
    if not projection:
        return doc
    exclude = {k for k, v in projection.items() if v == 0}
    if exclude and all(v == 0 for v in projection.values()):
        return {k: v for k, v in doc.items() if k not in exclude}
    if exclude:
        return {k: v for k, v in doc.items() if k not in exclude}
    include = {k for k, v in projection.items() if v == 1}
    return {k: v for k, v in doc.items() if k in include}


def _conflict_for_query(query: Dict[str, Any]) -> str:
    """Choose PostgREST on_conflict target from the upsert filter."""
    if query.get("gmail_id"):
        return "workspace_id,gmail_id"
    if query.get("ms_id"):
        return "workspace_id,ms_id"
    return "workspace_id,inbox_id"


class InboxDualWriteCollection:
    """Motor-like facade over Mongo ``inbox_items`` + optional Supabase table."""

    def __init__(self, mongo_col: Any):
        self._mongo = mongo_col
        self.table = TABLE_INBOX

    # ── reads ─────────────────────────────────────────────────────────

    async def find_one(self, query: Dict[str, Any], projection: Optional[Dict[str, int]] = None):
        if is_inbox_supabase_primary():
            row = await self._sb_find_one(query)
            if row is not None:
                return _project(_strip_pg_id(row), projection)
            return await self._mongo.find_one(query, projection) if projection is not None else await self._mongo.find_one(query)
        try:
            return await self._mongo.find_one(query, projection)
        except TypeError:
            return await self._mongo.find_one(query)

    def find(self, query: Dict[str, Any], projection: Optional[Dict[str, int]] = None):
        return _LazyFindCursor(self, query, projection)

    async def count_documents(self, query: Dict[str, Any]) -> int:
        if is_inbox_supabase_primary():
            n = await self._sb_count(query)
            if n is not None:
                return n
        return await self._mongo.count_documents(query)

    # ── writes ────────────────────────────────────────────────────────

    async def insert_one(self, doc: Dict[str, Any]):
        primary_sb = is_inbox_supabase_primary()
        if primary_sb:
            sb_ok = await self._sb_upsert_doc(doc, conflict="workspace_id,inbox_id")
            if sb_ok is False:
                logger.warning("inbox.store: SB insert degraded — writing Mongo")
                return await self._mongo.insert_one(dict(doc))
            if is_inbox_mongo_write_enabled():
                try:
                    await self._mongo.insert_one(dict(doc))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("inbox.store mongo mirror insert_one failed: %s", exc)
            return doc

        result = await self._mongo.insert_one(dict(doc))
        if is_inbox_dual_write_enabled():
            try:
                await self._sb_upsert_doc(doc, conflict="workspace_id,inbox_id")
            except Exception as exc:  # noqa: BLE001
                logger.warning("inbox.store SB dual-write insert_one failed: %s", exc)
        return result

    async def insert_many(self, docs: List[Dict[str, Any]]):
        # Prefer native mongo insert_many when primary=mongo for seed speed.
        if not is_inbox_supabase_primary() and hasattr(self._mongo, "insert_many"):
            result = await self._mongo.insert_many([dict(d) for d in docs])
            if is_inbox_dual_write_enabled():
                for d in docs:
                    try:
                        await self._sb_upsert_doc(d, conflict="workspace_id,inbox_id")
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("inbox.store SB dual-write insert_many item failed: %s", exc)
            return result
        results = []
        for d in docs:
            results.append(await self.insert_one(d))
        return results

    async def update_one(
        self,
        query: Dict[str, Any],
        update: Dict[str, Any],
        upsert: bool = False,
    ):
        fields = (update or {}).get("$set") or {}
        unset = (update or {}).get("$unset") or {}
        set_on_insert = (update or {}).get("$setOnInsert") or {}
        primary_sb = is_inbox_supabase_primary()

        if primary_sb:
            ok = await self._sb_update(
                query, fields, unset=unset, set_on_insert=set_on_insert, upsert=upsert,
            )
            if is_inbox_mongo_write_enabled():
                try:
                    await self._mongo.update_one(query, update, upsert=upsert)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("inbox.store mongo mirror update_one failed: %s", exc)
            return ok

        result = await self._mongo.update_one(query, update, upsert=upsert)
        if is_inbox_dual_write_enabled():
            try:
                await self._sb_update(
                    query, fields, unset=unset, set_on_insert=set_on_insert, upsert=upsert,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("inbox.store SB dual-write update_one failed: %s", _safe_err_text(str(exc)))
        return result

    async def update_many(self, query: Dict[str, Any], update: Dict[str, Any]):
        """Bulk patch (e.g. hidden_by_real after Google sync)."""
        fields = (update or {}).get("$set") or {}
        unset = (update or {}).get("$unset") or {}
        primary_sb = is_inbox_supabase_primary()

        if primary_sb:
            await self._sb_update(query, fields, unset=unset, upsert=False)
            if is_inbox_mongo_write_enabled() and hasattr(self._mongo, "update_many"):
                try:
                    return await self._mongo.update_many(query, update)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("inbox.store mongo mirror update_many failed: %s", exc)
                    return None
            return None

        if hasattr(self._mongo, "update_many"):
            result = await self._mongo.update_many(query, update)
        else:
            # Minimal fakes may only expose update_one — loop.
            result = await self._mongo.update_one(query, update)
        if is_inbox_dual_write_enabled():
            try:
                await self._sb_update(query, fields, unset=unset, upsert=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("inbox.store SB dual-write update_many failed: %s", exc)
        return result

    async def delete_one(self, query: Dict[str, Any]):
        primary_sb = is_inbox_supabase_primary()
        if primary_sb:
            await self._sb_delete(query)
            if is_inbox_mongo_write_enabled():
                try:
                    return await self._mongo.delete_one(query)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("inbox.store mongo mirror delete_one failed: %s", exc)
            return None
        result = await self._mongo.delete_one(query)
        if is_inbox_dual_write_enabled():
            try:
                await self._sb_delete(query)
            except Exception as exc:  # noqa: BLE001
                logger.warning("inbox.store SB dual-write delete_one failed: %s", exc)
        return result

    async def delete_many(self, query: Dict[str, Any]):
        primary_sb = is_inbox_supabase_primary()
        if primary_sb:
            await self._sb_delete(query)
            if is_inbox_mongo_write_enabled() and hasattr(self._mongo, "delete_many"):
                try:
                    return await self._mongo.delete_many(query)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("inbox.store mongo mirror delete_many failed: %s", exc)
            return None
        if hasattr(self._mongo, "delete_many"):
            result = await self._mongo.delete_many(query)
        else:
            result = await self.delete_one(query)
        if is_inbox_dual_write_enabled():
            try:
                await self._sb_delete(query)
            except Exception as exc:  # noqa: BLE001
                logger.warning("inbox.store SB dual-write delete_many failed: %s", exc)
        return result

    async def create_index(self, *args, **kwargs):
        if hasattr(self._mongo, "create_index"):
            return await self._mongo.create_index(*args, **kwargs)
        return None

    # ── Supabase primitives ───────────────────────────────────────────

    async def _sb_find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        params = _mongo_filter_to_params(query)
        params["limit"] = "1"
        resp = await _sb_request("GET", f"/rest/v1/{self.table}", params=params)
        if resp is None or resp.status_code >= 400:
            if resp is not None and resp.status_code >= 400:
                logger.warning(
                    "inbox.store SB find_one → %s %s",
                    resp.status_code, _safe_err_text(resp.text or ""),
                )
            return None
        rows = resp.json()
        if not rows:
            return None
        return inbox_sb_to_mongo(rows[0])

    async def _sb_find_many(self, query: Dict[str, Any], *, limit: int = 100) -> Optional[List[Dict[str, Any]]]:
        params = _mongo_filter_to_params(query)
        params["limit"] = str(limit)
        resp = await _sb_request("GET", f"/rest/v1/{self.table}", params=params)
        if resp is None or resp.status_code >= 400:
            return None
        rows = resp.json() or []
        return [inbox_sb_to_mongo(r) for r in rows]

    async def _sb_count(self, query: Dict[str, Any]) -> Optional[int]:
        params = _mongo_filter_to_params(query, select="*")
        resp = await _sb_request(
            "GET", f"/rest/v1/{self.table}",
            params={**params, "limit": "0"},
            prefer="count=exact",
        )
        if resp is None:
            return None
        cr = resp.headers.get("content-range") or resp.headers.get("Content-Range")
        if cr and "/" in cr:
            try:
                return int(cr.rsplit("/", 1)[-1])
            except ValueError:
                pass
        rows = await self._sb_find_many(query, limit=10000)
        return None if rows is None else len(rows)

    async def _sb_upsert_doc(self, doc: Dict[str, Any], *, conflict: str) -> bool:
        payload = inbox_mongo_to_sb(doc)
        if not payload.get("inbox_id") or not payload.get("workspace_id"):
            logger.warning(
                "inbox.store: skip SB write missing inbox_id/workspace_id keys=%s",
                sorted(k for k in payload if k not in _SENSITIVE_LOG_KEYS),
            )
            return False
        path = f"/rest/v1/{self.table}?on_conflict={conflict}"
        prefer = "resolution=merge-duplicates,return=minimal"
        resp = await _sb_request("POST", path, json=payload, prefer=prefer)
        if resp is None:
            return False
        if resp.status_code == 409:
            return True
        if resp.status_code >= 400:
            logger.warning(
                "inbox.store SB upsert → %s %s",
                resp.status_code, _safe_err_text(resp.text or ""),
            )
            return False
        return True

    async def _sb_update(
        self,
        query: Dict[str, Any],
        fields: Dict[str, Any],
        *,
        unset: Optional[Dict[str, Any]] = None,
        set_on_insert: Optional[Dict[str, Any]] = None,
        upsert: bool = False,
    ) -> Any:
        if not fields and not unset and not (upsert and set_on_insert):
            return None

        if upsert:
            # Prefer upsert via on_conflict so sync + seed stay idempotent.
            merged = {**{k: query.get(k) for k in ("workspace_id", "inbox_id", "gmail_id", "ms_id", "id") if k in query}}
            merged.update(set_on_insert or {})
            merged.update(fields or {})
            # Ensure app id for NOT NULL inbox_id column.
            if not merged.get("inbox_id"):
                merged["inbox_id"] = merged.get("id") or _app_inbox_id(merged)
            conflict = _conflict_for_query(query if query.get("gmail_id") or query.get("ms_id") else merged)
            # If conflicting on gmail/ms, still need inbox_id in payload.
            if not merged.get("inbox_id"):
                # Generate-less: leave to caller; sync always $setOnInsert id.
                logger.warning("inbox.store upsert without inbox_id/id — SB skip")
                return False
            return await self._sb_upsert_doc(merged, conflict=conflict)

        patch = inbox_mongo_to_sb(fields) if fields else {}
        # Never rewrite identity keys via accidental $set.
        for k in ("workspace_id", "inbox_id", "gmail_id", "ms_id"):
            if k in query and k in patch and patch[k] == query.get(k):
                pass  # ok if same
        if unset:
            for k in unset:
                col = "inbox_id" if k == "id" else k
                if col in _KNOWN_COLS:
                    patch[col] = None
        params = _mongo_filter_to_params(query, select="")
        params.pop("select", None)
        resp = await _sb_request(
            "PATCH", f"/rest/v1/{self.table}",
            json=patch, params=params, prefer="return=minimal",
        )
        if resp is not None and resp.status_code >= 400:
            logger.warning(
                "inbox.store SB update → %s %s",
                resp.status_code, _safe_err_text(resp.text or ""),
            )
        return resp

    async def _sb_delete(self, query: Dict[str, Any]) -> None:
        params = _mongo_filter_to_params(query, select="")
        params.pop("select", None)
        resp = await _sb_request(
            "DELETE", f"/rest/v1/{self.table}",
            params=params, prefer="return=minimal",
        )
        if resp is not None and resp.status_code >= 400:
            logger.warning(
                "inbox.store SB delete → %s %s",
                resp.status_code, _safe_err_text(resp.text or ""),
            )


class _LazyFindCursor:
    """Mimics Motor cursor: find() → sort() → to_list()."""

    def __init__(
        self,
        store: InboxDualWriteCollection,
        query: Dict[str, Any],
        projection: Optional[Dict[str, int]],
    ):
        self._store = store
        self._query = query
        self._projection = projection
        self._sort: Optional[Tuple[str, int]] = None

    def sort(self, key: str, direction: int = 1):
        self._sort = (key, direction)
        return self

    async def to_list(self, n: int) -> List[Dict[str, Any]]:
        if is_inbox_supabase_primary():
            params = _mongo_filter_to_params(self._query)
            params["limit"] = str(n)
            if self._sort:
                key, direction = self._sort
                params["order"] = f"{key}.{'desc' if direction < 0 else 'asc'}"
            resp = await _sb_request("GET", f"/rest/v1/{self._store.table}", params=params)
            if resp is not None and resp.status_code < 400:
                rows = resp.json() or []
                return [
                    _project(_strip_pg_id(inbox_sb_to_mongo(r)), self._projection)
                    for r in rows
                ]
        try:
            cursor = (
                self._store._mongo.find(self._query, self._projection)
                if self._projection is not None
                else self._store._mongo.find(self._query)
            )
        except TypeError:
            cursor = self._store._mongo.find(self._query)
        if self._sort and hasattr(cursor, "sort"):
            cursor = cursor.sort(self._sort[0], self._sort[1])
        if hasattr(cursor, "to_list"):
            return await cursor.to_list(n)
        return []


def wrap_inbox_col(mongo_col: Any) -> InboxDualWriteCollection:
    """Public wiring helper — drop-in for ``db['inbox_items']``."""
    return InboxDualWriteCollection(mongo_col)
