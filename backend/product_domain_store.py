"""Phase 6.2–6.3 — dual-write facades for activity / content / CRM / calendar.

Mirrors ``inbox_store.InboxDualWriteCollection`` with per-domain config.
Dual-write when SUPABASE_* configured while Mongo is primary.

Env (read per call)
-------------------
QUANTRO_ACTIVITY_PRIMARY / QUANTRO_CONTENT_PRIMARY /
QUANTRO_CONTACTS_PRIMARY / QUANTRO_CALENDAR_PRIMARY
  ``supabase`` (default since the Mongo exit) | ``mongo``

QUANTRO_*_MONGO_MIRROR, else QUANTRO_MONGO_MIRROR (default off). With
Supabase primary and the mirror off Mongo is never touched: filters
PostgREST cannot express are evaluated in Python, fields without a column
go to the ``extra`` jsonb, and Supabase failures raise
``sb_rest.SupabaseStoreError`` instead of silently falling back.
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

import mongo_compat as mc
import sb_rest
import storage_flags
from sb_rest import SupabaseStoreError

logger = logging.getLogger("quantro.product_domain.store")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


def _is_sb_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _env_primary(name: str) -> str:
    return storage_flags.parse_primary(name)


def _env_mirror(dedicated: str) -> bool:
    return storage_flags.parse_mirror(dedicated)


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
    # NOT NULL columns: $unset writes the column default instead of NULL.
    not_null_defaults: tuple = ()
    # Legacy Mongo aliases normalized into canonical columns (not spilled).
    drop_keys: frozenset = frozenset()


ACTIVITY_CFG = DomainConfig(
    name="activity",
    table="activity_events",
    app_id_field="event_id",
    primary_env="QUANTRO_ACTIVITY_PRIMARY",
    mirror_env="QUANTRO_ACTIVITY_MONGO_MIRROR",
    known_cols=frozenset({
        "event_id", "workspace_id", "event_type", "title", "description",
        "related_id", "related_type", "timestamp", "is_simulation",
        "hidden_by_real", "extra",
        "created_at", "updated_at",
    }),
    dt_keys=frozenset({"timestamp", "created_at", "updated_at"}),
    json_keys=frozenset({"extra"}),
    conflict="workspace_id,event_id",
    not_null_defaults=(("is_simulation", False), ("hidden_by_real", False)),
)

CONTENT_ITEMS_CFG = DomainConfig(
    name="content_items",
    table="content_items",
    app_id_field="content_id",
    primary_env="QUANTRO_CONTENT_PRIMARY",
    mirror_env="QUANTRO_CONTENT_MONGO_MIRROR",
    known_cols=frozenset({
        "content_id", "workspace_id", "type", "title", "content", "status",
        "created_by", "is_simulation", "hidden_by_real", "extra",
        "created_at", "updated_at",
    }),
    dt_keys=frozenset({"created_at", "updated_at"}),
    json_keys=frozenset({"content", "extra"}),
    conflict="workspace_id,content_id",
    not_null_defaults=(("is_simulation", False), ("hidden_by_real", False)),
)

CONTENT_TEMPLATES_CFG = DomainConfig(
    name="content_templates",
    table="content_templates",
    app_id_field="template_id",
    primary_env="QUANTRO_CONTENT_PRIMARY",
    mirror_env="QUANTRO_CONTENT_MONGO_MIRROR",
    known_cols=frozenset({
        "template_id", "workspace_id", "name", "category", "body", "channel",
        "is_default", "is_simulation", "hidden_by_real",
        # Template editor fields (were Mongo-only before the Mongo exit).
        "template_type", "subject_template", "body_template", "variables", "tags",
        "status", "created_by", "extra",
        "created_at", "updated_at",
    }),
    dt_keys=frozenset({"created_at", "updated_at"}),
    json_keys=frozenset({"body", "variables", "tags", "extra"}),
    conflict="workspace_id,template_id",
    not_null_defaults=(("is_default", False), ("is_simulation", False), ("hidden_by_real", False)),
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
        "is_simulation", "hidden_by_real", "extra",
        "created_at", "updated_at",
    }),
    dt_keys=frozenset({"ghl_last_sync", "created_at", "updated_at"}),
    json_keys=frozenset({"tags", "extra"}),
    conflict="workspace_id,contact_id",
    not_null_defaults=(("is_simulation", False), ("hidden_by_real", False)),
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
        "ical_uid", "external_updated_at",
        "title", "description",
        "start_time", "end_time", "location", "attendees", "status",
        "source", "contact_id",
        # legacy column kept readable during transition
        "google_event_id",
        "is_simulation", "hidden_by_real", "is_real", "extra",
        "created_at", "updated_at", "synced_at",
    }),
    dt_keys=frozenset({
        "start_time", "end_time", "created_at", "updated_at", "synced_at", "external_updated_at",
    }),
    json_keys=frozenset({"attendees", "extra"}),
    conflict="workspace_id,event_id",
    not_null_defaults=(("is_simulation", False), ("hidden_by_real", False)),
    # normalize_calendar_doc maps these onto external_* / start_time / …
    drop_keys=frozenset({"gcal_id", "ms_id", "start", "end", "html_link"}),
)

# Valid external_provider values for canonical calendar rows.
CALENDAR_EXTERNAL_PROVIDERS = frozenset({"google", "microsoft", "internal"})


def normalize_calendar_doc(doc: Dict[str, Any], *, infer_provider: bool = True) -> Dict[str, Any]:
    """Map legacy Mongo Google/MS shapes onto the canonical calendar model.

    Legacy inputs accepted on read/backfill:
      gcal_id / ms_id / google_event_id / id → external_event_id + event_id
      start / end → start_time / end_time
      html_link → external_url

    New writes should already be canonical; this is idempotent.

    ``infer_provider=False`` for PARTIAL docs (``$set`` / ``$setOnInsert``
    patches): inferring ``external_provider="internal"`` there rewrote the
    provider of the rows being patched and, for sync upserts, made Mongo
    reject the update ($set and $setOnInsert both writing external_provider).
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
    if provider not in CALENDAR_EXTERNAL_PROVIDERS and infer_provider:
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
    ical_uid: Optional[str] = None,
    external_updated_at: Any = None,
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
        "ical_uid": ical_uid,
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
    if external_updated_at is not None:
        doc["external_updated_at"] = external_updated_at
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


