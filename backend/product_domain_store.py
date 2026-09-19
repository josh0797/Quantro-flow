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
import uuid
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
        "event_id", "workspace_id",
        "external_event_id", "external_provider", "external_url",
        "title", "description",
        "start_time", "end_time", "location", "attendees", "status",
        "source", "contact_id",
        # legacy column kept readable during transition
        "google_event_id",
        "is_simulation", "hidden_by_real",
        "created_at", "updated_at", "synced_at",
    }),
    dt_keys=frozenset({"start_time", "end_time", "created_at", "updated_at", "synced_at"}),
    json_keys=frozenset({"attendees"}),
    conflict="workspace_id,event_id",
)

# Valid external_provider values for canonical calendar rows.
CALENDAR_EXTERNAL_PROVIDERS = frozenset({"google", "microsoft", "internal"})


def normalize_calendar_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Map legacy Mongo Google/MS shapes onto the canonical calendar model.

    Legacy inputs accepted on read/backfill:
      gcal_id / ms_id / google_event_id / id → external_event_id + event_id
      start / end → start_time / end_time
      html_link → external_url

    New writes should already be canonical; this is idempotent.
    """
    if not doc:
        return {}
    out = dict(doc)

    # App / Mongo id aliases
    if out.get("id") and not out.get("event_id"):
        out["event_id"] = out["id"]

    # External provider ids
    if out.get("gcal_id") and not out.get("external_event_id"):
        out["external_event_id"] = out["gcal_id"]
        out.setdefault("external_provider", "google")
    if out.get("ms_id") and not out.get("external_event_id"):
        out["external_event_id"] = out["ms_id"]
        out.setdefault("external_provider", "microsoft")
    if out.get("google_event_id") and not out.get("external_event_id"):
        out["external_event_id"] = out["google_event_id"]
        out.setdefault("external_provider", "google")

    # Time + URL aliases
    if out.get("start") and not out.get("start_time"):
        out["start_time"] = out["start"]
    if out.get("end") and not out.get("end_time"):
        out["end_time"] = out["end"]
    if out.get("html_link") and not out.get("external_url"):
        out["external_url"] = out["html_link"]

    # Infer provider from source when still unset
    provider = (out.get("external_provider") or "").lower().strip()
    if provider not in CALENDAR_EXTERNAL_PROVIDERS:
        src = (out.get("source") or "").lower()
        if "google" in src:
            provider = "google"
        elif "outlook" in src or "microsoft" in src or "ms_" in src:
            provider = "microsoft"
        else:
            provider = "internal"
        out["external_provider"] = provider

    # Keep google_event_id populated for older readers when provider=google
    if out.get("external_provider") == "google" and out.get("external_event_id"):
        out.setdefault("google_event_id", out["external_event_id"])

    return out


def normalize_calendar_query(query: Dict[str, Any]) -> Dict[str, Any]:
    """Translate legacy filter keys so Supabase primary reads hit canonical cols."""
    if not query:
        return {}
    q = dict(query)
    if "gcal_id" in q:
        q["external_event_id"] = q.pop("gcal_id")
        q.setdefault("external_provider", "google")
    if "ms_id" in q:
        q["external_event_id"] = q.pop("ms_id")
        q.setdefault("external_provider", "microsoft")
    if "google_event_id" in q and "external_event_id" not in q:
        q["external_event_id"] = q.pop("google_event_id")
        q.setdefault("external_provider", "google")
    if "id" in q and "event_id" not in q:
        q["event_id"] = q.pop("id")
    # Drop pure-Mongo aliases that are not SB columns
    for legacy in ("start", "end", "html_link", "gcal_id", "ms_id"):
        q.pop(legacy, None)
    return q


def canonical_calendar_write(
    *,
    workspace_id: str,
    event_id: str,
    external_provider: str,
    external_event_id: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    start_time: Any = None,
    end_time: Any = None,
    location: Optional[str] = None,
    attendees: Any = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    contact_id: Optional[str] = None,
    external_url: Optional[str] = None,
    is_simulation: bool = False,
    hidden_by_real: bool = False,
    synced_at: Any = None,
    created_at: Any = None,
    updated_at: Any = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a canonical calendar document for new writes (sync + internal)."""
    provider = (external_provider or "internal").lower().strip()
    if provider not in CALENDAR_EXTERNAL_PROVIDERS:
        provider = "internal"
    doc: Dict[str, Any] = {
        "event_id": event_id,
        "workspace_id": workspace_id,
        "external_provider": provider,
        "external_event_id": external_event_id,
        "title": title,
        "description": description,
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "attendees": attendees if attendees is not None else [],
        "status": status,
        "source": source,
        "contact_id": contact_id,
        "external_url": external_url,
        "is_simulation": bool(is_simulation),
        "hidden_by_real": bool(hidden_by_real),
    }
    if provider == "google" and external_event_id:
        doc["google_event_id"] = external_event_id
    if synced_at is not None:
        doc["synced_at"] = synced_at
    if created_at is not None:
        doc["created_at"] = created_at
    if updated_at is not None:
        doc["updated_at"] = updated_at
    if extra:
        doc.update(extra)
    return normalize_calendar_doc(doc)


