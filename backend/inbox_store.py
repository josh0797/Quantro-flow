"""Phase 6.1 — inbox_items dual-write (Mongo ↔ Supabase).

Motor-like facade so ``server.py`` can keep ``inbox_col.find / update_one /
insert_many / update_many / count_documents`` call sites unchanged.

Flags
-----
``QUANTRO_INBOX_PRIMARY`` (default ``supabase`` since the Mongo exit):
  * ``mongo``     — reads from Mongo; dual-write Supabase when configured.
  * ``supabase``  — reads/writes Supabase. Mongo is only touched while it is
                    kept as a mirror (``QUANTRO_INBOX_MONGO_MIRROR`` if set,
                    else ``QUANTRO_MONGO_MIRROR``; default off): writes are
                    replayed there and a Supabase miss/error falls back to it.
                    Mirror off → Supabase failures raise
                    ``sb_rest.SupabaseStoreError`` instead of dropping data.

Filters PostgREST cannot express exactly are evaluated in Python on the
fetched rows (sb_rest.split_filter + mongo_compat.match). Fields without a
column land in the ``extra`` jsonb, so nothing is dropped.
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

import mongo_compat as mc
import sb_rest
import storage_flags
from sb_rest import SupabaseStoreError

logger = logging.getLogger("quantro.inbox.store")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# Snapshot at import (tests reload the module with a patched env).
INBOX_PRIMARY = storage_flags.parse_primary("QUANTRO_INBOX_PRIMARY")
MONGO_MIRROR = storage_flags.parse_mirror("QUANTRO_INBOX_MONGO_MIRROR")

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
    # Policy / auto-execution outcome (SmartInbox reads these).
    "policy_action", "escalation",
    "auto_executed", "auto_executed_at", "execution_source", "execution_results",
    # Catch-all for any other field (never dropped).
    "extra",
})
_DT_KEYS = frozenset({"received_at", "synced_at", "created_at", "updated_at", "auto_executed_at"})
_JSON_KEYS = frozenset({
    "ai_intent", "ai_suggested_action", "label_ids", "categories",
    "escalation", "execution_results", "extra",
})
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


def _mongo_fallback_ok() -> bool:
    """Supabase primary consults Mongo only while it is kept as a mirror."""
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


def inbox_mongo_to_sb(doc: Dict[str, Any], *, full: bool = False) -> Dict[str, Any]:
    """Map a Mongo inbox doc (or $set patch) to a Postgres row payload.

    Unknown fields go to ``extra`` (jsonb) instead of being dropped.
    ``full=True`` (whole-document writes) always sends ``extra`` so fields
    removed from the doc are removed from the row too.
    """
    out: Dict[str, Any] = {}
    extra: Dict[str, Any] = {}
    for k, v in doc.items():
        if k in {"_id", "id"} and k != "inbox_id":
            # Postgres uuid pk is separate; Mongo `id` is the app id for sync.
            continue
        if k == "extra":
            if isinstance(v, dict):
                extra.update(mc.to_json(v))
            else:
                extra["extra"] = mc.to_json(v)
            continue
        if k not in _KNOWN_COLS:
            extra[k] = mc.to_json(v)
            continue
        if k in _DT_KEYS:
            out[k] = _iso(v)
        elif k in _JSON_KEYS:
            out[k] = mc.to_json(v)  # None stays None for jsonb
        else:
            out[k] = v
    if extra or full:
        out["extra"] = extra
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
    out = {k: v for k, v in row.items() if k not in {"id", "extra"}}  # drop PG uuid pk
    for k in _DT_KEYS:
        if k in out:
            out[k] = _parse_dt(out[k])
    extra_val = row.get("extra")
    for k, v in (extra_val.items() if isinstance(extra_val, dict) else ()):
        out.setdefault(k, mc.from_json(v))
    # Keep `id` alias for sync-shaped docs that historically used `id`.
    if out.get("inbox_id") and "id" not in out:
        out["id"] = out["inbox_id"]
    return out


def _split(query: Dict[str, Any]):
    """(PostgREST params, residual Mongo filter). Raises sb_rest.Impossible."""
    return sb_rest.split_filter(
        query, _KNOWN_COLS - {"extra"}, aliases={"id": "inbox_id"}, json_cols=_JSON_KEYS,
    )


def _mongo_filter_to_params(query: Dict[str, Any], *, select: str = "*") -> Dict[str, str]:
    """PostgREST params for the exactly-expressible part of a Motor filter.

    ``$ne: True`` on nullable bools uses ``not.is.true`` so missing/NULL
    rows match (Mongo semantics for hidden_by_real / is_simulation).
    Callers that must honour the whole filter use ``_split`` and apply the
    residual in Python.
    """
    try:
        params, _residual = _split(query)
    except sb_rest.Impossible:
        params = {"inbox_id": "is.null", "and": "(inbox_id.not.is.null)"}
    out: Dict[str, str] = {"select": select}
    out.update(params)
    return out


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


async def _req(method: str, path: str, **kwargs: Any):
    """Late-bound so tests can patch ``inbox_store._sb_request``."""
    return await _sb_request(method, path, **kwargs)


_ORDER_DEFAULT = "created_at.asc,id.asc"


class InboxDualWriteCollection:
    """Motor-like facade over Mongo ``inbox_items`` + optional Supabase table."""

    def __init__(self, mongo_col: Any):
        self._mongo = mongo_col
        self.table = TABLE_INBOX

    # ── Supabase read primitives ──────────────────────────────────────
    async def _sb_rows(
        self,
        query: Dict[str, Any],
        *,
        sort: Optional[List[Tuple[str, int]]] = None,
        skip: int = 0,
        limit: int = 0,
    ) -> List[Dict[str, Any]]:
        """Mongo-shaped docs (+``_pk``) matching the WHOLE filter. Raises on error."""
        try:
            params, residual = _split(query)
        except sb_rest.Impossible:
            return []
        params["select"] = "*"
        order = sb_rest.order_param(sort or [], _KNOWN_COLS, aliases={"id": "inbox_id"}) if sort else _ORDER_DEFAULT
        exact = not residual and (order is not None)
        rows = await sb_rest.fetch_all(
            _req, self.table, params,
            order=order or _ORDER_DEFAULT,
            limit=limit if (exact and limit) else None,
            offset=skip if exact else 0,
        )
        if rows is None:
            raise SupabaseStoreError("inbox_items read failed", table=self.table)
        docs = []
        for r in rows:
            d = inbox_sb_to_mongo(r)
            if residual and not mc.match(d, residual):
                continue
            d["_pk"] = r.get("id")
            docs.append(d)
        if not exact:
            if sort:
                docs = mc.sort_docs(docs, sort)
            if skip:
                docs = docs[skip:]
            if limit:
                docs = docs[:limit]
        return docs

    @staticmethod
    def _public(doc: Dict[str, Any], projection: Optional[Dict[str, int]]) -> Dict[str, Any]:
        d = {k: v for k, v in doc.items() if k != "_pk"}
        return _project(_strip_pg_id(d), projection)

    async def _sb_find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        docs = await self._sb_rows(query, limit=1)
        if not docs:
            return None
        return {k: v for k, v in docs[0].items() if k != "_pk"}

    async def _sb_find_many(self, query: Dict[str, Any], *, limit: int = 100) -> Optional[List[Dict[str, Any]]]:
        try:
            docs = await self._sb_rows(query, limit=limit)
        except SupabaseStoreError:
            return None
        return [{k: v for k, v in d.items() if k != "_pk"} for d in docs]

    async def _sb_count(self, query: Dict[str, Any]) -> Optional[int]:
        try:
            params, residual = _split(query)
        except sb_rest.Impossible:
            return 0
        if not residual:
            n = await sb_rest.count_exact(_req, self.table, params)
            if n is not None:
                return n
        try:
            return len(await self._sb_rows(query))
        except SupabaseStoreError:
            return None

    # ── reads ─────────────────────────────────────────────────────────

    async def find_one(self, query: Dict[str, Any], projection: Optional[Dict[str, int]] = None, **_: Any):
        if is_inbox_supabase_primary():
            try:
                row = await self._sb_find_one(query)
            except SupabaseStoreError:
                if not _mongo_fallback_ok():
                    raise
                row = None
                logger.warning("%s inbox.store: Supabase read failed — Mongo mirror fallback", storage_flags.MONGO_ONLY)
            if row is not None:
                return _project(_strip_pg_id(row), projection)
            if not _mongo_fallback_ok():
                return None
            doc = await self._mongo.find_one(query, projection) if projection is not None else await self._mongo.find_one(query)
            if doc is not None:
                logger.warning("%s inbox.store: row only in Mongo (inbox_id=%s) — re-run the backfill",
                               storage_flags.MONGO_ONLY, _app_inbox_id(doc) or "?")
            return doc
        try:
            return await self._mongo.find_one(query, projection)
        except TypeError:
            return await self._mongo.find_one(query)

    def find(self, query: Optional[Dict[str, Any]] = None, projection: Optional[Dict[str, int]] = None, **kwargs: Any):
        cur = _LazyFindCursor(self, query or {}, projection)
        if kwargs.get("sort"):
            cur.sort(kwargs["sort"])
        return cur

    async def count_documents(self, query: Dict[str, Any], **_: Any) -> int:
        if is_inbox_supabase_primary():
            n = await self._sb_count(query)
            if n is not None:
                return n
            if not _mongo_fallback_ok():
                raise SupabaseStoreError("inbox_items count failed", table=self.table)
        return await self._mongo.count_documents(query)

    # ── writes ────────────────────────────────────────────────────────

    async def insert_one(self, doc: Dict[str, Any], *_: Any, **__: Any):
        primary_sb = is_inbox_supabase_primary()
        if primary_sb:
            sb_ok = await self._sb_upsert_doc(doc, conflict="workspace_id,inbox_id")
            if sb_ok is False:
                if not _mongo_fallback_ok():
                    raise SupabaseStoreError("inbox_items insert failed", table=self.table)
                logger.warning("%s inbox.store: SB insert degraded — writing Mongo", storage_flags.MONGO_ONLY)
                return await self._mongo.insert_one(dict(doc))
            if is_inbox_mongo_write_enabled():
                try:
                    await self._mongo.insert_one(dict(doc))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s inbox.store mongo mirror insert_one failed: %s", storage_flags.STORE_DRIFT, exc)
            return mc.InsertOneResult(_app_inbox_id(doc))

        result = await self._mongo.insert_one(dict(doc))
        if is_inbox_dual_write_enabled():
            try:
                await self._sb_upsert_doc(doc, conflict="workspace_id,inbox_id")
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s inbox.store SB dual-write insert_one failed: %s", storage_flags.MONGO_ONLY, exc)
        return result

    async def insert_many(self, docs: List[Dict[str, Any]], *_: Any, **__: Any):
        # Prefer native mongo insert_many when primary=mongo for seed speed.
        if not is_inbox_supabase_primary() and hasattr(self._mongo, "insert_many"):
            result = await self._mongo.insert_many([dict(d) for d in docs])
            if is_inbox_dual_write_enabled():
                for d in docs:
                    try:
                        await self._sb_upsert_doc(d, conflict="workspace_id,inbox_id")
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("%s inbox.store SB dual-write insert_many item failed: %s", storage_flags.MONGO_ONLY, exc)
            return result
        results = []
        for d in docs:
            results.append(getattr(await self.insert_one(d), "inserted_id", None))
        return mc.InsertManyResult(results)

    async def update_one(
        self,
        query: Dict[str, Any],
        update: Dict[str, Any],
        upsert: bool = False,
        **_: Any,
    ):
        if is_inbox_supabase_primary():
            res = await self._sb_update(query, update, upsert=upsert, many=False)
            if res is None:
                if not _mongo_fallback_ok():
                    raise SupabaseStoreError("inbox_items update failed", table=self.table)
                logger.warning("%s inbox.store: SB update degraded — Mongo mirror only", storage_flags.MONGO_ONLY)
            if is_inbox_mongo_write_enabled():
                try:
                    mres = await self._mongo.update_one(query, update, upsert=upsert)
                    if res is None:
                        return mres
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s inbox.store mongo mirror update_one failed: %s", storage_flags.STORE_DRIFT, exc)
            return res

        result = await self._mongo.update_one(query, update, upsert=upsert)
        if is_inbox_dual_write_enabled():
            try:
                await self._sb_update(query, update, upsert=upsert, many=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s inbox.store SB dual-write update_one failed: %s", storage_flags.MONGO_ONLY, _safe_err_text(str(exc)))
        return result

    async def update_many(self, query: Dict[str, Any], update: Dict[str, Any], **_: Any):
        """Bulk patch (e.g. hidden_by_real after Google sync)."""
        if is_inbox_supabase_primary():
            res = await self._sb_update(query, update, upsert=False, many=True)
            if res is None and not _mongo_fallback_ok():
                raise SupabaseStoreError("inbox_items update failed", table=self.table)
            if is_inbox_mongo_write_enabled() and hasattr(self._mongo, "update_many"):
                try:
                    mres = await self._mongo.update_many(query, update)
                    if res is None:
                        return mres
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s inbox.store mongo mirror update_many failed: %s", storage_flags.STORE_DRIFT, exc)
            return res

        if hasattr(self._mongo, "update_many"):
            result = await self._mongo.update_many(query, update)
        else:
            # Minimal fakes may only expose update_one — loop.
            result = await self._mongo.update_one(query, update)
        if is_inbox_dual_write_enabled():
            try:
                await self._sb_update(query, update, upsert=False, many=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s inbox.store SB dual-write update_many failed: %s", storage_flags.MONGO_ONLY, exc)
        return result

    async def delete_one(self, query: Dict[str, Any], **_: Any):
        primary_sb = is_inbox_supabase_primary()
        if primary_sb:
            n = await self._sb_delete(query, many=False)
            if n is None and not _mongo_fallback_ok():
                raise SupabaseStoreError("inbox_items delete failed", table=self.table)
            if is_inbox_mongo_write_enabled():
                try:
                    await self._mongo.delete_one(query)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s inbox.store mongo mirror delete_one failed: %s", storage_flags.STORE_DRIFT, exc)
            return mc.DeleteResult(n or 0)
        result = await self._mongo.delete_one(query)
        if is_inbox_dual_write_enabled():
            try:
                await self._sb_delete(query, many=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s inbox.store SB dual-write delete_one failed: %s", storage_flags.MONGO_ONLY, exc)
        return result

    async def delete_many(self, query: Dict[str, Any], **_: Any):
        primary_sb = is_inbox_supabase_primary()
        if primary_sb:
            n = await self._sb_delete(query, many=True)
            if n is None and not _mongo_fallback_ok():
                raise SupabaseStoreError("inbox_items delete failed", table=self.table)
            if is_inbox_mongo_write_enabled() and hasattr(self._mongo, "delete_many"):
                try:
                    await self._mongo.delete_many(query)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s inbox.store mongo mirror delete_many failed: %s", storage_flags.STORE_DRIFT, exc)
            return mc.DeleteResult(n or 0)
        if hasattr(self._mongo, "delete_many"):
            result = await self._mongo.delete_many(query)
        else:
            result = await self._mongo.delete_one(query)
        if is_inbox_dual_write_enabled():
            try:
                await self._sb_delete(query, many=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s inbox.store SB dual-write delete_many failed: %s", storage_flags.MONGO_ONLY, exc)
        return result

    async def create_index(self, *args, **kwargs):
        if not is_inbox_supabase_primary() and hasattr(self._mongo, "create_index"):
            return await self._mongo.create_index(*args, **kwargs)
        return None

    # ── Supabase write primitives ─────────────────────────────────────

    async def _sb_upsert_doc(self, doc: Dict[str, Any], *, conflict: str, overwrite: bool = True) -> bool:
        payload = inbox_mongo_to_sb(doc)
        if not payload.get("inbox_id") or not payload.get("workspace_id"):
            logger.warning(
                "inbox.store: skip SB write missing inbox_id/workspace_id keys=%s",
                sorted(k for k in payload if k not in _SENSITIVE_LOG_KEYS),
            )
            return False
        path = f"/rest/v1/{self.table}?on_conflict={conflict}"
        prefer = f"resolution={'merge' if overwrite else 'ignore'}-duplicates,return=minimal"
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

    async def _patch(self, params: Dict[str, str], patch: Dict[str, Any]) -> Optional[int]:
        """PATCH matching rows; returns rows changed or None on failure."""
        p = dict(params)
        p["select"] = "inbox_id"
        resp = await _sb_request(
            "PATCH", f"/rest/v1/{self.table}",
            json=patch, params=p, prefer="return=representation",
        )
        if resp is None or resp.status_code >= 400:
            if resp is not None:
                logger.warning(
                    "inbox.store SB update → %s %s",
                    resp.status_code, _safe_err_text(resp.text or ""),
                )
            return None
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = None
        return len(body) if isinstance(body, list) else 1

    def _column_patch(self, update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Plain SQL patch for $set/$unset on real columns, else None."""
        touched, simple = mc.update_touches(update)
        if not simple or any(f not in _KNOWN_COLS and f != "id" for f in touched):
            return None
        if "extra" in touched:
            return None
        fields = (update or {}).get("$set") or {}
        patch = inbox_mongo_to_sb(fields) if fields else {}
        patch.pop("extra", None)
        for k in (update or {}).get("$unset") or {}:
            col = "inbox_id" if k == "id" else k
            patch[col] = None
        return patch

    async def _sb_update(
        self,
        query: Dict[str, Any],
        update: Dict[str, Any],
        *,
        upsert: bool,
        many: bool,
    ) -> Optional[mc.UpdateResult]:
        """Mongo update semantics on Supabase. None = Supabase unavailable."""
        if not update:
            return mc.UpdateResult(0, 0)
        try:
            if upsert:
                return await self._sb_upsert(query, update)
            try:
                params, residual = _split(query)
            except sb_rest.Impossible:
                return mc.UpdateResult(0, 0)
            patch = self._column_patch(update)
            if patch is not None and not residual:
                if not patch:
                    return mc.UpdateResult(0, 0)
                n = await self._patch(params, patch)
                return None if n is None else mc.UpdateResult(n, n)
            docs = await self._sb_rows(query, limit=0 if many else 1)
            changed = 0
            for d in docs:
                pk = d.pop("_pk")
                new = mc.apply_update(d, update)
                row = inbox_mongo_to_sb(new, full=True)
                n = await self._patch({"id": f"eq.{pk}"}, row)
                if n is None:
                    return None
                changed += 1
            return mc.UpdateResult(len(docs), changed)
        except SupabaseStoreError:
            return None

    async def _sb_upsert(self, query: Dict[str, Any], update: Dict[str, Any]) -> Optional[mc.UpdateResult]:
        """Upsert honouring $setOnInsert (only applied when inserting)."""
        existing = await self._sb_rows(query, limit=1)
        set_only = {k: v for k, v in update.items() if k != "$setOnInsert"}
        if existing:
            pk = existing[0].pop("_pk")
            patch = self._column_patch(set_only)
            if patch is None:
                patch = inbox_mongo_to_sb(mc.apply_update(existing[0], set_only), full=True)
            if not patch:
                return mc.UpdateResult(1, 0)
            n = await self._patch({"id": f"eq.{pk}"}, patch)
            return None if n is None else mc.UpdateResult(1, n)
        new_doc = mc.apply_update(mc.seed_from_query(query), update, is_insert=True)
        if not _app_inbox_id(new_doc):
            logger.warning("inbox.store upsert without inbox_id/id — SB skip")
            return None
        conflict = _conflict_for_query(query if query.get("gmail_id") or query.get("ms_id") else new_doc)
        payload = inbox_mongo_to_sb(new_doc)
        resp = await _sb_request(
            "POST",
            f"/rest/v1/{self.table}?on_conflict={conflict}",
            json=payload,
            prefer="resolution=ignore-duplicates,return=representation",
        )
        if resp is None or resp.status_code >= 400:
            if resp is not None:
                logger.warning("inbox.store SB upsert → %s %s", resp.status_code, _safe_err_text(resp.text or ""))
            return None
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = None
        if isinstance(body, list) and not body:
            # Lost an insert race: the row exists now — apply the $set part.
            patch = self._column_patch(set_only) or {}
            if patch:
                params, _ = _split(query)
                await self._patch(params, patch)
            return mc.UpdateResult(1, 1)
        return mc.UpdateResult(0, 0, payload.get("inbox_id"))

    async def _sb_delete(self, query: Dict[str, Any], *, many: bool) -> Optional[int]:
        try:
            try:
                params, residual = _split(query)
            except sb_rest.Impossible:
                return 0
            if residual or not many:
                docs = await self._sb_rows(query, limit=0 if many else 1)
                ids = [d["_pk"] for d in docs if d.get("_pk")]
                if not ids:
                    return 0
                total = 0
                for chunk in sb_rest.chunked(ids, 100):
                    n = await self._delete({"id": "in.(" + ",".join(sb_rest.quote(i) for i in chunk) + ")"})
                    if n is None:
                        return None
                    total += n
                return total
            return await self._delete(params)
        except SupabaseStoreError:
            return None

    async def _delete(self, params: Dict[str, str]) -> Optional[int]:
        p = dict(params)
        p["select"] = "inbox_id"
        resp = await _sb_request(
            "DELETE", f"/rest/v1/{self.table}",
            params=p, prefer="return=representation",
        )
        if resp is None or resp.status_code >= 400:
            if resp is not None:
                logger.warning(
                    "inbox.store SB delete → %s %s",
                    resp.status_code, _safe_err_text(resp.text or ""),
                )
            return None
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = None
        return len(body) if isinstance(body, list) else 1