def _calendar_mongo_ok(calendar_col: Any) -> bool:
    """Legacy Mongo-only lookups/writes are allowed for calendar right now."""
    mongo = getattr(calendar_col, "_mongo", None)
    if mongo is None:
        return False
    cfg = getattr(calendar_col, "cfg", CALENDAR_CFG)
    return is_mongo_write(cfg)


def _is_legacy_provider(value: Any) -> bool:
    """Provider a schema migration inferred, never one a sync wrote.

    Konta 20260919010000 set ``external_provider = 'internal'`` on every row
    that had none — including the Supabase shadows of synced Google/MS
    events (their provider id had been dropped). The backfill later filled
    ``external_event_id`` on them but kept the non-NULL ``internal``. The app
    never writes an ``internal`` row with an external id, so such a row is
    that legacy shape.
    """
    return (value or "internal") == "internal"


async def _sb_find_calendar_external(
    calendar_col: "DualWriteCollection", workspace_id: str, provider: str, external_event_id: str,
) -> Optional[Dict[str, Any]]:
    """Supabase row for a provider event: exact identity first, else the
    legacy-provider row carrying the same external id. Keeps ``_pk``.

    Both at once is two rows for one event: the legacy one cannot take the
    identity (unique index) and stays listed with its old data, so it is
    logged as STORE_DRIFT (event ids only) for a human to remove."""
    rows = await calendar_col._sb_rows({"workspace_id": workspace_id, "external_event_id": external_event_id})
    exact = next((r for r in rows if (r.get("external_provider") or "") == provider), None)
    legacy = [r for r in rows if _is_legacy_provider(r.get("external_provider"))]
    if exact is not None:
        if legacy:
            logger.warning("%s calendar: legacy-provider row(s) duplicate a synced event (event_id=%s, "
                           "duplicate event_id=%s) — review by hand", storage_flags.STORE_DRIFT,
                           exact.get("event_id", "?"), ",".join(str(r.get("event_id", "?")) for r in legacy))
        return exact
    return legacy[0] if legacy else None


def _needs_identity_repair(existing: Dict[str, Any], provider: str, external_event_id: str) -> bool:
    """A Supabase row found for this provider event that does not carry its identity."""
    return "_pk" in existing and (
        existing.get("external_provider") != provider or existing.get("external_event_id") != external_event_id
    )