def calendar_on_conflict(doc: Dict[str, Any]) -> str:
    """PostgREST ``on_conflict`` target for calendar_events only.

    External syncs mint a fresh UUID ``event_id`` each pass, so upserting on
    ``workspace_id,event_id`` creates duplicates and fights the unique
    ``(workspace_id, external_provider, external_event_id)`` index.
    Internal rows (null external_event_id) keep ``workspace_id,event_id``.
    """
    if doc.get("external_event_id"):
        return "workspace_id,external_provider,external_event_id"
    return "workspace_id,event_id"


async def find_calendar_event_for_external_sync(
    calendar_col: Any,
    *,
    workspace_id: str,
    provider: str,
    external_event_id: str,
) -> Optional[Dict[str, Any]]:
    """Resolve an existing calendar row for Google/MS sync.

    Lookup order (transition-safe):
      1. Canonical ``workspace_id + external_provider + external_event_id``
      2. Legacy Google ``workspace_id + gcal_id`` / MS ``workspace_id + ms_id``
    """
    if not external_event_id:
        return None
    provider = (provider or "").lower().strip()
    doc = await calendar_col.find_one(
        {
            "workspace_id": workspace_id,
            "external_provider": provider,
            "external_event_id": external_event_id,
        }
    )
    if doc:
        return doc
    # Legacy keys live only on Mongo; DualWriteCollection remaps gcal_id/ms_id
    # to external_event_id, so query the underlying collection directly.
    mongo = getattr(calendar_col, "_mongo", calendar_col)
    legacy_key = "gcal_id" if provider == "google" else ("ms_id" if provider == "microsoft" else None)
    if not legacy_key or not hasattr(mongo, "find_one"):
        return None
    return await mongo.find_one({"workspace_id": workspace_id, legacy_key: external_event_id})


