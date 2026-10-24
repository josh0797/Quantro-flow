"""Flow's schemaless collections on Supabase (``public.flow_documents``).

Collections that only ever lived in Mongo — users, workspaces,
workspace_members, workspace_invites, audit_log, people_onboarding_steps,
business_profile, agents, onboarding_tasks, escalation_rules,
system_health_events — are stored one row per document::

    flow_documents(collection, doc_id, workspace_id, doc jsonb,
                   created_at, updated_at)   primary key (collection, doc_id)

``doc_id`` is the Mongo ``_id`` (hex) for backfilled rows and a fresh
ObjectId-shaped hex for new ones, and is exposed as ``_id`` — so
``serialize_doc`` keeps returning the same ``id`` values after the cutover.
``doc`` is the whole document; datetimes round-trip via ``{"$date": …}``
(mongo_compat.to_json), so code that calls ``.isoformat()`` keeps working.
Upgrade hook: a collection can later move to its own typed table without
touching callers, because they only see the Motor-shaped facade below.

Routing (storage_flags ``docs`` domain: ``QUANTRO_DOCS_PRIMARY`` /
``QUANTRO_DOCS_MONGO_MIRROR``):

* supabase primary  — reads/writes Supabase only. With the mirror on, every
  write is replayed on Mongo by ``_id`` and a Supabase miss/error falls back
  to Mongo (logged). With the mirror off Mongo is never touched.
* mongo primary     — Mongo as before; when Supabase is configured every
  write is shadow-copied to Supabase by ``_id`` so the backfill → flip
  window loses nothing.

Filtering: ``workspace_id`` / ``_id`` and a per-collection allowlist of
scalar fields are pushed to PostgREST; the full Mongo filter is always
re-checked in Python (mongo_compat.match), so pushdown can only narrow
the transfer, never change the answer. Updates are read-modify-write with
optimistic concurrency on ``updated_at`` (retried), which gives
``$inc``/``$push``/``find_one_and_update`` their Mongo atomicity per doc.
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import mongo_compat as mc
import mongo_legacy
import sb_rest
import storage_flags

logger = logging.getLogger("quantro.doc_store")

TABLE = "flow_documents"
DOMAIN = "docs"
_MAX_RETRIES = 5

# Top-level scalar fields safe to push down as ``doc->>field=eq.value``.
# (Scalar = never an array, so SQL equality == Mongo equality.)
PUSHDOWN_KEYS: Dict[str, Tuple[str, ...]] = {
    "users": ("user_id", "email"),
    "workspaces": ("workspace_id", "org_id", "owner_user_id"),
    "workspace_members": ("user_id", "role"),
    "workspace_invites": ("token", "invite_id", "role"),
    "audit_log": ("event_type", "target_member_id", "event_id"),
    "people_onboarding_steps": ("member_user_id", "step_key"),
    "business_profile": ("profile_id",),
    "agents": ("agent_id", "status"),
    "onboarding_tasks": ("agent_id", "task_id"),
    "escalation_rules": ("rule_id", "name"),
    "system_health_events": ("scope",),
}

DOC_COLLECTIONS: Tuple[str, ...] = tuple(PUSHDOWN_KEYS)


async def _sb_request(method: str, path: str, **kwargs: Any):
    """Indirection so tests can swap the transport (monkeypatch this)."""
    return await sb_rest.request(method, path, **kwargs)


def _req(method: str, path: str, **kwargs: Any):
    return _sb_request(method, path, **kwargs)


def sb_primary() -> bool:
    return storage_flags.domain_on_supabase(DOMAIN)


def mirror_on() -> bool:
    return storage_flags.domain_mirror(DOMAIN)


# ── row codec ──────────────────────────────────────────────────────────

def doc_to_row(collection: str, doc: Dict[str, Any], *, created_at: Optional[datetime] = None) -> Dict[str, Any]:
    body = {k: v for k, v in doc.items() if k != "_id"}
    ws = doc.get("workspace_id")
    row: Dict[str, Any] = {
        "collection": collection,
        "doc_id": str(doc["_id"]),
        "workspace_id": ws if isinstance(ws, str) else None,
        "doc": mc.to_json(body),
    }
    if created_at is not None:
        row["created_at"] = sb_rest.iso(created_at)
    return row


def row_to_doc(row: Dict[str, Any]) -> Dict[str, Any]:
    body = mc.from_json(row.get("doc") or {})
    out: Dict[str, Any] = {"_id": row.get("doc_id")}
    if isinstance(body, dict):
        out.update(body)
    return out


# ── cursor ─────────────────────────────────────────────────────────────

class DocCursor:
    def __init__(self, col: "FlowDocCollection", query: Dict[str, Any], projection: Optional[Dict[str, Any]],
                 sort: Any = None, skip: int = 0, limit: int = 0):
        self._col = col
        self._query = query or {}
        self._projection = projection
        self._sort: mc.SortSpec = mc.normalize_sort(sort) if sort else []
        self._skip = int(skip or 0)
        self._limit = int(limit or 0)

    def sort(self, key_or_list: Any, direction: Optional[int] = None) -> "DocCursor":
        self._sort = mc.normalize_sort(key_or_list, direction)
        return self

    def skip(self, n: int) -> "DocCursor":
        self._skip = int(n or 0)
        return self

    def limit(self, n: int) -> "DocCursor":
        self._limit = int(n or 0)
        return self

    async def to_list(self, length: Optional[int] = None) -> List[Dict[str, Any]]:
        limit = self._limit
        if length:
            limit = min(limit, int(length)) if limit else int(length)
        return await self._col._find_docs(
            self._query, projection=self._projection, sort=self._sort, skip=self._skip, limit=limit,
        )

    def __aiter__(self):
        self._iter_docs: Optional[List[Dict[str, Any]]] = None
        self._iter_pos = 0
        return self

    async def __anext__(self) -> Dict[str, Any]:
        if self._iter_docs is None:
            self._iter_docs = await self.to_list(None)
        if self._iter_pos >= len(self._iter_docs):
            raise StopAsyncIteration
        doc = self._iter_docs[self._iter_pos]
        self._iter_pos += 1
        return doc


# ── collection ─────────────────────────────────────────────────────────

class FlowDocCollection:
    """Motor-shaped collection backed by ``flow_documents`` (+ legacy Mongo)."""

    def __init__(self, name: str, mongo_col: Any = None):
        self.name = name
        self._mongo = mongo_col
        self._pushdown = set(PUSHDOWN_KEYS.get(name, ()))

    # ── routing helpers ────────────────────────────────────────────────
    def _use_sb(self) -> bool:
        return sb_primary()

    def _mongo_ok(self) -> bool:
        return self._mongo is not None and (not self._use_sb() or mirror_on())

    def _shadow_sb(self) -> bool:
        return not self._use_sb() and sb_rest.configured()

    # ── pushdown ───────────────────────────────────────────────────────
    def _params(self, query: Dict[str, Any]) -> Tuple[Dict[str, str], bool]:
        """(params, exact). Raises sb_rest.Impossible for never-matching filters."""
        params: Dict[str, str] = {"collection": f"eq.{self.name}"}
        exact = True
        for key, cond in (query or {}).items():
            if key == "_id":
                pushed = self._push_scalar("doc_id", cond, allow_in=True)
            elif key == "workspace_id":
                pushed = self._push_scalar("workspace_id", cond, allow_in=True)
            elif key in self._pushdown:
                pushed = self._push_scalar(f"doc->>{key}", cond, allow_in=True, json_text=True)
            else:
                pushed = None
            if pushed is None:
                exact = False
                continue
            col, val = pushed
            if col in params:
                exact = False
                continue
            params[col] = val
        return params, exact

    @staticmethod
    def _push_scalar(col: str, cond: Any, *, allow_in: bool, json_text: bool = False) -> Optional[Tuple[str, str]]:
        def _txt(v: Any) -> Optional[str]:
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, (str, int)) and not isinstance(v, bool):
                return str(v)
            return None

        if isinstance(cond, dict):
            if set(cond) == {"$in"} and allow_in and isinstance(cond["$in"], (list, tuple)):
                vals = [_txt(v) for v in cond["$in"]]
                if not cond["$in"]:
                    raise sb_rest.Impossible()
                if any(v is None for v in vals):
                    return None
                return col, "in.(" + ",".join(sb_rest.quote(v) for v in vals) + ")"
            if set(cond) == {"$eq"}:
                cond = cond["$eq"]
            else:
                return None
        v = _txt(cond)
        if v is None:
            return None
        return col, f"eq.{v}"

    # ── Supabase primitives ────────────────────────────────────────────
    async def _sb_rows(self, query: Dict[str, Any], *, limit: int = 0) -> List[Dict[str, Any]]:
        """Rows whose doc matches ``query`` (natural order). Raises on SB error."""
        try:
            params, exact = self._params(query)
        except sb_rest.Impossible:
            return []
        params["select"] = "doc_id,doc,updated_at"
        rows = await sb_rest.fetch_all(
            _req, TABLE, params,
            order="created_at.asc,doc_id.asc",
            limit=(limit or None) if exact else None,
        )
        if rows is None:
            raise sb_rest.SupabaseStoreError(f"flow_documents read failed ({self.name})", table=TABLE)
        out: List[Dict[str, Any]] = []
        for row in rows:
            doc = row_to_doc(row)
            if mc.match(doc, query):
                row["_decoded"] = doc
                out.append(row)
                if limit and len(out) >= limit:
                    break
        return out

    async def _sb_find(self, query: Dict[str, Any], *, sort: mc.SortSpec, skip: int, limit: int) -> List[Dict[str, Any]]:
        need = 0 if sort else ((skip + limit) if limit else 0)
        rows = await self._sb_rows(query, limit=need)
        docs = [r["_decoded"] for r in rows]
        if sort:
            docs = mc.sort_docs(docs, sort)
        if skip:
            docs = docs[skip:]
        if limit:
            docs = docs[:limit]
        return docs

    async def _sb_insert_doc(self, doc: Dict[str, Any], *, created_at: Optional[datetime] = None) -> None:
        resp = await _req(
            "POST", f"/rest/v1/{TABLE}",
            json=doc_to_row(self.name, doc, created_at=created_at),
            prefer="return=minimal",
        )
        if resp is not None and resp.status_code == 409:
            raise mc.DuplicateKeyError(f"duplicate _id in {self.name}")
        if resp is None or resp.status_code >= 400:
            raise sb_rest.SupabaseStoreError(
                f"flow_documents insert failed ({self.name}): {sb_rest.short_error(resp)}", table=TABLE,
                status=getattr(resp, "status_code", None),
            )

    async def _sb_replace(self, doc: Dict[str, Any], expected_updated_at: Optional[str]) -> bool:
        """Write ``doc`` over its row iff the row is unchanged. False = conflict."""
        row = doc_to_row(self.name, doc)
        params = {
            "collection": f"eq.{self.name}",
            "doc_id": f"eq.{row['doc_id']}",
            "select": "doc_id",
        }
        if expected_updated_at:
            params["updated_at"] = f"eq.{expected_updated_at}"
        resp = await _req(
            "PATCH", f"/rest/v1/{TABLE}",
            json={"doc": row["doc"], "workspace_id": row["workspace_id"]},
            params=params,
            prefer="return=representation",
        )
        if resp is None or resp.status_code >= 400:
            raise sb_rest.SupabaseStoreError(
                f"flow_documents update failed ({self.name}): {sb_rest.short_error(resp)}", table=TABLE,
            )
        return bool(resp.json() or [])

    async def _sb_delete_ids(self, ids: Sequence[str]) -> int:
        deleted = 0
        for chunk in sb_rest.chunked(list(ids), 100):
            resp = await _req(
                "DELETE", f"/rest/v1/{TABLE}",
                params={
                    "collection": f"eq.{self.name}",
                    "doc_id": "in.(" + ",".join(sb_rest.quote(i) for i in chunk) + ")",
                    "select": "doc_id",
                },
                prefer="return=representation",
            )
            if resp is None or resp.status_code >= 400:
                raise sb_rest.SupabaseStoreError(
                    f"flow_documents delete failed ({self.name}): {sb_rest.short_error(resp)}", table=TABLE,
                )
            deleted += len(resp.json() or [])
        return deleted

    async def upsert_docs(self, docs: Iterable[Dict[str, Any]], *, created_at_from_id: bool = False) -> int:
        """Idempotent upsert by ``_id`` (shadow writes + backfill). Returns rows sent."""
        rows = []
        for d in docs:
            if d.get("_id") is None:
                continue
            created = _object_id_time(d["_id"]) if created_at_from_id else None
            rows.append(doc_to_row(self.name, {**d, "_id": str(d["_id"])}, created_at=created))
        sent = 0
        for chunk in sb_rest.chunked(rows, 200):
            resp = await _req(
                "POST", f"/rest/v1/{TABLE}?on_conflict=collection,doc_id",
                json=list(chunk),
                prefer="resolution=merge-duplicates,return=minimal",
            )
            if resp is None or resp.status_code >= 400:
                raise sb_rest.SupabaseStoreError(
                    f"flow_documents upsert failed ({self.name}): {sb_rest.short_error(resp)}", table=TABLE,
                )
            sent += len(chunk)
        return sent

    # ── shadow (mongo primary) / mirror (supabase primary) ─────────────
    async def _mongo_ids(self, query: Dict[str, Any], *, one: bool) -> List[Any]:
        try:
            cur = self._mongo.find(query, {"_id": 1})
            docs = await cur.to_list(1 if one else None)
        except TypeError:
            docs = await self._mongo.find(query).to_list(1 if one else None)
        return [d.get("_id") for d in docs if d.get("_id") is not None]

    async def _shadow_sync_ids(self, ids: List[Any]) -> None:
        if not ids:
            return
        try:
            docs = await self._mongo.find({"_id": {"$in": ids}}).to_list(None)
            await self.upsert_docs(docs, created_at_from_id=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s doc_store shadow sync %s failed: %s", storage_flags.MONGO_ONLY, self.name, exc)

    async def _shadow_delete_ids(self, ids: List[Any]) -> None:
        if not ids:
            return
        try:
            await self._sb_delete_ids([str(i) for i in ids])
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s doc_store shadow delete %s failed (Supabase kept the row): %s",
                           storage_flags.STORE_DRIFT, self.name, exc)

    async def _mirror_replace(self, docs: List[Dict[str, Any]]) -> None:
        if not docs or not self._mongo_ok():
            return
        for d in docs:
            try:
                body = {k: v for k, v in d.items() if k != "_id"}
                await self._mongo.replace_one({"_id": mongo_legacy.to_mongo_id(d["_id"])}, body, upsert=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s doc_store mongo mirror %s failed: %s", storage_flags.STORE_DRIFT, self.name, exc)

    async def _mirror_delete(self, ids: List[str]) -> None:
        if not ids or not self._mongo_ok():
            return
        try:
            await self._mongo.delete_many({"_id": {"$in": [mongo_legacy.to_mongo_id(i) for i in ids]}})
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s doc_store mongo mirror delete %s failed: %s", storage_flags.STORE_DRIFT, self.name, exc)

    # ── reads ──────────────────────────────────────────────────────────
    async def _find_docs(self, query: Dict[str, Any], *, projection: Optional[Dict[str, Any]] = None,
                         sort: Optional[mc.SortSpec] = None, skip: int = 0, limit: int = 0) -> List[Dict[str, Any]]:
        sort = sort or []
        if self._use_sb():
            try:
                docs = await self._sb_find(query, sort=sort, skip=skip, limit=limit)
                return [mc.project(d, projection) for d in docs]
            except sb_rest.SupabaseStoreError:
                if not self._mongo_ok():
                    raise
                logger.warning("%s doc_store %s: Supabase read failed — Mongo mirror fallback", storage_flags.MONGO_ONLY, self.name)
        cur = self._mongo.find(query, projection) if projection is not None else self._mongo.find(query)
        if sort and hasattr(cur, "sort"):
            cur = cur.sort(sort)
        if skip and hasattr(cur, "skip"):
            cur = cur.skip(skip)
        if limit and hasattr(cur, "limit"):
            cur = cur.limit(limit)
        return await cur.to_list(limit or None)

    def find(self, query: Optional[Dict[str, Any]] = None, projection: Optional[Dict[str, Any]] = None, *,
             sort: Any = None, skip: int = 0, limit: int = 0, **_: Any) -> DocCursor:
        return DocCursor(self, query or {}, projection, sort=sort, skip=skip, limit=limit)

    async def find_one(self, query: Optional[Dict[str, Any]] = None, projection: Optional[Dict[str, Any]] = None, *,
                       sort: Any = None, **_: Any) -> Optional[Dict[str, Any]]:
        query = query or {}
        spec = mc.normalize_sort(sort) if sort else []
        miss = False
        if self._use_sb():
            try:
                docs = await self._sb_find(query, sort=spec, skip=0, limit=1)
                if docs:
                    return mc.project(docs[0], projection)
                if not self._mongo_ok():
                    return None
                miss = True
            except sb_rest.SupabaseStoreError:
                if not self._mongo_ok():
                    raise
                logger.warning("%s doc_store %s: Supabase read failed — Mongo mirror fallback", storage_flags.MONGO_ONLY, self.name)
        if spec:
            docs = await self._find_docs_mongo(query, projection, spec, 1)
            doc = docs[0] if docs else None
        elif projection is not None:
            doc = await self._mongo.find_one(query, projection)
        else:
            doc = await self._mongo.find_one(query)
        if miss and doc is not None:
            # A row Supabase does not have: the backfill missed it or a
            # Supabase write degraded. Ids only, never the document.
            logger.warning("%s doc_store %s: row only in Mongo (_id=%s) — re-run the backfill",
                           storage_flags.MONGO_ONLY, self.name, doc.get("_id", "?"))
        return doc

    async def _find_docs_mongo(self, query, projection, sort, limit):
        cur = self._mongo.find(query, projection) if projection is not None else self._mongo.find(query)
        if sort:
            cur = cur.sort(sort)
        return await cur.to_list(limit)

    async def count_documents(self, query: Optional[Dict[str, Any]] = None, **_: Any) -> int:
        query = query or {}
        if self._use_sb():
            try:
                try:
                    params, exact = self._params(query)
                except sb_rest.Impossible:
                    return 0
                if exact:
                    n = await sb_rest.count_exact(_req, TABLE, params)
                    if n is None:
                        raise sb_rest.SupabaseStoreError(f"flow_documents count failed ({self.name})", table=TABLE)
                    return n
                return len(await self._sb_rows(query))
            except sb_rest.SupabaseStoreError:
                if not self._mongo_ok():
                    raise
                logger.warning("%s doc_store %s: Supabase count failed — Mongo mirror fallback", storage_flags.MONGO_ONLY, self.name)
        return await self._mongo.count_documents(query)

    # ── writes ─────────────────────────────────────────────────────────
    async def insert_one(self, doc: Dict[str, Any], *_, **__) -> mc.InsertOneResult:
        if self._use_sb():
            if doc.get("_id") is None:
                doc["_id"] = mc.new_object_id()  # Motor also mutates the caller's dict
            else:
                doc["_id"] = str(doc["_id"])
            await self._sb_insert_doc(doc)
            await self._mirror_replace([copy.deepcopy(doc)])
            return mc.InsertOneResult(doc["_id"])
        res = await self._mongo.insert_one(doc)
        if self._shadow_sb():
            _id = doc.get("_id") if doc.get("_id") is not None else getattr(res, "inserted_id", None)
            if _id is not None:
                try:
                    await self.upsert_docs([{**doc, "_id": _id}], created_at_from_id=True)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s doc_store shadow insert %s failed: %s", storage_flags.MONGO_ONLY, self.name, exc)
        return res

    async def insert_many(self, docs: List[Dict[str, Any]], *_, **__) -> mc.InsertManyResult:
        if self._use_sb():
            ids = []
            for d in docs:
                ids.append((await self.insert_one(d)).inserted_id)
            return mc.InsertManyResult(ids)
        res = await self._mongo.insert_many(docs)
        if self._shadow_sb():
            try:
                await self.upsert_docs([d for d in docs if d.get("_id") is not None], created_at_from_id=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s doc_store shadow insert_many %s failed: %s", storage_flags.MONGO_ONLY, self.name, exc)
        return res

    async def _sb_update(self, query: Dict[str, Any], update: Dict[str, Any], *, upsert: bool, many: bool,
                         sort: Optional[mc.SortSpec] = None) -> Tuple[mc.UpdateResult, List[Tuple[Dict[str, Any], Dict[str, Any]]]]:
        """Read-modify-write with optimistic retry. Returns (result, [(before, after)])."""
        changed: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        matched = modified = 0
        handled: set = set()
        for _attempt in range(_MAX_RETRIES):
            rows = await self._sb_rows(query, limit=0 if (many or sort) else 1)
            if sort and rows:
                ordered = mc.sort_docs([r["_decoded"] for r in rows], sort)
                by_id = {r["doc_id"]: r for r in rows}
                rows = [by_id[d["_id"]] for d in ordered]
            if not many:
                rows = rows[:1]
            rows = [r for r in rows if r["doc_id"] not in handled]
            conflict = False
            for row in rows:
                before = row["_decoded"]
                after = mc.apply_update(before, update)
                after["_id"] = before["_id"]
                handled.add(row["doc_id"])
                matched += 1
                if after == before:
                    continue
                if await self._sb_replace(after, row.get("updated_at")):
                    modified += 1
                    changed.append((before, after))
                else:
                    handled.discard(row["doc_id"])
                    matched -= 1
                    conflict = True
            if not conflict:
                break
        else:
            raise sb_rest.SupabaseStoreError(f"flow_documents update kept conflicting ({self.name})", table=TABLE)

        if matched == 0 and upsert:
            seed = mc.seed_from_query(query)
            new_doc = mc.apply_update(seed, update, is_insert=True)
            new_doc["_id"] = str(new_doc.get("_id") or mc.new_object_id())
            await self._sb_insert_doc(new_doc)
            changed.append(({}, new_doc))
            return mc.UpdateResult(0, 0, new_doc["_id"]), changed
        return mc.UpdateResult(matched, modified), changed

    async def update_one(self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False, **_: Any) -> mc.UpdateResult:
        if self._use_sb():
            res, changed = await self._sb_update(query, update, upsert=upsert, many=False)
            await self._mirror_replace([a for _, a in changed])
            return res
        ids = await self._mongo_ids(query, one=True) if self._shadow_sb() else []
        res = await self._mongo.update_one(query, update, upsert=upsert)
        if self._shadow_sb():
            upserted = getattr(res, "upserted_id", None)
            if upserted is not None:
                ids.append(upserted)
            if getattr(res, "modified_count", 1) or upserted is not None:
                await self._shadow_sync_ids(ids)
        return res

    async def update_many(self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False, **_: Any) -> mc.UpdateResult:
        if self._use_sb():
            res, changed = await self._sb_update(query, update, upsert=upsert, many=True)
            await self._mirror_replace([a for _, a in changed])
            return res
        ids = await self._mongo_ids(query, one=False) if self._shadow_sb() else []
        res = await self._mongo.update_many(query, update, upsert=upsert) if upsert else await self._mongo.update_many(query, update)
        if self._shadow_sb():
            upserted = getattr(res, "upserted_id", None)
            if upserted is not None:
                ids.append(upserted)
            if getattr(res, "modified_count", 1) or upserted is not None:
                await self._shadow_sync_ids(ids)
        return res

    async def replace_one(self, query: Dict[str, Any], replacement: Dict[str, Any], upsert: bool = False, **_: Any) -> mc.UpdateResult:
        return await self.update_one(query, {k: v for k, v in replacement.items() if k != "_id"} or {"$set": {}}, upsert=upsert)

    async def find_one_and_update(self, query: Dict[str, Any], update: Dict[str, Any], projection: Optional[Dict[str, Any]] = None,
                                  return_document: Any = False, upsert: bool = False, sort: Any = None, **_: Any) -> Optional[Dict[str, Any]]:
        spec = mc.normalize_sort(sort) if sort else None
        if self._use_sb():
            res, changed = await self._sb_update(query, update, upsert=upsert, many=False, sort=spec)
            await self._mirror_replace([a for _, a in changed])
            if changed:
                before, after = changed[0]
                if res.upserted_id is not None:
                    return mc.project(after, projection) if return_document else None
                return mc.project(after if return_document else before, projection)
            if res.matched_count:
                # Matched but no change: before == after.
                docs = await self._sb_find(query, sort=spec or [], skip=0, limit=1)
                return mc.project(docs[0], projection) if docs else None
            return None
        ids = await self._mongo_ids(query, one=True) if self._shadow_sb() else []
        kwargs: Dict[str, Any] = {"upsert": upsert}
        if projection is not None:
            kwargs["projection"] = projection
        if return_document:
            kwargs["return_document"] = return_document
        if sort:
            kwargs["sort"] = sort
        doc = await self._mongo.find_one_and_update(query, update, **kwargs)
        if self._shadow_sb():
            if not ids and doc is not None and doc.get("_id") is not None:
                ids.append(doc["_id"])
            await self._shadow_sync_ids(ids)
        return doc

    async def find_one_and_delete(self, query: Dict[str, Any], projection: Optional[Dict[str, Any]] = None, **_: Any) -> Optional[Dict[str, Any]]:
        if self._use_sb():
            for _attempt in range(_MAX_RETRIES):
                rows = await self._sb_rows(query, limit=1)
                if not rows:
                    return None
                n = await self._sb_delete_ids([rows[0]["doc_id"]])
                if n:
                    await self._mirror_delete([rows[0]["doc_id"]])
                    return mc.project(rows[0]["_decoded"], projection)
            return None
        doc = await self._mongo.find_one_and_delete(query, projection=projection) if projection else await self._mongo.find_one_and_delete(query)
        if self._shadow_sb() and doc is not None and doc.get("_id") is not None:
            await self._shadow_delete_ids([doc["_id"]])
        return doc

    async def delete_one(self, query: Dict[str, Any], **_: Any) -> mc.DeleteResult:
        if self._use_sb():
            rows = await self._sb_rows(query, limit=1)
            ids = [r["doc_id"] for r in rows]
            n = await self._sb_delete_ids(ids) if ids else 0
            await self._mirror_delete(ids)
            return mc.DeleteResult(n)
        ids = await self._mongo_ids(query, one=True) if self._shadow_sb() else []
        res = await self._mongo.delete_one(query)
        if self._shadow_sb():
            await self._shadow_delete_ids(ids)
        return res

    async def delete_many(self, query: Dict[str, Any], **_: Any) -> mc.DeleteResult:
        if self._use_sb():
            rows = await self._sb_rows(query)
            ids = [r["doc_id"] for r in rows]
            n = await self._sb_delete_ids(ids) if ids else 0
            await self._mirror_delete(ids)
            return mc.DeleteResult(n)
        ids = await self._mongo_ids(query, one=False) if self._shadow_sb() else []
        res = await self._mongo.delete_many(query)
        if self._shadow_sb():
            await self._shadow_delete_ids(ids)
        return res

    async def create_index(self, *args: Any, **kwargs: Any) -> Any:
        """Postgres indexes live in migrations; only Mongo gets create_index."""
        if not self._use_sb() and self._mongo is not None:
            return await self._mongo.create_index(*args, **kwargs)
        return None


def _object_id_time(value: Any) -> Optional[datetime]:
    """Creation time embedded in an ObjectId (keeps natural order on backfill)."""
    try:
        if hasattr(value, "generation_time"):
            return value.generation_time
        if mc.is_object_id_hex(value):
            return datetime.fromtimestamp(int(value[:8], 16), tz=timezone.utc)
    except Exception:  # noqa: BLE001
        return None
    return None


def wrap(name: str, mongo_col: Any = None) -> FlowDocCollection:
    return FlowDocCollection(name, mongo_col)