async def find_calendar_event_for_external_sync(
    calendar_col: Any,
    *,
    workspace_id: str,
    provider: str,
    external_event_id: str,
) -> Optional[Dict[str, Any]]:
    """Resolve an existing calendar row for Google/MS sync.

    Lookup order (transition-safe):
      0. Supabase primary: Supabase by ``workspace_id + external_event_id`` —
         the exact provider, else a legacy-provider row (``internal``/NULL,
         see ``_is_legacy_provider``) that the upsert then repairs in place.
         Without this a sync after the Mongo mirror is off inserted a
         second row for every such event.
      1. Canonical ``workspace_id + external_provider + external_event_id``
         (and, while mirrored, the Mongo mirror)
      2. Legacy Google ``workspace_id + gcal_id`` / MS ``workspace_id + ms_id``
         — Mongo only, and only while Mongo is still primary or mirrored
         (the backfill normalizes legacy rows onto external_* in Supabase).
    """
    if not external_event_id:
        return None
    provider = (provider or "").lower().strip()
    if isinstance(calendar_col, DualWriteCollection) and is_supabase_primary(calendar_col.cfg):
        try:
            doc = await _sb_find_calendar_external(calendar_col, workspace_id, provider, external_event_id)
        except SupabaseStoreError:
            if not _mongo_fallback_ok(calendar_col.cfg):
                raise
            doc = None  # find_one below logs the failure and reads the mirror
        else:
            if doc is not None or not _mongo_fallback_ok(calendar_col.cfg):
                return doc
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
    if isinstance(calendar_col, DualWriteCollection):
        if not _calendar_mongo_ok(calendar_col):
            return None
        mongo = calendar_col._mongo
    else:
        mongo = calendar_col
    legacy_key = "gcal_id" if provider == "google" else ("ms_id" if provider == "microsoft" else None)
    if not legacy_key or not hasattr(mongo, "find_one"):
        return None
    return await mongo.find_one({"workspace_id": workspace_id, legacy_key: external_event_id})


def _loose(value: Any) -> Any:
    if isinstance(value, str):
        parsed = _parse_dt(value)
        if isinstance(parsed, datetime):
            value = parsed
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return str(value or "")


def _calendar_compare_unchanged(existing: Dict[str, Any], canonical: Dict[str, Any]) -> bool:
    """True when provider payload matches stored compare metadata (skip write)."""
    keys = (
        "title", "start_time", "end_time", "status", "location",
        "ical_uid", "external_updated_at", "external_url", "description",
    )
    for k in keys:
        left = existing.get(k)
        right = canonical.get(k)
        if left is None and right in (None, "", []):
            continue
        if _loose(left) != _loose(right):
            return False
    return True


