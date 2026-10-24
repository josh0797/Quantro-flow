"""Phase 3 — Actions executions + policies dual-write (Mongo ↔ Supabase).

Central persistence for:
  * ``action_executions`` — ledger + idempotency claim
  * ``automation_policies`` — SoT (inbox + ``scope=action``)
  * ``action_policies`` — legacy auto_approve / daily_limit (compat)

Flags
-----
``QUANTRO_ACTIONS_PRIMARY`` (default ``supabase`` since the Mongo exit):
  * ``mongo``     — reads from Mongo; dual-write Supabase when configured.
  * ``supabase``  — reads/writes Supabase. Mongo is only touched while it is
                    kept as a mirror (``QUANTRO_ACTIONS_MONGO_MIRROR`` if set,
                    else ``QUANTRO_MONGO_MIRROR``; default off). Mirror off →
                    Supabase failures raise ``sb_rest.SupabaseStoreError``.

Filters PostgREST cannot express exactly are evaluated in Python; fields
without a column go to the ``extra`` jsonb.

``escalation_rules`` live in ``flow_documents`` (doc_store.py) since the
Mongo exit.

Facades present a Motor-like surface (``find_one``, ``insert_one``,
``update_one``, ``find_one_and_update``, ``count_documents``, ``find``,
``delete_one``, ``insert_many``) so ActionExecutor / PolicyEngine / server
routes keep their contracts. Unit tests may still pass FakeAsyncCollection
directly without this module.
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
from mongo_compat import DuplicateKeyError
from sb_rest import SupabaseStoreError

logger = logging.getLogger("quantro.actions.store")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# Snapshot at import (tests reload the module with a patched env).
ACTIONS_PRIMARY = storage_flags.parse_primary("QUANTRO_ACTIONS_PRIMARY")
# Prefer dedicated mirror flag; fall back to shared QUANTRO_MONGO_MIRROR; default off.
MONGO_MIRROR = storage_flags.parse_mirror("QUANTRO_ACTIONS_MONGO_MIRROR")

# Statuses that claim an idempotency key (mirror executor._CLAIMED_STATUSES).
CLAIMED_STATUSES = frozenset({
    "running", "pending_approval", "approved", "succeeded",
    "simulated", "failed", "suggested",
})

TABLE_EXECUTIONS = "action_executions"
TABLE_AUTOMATION_POLICIES = "automation_policies"
TABLE_ACTION_POLICIES = "action_policies"


def _is_sb_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def is_actions_supabase_primary() -> bool:
    return ACTIONS_PRIMARY == "supabase" and _is_sb_configured()


def is_actions_dual_write_enabled() -> bool:
    return _is_sb_configured()


def is_actions_mongo_write_enabled() -> bool:
    if not _is_sb_configured():
        return True
    if ACTIONS_PRIMARY != "supabase":
        return True
    return MONGO_MIRROR


def _mongo_fallback_ok() -> bool:
    """Supabase primary consults Mongo only while it is kept as a mirror."""
    return MONGO_MIRROR


def actions_health() -> Dict[str, Any]:
    return {
        "actions_primary": ACTIONS_PRIMARY,
        "supabase_configured": _is_sb_configured(),
        "dual_write": is_actions_dual_write_enabled(),
        "mongo_write": is_actions_mongo_write_enabled(),
        "mongo_mirror": MONGO_MIRROR,
        "escalation_rules": "flow_documents",
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


def _is_unique_violation(resp: Optional[httpx.Response]) -> bool:
    if resp is None:
        return False
    # PostgREST maps unique_violation to 409 Conflict
    return resp.status_code == 409


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
                "actions.store: Supabase table missing for %s %s — "
                "apply migration 20260918120000_actions_postgres.sql",
                method, path,
            )
            return None
        return resp
    except Exception as exc:  # noqa: BLE001
        logger.warning("actions.store %s %s failed: %s", method, path, exc)
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


# ── query helpers (Mongo filter → PostgREST params) ───────────────────

def _mongo_filter_to_params(query: Dict[str, Any], *, select: str = "*", columns: Optional[Sequence[str]] = None) -> Dict[str, str]:
    """PostgREST params for the exactly-expressible part of ``query``.

    Facades call ``_split`` and evaluate the residual in Python; this
    wrapper is kept for callers/tests that only need the params.
    """
    cols = set(columns) if columns else {k for k in (query or {}) if not str(k).startswith("$")}
    try:
        params, _ = sb_rest.split_filter(query, cols, json_cols=_JSON_COLS)
    except sb_rest.Impossible:
        params = {}
    out: Dict[str, str] = {"select": select}
    out.update(params)
    return out


def _strip_id(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return doc
    out = dict(doc)
    out.pop("_id", None)
    out.pop("id", None)  # Postgres uuid pk — not part of Action API docs
    out.pop("_pk", None)
    return out


# ── row mappers ───────────────────────────────────────────────────────

_EXEC_DT_KEYS = ("started_at", "completed_at", "approved_at", "created_at", "updated_at")
_EXEC_JSON_KEYS = ("input", "result_metadata")
_JSON_COLS = frozenset({"input", "result_metadata", "extra"})

EXEC_COLUMNS = frozenset({
    "execution_id", "workspace_id", "action_id", "provider", "requested_by",
    "actor_role", "source", "input", "status", "risk_level", "policy_decision",
    "confidence", "idempotency_key", "started_at", "completed_at",
    "provider_request_id", "result_metadata", "error_code",
    "error_message_sanitized", "approved_by", "approved_at",
    "created_at", "updated_at", "extra",
})


def execution_mongo_to_sb(doc: Dict[str, Any], *, full: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    extra: Dict[str, Any] = {}
    for k, v in doc.items():
        if k in {"_id", "id", "_pk"}:
            continue
        if k == "extra":
            extra.update(mc.to_json(v) if isinstance(v, dict) else {"extra": mc.to_json(v)})
        elif k in _EXEC_DT_KEYS:
            out[k] = _iso(v)
        elif k in _EXEC_JSON_KEYS:
            out[k] = mc.to_json(v) if v is not None else {}
        elif k in EXEC_COLUMNS:
            out[k] = v
        else:
            extra[k] = mc.to_json(v)
    if extra or full:
        out["extra"] = extra
    return out


def execution_sb_to_mongo(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return {}
    out = {k: v for k, v in row.items() if k not in {"id", "extra"}}
    for k in _EXEC_DT_KEYS:
        if k in out:
            out[k] = _parse_dt(out[k])
    for k in _EXEC_JSON_KEYS:
        if out.get(k) is None:
            out[k] = {}
        else:
            out[k] = mc.from_json(out[k])
    extra = row.get("extra")
    if isinstance(extra, dict):
        for k, v in extra.items():
            out.setdefault(k, mc.from_json(v))
    return out


_POLICY_KNOWN = {
    "policy_id", "workspace_id", "org_id", "enabled",
    "intent", "action", "confidence_threshold_high", "confidence_threshold_medium",
    "high_action", "medium_action", "low_action",
    "scope", "action_id", "provider", "mode", "minimum_role", "daily_limit",
    "created_at", "updated_at",
}
_POLICY_DT = ("created_at", "updated_at")
POLICY_COLUMNS = frozenset(_POLICY_KNOWN | {"extra"})


def policy_mongo_to_sb(doc: Dict[str, Any], *, full: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    extra: Dict[str, Any] = {}
    for k, v in doc.items():
        if k in {"_id", "id", "_pk"}:
            continue
        if k == "extra" and isinstance(v, dict):
            extra.update(mc.to_json(v))
            continue
        if k in _POLICY_KNOWN:
            if k in _POLICY_DT:
                out[k] = _iso(v)
            else:
                out[k] = v
        else:
            extra[k] = mc.to_json(v)
    if extra:
        out["extra"] = extra
    else:
        out.setdefault("extra", {})
    return out


def policy_sb_to_mongo(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return {}
    out = {k: v for k, v in row.items() if k not in {"id"}}
    extra = out.pop("extra", None) or {}
    if isinstance(extra, dict):
        for k, v in extra.items():
            out.setdefault(k, mc.from_json(v))
    for k in _POLICY_DT:
        if k in out:
            out[k] = _parse_dt(out[k])
    return out


ACTION_POLICY_COLUMNS = frozenset({
    "policy_id", "workspace_id", "action_id", "auto_approve", "daily_limit",
    "created_at", "updated_at", "extra",
})


def action_policy_mongo_to_sb(doc: Dict[str, Any], *, full: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    extra: Dict[str, Any] = {}
    for k, v in doc.items():
        if k in {"_id", "id", "_pk"}:
            continue
        if k in _POLICY_DT:
            out[k] = _iso(v)
        elif k == "extra" and isinstance(v, dict):
            extra.update(mc.to_json(v))
        elif k in ACTION_POLICY_COLUMNS:
            out[k] = v
        else:
            extra[k] = mc.to_json(v)
    if extra or full:
        out["extra"] = extra
    return out


def action_policy_sb_to_mongo(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return {}
    out = {k: v for k, v in row.items() if k not in {"id", "extra"}}
    for k in _POLICY_DT:
        if k in out:
            out[k] = _parse_dt(out[k])
    extra = row.get("extra")
    if isinstance(extra, dict):
        for k, v in extra.items():
            out.setdefault(k, mc.from_json(v))
    return out


# ── dual-write collection ─────────────────────────────────────────────

async def _req(method: str, path: str, **kwargs: Any):
    """Late-bound so tests can patch ``actions.store._sb_request``."""
    return await _sb_request(method, path, **kwargs)


class DualWriteCollection:
    """Motor-like facade over a Mongo collection + optional Supabase table."""

    def __init__(
        self,
        mongo_col: Any,
        *,
        table: str,
        to_sb,
        from_sb,
        conflict_target: Optional[str] = None,
        identity_keys: Sequence[str] = ("workspace_id",),
        columns: Sequence[str] = (),
    ):
        self._mongo = mongo_col
        self.table = table
        self._to_sb = to_sb
        self._from_sb = from_sb
        self._conflict = conflict_target
        self._identity_keys = tuple(identity_keys)
        self._columns = frozenset(columns)

    # ── Supabase read primitives ──────────────────────────────────────
    def _split(self, query: Dict[str, Any]):
        return sb_rest.split_filter(query, self._columns - {"extra"}, json_cols=_JSON_COLS)

    async def _sb_rows(self, query: Dict[str, Any], *, sort=None, skip: int = 0, limit: int = 0) -> List[Dict[str, Any]]:
        """Docs (+``_pk``) matching the whole filter. Raises SupabaseStoreError."""
        try:
            params, residual = self._split(query)
        except sb_rest.Impossible:
            return []
        params["select"] = "*"
        order = sb_rest.order_param(sort or [], self._columns) if sort else "created_at.asc,id.asc"
        exact = not residual and order is not None
        rows = await sb_rest.fetch_all(
            _req, self.table, params,
            order=order or "created_at.asc,id.asc",
            limit=limit if (exact and limit) else None,
            offset=skip if exact else 0,
        )
        if rows is None:
            raise SupabaseStoreError(f"{self.table} read failed", table=self.table)
        docs = []
        for r in rows:
            d = self._from_sb(r)
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

    # ── reads ─────────────────────────────────────────────────────────

    async def find_one(self, query: Dict[str, Any], projection: Optional[Dict[str, int]] = None, **_: Any):
        if is_actions_supabase_primary():
            try:
                row = await self._sb_find_one(query)
            except SupabaseStoreError:
                if not _mongo_fallback_ok():
                    raise
                row = None
            if row is not None:
                return _project(_strip_id(row), projection)
            if not _mongo_fallback_ok():
                return None
            # fallback mongo (mirror kept)
            doc = await self._mongo.find_one(query, projection)
            if doc is not None:
                logger.warning("%s actions.store %s: row only in Mongo (%s) — re-run the backfill",
                               storage_flags.MONGO_ONLY, self.table,
                               doc.get("execution_id") or doc.get("policy_id") or doc.get("action_id") or "?")
            return doc
        return await self._mongo.find_one(query, projection)

    def find(self, query: Optional[Dict[str, Any]] = None, projection: Optional[Dict[str, int]] = None, **kwargs: Any):
        cur = _LazyFindCursor(self, query or {}, projection)
        if kwargs.get("sort"):
            cur.sort(kwargs["sort"])
        return cur

    async def count_documents(self, query: Dict[str, Any], **_: Any) -> int:
        if is_actions_supabase_primary():
            n = await self._sb_count(query)
            if n is not None:
                return n
            if not _mongo_fallback_ok():
                raise SupabaseStoreError(f"{self.table} count failed", table=self.table)
        return await self._mongo.count_documents(query)

    # ── writes ────────────────────────────────────────────────────────

    async def insert_one(self, doc: Dict[str, Any], *_: Any, **__: Any):
        primary_sb = is_actions_supabase_primary()
        if primary_sb:
            sb_ok = await self._sb_insert(doc, raise_dup=True)
            if sb_ok is False:
                if not _mongo_fallback_ok():
                    raise SupabaseStoreError(f"{self.table} insert failed", table=self.table)
                # Table missing / transport — degrade to the Mongo mirror
                logger.warning(
                    "%s actions.store: SB insert degraded for %s — writing Mongo",
                    storage_flags.MONGO_ONLY, self.table,
                )
                return await self._mongo.insert_one(dict(doc))
            if is_actions_mongo_write_enabled():
                try:
                    await self._mongo.insert_one(dict(doc))
                except DuplicateKeyError:
                    pass  # mirror race / already present
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s actions.store mongo mirror insert_one failed: %s", storage_flags.STORE_DRIFT, exc)
            return mc.InsertOneResult(doc.get("execution_id") or doc.get("policy_id"))

        # Mongo primary
        result = await self._mongo.insert_one(dict(doc))
        if is_actions_dual_write_enabled():
            try:
                await self._sb_insert(doc, raise_dup=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s actions.store SB dual-write insert_one failed: %s", storage_flags.MONGO_ONLY, exc)
        return result

    async def insert_many(self, docs: List[Dict[str, Any]], *_: Any, **__: Any):
        results = []
        for d in docs:
            results.append(await self.insert_one(d))
        return results

    async def update_one(self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False, **_: Any):
        primary_sb = is_actions_supabase_primary()

        if primary_sb:
            res = await self._sb_update(query, update, upsert=upsert, many=False)
            if res is None and not _mongo_fallback_ok():
                raise SupabaseStoreError(f"{self.table} update failed", table=self.table)
            if res is None:
                logger.warning("%s actions.store: SB update degraded for %s — Mongo mirror only",
                               storage_flags.MONGO_ONLY, self.table)
            if is_actions_mongo_write_enabled():
                try:
                    mres = await self._mongo.update_one(query, update, upsert=upsert)
                    if res is None:
                        return mres
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s actions.store mongo mirror update_one failed: %s", storage_flags.STORE_DRIFT, exc)
            # Motor-shaped result (callers read .matched_count).
            return res or mc.UpdateResult(0, 0)

        result = await self._mongo.update_one(query, update, upsert=upsert)
        if is_actions_dual_write_enabled():
            try:
                await self._sb_update(query, update, upsert=upsert, many=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s actions.store SB dual-write update_one failed: %s", storage_flags.MONGO_ONLY, exc)
        return result

    async def update_many(self, query: Dict[str, Any], update: Dict[str, Any], **_: Any):
        """Bulk update (server.py startup repairs when this domain is rolled
        back to Mongo). Same routing as update_one."""
        if is_actions_supabase_primary():
            res = await self._sb_update(query, update, upsert=False, many=True)
            if res is None and not _mongo_fallback_ok():
                raise SupabaseStoreError(f"{self.table} update failed", table=self.table)
            if res is None:
                logger.warning("%s actions.store: SB update degraded for %s — Mongo mirror only",
                               storage_flags.MONGO_ONLY, self.table)
            if is_actions_mongo_write_enabled() and hasattr(self._mongo, "update_many"):
                try:
                    mres = await self._mongo.update_many(query, update)
                    if res is None:
                        return mres
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s actions.store mongo mirror update_many failed: %s", storage_flags.STORE_DRIFT, exc)
            return res or mc.UpdateResult(0, 0)

        result = await self._mongo.update_many(query, update)
        if is_actions_dual_write_enabled():
            try:
                await self._sb_update(query, update, upsert=False, many=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s actions.store SB dual-write update_many failed: %s", storage_flags.MONGO_ONLY, exc)
        return result

    async def find_one_and_update(
        self,
        query: Dict[str, Any],
        update: Dict[str, Any],
        projection: Optional[Dict[str, int]] = None,
        return_document=None,
        **_: Any,
    ):
        fields = (update or {}).get("$set") or {}
        primary_sb = is_actions_supabase_primary()

        if primary_sb:
            row = await self._sb_find_one_and_update(query, update)
            if is_actions_mongo_write_enabled() and row is not None:
                try:
                    await self._mongo.update_one(query, update)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s actions.store mongo mirror find_one_and_update failed: %s", storage_flags.STORE_DRIFT, exc)
            if row is None:
                # Also try mongo (mid-flip / degrade) while it is mirrored
                if _mongo_fallback_ok() and hasattr(self._mongo, "find_one_and_update"):
                    return await self._mongo.find_one_and_update(
                        query, update, projection=projection, return_document=return_document,
                    )
                return None
            return _project(_strip_id(row), projection)

        if hasattr(self._mongo, "find_one_and_update"):
            doc = await self._mongo.find_one_and_update(
                query, update, projection=projection, return_document=return_document,
            )
        else:
            doc = await self._mongo.find_one(query, projection)
            if doc:
                await self._mongo.update_one(query, update)
                doc = {**doc, **fields}
        if doc is not None and is_actions_dual_write_enabled():
            try:
                await self._sb_update(query, {"$set": fields}, upsert=False, many=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s actions.store SB dual-write find_one_and_update failed: %s", storage_flags.MONGO_ONLY, exc)
        return doc

    async def delete_one(self, query: Dict[str, Any], **_: Any):
        return await self._delete(query, many=False)

    async def delete_many(self, query: Dict[str, Any], **_: Any):
        return await self._delete(query, many=True)

    async def _delete(self, query: Dict[str, Any], *, many: bool):
        primary_sb = is_actions_supabase_primary()
        if primary_sb:
            n = await self._sb_delete(query, many=many)
            if n is None and not _mongo_fallback_ok():
                raise SupabaseStoreError(f"{self.table} delete failed", table=self.table)
            if is_actions_mongo_write_enabled():
                try:
                    mres = await (self._mongo.delete_many(query) if many and hasattr(self._mongo, "delete_many")
                                  else self._mongo.delete_one(query))
                    if n is None:
                        return mres
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s actions.store mongo mirror delete failed: %s", storage_flags.STORE_DRIFT, exc)
            return mc.DeleteResult(n or 0)
        if many and hasattr(self._mongo, "delete_many"):
            result = await self._mongo.delete_many(query)
        else:
            result = await self._mongo.delete_one(query)
        if is_actions_dual_write_enabled():
            try:
                await self._sb_delete(query, many=many)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s actions.store SB dual-write delete failed: %s", storage_flags.MONGO_ONLY, exc)
        return result

    async def create_index(self, *args, **kwargs):
        """Delegate index creation to Mongo only (Postgres indexes live in SQL migrations)."""
        if not is_actions_supabase_primary() and hasattr(self._mongo, "create_index"):
            return await self._mongo.create_index(*args, **kwargs)
        return None

    # ── Supabase primitives ───────────────────────────────────────────

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
            params, residual = self._split(query)
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

    async def _sb_insert(self, doc: Dict[str, Any], *, raise_dup: bool) -> bool:
        """Return True on success, False if SB unavailable (degrade)."""
        payload = self._to_sb(doc)
        prefer = "return=minimal"
        path = f"/rest/v1/{self.table}"
        if self._conflict:
            path = f"{path}?on_conflict={self._conflict}"
            prefer = "resolution=merge-duplicates,return=minimal"
        resp = await _req("POST", path, json=payload, prefer=prefer)
        if resp is None:
            return False
        if _is_unique_violation(resp):
            if raise_dup:
                raise DuplicateKeyError(f"duplicate on {self.table}")
            return True  # conflict treated as ok when not raising
        if resp.status_code >= 400:
            logger.warning(
                "actions.store SB insert %s → %s %s",
                self.table, resp.status_code, (resp.text or "")[:200],
            )
            return False
        return True

    def _column_patch(self, update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        touched, simple = mc.update_touches(update)
        if not simple or "extra" in touched or any(f not in self._columns for f in touched):
            return None
        fields = (update or {}).get("$set") or {}
        patch = self._to_sb(fields) if fields else {}
        patch.pop("extra", None)  # only real columns are touched here
        # Remove identity keys from patch body if they slipped in
        for k in self._identity_keys:
            patch.pop(k, None)
        for k in (update or {}).get("$unset") or {}:
            patch[k] = None
        return patch

    async def _patch(self, params: Dict[str, str], patch: Dict[str, Any], *, representation: bool = False):
        p = dict(params)
        p.pop("select", None)
        if not representation:
            p["select"] = "id"
        resp = await _req(
            "PATCH", f"/rest/v1/{self.table}",
            json=patch, params=p, prefer="return=representation",
        )
        if resp is None or resp.status_code >= 400:
            if resp is not None:
                logger.warning(
                    "actions.store SB update %s → %s %s",
                    self.table, resp.status_code, (resp.text or "")[:200],
                )
            return None
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = None
        return body if isinstance(body, list) else [{}]

    async def _sb_update(
        self,
        query: Dict[str, Any],
        update: Dict[str, Any],
        *,
        upsert: bool = False,
        many: bool = False,
    ) -> Optional[mc.UpdateResult]:
        """Mongo update semantics on Supabase. None = Supabase unavailable."""
        if not update:
            return mc.UpdateResult(0, 0)
        try:
            try:
                params, residual = self._split(query)
            except sb_rest.Impossible:
                return mc.UpdateResult(0, 0)
            set_only = {k: v for k, v in update.items() if k != "$setOnInsert"}
            patch = self._column_patch(set_only)
            if upsert:
                docs = await self._sb_rows(query, limit=1)
                if not docs:
                    new_doc = mc.apply_update(mc.seed_from_query(query), update, is_insert=True)
                    ok = await self._sb_insert(new_doc, raise_dup=False)
                    return mc.UpdateResult(0, 0, new_doc.get("policy_id") or new_doc.get("execution_id")) if ok else None
                pk = docs[0]["_pk"]
                if patch is None:
                    patch = self._to_sb(mc.apply_update({k: v for k, v in docs[0].items() if k != "_pk"}, set_only), full=True)
                rows = await self._patch({"id": f"eq.{pk}"}, patch) if patch else []
                return None if rows is None else mc.UpdateResult(1, len(rows))
            if patch is not None and not residual:
                if not patch:
                    return mc.UpdateResult(0, 0)
                rows = await self._patch(params, patch)
                return None if rows is None else mc.UpdateResult(len(rows), len(rows))
            docs = await self._sb_rows(query, limit=0 if many else 1)
            for d in docs:
                pk = d.pop("_pk")
                new = mc.apply_update(d, update)
                if await self._patch({"id": f"eq.{pk}"}, self._to_sb(new, full=True)) is None:
                    return None
            return mc.UpdateResult(len(docs), len(docs))
        except SupabaseStoreError:
            return None

    async def _sb_find_one_and_update(self, query: Dict[str, Any], update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Atomic when the filter is exact (single conditional PATCH)."""
        try:
            params, residual = self._split(query)
        except sb_rest.Impossible:
            return None
        patch = self._column_patch(update)
        if patch is not None and not residual:
            rows = await self._patch(params, patch, representation=True)
            if not rows:
                return None
            return self._from_sb(rows[0])
        try:
            docs = await self._sb_rows(query, limit=1)
        except SupabaseStoreError:
            return None
        if not docs:
            return None
        pk = docs[0].pop("_pk")
        new = mc.apply_update(docs[0], update)
        rows = await self._patch({"id": f"eq.{pk}"}, self._to_sb(new, full=True), representation=True)
        return self._from_sb(rows[0]) if rows else None

    async def _sb_delete(self, query: Dict[str, Any], *, many: bool = True) -> Optional[int]:
        try:
            try:
                params, residual = self._split(query)
            except sb_rest.Impossible:
                return 0
            if residual or not many:
                docs = await self._sb_rows(query, limit=0 if many else 1)
                ids = [d["_pk"] for d in docs if d.get("_pk")]
                total = 0
                for chunk in sb_rest.chunked(ids, 100):
                    n = await self._delete_params({"id": "in.(" + ",".join(sb_rest.quote(i) for i in chunk) + ")"})
                    if n is None:
                        return None
                    total += n
                return total
            return await self._delete_params(params)
        except SupabaseStoreError:
            return None

    async def _delete_params(self, params: Dict[str, str]) -> Optional[int]:
        p = dict(params)
        p["select"] = "id"
        resp = await _req(
            "DELETE", f"/rest/v1/{self.table}",
            params=p, prefer="return=representation",
        )
        if resp is None or resp.status_code >= 400:
            if resp is not None:
                logger.warning(
                    "actions.store SB delete %s → %s %s",
                    self.table, resp.status_code, (resp.text or "")[:200],
                )
            return None
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = None
        return len(body) if isinstance(body, list) else 1


