"""Phase 3 — Actions executions + policies dual-write (Mongo ↔ Supabase).

Central persistence for:
  * ``action_executions`` — ledger + idempotency claim
  * ``automation_policies`` — SoT (inbox + ``scope=action``)
  * ``action_policies`` — legacy auto_approve / daily_limit (compat)

Flags
-----
``QUANTRO_ACTIONS_PRIMARY`` (default ``mongo``):
  * ``mongo``     — reads from Mongo; dual-write Supabase when configured.
  * ``supabase``  — reads from Supabase first (Mongo fallback); Mongo
                    writes gated by ``QUANTRO_ACTIONS_MONGO_MIRROR`` if set,
                    else ``QUANTRO_MONGO_MIRROR`` (default on).

Graceful degrade: missing tables / transport errors → log + keep Mongo.

``escalation_rules`` are intentionally NOT migrated here (inbox-coupled;
see docs/phase3-actions-postgres.md).

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
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger("quantro.actions.store")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

_ACTIONS_PRIMARY_RAW = (os.environ.get("QUANTRO_ACTIONS_PRIMARY") or "mongo").lower().strip()
ACTIONS_PRIMARY = _ACTIONS_PRIMARY_RAW if _ACTIONS_PRIMARY_RAW in {"mongo", "supabase"} else "mongo"

# Prefer dedicated mirror flag; fall back to shared QUANTRO_MONGO_MIRROR.
_MIRROR_DEDICATED = os.environ.get("QUANTRO_ACTIONS_MONGO_MIRROR")
if _MIRROR_DEDICATED is None or _MIRROR_DEDICATED == "":
    _MIRROR_RAW = (os.environ.get("QUANTRO_MONGO_MIRROR") or "1").lower().strip()
else:
    _MIRROR_RAW = _MIRROR_DEDICATED.lower().strip()
MONGO_MIRROR = _MIRROR_RAW not in {"0", "false", "no", "off"}

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


def actions_health() -> Dict[str, Any]:
    return {
        "actions_primary": ACTIONS_PRIMARY,
        "supabase_configured": _is_sb_configured(),
        "dual_write": is_actions_dual_write_enabled(),
        "mongo_write": is_actions_mongo_write_enabled(),
        "mongo_mirror": MONGO_MIRROR,
        "escalation_rules": "deferred_mongo",
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

def _mongo_filter_to_params(query: Dict[str, Any], *, select: str = "*") -> Dict[str, str]:
    params: Dict[str, str] = {"select": select}
    for key, val in (query or {}).items():
        if key == "_id":
            continue
        if isinstance(val, dict):
            if "$in" in val:
                items = ",".join(str(x) for x in val["$in"])
                params[key] = f"in.({items})"
            elif "$gte" in val:
                params[key] = f"gte.{_iso(val['$gte'])}"
            elif "$exists" in val:
                if val["$exists"] is False:
                    params[key] = "is.null"
                # $exists True → omit (any value including null is fine for match-all)
            elif "$ne" in val:
                params[key] = f"neq.{val['$ne']}"
            else:
                # Unsupported operator — skip rather than wrong-match
                logger.debug("actions.store: skipping unsupported filter %s=%s", key, val)
        elif val is None:
            params[key] = "is.null"
        elif isinstance(val, bool):
            params[key] = f"eq.{str(val).lower()}"
        else:
            params[key] = f"eq.{val}"
    return params


def _strip_id(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return doc
    out = dict(doc)
    out.pop("_id", None)
    out.pop("id", None)  # Postgres uuid pk — not part of Action API docs
    return out


# ── row mappers ───────────────────────────────────────────────────────

_EXEC_DT_KEYS = ("started_at", "completed_at", "approved_at", "created_at", "updated_at")
_EXEC_JSON_KEYS = ("input", "result_metadata")


def execution_mongo_to_sb(doc: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in doc.items():
        if k in {"_id", "id"}:
            continue
        if k in _EXEC_DT_KEYS:
            out[k] = _iso(v)
        elif k in _EXEC_JSON_KEYS:
            out[k] = v if v is not None else {}
        else:
            out[k] = v
    return out


def execution_sb_to_mongo(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return {}
    out = {k: v for k, v in row.items() if k not in {"id"}}
    for k in _EXEC_DT_KEYS:
        if k in out:
            out[k] = _parse_dt(out[k])
    for k in _EXEC_JSON_KEYS:
        if out.get(k) is None:
            out[k] = {}
    return out


_POLICY_KNOWN = {
    "policy_id", "workspace_id", "org_id", "enabled",
    "intent", "action", "confidence_threshold_high", "confidence_threshold_medium",
    "high_action", "medium_action", "low_action",
    "scope", "action_id", "provider", "mode", "minimum_role", "daily_limit",
    "created_at", "updated_at",
}
_POLICY_DT = ("created_at", "updated_at")


def policy_mongo_to_sb(doc: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    extra: Dict[str, Any] = {}
    for k, v in doc.items():
        if k in {"_id", "id"}:
            continue
        if k == "extra" and isinstance(v, dict):
            extra.update(v)
            continue
        if k in _POLICY_KNOWN:
            if k in _POLICY_DT:
                out[k] = _iso(v)
            else:
                out[k] = v
        else:
            extra[k] = v
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
            out.setdefault(k, v)
    for k in _POLICY_DT:
        if k in out:
            out[k] = _parse_dt(out[k])
    return out


def action_policy_mongo_to_sb(doc: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in ("policy_id", "workspace_id", "action_id", "auto_approve", "daily_limit",
              "created_at", "updated_at"):
        if k in doc:
            if k in _POLICY_DT:
                out[k] = _iso(doc[k])
            else:
                out[k] = doc[k]
    return out


def action_policy_sb_to_mongo(row: Dict[str, Any]) -> Dict[str, Any]:
    if not row:
        return {}
    out = {k: v for k, v in row.items() if k not in {"id"}}
    for k in _POLICY_DT:
        if k in out:
            out[k] = _parse_dt(out[k])
    return out


# ── cursor ────────────────────────────────────────────────────────────

class _StoreCursor:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows
        self._sort_key: Optional[str] = None
        self._sort_dir: int = 1

    def sort(self, key: str, direction: int = 1):
        self._sort_key = key
        self._sort_dir = direction
        return self

    async def to_list(self, n: int) -> List[Dict[str, Any]]:
        rows = list(self._rows)
        if self._sort_key:
            rev = self._sort_dir < 0
            rows.sort(key=lambda r: (r.get(self._sort_key) is None, r.get(self._sort_key)), reverse=rev)
        return rows[:n]


# ── dual-write collection ─────────────────────────────────────────────

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
    ):
        self._mongo = mongo_col
        self.table = table
        self._to_sb = to_sb
        self._from_sb = from_sb
        self._conflict = conflict_target
        self._identity_keys = tuple(identity_keys)

    # ── reads ─────────────────────────────────────────────────────────

    async def find_one(self, query: Dict[str, Any], projection: Optional[Dict[str, int]] = None):
        if is_actions_supabase_primary():
            row = await self._sb_find_one(query)
            if row is not None:
                return _project(_strip_id(row), projection)
            # fallback mongo
            doc = await self._mongo.find_one(query, projection)
            return doc
        return await self._mongo.find_one(query, projection)

    def find(self, query: Dict[str, Any], projection: Optional[Dict[str, int]] = None):
        # Sync wrapper returning an awaitable cursor builder — Motor style
        # is sync find() → cursor with async to_list. We return a lazy proxy.
        return _LazyFindCursor(self, query, projection)

    async def _find_rows(self, query: Dict[str, Any], projection: Optional[Dict[str, int]], limit: int) -> List[Dict[str, Any]]:
        if is_actions_supabase_primary():
            rows = await self._sb_find_many(query, limit=limit)
            if rows is not None:
                return [_project(_strip_id(r), projection) for r in rows]
        # Mongo primary or SB miss
        cursor = self._mongo.find(query, projection) if projection is not None else self._mongo.find(query)
        if hasattr(cursor, "sort"):
            # Caller may still call .sort on LazyFindCursor; this path is for
            # LazyFindCursor.to_list when no sort was set after SB miss.
            pass
        if hasattr(cursor, "to_list"):
            return await cursor.to_list(limit)
        # FakeAsyncCollection returns _FakeCursor without sort — already filtered
        if hasattr(cursor, "to_list"):
            return await cursor.to_list(limit)
        return []

    async def count_documents(self, query: Dict[str, Any]) -> int:
        if is_actions_supabase_primary():
            n = await self._sb_count(query)
            if n is not None:
                return n
        return await self._mongo.count_documents(query)

    # ── writes ────────────────────────────────────────────────────────

    async def insert_one(self, doc: Dict[str, Any]):
        primary_sb = is_actions_supabase_primary()
        if primary_sb:
            try:
                sb_ok = await self._sb_insert(doc, raise_dup=True)
            except DuplicateKeyError:
                raise
            if sb_ok is False:
                # Table missing / transport — degrade to Mongo write
                logger.warning(
                    "actions.store: SB insert degraded for %s — writing Mongo",
                    self.table,
                )
                return await self._mongo.insert_one(dict(doc))
            if is_actions_mongo_write_enabled():
                try:
                    await self._mongo.insert_one(dict(doc))
                except DuplicateKeyError:
                    pass  # mirror race / already present
                except Exception as exc:  # noqa: BLE001
                    logger.warning("actions.store mongo mirror insert_one failed: %s", exc)
            return doc

        # Mongo primary
        result = await self._mongo.insert_one(dict(doc))
        if is_actions_dual_write_enabled():
            try:
                await self._sb_insert(doc, raise_dup=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("actions.store SB dual-write insert_one failed: %s", exc)
        return result

    async def insert_many(self, docs: List[Dict[str, Any]]):
        results = []
        for d in docs:
            results.append(await self.insert_one(d))
        return results

    async def update_one(self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False):
        primary_sb = is_actions_supabase_primary()
        fields = (update or {}).get("$set") or {}
        unset = (update or {}).get("$unset") or {}

        if primary_sb:
            ok = await self._sb_update(query, fields, unset=unset, upsert=upsert)
            if is_actions_mongo_write_enabled():
                try:
                    await self._mongo.update_one(query, update, upsert=upsert)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("actions.store mongo mirror update_one failed: %s", exc)
            return ok

        result = await self._mongo.update_one(query, update, upsert=upsert)
        if is_actions_dual_write_enabled():
            try:
                await self._sb_update(query, fields, unset=unset, upsert=upsert)
            except Exception as exc:  # noqa: BLE001
                logger.warning("actions.store SB dual-write update_one failed: %s", exc)
        return result

    async def find_one_and_update(
        self,
        query: Dict[str, Any],
        update: Dict[str, Any],
        projection: Optional[Dict[str, int]] = None,
        return_document=None,
    ):
        fields = (update or {}).get("$set") or {}
        primary_sb = is_actions_supabase_primary()

        if primary_sb:
            row = await self._sb_find_one_and_update(query, fields)
            if is_actions_mongo_write_enabled() and row is not None:
                try:
                    await self._mongo.update_one(query, update)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("actions.store mongo mirror find_one_and_update failed: %s", exc)
            if row is None:
                # Also try mongo (mid-flip / degrade)
                if hasattr(self._mongo, "find_one_and_update"):
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
                await self._sb_update(query, fields, unset={})
            except Exception as exc:  # noqa: BLE001
                logger.warning("actions.store SB dual-write find_one_and_update failed: %s", exc)
        return doc

    async def delete_one(self, query: Dict[str, Any]):
        primary_sb = is_actions_supabase_primary()
        if primary_sb:
            await self._sb_delete(query)
            if is_actions_mongo_write_enabled():
                try:
                    return await self._mongo.delete_one(query)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("actions.store mongo mirror delete_one failed: %s", exc)
                    return None
            return None
        result = await self._mongo.delete_one(query)
        if is_actions_dual_write_enabled():
            try:
                await self._sb_delete(query)
            except Exception as exc:  # noqa: BLE001
                logger.warning("actions.store SB dual-write delete_one failed: %s", exc)
        return result

    async def delete_many(self, query: Dict[str, Any]):
        # Rare; loop via find then delete_one is enough for Phase 3
        if hasattr(self._mongo, "delete_many") and not is_actions_supabase_primary():
            result = await self._mongo.delete_many(query)
            if is_actions_dual_write_enabled():
                try:
                    await self._sb_delete(query)  # PostgREST deletes all matches
                except Exception as exc:  # noqa: BLE001
                    logger.warning("actions.store SB dual-write delete_many failed: %s", exc)
            return result
        # Fallback
        return await self.delete_one(query)

    async def create_index(self, *args, **kwargs):
        """Delegate index creation to Mongo only (Postgres indexes live in SQL migrations)."""
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
                logger.warning("actions.store SB find_one %s → %s %s", self.table, resp.status_code, resp.text[:160])
            return None
        rows = resp.json()
        if not rows:
            return None
        return self._from_sb(rows[0])

    async def _sb_find_many(self, query: Dict[str, Any], *, limit: int = 100) -> Optional[List[Dict[str, Any]]]:
        params = _mongo_filter_to_params(query)
        params["limit"] = str(limit)
        resp = await _sb_request("GET", f"/rest/v1/{self.table}", params=params)
        if resp is None or resp.status_code >= 400:
            return None
        rows = resp.json() or []
        return [self._from_sb(r) for r in rows]

    async def _sb_count(self, query: Dict[str, Any]) -> Optional[int]:
        params = _mongo_filter_to_params(query, select="*")
        headers_prefer = "count=exact"
        resp = await _sb_request(
            "GET", f"/rest/v1/{self.table}",
            params={**params, "limit": "0"},
            prefer=headers_prefer,
        )
        if resp is None:
            return None
        # Content-Range: 0-0/123
        cr = resp.headers.get("content-range") or resp.headers.get("Content-Range")
        if cr and "/" in cr:
            try:
                return int(cr.rsplit("/", 1)[-1])
            except ValueError:
                pass
        # Fallback: fetch ids
        rows = await self._sb_find_many(query, limit=10000)
        return None if rows is None else len(rows)

    async def _sb_insert(self, doc: Dict[str, Any], *, raise_dup: bool) -> bool:
        """Return True on success, False if SB unavailable (degrade)."""
        payload = self._to_sb(doc)
        prefer = "return=minimal"
        path = f"/rest/v1/{self.table}"
        if self._conflict:
            path = f"{path}?on_conflict={self._conflict}"
            prefer = "resolution=merge-duplicates,return=minimal"
        resp = await _sb_request("POST", path, json=payload, prefer=prefer)
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

    async def _sb_update(
        self,
        query: Dict[str, Any],
        fields: Dict[str, Any],
        *,
        unset: Optional[Dict[str, Any]] = None,
        upsert: bool = False,
    ) -> Any:
        if not fields and not unset:
            return None
        patch = self._to_sb(fields) if fields else {}
        # Remove identity keys from patch body if they slipped in
        for k in self._identity_keys:
            patch.pop(k, None)
        if unset:
            for k in unset:
                patch[k] = None
        params = _mongo_filter_to_params(query, select="")
        params.pop("select", None)
        if upsert and self._conflict:
            # Upsert via POST on_conflict
            merged = {**{k: query.get(k) for k in self._identity_keys if k in query}, **fields}
            await self._sb_insert(merged, raise_dup=False)
            return True
        resp = await _sb_request(
            "PATCH", f"/rest/v1/{self.table}",
            json=patch, params=params, prefer="return=minimal",
        )
        if resp is not None and resp.status_code >= 400:
            logger.warning(
                "actions.store SB update %s → %s %s",
                self.table, resp.status_code, (resp.text or "")[:200],
            )
        return resp

    async def _sb_find_one_and_update(self, query: Dict[str, Any], fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        patch = self._to_sb(fields)
        for k in self._identity_keys:
            patch.pop(k, None)
        params = _mongo_filter_to_params(query, select="")
        params.pop("select", None)
        resp = await _sb_request(
            "PATCH", f"/rest/v1/{self.table}",
            json=patch, params=params, prefer="return=representation",
        )
        if resp is None or resp.status_code >= 400:
            return None
        rows = resp.json() or []
        if not rows:
            return None
        return self._from_sb(rows[0])

    async def _sb_delete(self, query: Dict[str, Any]) -> None:
        params = _mongo_filter_to_params(query, select="")
        params.pop("select", None)
        resp = await _sb_request(
            "DELETE", f"/rest/v1/{self.table}",
            params=params, prefer="return=minimal",
        )
        if resp is not None and resp.status_code >= 400:
            logger.warning(
                "actions.store SB delete %s → %s %s",
                self.table, resp.status_code, (resp.text or "")[:200],
            )


class _LazyFindCursor:
    """Mimics Motor cursor: find() → sort() → to_list()."""

    def __init__(self, store: DualWriteCollection, query: Dict[str, Any], projection: Optional[Dict[str, int]]):
        self._store = store
        self._query = query
        self._projection = projection
        self._sort: Optional[Tuple[str, int]] = None

    def sort(self, key: str, direction: int = 1):
        self._sort = (key, direction)
        return self

    async def to_list(self, n: int) -> List[Dict[str, Any]]:
        if is_actions_supabase_primary():
            params = _mongo_filter_to_params(self._query)
            params["limit"] = str(n)
            if self._sort:
                key, direction = self._sort
                params["order"] = f"{key}.{'desc' if direction < 0 else 'asc'}"
            resp = await _sb_request("GET", f"/rest/v1/{self._store.table}", params=params)
            if resp is not None and resp.status_code < 400:
                rows = resp.json() or []
                return [_project(_strip_id(self._store._from_sb(r)), self._projection) for r in rows]
            # degrade to mongo
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
            cursor = cursor.sort(self._sort[0], self._sort[1])
        if hasattr(cursor, "to_list"):
            return await cursor.to_list(n)
        return []


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
    )


def wrap_automation_policies_col(mongo_col: Any) -> DualWriteCollection:
    return DualWriteCollection(
        mongo_col,
        table=TABLE_AUTOMATION_POLICIES,
        to_sb=policy_mongo_to_sb,
        from_sb=policy_sb_to_mongo,
        conflict_target="policy_id",
        identity_keys=("policy_id", "workspace_id"),
    )


def wrap_action_policies_col(mongo_col: Any) -> DualWriteCollection:
    return DualWriteCollection(
        mongo_col,
        table=TABLE_ACTION_POLICIES,
        to_sb=action_policy_mongo_to_sb,
        from_sb=action_policy_sb_to_mongo,
        conflict_target="workspace_id,action_id",
        identity_keys=("workspace_id", "action_id"),
    )