async def upsert_calendar_external_event(
    calendar_col: Any,
    *,
    workspace_id: str,
    provider: str,
    external_event_id: str,
    canonical: Dict[str, Any],
    now: Any,
) -> Dict[str, Any]:
    """Upsert a Google/MS calendar event without duplicating legacy rows.

    Returns ``{"event_id": str, "outcome": "inserted"|"updated"|"unchanged"|"cancelled"}``.
    If a legacy ``gcal_id`` / ``ms_id`` row is found, update that document in
    place, add canonical ``external_*`` fields, and preserve ``event_id``/``id``.
    Do **not** delete legacy ``gcal_id``/``ms_id``; new writes simply stop
    writing those keys (canonical payload has none).
    Do **not** auto-merge Google/MS by title/time — identity is
    ``(workspace_id, external_provider, external_event_id)`` (+ ``ical_uid`` stored).
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

    status_val = (canonical.get("status") or "").lower()
    is_cancelled = status_val == "cancelled" or bool(canonical.get("cancelled"))

    is_facade = isinstance(calendar_col, DualWriteCollection)
    cfg = getattr(calendar_col, "cfg", CALENDAR_CFG)
    sb_primary = is_facade and is_supabase_primary(cfg)

    if existing is not None:
        event_id = existing.get("event_id") or existing.get("id") or str(uuid.uuid4())
        repair = sb_primary and _needs_identity_repair(existing, provider, external_event_id)
        if not repair and _calendar_compare_unchanged(existing, canonical):
            return {"event_id": event_id, "outcome": "unchanged"}
        set_fields_with_id = {**set_fields, "event_id": event_id}
        if repair:
            # Legacy-provider row: patch it by primary key (keeps event_id,
            # takes the provider identity). An upsert on the external identity
            # would try to INSERT and hit (workspace_id, event_id) → 409.
            ok = await _sb_patch_calendar_row(calendar_col, existing, set_fields_with_id)
            if not ok and not _mongo_fallback_ok(cfg):
                raise SupabaseStoreError("calendar_events identity repair failed", table=cfg.table)
            if _calendar_mongo_ok(calendar_col):
                await _mirror_calendar_legacy(calendar_col, existing, workspace_id, provider,
                                              external_event_id, set_fields, set_fields_with_id)
        elif sb_primary:
            # Supabase is the SoT: one upsert on the external identity keeps
            # the stored event_id (see _sb_upsert_doc).
            ok = await calendar_col._sb_upsert_doc(set_fields_with_id)
            if not ok and not _mongo_fallback_ok(cfg):
                raise SupabaseStoreError("calendar_events upsert failed", table=cfg.table)
            if _calendar_mongo_ok(calendar_col):
                await _mirror_calendar_legacy(calendar_col, existing, workspace_id, provider,
                                              external_event_id, set_fields, set_fields_with_id)
        else:
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
            if hasattr(calendar_col, "_sb_upsert_doc") and is_dual_write(cfg):
                await calendar_col._sb_upsert_doc({**set_fields, "event_id": event_id})
        outcome = "cancelled" if is_cancelled else "updated"
        return {"event_id": event_id, "outcome": outcome}

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
    outcome = "cancelled" if is_cancelled else "inserted"
    return {"event_id": event_id, "outcome": outcome}


async def _sb_patch_calendar_row(calendar_col: "DualWriteCollection", existing: Dict[str, Any],
                                 fields: Dict[str, Any]) -> bool:
    """PATCH one Supabase calendar row (``existing`` from ``_sb_rows``) by primary key."""
    update = {"$set": fields}
    patch = calendar_col._column_patch(update)
    if patch is None:
        base = {k: v for k, v in existing.items() if k != "_pk"}
        patch = calendar_col._full_row(mc.apply_update(base, update))
    return await calendar_col._patch({"id": f"eq.{existing['_pk']}"}, patch) is not None


async def _mirror_calendar_legacy(calendar_col, existing, workspace_id, provider, external_event_id,
                                  set_fields, set_fields_with_id) -> None:
    """Best-effort Mongo mirror of a sync update (Supabase primary + mirror on)."""
    mongo = calendar_col._mongo
    try:
        if existing.get("_id") is not None:
            await mongo.update_one({"_id": existing["_id"]}, {"$set": set_fields_with_id})
        else:
            await mongo.update_one(
                {"workspace_id": workspace_id, "external_provider": provider,
                 "external_event_id": external_event_id},
                {"$set": set_fields_with_id},
                upsert=True,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s calendar mongo mirror failed: %s", storage_flags.STORE_DRIFT, exc)



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


def _mongo_fallback_ok(cfg: DomainConfig) -> bool:
    """Supabase primary consults Mongo only while it is kept as a mirror."""
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


async def _req(method: str, path: str, **kwargs: Any):
    """Late-bound so tests can monkeypatch ``product_domain_store._sb_request``."""
    return await _sb_request(method, path, **kwargs)


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


def mongo_to_sb(cfg: DomainConfig, doc: Dict[str, Any], *, full: bool = False, partial: bool = False) -> Dict[str, Any]:
    """Mongo doc (or $set patch) → Postgres row.

    Fields without a column go to ``extra`` (jsonb) instead of being dropped;
    ``full=True`` always sends ``extra`` (whole-document writes);
    ``partial=True`` for patches (no calendar provider inference).
    """
    out: Dict[str, Any] = {}
    extra: Dict[str, Any] = {}
    src = dict(doc)
    if cfg.name == "calendar":
        src = normalize_calendar_doc(src, infer_provider=not partial)
    if "id" in src and cfg.app_id_field not in src:
        src[cfg.app_id_field] = src["id"]
    has_extra_col = "extra" in cfg.known_cols
    for k, v in src.items():
        if k == "id" or k == "_id":
            continue
        if k == "extra" and has_extra_col:
            if isinstance(v, dict):
                extra.update(mc.to_json(v))
            else:
                extra["extra"] = mc.to_json(v)
            continue
        if k not in cfg.known_cols:
            if has_extra_col and k not in cfg.drop_keys:
                extra[k] = mc.to_json(v)
            continue
        if k in cfg.dt_keys:
            out[k] = _iso(v)
        elif k in cfg.json_keys:
            out[k] = mc.to_json(v)
        else:
            out[k] = v
    if has_extra_col and (extra or full):
        out["extra"] = extra
    if cfg.app_id_field not in out and src.get(cfg.app_id_field):
        out[cfg.app_id_field] = src[cfg.app_id_field]
    return out


def sb_to_mongo(cfg: DomainConfig, row: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in row.items() if k not in ("id", "extra")}
    for k in cfg.dt_keys:
        if k in out:
            out[k] = _parse_dt(out[k])
    extra_val = row.get("extra")
    for k, v in (extra_val.items() if isinstance(extra_val, dict) else ()):
        out.setdefault(k, mc.from_json(v))
    return out


def _split(cfg: DomainConfig, query: Dict[str, Any]):
    """(PostgREST params, residual Mongo filter). Raises sb_rest.Impossible."""
    return sb_rest.split_filter(query, cfg.known_cols - {"extra"}, json_cols=cfg.json_keys)


def _mongo_filter_to_params(query: Dict[str, Any], *, select: str = "*", cfg: Optional[DomainConfig] = None) -> Dict[str, str]:
    """Params for the exactly-expressible part of ``query`` (see ``_split``)."""
    cols = (cfg.known_cols - {"extra"}) if cfg else {k for k in (query or {}) if not str(k).startswith("$")}
    try:
        params, _ = sb_rest.split_filter(query, cols, json_cols=(cfg.json_keys if cfg else ()))
    except sb_rest.Impossible:
        params = {}
    out: Dict[str, str] = {}
    if select:
        out["select"] = select
    out.update(params)
    return out


def _strip_pg_id(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return doc
    d = dict(doc)
    d.pop("id", None)
    d.pop("_pk", None)
    return d


def _project(doc: Optional[Dict[str, Any]], projection: Optional[Dict[str, int]]):
    if not doc or not projection:
        return doc
    include = {k for k, v in projection.items() if v}
    if include:
        return {k: doc[k] for k in include if k in doc}
    exclude = {k for k, v in projection.items() if not v}
    return {k: v for k, v in doc.items() if k not in exclude}


_ORDER_DEFAULT = "created_at.asc,id.asc"


class DualWriteCollection:
    def __init__(self, mongo_col: Any, cfg: DomainConfig):
        self._mongo = mongo_col
        self.cfg = cfg
        self.table = cfg.table

    # ── Supabase read primitives ──────────────────────────────────────
    async def _sb_rows(self, query: Dict[str, Any], *, sort=None, skip: int = 0, limit: int = 0) -> List[Dict[str, Any]]:
        """Docs (+``_pk``) matching the WHOLE filter. Raises SupabaseStoreError."""
        try:
            params, residual = _split(self.cfg, query)
        except sb_rest.Impossible:
            return []
        params["select"] = "*"
        order = sb_rest.order_param(sort or [], self.cfg.known_cols) if sort else _ORDER_DEFAULT
        exact = not residual and order is not None
        rows = await sb_rest.fetch_all(
            _req, self.table, params,
            order=order or _ORDER_DEFAULT,
            limit=limit if (exact and limit) else None,
            offset=skip if exact else 0,
        )
        if rows is None:
            raise SupabaseStoreError(f"{self.table} read failed", table=self.table)
        docs = []
        for r in rows:
            d = sb_to_mongo(self.cfg, r)
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

    async def _sb_find_one(self, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            docs = await self._sb_rows(query, limit=1)
        except SupabaseStoreError:
            return None
        return docs[0] if docs else None

    async def _sb_count(self, query: Dict[str, Any]) -> Optional[int]:
        try:
            params, residual = _split(self.cfg, query)
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
    def find(self, query: Optional[Dict[str, Any]] = None, projection: Optional[Dict[str, int]] = None, **kwargs: Any):
        q = query or {}
        if self.cfg.name == "calendar":
            q = normalize_calendar_query(q)
        cur = _LazyFindCursor(self, q, projection)
        if kwargs.get("sort"):
            cur.sort(kwargs["sort"])
        return cur

    async def find_one(self, query: Dict[str, Any], projection: Optional[Dict[str, int]] = None, **_: Any):
        if self.cfg.name == "calendar":
            query = normalize_calendar_query(query)
        if is_supabase_primary(self.cfg):
            try:
                docs = await self._sb_rows(query, limit=1)
            except SupabaseStoreError:
                if not _mongo_fallback_ok(self.cfg):
                    raise
                docs = []
                logger.warning("%s %s: Supabase read failed — Mongo mirror fallback", storage_flags.MONGO_ONLY, self.cfg.name)
            if docs:
                return _project(_strip_pg_id(docs[0]), projection)
            if not _mongo_fallback_ok(self.cfg):
                return None
        try:
            doc = await self._mongo.find_one(query, projection) if projection is not None else await self._mongo.find_one(query)
        except TypeError:
            doc = await self._mongo.find_one(query)
        if doc is not None and is_supabase_primary(self.cfg):
            # Name the lookup key: the id printed is the MONGO row's, and
            # Supabase may hold that same id under another key value (e.g. a
            # calendar row under another external identity) — not missing.
            keys = ",".join(sorted(k for k in query if not str(k).startswith("$"))) or "-"
            logger.warning("%s %s: Supabase has no row for this lookup, the Mongo mirror has one "
                           "(%s=%s, lookup on %s) — re-run the backfill; if it reports the row "
                           "'same', Supabase holds it under another key value: review it",
                           storage_flags.MONGO_ONLY, self.cfg.name, self.cfg.app_id_field,
                           doc.get(self.cfg.app_id_field, "?"), keys)
        return doc

    async def count_documents(self, query: Dict[str, Any], **_: Any) -> int:
        if self.cfg.name == "calendar":
            query = normalize_calendar_query(query)
        if is_supabase_primary(self.cfg):
            n = await self._sb_count(query)
            if n is not None:
                return n
            if not _mongo_fallback_ok(self.cfg):
                raise SupabaseStoreError(f"{self.table} count failed", table=self.table)
        return await self._mongo.count_documents(query)

    # ── writes ────────────────────────────────────────────────────────
    def _sb_failed(self, what: str) -> None:
        """Supabase primary write failed: raise unless Mongo still mirrors."""
        if is_supabase_primary(self.cfg) and not _mongo_fallback_ok(self.cfg):
            raise SupabaseStoreError(f"{self.table} {what} failed", table=self.table)
        logger.warning("%s %s SB %s failed (Mongo still written)", storage_flags.MONGO_ONLY, self.cfg.name, what)

    async def _mongo_call(self, fn, *args, **kwargs):
        """Mongo write: required while Mongo is primary, best-effort mirror
        once Supabase is primary (a Mongo outage must not fail the request)."""
        if not is_supabase_primary(self.cfg):
            return await fn(*args, **kwargs)
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s %s mongo mirror write failed: %s", storage_flags.STORE_DRIFT, self.cfg.name, exc)
            return None

    async def insert_one(self, doc: Dict[str, Any], *_: Any, **__: Any):
        if self.cfg.name == "calendar":
            doc = normalize_calendar_doc(doc)
        result = None
        if is_mongo_write(self.cfg):
            result = await self._mongo_call(self._mongo.insert_one, doc)
        if result is None:
            result = mc.InsertOneResult(doc.get(self.cfg.app_id_field))
        if is_dual_write(self.cfg):
            if not await self._sb_upsert_doc(doc):
                self._sb_failed("insert")
        return result

    async def insert_many(self, docs: List[Dict[str, Any]], *_: Any, **__: Any):
        if self.cfg.name == "calendar":
            docs = [normalize_calendar_doc(d) for d in docs]
        result = None
        if is_mongo_write(self.cfg):
            result = await self._mongo_call(self._mongo.insert_many, docs)
        if result is None:
            result = mc.InsertManyResult([d.get(self.cfg.app_id_field) for d in docs])
        if is_dual_write(self.cfg):
            for d in docs:
                if not await self._sb_upsert_doc(d):
                    self._sb_failed("insert")
        return result

    def _normalize_update(self, query: Dict[str, Any], update: Dict[str, Any]):
        if self.cfg.name == "calendar":
            query = normalize_calendar_query(query)
            if "$set" in update:
                update = {**update, "$set": normalize_calendar_doc(update["$set"], infer_provider=False)}
            if "$setOnInsert" in update:
                soi = normalize_calendar_doc(update["$setOnInsert"], infer_provider=False)
                # Mongo rejects an update where $set and $setOnInsert write
                # the same path; $set already carries those values.
                set_keys = set(update.get("$set") or {})
                update = {**update, "$setOnInsert": {k: v for k, v in soi.items() if k not in set_keys}}
        return query, update

    async def update_one(self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False, **_: Any):
        query, update = self._normalize_update(query, update)
        result = None
        if is_mongo_write(self.cfg):
            try:
                result = await self._mongo.update_one(query, update, upsert=upsert)
            except Exception:
                if not is_supabase_primary(self.cfg):
                    raise
                logger.warning("%s %s mongo mirror update_one failed", storage_flags.STORE_DRIFT, self.cfg.name)
        sb_res = None
        if is_dual_write(self.cfg):
            sb_res = await self._sb_update(query, update, upsert=upsert, many=False)
            if sb_res is None:
                self._sb_failed("update")
        if is_supabase_primary(self.cfg) and sb_res is not None:
            return sb_res
        return result if result is not None else (sb_res or mc.UpdateResult(0, 0))

    async def update_many(self, query: Dict[str, Any], update: Dict[str, Any], **_: Any):
        query, update = self._normalize_update(query, update)
        result = None
        if is_mongo_write(self.cfg):
            try:
                result = await self._mongo.update_many(query, update)
            except Exception:
                if not is_supabase_primary(self.cfg):
                    raise
                logger.warning("%s %s mongo mirror update_many failed", storage_flags.STORE_DRIFT, self.cfg.name)
        sb_res = None
        if is_dual_write(self.cfg):
            sb_res = await self._sb_update(query, update, upsert=False, many=True)
            if sb_res is None:
                self._sb_failed("update")
        if is_supabase_primary(self.cfg) and sb_res is not None:
            return sb_res
        return result if result is not None else (sb_res or mc.UpdateResult(0, 0))

    async def delete_one(self, query: Dict[str, Any], **_: Any):
        return await self._delete(query, many=False)

    async def delete_many(self, query: Dict[str, Any], **_: Any):
        return await self._delete(query, many=True)

    async def _delete(self, query: Dict[str, Any], *, many: bool):
        if self.cfg.name == "calendar":
            query = normalize_calendar_query(query)
        result = None
        if is_mongo_write(self.cfg):
            try:
                result = await (self._mongo.delete_many(query) if many else self._mongo.delete_one(query))
            except Exception:
                if not is_supabase_primary(self.cfg):
                    raise
                logger.warning("%s %s mongo mirror delete failed", storage_flags.STORE_DRIFT, self.cfg.name)
        n = None
        if is_dual_write(self.cfg):
            n = await self._sb_delete(query, many=many)
            if n is None:
                self._sb_failed("delete")
        if is_supabase_primary(self.cfg) and n is not None:
            return mc.DeleteResult(n)
        return result if result is not None else mc.DeleteResult(n or 0)

    async def create_index(self, *args, **kwargs):
        if not is_supabase_primary(self.cfg) and hasattr(self._mongo, "create_index"):
            return await self._mongo.create_index(*args, **kwargs)

    # ── Supabase write primitives ─────────────────────────────────────
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
        resp = await _req(
            "POST",
            f"/rest/v1/{self.table}?on_conflict={conflict}",
            json=payload,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        if resp is None:
            return False
        if resp.status_code >= 400:
            logger.warning("%s SB upsert → %s %s", self.cfg.name, resp.status_code, (resp.text or "")[:160])
            return False
        return True

    def _column_patch(self, update: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Plain SQL patch for $set/$unset on real columns, else None."""
        touched, simple = mc.update_touches(update)
        cols = self.cfg.known_cols
        if not simple or "extra" in touched or any(f not in cols and f not in ("id",) for f in touched):
            return None
        fields = dict((update or {}).get("$set") or {})
        patch = mongo_to_sb(self.cfg, fields, partial=True) if fields else {}
        patch.pop("extra", None)
        defaults = dict(self.cfg.not_null_defaults)
        for k in (update or {}).get("$unset") or {}:
            if k in cols:
                patch[k] = defaults.get(k)
        return patch

    async def _patch(self, params: Dict[str, str], patch: Dict[str, Any]) -> Optional[int]:
        p = dict(params)
        p.pop("select", None)
        p["select"] = self.cfg.app_id_field
        resp = await _req("PATCH", f"/rest/v1/{self.table}", json=patch, params=p, prefer="return=representation")
        if resp is None or resp.status_code >= 400:
            if resp is not None:
                logger.warning("%s SB update → %s %s", self.cfg.name, resp.status_code, (resp.text or "")[:160])
            return None
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = None
        return len(body) if isinstance(body, list) else 1

    def _full_row(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        row = mongo_to_sb(self.cfg, {k: v for k, v in doc.items() if k != "_pk"}, full=True)
        for k, default in self.cfg.not_null_defaults:
            if k in self.cfg.known_cols and row.get(k, default) is None:
                row[k] = default
        return row

    async def _sb_update(self, query: Dict[str, Any], update: Dict[str, Any], *, upsert: bool, many: bool = True) -> Optional[mc.UpdateResult]:
        """Mongo update semantics on Supabase. None = Supabase unavailable."""
        if not update:
            return mc.UpdateResult(0, 0)
        try:
            if upsert:
                return await self._sb_upsert(query, update)
            try:
                params, residual = _split(self.cfg, query)
            except sb_rest.Impossible:
                return mc.UpdateResult(0, 0)
            patch = self._column_patch(update)
            if patch is not None and not residual:
                if not patch:
                    return mc.UpdateResult(0, 0)
                n = await self._patch(params, patch)
                return None if n is None else mc.UpdateResult(n, n)
            docs = await self._sb_rows(query, limit=0 if many else 1)
            for d in docs:
                pk = d.pop("_pk")
                new = mc.apply_update(d, update)
                if await self._patch({"id": f"eq.{pk}"}, self._full_row(new)) is None:
                    return None
            return mc.UpdateResult(len(docs), len(docs))
        except SupabaseStoreError:
            return None

    async def _sb_upsert(self, query: Dict[str, Any], update: Dict[str, Any]) -> Optional[mc.UpdateResult]:
        """Upsert honouring $setOnInsert (only applied when inserting)."""
        docs = await self._sb_rows(query, limit=1)
        set_only = {k: v for k, v in update.items() if k != "$setOnInsert"}
        if docs:
            pk = docs[0].pop("_pk")
            patch = self._column_patch(set_only)
            if patch is None:
                patch = self._full_row(mc.apply_update(docs[0], set_only))
            if not patch:
                return mc.UpdateResult(1, 0)
            n = await self._patch({"id": f"eq.{pk}"}, patch)
            return None if n is None else mc.UpdateResult(1, n)
        new_doc = mc.apply_update(mc.seed_from_query(query), update, is_insert=True)
        if not new_doc.get(self.cfg.app_id_field):
            new_doc[self.cfg.app_id_field] = query.get(self.cfg.app_id_field) or query.get("id") or str(uuid.uuid4())
        ok = await self._sb_upsert_doc(new_doc)
        if not ok:
            return None
        return mc.UpdateResult(0, 0, new_doc.get(self.cfg.app_id_field))

    async def _sb_delete(self, query: Dict[str, Any], *, many: bool) -> Optional[int]:
        try:
            try:
                params, residual = _split(self.cfg, query)
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
        p["select"] = self.cfg.app_id_field
        resp = await _req("DELETE", f"/rest/v1/{self.table}", params=p, prefer="return=representation")
        if resp is None or resp.status_code >= 400:
            if resp is not None:
                logger.warning("%s SB delete → %s %s", self.cfg.name, resp.status_code, (resp.text or "")[:160])
            return None
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = None
        return len(body) if isinstance(body, list) else 1


class _LazyFindCursor:
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
        cfg = self._store.cfg
        limit = self._limit
        if n:
            limit = min(limit, int(n)) if limit else int(n)
        if is_supabase_primary(cfg):
            try:
                docs = await self._store._sb_rows(self._query, sort=self._sort, skip=self._skip, limit=limit)
                return [_project(_strip_pg_id(d), self._projection) for d in docs]
            except SupabaseStoreError:
                if not _mongo_fallback_ok(cfg):
                    raise
                logger.warning("%s %s: Supabase list failed — Mongo mirror fallback", storage_flags.MONGO_ONLY, cfg.name)
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