async def upsert_calendar_external_event(
    calendar_col: Any,
    *,
    workspace_id: str,
    provider: str,
    external_event_id: str,
    canonical: Dict[str, Any],
    now: Any,
) -> str:
    """Upsert a Google/MS calendar event without duplicating legacy rows.

    If a legacy ``gcal_id`` / ``ms_id`` row is found, update that document in
    place, add canonical ``external_*`` fields, and preserve ``event_id``/``id``.
    Do **not** delete legacy ``gcal_id``/``ms_id``; new writes simply stop
    writing those keys (canonical payload has none).
    """
    provider = (provider or "").lower().strip()
    existing = await find_calendar_event_for_external_sync(
        calendar_col,
        workspace_id=workspace_id,
        provider=provider,
        external_event_id=external_event_id,
    )
    set_fields = {
        k: v
        for k, v in canonical.items()
        if k not in ("event_id", "id", "_id")
    }
    set_fields["workspace_id"] = workspace_id
    set_fields["external_provider"] = provider
    set_fields["external_event_id"] = external_event_id

    if existing is not None:
        event_id = existing.get("event_id") or existing.get("id") or str(uuid.uuid4())
        set_fields_with_id = {**set_fields, "event_id": event_id}
        mongo = getattr(calendar_col, "_mongo", calendar_col)
        if existing.get("_id") is not None and hasattr(mongo, "update_one"):
            await mongo.update_one({"_id": existing["_id"]}, {"$set": set_fields_with_id})
        elif existing.get("event_id"):
            await calendar_col.update_one(
                {"workspace_id": workspace_id, "event_id": event_id},
                {"$set": set_fields},
            )
        else:
            legacy_key = "gcal_id" if provider == "google" else "ms_id"
            await mongo.update_one(
                {"workspace_id": workspace_id, legacy_key: external_event_id},
                {"$set": set_fields_with_id},
            )
        # Dual-write / SB path: preserve stable event_id via external conflict.
        if hasattr(calendar_col, "_sb_upsert_doc") and is_dual_write(CALENDAR_CFG):
            await calendar_col._sb_upsert_doc({**set_fields, "event_id": event_id})
        return event_id

    event_id = canonical.get("event_id") or str(uuid.uuid4())
    await calendar_col.update_one(
        {
            "workspace_id": workspace_id,
            "external_provider": provider,
            "external_event_id": external_event_id,
        },
        {
            "$set": set_fields,
            "$setOnInsert": {"event_id": event_id, "created_at": now},
        },
        upsert=True,
    )
    return event_id



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
    if cfg.name == "calendar":
        src = normalize_calendar_doc(src)
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
        q = query or {}
        if self.cfg.name == "calendar":
            q = normalize_calendar_query(q)
        return _LazyFindCursor(self, q, projection)

    async def find_one(self, query: Dict[str, Any], projection: Optional[Dict[str, int]] = None):
        if self.cfg.name == "calendar":
            query = normalize_calendar_query(query)
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
        if self.cfg.name == "calendar":
            query = normalize_calendar_query(query)
        if is_supabase_primary(self.cfg):
            n = await self._sb_count(query)
            if n is not None:
                return n
        return await self._mongo.count_documents(query)

    async def insert_one(self, doc: Dict[str, Any]):
        if self.cfg.name == "calendar":
            doc = normalize_calendar_doc(doc)
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
        if self.cfg.name == "calendar":
            docs = [normalize_calendar_doc(d) for d in docs]
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
        if self.cfg.name == "calendar":
            query = normalize_calendar_query(query)
            if "$set" in update:
                update = {**update, "$set": normalize_calendar_doc(update["$set"])}
            if "$setOnInsert" in update:
                update = {**update, "$setOnInsert": normalize_calendar_doc(update["$setOnInsert"])}
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
        if self.cfg.name == "calendar":
            query = normalize_calendar_query(query)
            if "$set" in update:
                update = {**update, "$set": normalize_calendar_doc(update["$set"])}
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
        if self.cfg.name == "calendar":
            query = normalize_calendar_query(query)
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
        if self.cfg.name == "calendar":
            query = normalize_calendar_query(query)
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
        if self.cfg.name == "calendar":
            doc = normalize_calendar_doc(doc)
        payload = mongo_to_sb(self.cfg, doc)
        if not payload.get("workspace_id") or not payload.get(self.cfg.app_id_field):
            logger.warning("%s upsert skip — missing workspace_id/%s", self.cfg.name, self.cfg.app_id_field)
            return False
        conflict = self.cfg.conflict
        if self.cfg.name == "calendar":
            conflict = calendar_on_conflict(payload)
            # Preserve original event_id when upserting by external identity.
            if payload.get("external_event_id"):
                existing = await self._sb_find_one(
                    {
                        "workspace_id": payload["workspace_id"],
                        "external_provider": payload.get("external_provider"),
                        "external_event_id": payload["external_event_id"],
                    }
                )
                if existing and existing.get("event_id"):
                    payload["event_id"] = existing["event_id"]
        resp = await _sb_request(
            "POST",
            f"/rest/v1/{self.table}?on_conflict={conflict}",
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
            merge_keys = ("workspace_id", self.cfg.app_id_field, "external_provider", "external_event_id")
            merged = {**{k: query.get(k) for k in merge_keys if k in query}}
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
