"""Phase 6.2–6.3 — dual-write facades for activity / content / CRM / calendar.

Mirrors ``inbox_store.InboxDualWriteCollection`` with per-domain config.
Primary flags default to mongo; dual-write when SUPABASE_* configured.

Env
---
QUANTRO_ACTIVITY_PRIMARY / QUANTRO_CONTENT_PRIMARY /
QUANTRO_CONTACTS_PRIMARY / QUANTRO_CALENDAR_PRIMARY
  ``mongo`` (default) | ``supabase``

QUANTRO_*_MONGO_MIRROR or QUANTRO_MONGO_MIRROR (default on when primary=supabase)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

logger = logging.getLogger("quantro.product_domain.store")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _is_sb_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _env_primary(name: str) -> str:
    raw = (os.environ.get(name) or "mongo").lower().strip()
    return raw if raw in {"mongo", "supabase"} else "mongo"


def _env_mirror(dedicated: str) -> bool:
    val = os.environ.get(dedicated)
    if val is None or val == "":
        val = os.environ.get("QUANTRO_MONGO_MIRROR") or "1"
    return str(val).lower().strip() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class DomainConfig:
    name: str
    table: str
    app_id_field: str          # e.g. event_id / contact_id
    primary_env: str
    mirror_env: str
    known_cols: frozenset
    dt_keys: frozenset
    json_keys: frozenset
    conflict: str              # on_conflict columns


ACTIVITY_CFG = DomainConfig(
    name="activity",
    table="activity_events",
    app_id_field="event_id",
    primary_env="QUANTRO_ACTIVITY_PRIMARY",
    mirror_env="QUANTRO_ACTIVITY_MONGO_MIRROR",
    known_cols=frozenset({
        "event_id", "workspace_id", "event_type", "title", "description",
        "related_id", "related_type", "timestamp", "is_simulation",
        "created_at", "updated_at",
    }),
    dt_keys=frozenset({"timestamp", "created_at", "updated_at"}),
    json_keys=frozenset(),
    conflict="workspace_id,event_id",
)

CONTENT_ITEMS_CFG = DomainConfig(
    name="content_items",
    table="content_items",
    app_id_field="content_id",
    primary_env="QUANTRO_CONTENT_PRIMARY",
    mirror_env="QUANTRO_CONTENT_MONGO_MIRROR",
    known_cols=frozenset({
        "content_id", "workspace_id", "type", "title", "content", "status",
        "created_by", "is_simulation", "created_at", "updated_at",
    }),
    dt_keys=frozenset({"created_at", "updated_at"}),
    json_keys=frozenset({"content"}),
    conflict="workspace_id,content_id",
)

CONTENT_TEMPLATES_CFG = DomainConfig(
    name="content_templates",
    table="content_templates",
    app_id_field="template_id",
    primary_env="QUANTRO_CONTENT_PRIMARY",
    mirror_env="QUANTRO_CONTENT_MONGO_MIRROR",
    known_cols=frozenset({
        "template_id", "workspace_id", "name", "category", "body", "channel",
        "is_default", "is_simulation", "created_at", "updated_at",
    }),
    dt_keys=frozenset({"created_at", "updated_at"}),
    json_keys=frozenset({"body"}),
    conflict="workspace_id,template_id",
)

CONTACTS_CFG = DomainConfig(
    name="contacts",
    table="contacts",
    app_id_field="contact_id",
    primary_env="QUANTRO_CONTACTS_PRIMARY",
    mirror_env="QUANTRO_CONTACTS_MONGO_MIRROR",
    known_cols=frozenset({
        "contact_id", "workspace_id", "name", "email", "phone", "type",
        "lifecycle_stage", "source", "notes", "tags",
        "ghl_sync_status", "ghl_last_sync", "ghl_id",
        "is_simulation", "created_at", "updated_at",
    }),
    dt_keys=frozenset({"ghl_last_sync", "created_at", "updated_at"}),
    json_keys=frozenset({"tags"}),
    conflict="workspace_id,contact_id",
)

CALENDAR_CFG = DomainConfig(
    name="calendar",
    table="calendar_events",
    app_id_field="event_id",
    primary_env="QUANTRO_CALENDAR_PRIMARY",
    mirror_env="QUANTRO_CALENDAR_MONGO_MIRROR",
    known_cols=frozenset({
        "event_id", "workspace_id", "title", "description",
        "start_time", "end_time", "location", "attendees", "status",
        "source", "contact_id", "google_event_id",
        "is_simulation", "hidden_by_real",
        "created_at", "updated_at",
    }),
    dt_keys=frozenset({"start_time", "end_time", "created_at", "updated_at"}),
    json_keys=frozenset({"attendees"}),
    conflict="workspace_id,event_id",
)


def _primary(cfg: DomainConfig) -> str:
    return _env_primary(cfg.primary_env)


def is_supabase_primary(cfg: DomainConfig) -> bool:
    return _primary(cfg) == "supabase" and _is_sb_configured()


def is_dual_write(cfg: DomainConfig) -> bool:
    return _is_sb_configured()


def is_mongo_write(cfg: DomainConfig) -> bool:
    if not _is_sb_configured():
        return True
    if _primary(cfg) != "supabase":
        return True
    return _env_mirror(cfg.mirror_env)


def domain_health(cfg: DomainConfig) -> Dict[str, Any]:
    return {
        f"{cfg.name}_primary": _primary(cfg),
        "supabase_configured": _is_sb_configured(),
        "dual_write": is_dual_write(cfg),
        "mongo_write": is_mongo_write(cfg),
        "table": cfg.table,
    }


def product_domains_health() -> Dict[str, Any]:
    return {
        c.name: domain_health(c)
        for c in (ACTIVITY_CFG, CONTENT_ITEMS_CFG, CONTENT_TEMPLATES_CFG, CONTACTS_CFG, CALENDAR_CFG)
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


async def _sb_request(
    method: str,
    path: str,
    *,
    json: Any = None,
    params: Optional[Dict[str, str]] = None,
    prefer: Optional[str] = None,
) -> Optional[httpx.Response]:
    headers = _service_headers(prefer)
    if not headers or not SUPABASE_URL:
        return None
    url = f"{SUPABASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            return await client.request(method, url, headers=headers, json=json, params=params)
    except Exception as exc:
        logger.warning("product_domain SB %s %s failed: %s", method, path, exc)
        return None


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value) if value != "" else None


def _parse_dt(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return value


def mongo_to_sb(cfg: DomainConfig, doc: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    src = dict(doc)
    if "id" in src and cfg.app_id_field not in src:
        src[cfg.app_id_field] = src["id"]
    for k, v in src.items():
        if k == "id" or k == "_id":
            continue
        if k not in cfg.known_cols:
            continue
        if k in cfg.dt_keys:
            out[k] = _iso(v)
        else:
            out[k] = v
    if cfg.app_id_field not in out and src.get(cfg.app_id_field):
        out[cfg.app_id_field] = src[cfg.app_id_field]
    return out


def sb_to_mongo(cfg: DomainConfig, row: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in row.items() if k != "id"}
    for k in cfg.dt_keys:
        if k in out:
            out[k] = _parse_dt(out[k])
    return out


def _mongo_filter_to_params(query: Dict[str, Any], *, select: str = "*") -> Dict[str, str]:
    params: Dict[str, str] = {}
    if select:
        params["select"] = select
    for k, v in (query or {}).items():
        if k == "_id":
            continue
        if isinstance(v, dict):
            if "$in" in v:
                vals = ",".join(str(x) for x in v["$in"])
                params[k] = f"in.({vals})"
            elif "$ne" in v:
                params[k] = f"neq.{v['$ne']}"
            elif "$exists" in v:
                params[k] = "not.is.null" if v["$exists"] else "is.null"
            else:
                # skip complex ops
                continue
        elif v is None:
            params[k] = "is.null"
        elif isinstance(v, bool):
            params[k] = f"eq.{str(v).lower()}"
        else:
            params[k] = f"eq.{v}"
    return params


def _strip_pg_id(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return doc
    d = dict(doc)
    d.pop("id", None)
    return d


def _project(doc: Optional[Dict[str, Any]], projection: Optional[Dict[str, int]]):
    if not doc or not projection:
        return doc
    include = {k for k, v in projection.items() if v}
    if include:
        return {k: doc[k] for k in include if k in doc}
    exclude = {k for k, v in projection.items() if not v}
    return {k: v for k, v in doc.items() if k not in exclude}


class DualWriteCollection:
    def __init__(self, mongo_col: Any, cfg: DomainConfig):
        self._mongo = mongo_col
        self.cfg = cfg
        self.table = cfg.table

    def find(self, query: Optional[Dict[str, Any]] = None, projection: Optional[Dict[str, int]] = None):
        return _LazyFindCursor(self, query or {}, projection)

    async def find_one(self, query: Dict[str, Any], projection: Optional[Dict[str, int]] = None):
        if is_supabase_primary(self.cfg):
            row = await self._sb_find_one(query)
            if row is not None:
                return _project(_strip_pg_id(sb_to_mongo(self.cfg, row)), projection)
        try:
            doc = await self._mongo.find_one(query, projection) if projection is not None else await self._mongo.find_one(query)
        except TypeError:
            doc = await self._mongo.find_one(query)
        return doc

    async def count_documents(self, query: Dict[str, Any]) -> int:
        if is_supabase_primary(self.cfg):
            n = await self._sb_count(query)
            if n is not None:
                return n
        return await self._mongo.count_documents(query)

    async def insert_one(self, doc: Dict[str, Any]):
        if is_mongo_write(self.cfg):
            result = await self._mongo.insert_one(doc)
        else:
            class _R:
                inserted_id = doc.get("_id") or doc.get(self.cfg.app_id_field)
            result = _R()
        if is_dual_write(self.cfg):
            await self._sb_upsert_doc(doc)
        return result

    async def insert_many(self, docs: List[Dict[str, Any]]):
        if is_mongo_write(self.cfg):
            result = await self._mongo.insert_many(docs)
        else:
            class _R:
                inserted_ids = [d.get("_id") or d.get(self.cfg.app_id_field) for d in docs]
            result = _R()
        if is_dual_write(self.cfg):
            for d in docs:
                await self._sb_upsert_doc(d)
        return result

    async def update_one(self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False):
        if is_mongo_write(self.cfg):
            result = await self._mongo.update_one(query, update, upsert=upsert)
        else:
            class _R:
                matched_count = 1
                modified_count = 1
                upserted_id = None
            result = _R()
        if is_dual_write(self.cfg):
            await self._sb_update(query, update, upsert=upsert)
        return result

    async def update_many(self, query: Dict[str, Any], update: Dict[str, Any]):
        if is_mongo_write(self.cfg):
            result = await self._mongo.update_many(query, update)
        else:
            class _R:
                matched_count = 0
                modified_count = 0
            result = _R()
        if is_dual_write(self.cfg):
            await self._sb_update(query, update, upsert=False)
        return result

    async def delete_one(self, query: Dict[str, Any]):
        if is_mongo_write(self.cfg):
            result = await self._mongo.delete_one(query)
        else:
            class _R:
                deleted_count = 1
            result = _R()
        if is_dual_write(self.cfg):
            await self._sb_delete(query)
        return result

    async def delete_many(self, query: Dict[str, Any]):
        if is_mongo_write(self.cfg):
            result = await self._mongo.delete_many(query)
        else:
            class _R:
                deleted_count = 0
            result = _R()
        if is_dual_write(self.cfg):
            await self._sb_delete(query)
        return result

    async def create_index(self, *args, **kwargs):
        if hasattr(self._mongo, "create_index"):
            return await self._mongo.create_index(*args, **kwargs)

    async def _sb_find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        params = _mongo_filter_to_params(query)
        params["limit"] = "1"
        resp = await _sb_request("GET", f"/rest/v1/{self.table}", params=params)
        if resp is None or resp.status_code >= 400:
            return None
        rows = resp.json() or []
        return rows[0] if rows else None

    async def _sb_count(self, query: Dict[str, Any]) -> Optional[int]:
        params = _mongo_filter_to_params(query, select="")
        headers = _service_headers("count=exact")
        if not headers or not SUPABASE_URL:
            return None
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.head(
                    f"{SUPABASE_URL}/rest/v1/{self.table}",
                    headers={**headers, "Prefer": "count=exact"},
                    params=params,
                )
            cr = resp.headers.get("content-range") or ""
            if "/" in cr:
                return int(cr.split("/")[-1])
        except Exception as exc:
            logger.warning("%s SB count failed: %s", self.cfg.name, exc)
        return None

    async def _sb_upsert_doc(self, doc: Dict[str, Any]) -> bool:
        payload = mongo_to_sb(self.cfg, doc)
        if not payload.get("workspace_id") or not payload.get(self.cfg.app_id_field):
            logger.warning("%s upsert skip — missing workspace_id/%s", self.cfg.name, self.cfg.app_id_field)
            return False
        resp = await _sb_request(
            "POST",
            f"/rest/v1/{self.table}?on_conflict={self.cfg.conflict}",
            json=payload,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        if resp is not None and resp.status_code >= 400:
            logger.warning("%s SB upsert → %s %s", self.cfg.name, resp.status_code, (resp.text or "")[:160])
            return False
        return True

    async def _sb_update(self, query: Dict[str, Any], update: Dict[str, Any], *, upsert: bool) -> None:
        fields = update.get("$set") or {}
        set_on_insert = update.get("$setOnInsert") or {}
        unset = update.get("$unset") or {}
        if upsert:
            merged = {**{k: query.get(k) for k in ("workspace_id", self.cfg.app_id_field) if k in query}}
            merged.update(set_on_insert)
            merged.update(fields)
            if not merged.get(self.cfg.app_id_field):
                merged[self.cfg.app_id_field] = query.get(self.cfg.app_id_field) or query.get("id")
            await self._sb_upsert_doc(merged)
            return
        patch = mongo_to_sb(self.cfg, fields) if fields else {}
        for k in unset:
            if k in self.cfg.known_cols:
                patch[k] = None
        params = _mongo_filter_to_params(query, select="")
        params.pop("select", None)
        resp = await _sb_request("PATCH", f"/rest/v1/{self.table}", json=patch, params=params, prefer="return=minimal")
        if resp is not None and resp.status_code >= 400:
            logger.warning("%s SB update → %s %s", self.cfg.name, resp.status_code, (resp.text or "")[:160])

    async def _sb_delete(self, query: Dict[str, Any]) -> None:
        params = _mongo_filter_to_params(query, select="")
        params.pop("select", None)
        resp = await _sb_request("DELETE", f"/rest/v1/{self.table}", params=params, prefer="return=minimal")
        if resp is not None and resp.status_code >= 400:
            logger.warning("%s SB delete → %s %s", self.cfg.name, resp.status_code, (resp.text or "")[:160])


class _LazyFindCursor:
    def __init__(self, store: DualWriteCollection, query: Dict[str, Any], projection: Optional[Dict[str, int]]):
        self._store = store
        self._query = query
        self._projection = projection
        self._sort: Optional[Tuple[str, int]] = None

    def sort(self, key: str, direction: int = 1):
        self._sort = (key, direction)
        return self

    async def to_list(self, n: int) -> List[Dict[str, Any]]:
        cfg = self._store.cfg
        if is_supabase_primary(cfg):
            params = _mongo_filter_to_params(self._query)
            params["limit"] = str(n)
            if self._sort:
                key, direction = self._sort
                params["order"] = f"{key}.{'desc' if direction < 0 else 'asc'}"
            resp = await _sb_request("GET", f"/rest/v1/{self._store.table}", params=params)
            if resp is not None and resp.status_code < 400:
                rows = resp.json() or []
                return [_project(_strip_pg_id(sb_to_mongo(cfg, r)), self._projection) for r in rows]
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


def wrap_activity_col(mongo_col: Any) -> DualWriteCollection:
    return DualWriteCollection(mongo_col, ACTIVITY_CFG)


def wrap_content_items_col(mongo_col: Any) -> DualWriteCollection:
    return DualWriteCollection(mongo_col, CONTENT_ITEMS_CFG)


def wrap_content_templates_col(mongo_col: Any) -> DualWriteCollection:
    return DualWriteCollection(mongo_col, CONTENT_TEMPLATES_CFG)


def wrap_contacts_col(mongo_col: Any) -> DualWriteCollection:
    return DualWriteCollection(mongo_col, CONTACTS_CFG)


def wrap_calendar_col(mongo_col: Any) -> DualWriteCollection:
    return DualWriteCollection(mongo_col, CALENDAR_CFG)