class _LazyFindCursor:
    """Mimics Motor cursor: find() → sort()/skip()/limit() → to_list()."""

    def __init__(
        self,
        store: InboxDualWriteCollection,
        query: Dict[str, Any],
        projection: Optional[Dict[str, int]],
    ):
        self._store = store
        self._query = query
        self._projection = projection
        self._sort: List[Tuple[str, int]] = []
        self._skip = 0
        self._limit = 0

    def sort(self, key: Any, direction: Optional[int] = None):
        self._sort = mc.normalize_sort(key, direction)
        return self

    def skip(self, n: int):
        self._skip = int(n or 0)
        return self

    def limit(self, n: int):
        self._limit = int(n or 0)
        return self

    async def to_list(self, n: Optional[int] = None) -> List[Dict[str, Any]]:
        limit = self._limit
        if n:
            limit = min(limit, int(n)) if limit else int(n)
        if is_inbox_supabase_primary():
            try:
                docs = await self._store._sb_rows(self._query, sort=self._sort, skip=self._skip, limit=limit)
                return [self._store._public(d, self._projection) for d in docs]
            except SupabaseStoreError:
                if not _mongo_fallback_ok():
                    raise
                logger.warning("%s inbox.store: Supabase list failed — Mongo mirror fallback", storage_flags.MONGO_ONLY)
        try:
            cursor = (
                self._store._mongo.find(self._query, self._projection)
                if self._projection is not None
                else self._store._mongo.find(self._query)
            )
        except TypeError:
            cursor = self._store._mongo.find(self._query)
        if self._sort and hasattr(cursor, "sort"):
            if len(self._sort) == 1:
                cursor = cursor.sort(self._sort[0][0], self._sort[0][1])
            else:
                cursor = cursor.sort(self._sort)
        if self._skip and hasattr(cursor, "skip"):
            cursor = cursor.skip(self._skip)
        if hasattr(cursor, "to_list"):
            return await cursor.to_list(limit or None)
        return []

    def __aiter__(self):
        self._buf: Optional[List[Dict[str, Any]]] = None
        self._pos = 0
        return self

    async def __anext__(self):
        if self._buf is None:
            self._buf = await self.to_list(None)
        if self._pos >= len(self._buf):
            raise StopAsyncIteration
        self._pos += 1
        return self._buf[self._pos - 1]


def wrap_inbox_col(mongo_col: Any) -> InboxDualWriteCollection:
    """Public wiring helper — drop-in for ``db['inbox_items']``."""
    return InboxDualWriteCollection(mongo_col)