class _LazyFindCursor:
    """Mimics Motor cursor: find() → sort()/skip()/limit() → to_list()."""

    def __init__(self, store: DualWriteCollection, query: Dict[str, Any], projection: Optional[Dict[str, int]]):
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
        if is_actions_supabase_primary():
            try:
                docs = await self._store._sb_rows(self._query, sort=self._sort, skip=self._skip, limit=limit)
                return [_project(_strip_id(d), self._projection) for d in docs]
            except SupabaseStoreError:
                if not _mongo_fallback_ok():
                    raise
                logger.warning("%s actions.store %s: Supabase list failed — Mongo mirror fallback", storage_flags.MONGO_ONLY, self._store.table)
        # Motor accepts (query, projection); minimal fakes may only take query.
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


# ── public wrappers ───────────────────────────────────────────────────

def wrap_executions_col(mongo_col: Any) -> DualWriteCollection:
    return DualWriteCollection(
        mongo_col,
        table=TABLE_EXECUTIONS,
        to_sb=execution_mongo_to_sb,
        from_sb=execution_sb_to_mongo,
        conflict_target=None,  # inserts are plain; unique index enforces idempotency
        identity_keys=("execution_id", "workspace_id"),
        columns=EXEC_COLUMNS,
    )


def wrap_automation_policies_col(mongo_col: Any) -> DualWriteCollection:
    return DualWriteCollection(
        mongo_col,
        table=TABLE_AUTOMATION_POLICIES,
        to_sb=policy_mongo_to_sb,
        from_sb=policy_sb_to_mongo,
        conflict_target="policy_id",
        identity_keys=("policy_id", "workspace_id"),
        columns=POLICY_COLUMNS,
    )


def wrap_action_policies_col(mongo_col: Any) -> DualWriteCollection:
    return DualWriteCollection(
        mongo_col,
        table=TABLE_ACTION_POLICIES,
        to_sb=action_policy_mongo_to_sb,
        from_sb=action_policy_sb_to_mongo,
        conflict_target="workspace_id,action_id",
        identity_keys=("workspace_id", "action_id"),
        columns=ACTION_POLICY_COLUMNS,
    )
