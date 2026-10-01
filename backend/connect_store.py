"""Phase 4 — integrations_config dual-write (Connect UI catalog).

Reuses Phase 2 vault flags / HTTP helpers from ``provider_secrets_store``
for the ``integrations_config`` table (Connect UI catalog — non-secret).

The customer-owned Facturapi connection and its ``webhook_events`` inbox
that also lived here were retired on 2026-09-30: Flow no longer holds any
fiscal (PAC) credentials. Invoices come from Quantro OS through the
``quantro_invoicing`` provider (see docs/phase4-facturapi-connect.md).

Flags
-----
``QUANTRO_MONGO_MIRROR`` — shared with the Phase 2 OAuth vault.

``QUANTRO_INTEGRATIONS_CONFIG_PRIMARY`` (default ``supabase`` since the
Mongo exit) — independent flip for the UI catalog. Dual-write whenever
Supabase is configured while Mongo is primary.

``integrations_config`` rows carry the Fernet ciphertext of secret config
fields in ``secrets_enc`` (service-role only table, never returned to the
browser: server.py redacts ``config`` on every response), plus
``integration_id`` and an ``extra`` jsonb for any other legacy field, so a
Supabase-only deployment has everything Mongo had. Plaintext secrets are
never written to Supabase.

Never logs ciphertext/plaintext keys.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

import mongo_compat as mc
import provider_secrets_store as secrets_store
import sb_rest
import storage_flags
from integrations.secrets import SECRET_FIELD_NAMES
from sb_rest import SupabaseStoreError

logger = logging.getLogger("quantro.connect_store")

# Unset → supabase (fail-safe default since the Mongo exit).
INTEGRATIONS_CONFIG_PRIMARY = storage_flags.parse_primary("QUANTRO_INTEGRATIONS_CONFIG_PRIMARY")


def integrations_config_health() -> Dict[str, Any]:
    return {
        "integrations_config_primary": INTEGRATIONS_CONFIG_PRIMARY,
        "supabase_configured": secrets_store._is_sb_configured(),
        "secrets": secrets_store.secrets_health(),
    }


def is_integrations_supabase_primary() -> bool:
    return (
        INTEGRATIONS_CONFIG_PRIMARY == "supabase"
        and secrets_store._is_sb_configured()
    )


def is_integrations_dual_write_enabled() -> bool:
    return secrets_store._is_sb_configured()


def is_integrations_mongo_write_enabled() -> bool:
    if not secrets_store._is_sb_configured():
        return True
    if INTEGRATIONS_CONFIG_PRIMARY != "supabase":
        return True
    return secrets_store.MONGO_MIRROR


def _iso(value: Any) -> Optional[str]:
    return secrets_store._iso(value)


def _parse_dt(value: Any) -> Any:
    return secrets_store._parse_dt(value)


# ── integrations_config (UI catalog) ──────────────────────────────────
TABLE_INTEGRATIONS = "integrations_config"

_CONFIG_COLUMNS = frozenset({
    "workspace_id", "provider", "category", "display_name", "status",
    "last_sync_at", "config", "created_at", "updated_at",
    "integration_id", "secrets_enc", "extra",
})
_CONFIG_DT = frozenset({"last_sync_at", "created_at", "updated_at"})
_CONFIG_JSON = frozenset({"config", "secrets_enc", "extra"})


def _looks_encrypted(value: Any) -> bool:
    """Fernet tokens are urlsafe-base64 of 0x80|timestamp|… → 'gAAAAA…'."""
    return isinstance(value, str) and value.startswith("gAAAAA") and len(value) >= 60


def _split_config(config: Any) -> tuple:
    """(non-secret config, secrets_enc) — plaintext secrets are dropped."""
    if not isinstance(config, dict):
        return {}, {}
    plain: Dict[str, Any] = {}
    secrets_enc: Dict[str, Any] = {}
    for k, v in config.items():
        if k in SECRET_FIELD_NAMES:
            if _looks_encrypted(v):
                secrets_enc[k] = v
            elif v:
                logger.warning(
                    "connect_store: dropped a non-encrypted '%s' from integrations_config "
                    "(Supabase only stores ciphertext)", k,
                )
            continue
        plain[k] = mc.to_json(v)
    return plain, secrets_enc


def _strip_secrets_from_config(config: Any) -> Dict[str, Any]:
    """Drop known secret fields from UI config before Supabase write."""
    return _split_config(config)[0]


def config_doc_to_row(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Full Mongo-shaped integrations_config doc → Supabase row."""
    row: Dict[str, Any] = {}
    extra: Dict[str, Any] = {}
    for k, v in doc.items():
        if k in ("_id", "id"):
            continue
        if k == "config":
            plain, secrets_enc = _split_config(v)
            row["config"] = plain
            row["secrets_enc"] = secrets_enc
        elif k in _CONFIG_DT:
            row[k] = _iso(v)
        elif k in _CONFIG_COLUMNS and k not in _CONFIG_JSON:
            row[k] = v
        elif k == "extra" and isinstance(v, dict):
            extra.update(mc.to_json(v))
        else:
            extra[k] = mc.to_json(v)
    row["extra"] = extra
    return row


def _config_row_to_mongo(row: Dict[str, Any]) -> Dict[str, Any]:
    config = dict(row.get("config") or {})
    config = mc.from_json(config)
    for k, v in (row.get("secrets_enc") or {}).items():
        config.setdefault(k, v)
    out: Dict[str, Any] = {
        "workspace_id": row.get("workspace_id"),
        "provider": row.get("provider"),
        "category": row.get("category"),
        "display_name": row.get("display_name"),
        "status": row.get("status"),
        "last_sync_at": _parse_dt(row.get("last_sync_at")),
        "config": config,
        "created_at": _parse_dt(row.get("created_at")),
        "updated_at": _parse_dt(row.get("updated_at")),
    }
    if row.get("integration_id") is not None:
        out["integration_id"] = row.get("integration_id")
    for k, v in (row.get("extra") or {}).items():
        out.setdefault(k, mc.from_json(v))
    return out


def _config_mongo_to_sb(workspace_id: str, provider: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Partial row for a ``$set`` patch (dual-write upsert payload)."""
    out: Dict[str, Any] = {
        "workspace_id": workspace_id,
        "provider": provider,
    }
    for key in ("category", "display_name", "status", "integration_id"):
        if key in fields:
            out[key] = fields[key]
    if "last_sync_at" in fields:
        out["last_sync_at"] = _iso(fields.get("last_sync_at"))
    if "created_at" in fields:
        out["created_at"] = _iso(fields.get("created_at"))
    if "updated_at" in fields:
        out["updated_at"] = _iso(fields.get("updated_at"))
    if "config" in fields:
        plain, secrets_enc = _split_config(fields.get("config"))
        out["config"] = plain
        out["secrets_enc"] = secrets_enc
    return out


class IntegrationsConfigCollection:
    """Motor-shaped facade for ``integrations_config`` (Mongo ↔ Supabase).

    server.py's startup seeding and the /api/integrations routes go through
    this; with Supabase primary and the mirror off Mongo is never touched.
    """

    def __init__(self, mongo_col: Any = None):
        self._mongo = mongo_col
        self.name = TABLE_INTEGRATIONS

    # routing
    @staticmethod
    def _sb() -> bool:
        return is_integrations_supabase_primary()

    def _mongo_write(self) -> bool:
        return self._mongo is not None and is_integrations_mongo_write_enabled()

    async def _rows(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            params, residual = sb_rest.split_filter(query, _CONFIG_COLUMNS, json_cols=_CONFIG_JSON)
        except sb_rest.Impossible:
            return []
        params["select"] = "*"
        rows = await sb_rest.fetch_all(secrets_store._sb_request, TABLE_INTEGRATIONS, params, order="created_at.asc,id.asc")
        if rows is None:
            raise SupabaseStoreError("integrations_config read failed", table=TABLE_INTEGRATIONS)
        out = []
        for r in rows:
            doc = _config_row_to_mongo(r)
            if residual and not mc.match(doc, residual):
                continue
            doc["_row_id"] = r.get("id")
            out.append(doc)
        return out

    @staticmethod
    def _clean(doc: Dict[str, Any], projection: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        d = {k: v for k, v in doc.items() if k != "_row_id"}
        return mc.project(d, projection)

    async def find_one(self, query: Dict[str, Any], projection: Optional[Dict[str, Any]] = None, **_: Any):
        if self._sb():
            try:
                rows = await self._rows(query)
            except SupabaseStoreError:
                if not (self._mongo is not None and secrets_store.MONGO_MIRROR):
                    raise
                rows = None
            if rows:
                return self._clean(rows[0], projection)
            if not (self._mongo is not None and secrets_store.MONGO_MIRROR):
                return None
            doc = await (self._mongo.find_one(query, projection) if projection is not None
                         else self._mongo.find_one(query))
            if doc is not None:
                logger.warning("%s connect_store integrations_config: row only in Mongo — re-run the backfill",
                               storage_flags.MONGO_ONLY)
            return doc
        if projection is not None:
            return await self._mongo.find_one(query, projection)
        return await self._mongo.find_one(query)

    async def find_many(self, query: Dict[str, Any], projection: Optional[Dict[str, Any]] = None, limit: int = 0):
        if self._sb():
            try:
                rows = await self._rows(query)
                rows = rows[:limit] if limit else rows
                return [self._clean(r, projection) for r in rows]
            except SupabaseStoreError:
                if not (self._mongo is not None and secrets_store.MONGO_MIRROR):
                    raise
        cursor = self._mongo.find(query, projection)
        return await cursor.to_list(limit or None)

    def find(self, query: Dict[str, Any], projection: Optional[Dict[str, Any]] = None):
        col = self

        class _Cursor:
            async def to_list(self, n: Optional[int] = None):
                return await col.find_many(query, projection, limit=n or 0)

        return _Cursor()

    async def count_documents(self, query: Dict[str, Any], **_: Any) -> int:
        if self._sb():
            try:
                params, residual = sb_rest.split_filter(query, _CONFIG_COLUMNS, json_cols=_CONFIG_JSON)
            except sb_rest.Impossible:
                return 0
            if not residual:
                n = await sb_rest.count_exact(secrets_store._sb_request, TABLE_INTEGRATIONS, params)
                if n is not None:
                    return n
            return len(await self._rows(query))
        return await self._mongo.count_documents(query)

    async def _sb_insert(self, doc: Dict[str, Any], *, overwrite: bool) -> bool:
        row = config_doc_to_row(doc)
        resp = await secrets_store._sb_request(
            "POST",
            f"/rest/v1/{TABLE_INTEGRATIONS}",
            json=row,
            params={"on_conflict": "workspace_id,provider"},
            prefer=f"resolution={'merge' if overwrite else 'ignore'}-duplicates,return=minimal",
        )
        if resp is None or resp.status_code >= 400:
            if resp is not None:
                logger.warning("connect_store integrations_config insert %s: %s",
                               resp.status_code, (resp.text or "")[:200])
            return False
        return True

    async def insert_one(self, doc: Dict[str, Any], *_: Any, **__: Any):
        if self._sb():
            ok = await self._sb_insert(doc, overwrite=False)
            if not ok:
                raise SupabaseStoreError("integrations_config insert failed", table=TABLE_INTEGRATIONS)
            if self._mongo_write():
                try:
                    await self._mongo.insert_one(dict(doc))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s connect_store mongo mirror insert failed: %s", storage_flags.STORE_DRIFT, exc)
            return mc.InsertOneResult(doc.get("integration_id"))
        res = await self._mongo.insert_one(doc)
        if is_integrations_dual_write_enabled():
            if not await self._sb_insert({k: v for k, v in doc.items() if k != "_id"}, overwrite=False):
                logger.warning("%s connect_store integrations_config shadow insert failed", storage_flags.MONGO_ONLY)
        return res

    async def insert_many(self, docs: List[Dict[str, Any]], *_: Any, **__: Any):
        ids = []
        for d in docs:
            res = await self.insert_one(d)
            ids.append(getattr(res, "inserted_id", None))
        return mc.InsertManyResult(ids)

    async def update_one(self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False, **_: Any):
        if not self._sb():
            res = await self._mongo.update_one(query, update, upsert=upsert)
            if is_integrations_dual_write_enabled():
                try:
                    after = await self._mongo.find_one(query)
                    if after:
                        await self._sb_insert({k: v for k, v in after.items() if k != "_id"}, overwrite=True)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s connect_store integrations_config shadow failed: %s", storage_flags.MONGO_ONLY, exc)
            return res
        rows = await self._rows(query)
        if not rows:
            if not upsert:
                return mc.UpdateResult(0, 0)
            new_doc = mc.apply_update(mc.seed_from_query(query), update, is_insert=True)
            if not await self._sb_insert(new_doc, overwrite=True):
                raise SupabaseStoreError("integrations_config upsert failed", table=TABLE_INTEGRATIONS)
            if self._mongo_write():
                await self._mirror(query, update, upsert=True)
            return mc.UpdateResult(0, 0, new_doc.get("integration_id"))
        await self._sb_patch_doc(rows[0], update)
        if self._mongo_write():
            await self._mirror(query, update, upsert=upsert)
        return mc.UpdateResult(1, 1)

    async def update_many(self, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False, **_: Any):
        """Bulk update (server.py startup repairs). Same routing as update_one:
        Mongo primary → Mongo, then every touched doc is shadow-copied;
        Supabase primary → per-row PATCH, then the Mongo mirror."""
        if not self._sb():
            ids: List[Any] = []
            if is_integrations_dual_write_enabled():
                # Pre-read: the update may change what the filter matches.
                ids = [d.get("_id") for d in await self._mongo.find(query, {"_id": 1}).to_list(None)
                       if d.get("_id") is not None]
            res = await (self._mongo.update_many(query, update, upsert=upsert) if upsert
                         else self._mongo.update_many(query, update))
            upserted = getattr(res, "upserted_id", None)
            if upserted is not None:
                ids.append(upserted)
            if ids:
                try:
                    for doc in await self._mongo.find({"_id": {"$in": ids}}).to_list(None):
                        if not await self._sb_insert({k: v for k, v in doc.items() if k != "_id"}, overwrite=True):
                            logger.warning("%s connect_store integrations_config shadow update_many failed",
                                           storage_flags.MONGO_ONLY)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s connect_store integrations_config shadow failed: %s",
                                   storage_flags.MONGO_ONLY, exc)
            return res
        rows = await self._rows(query)
        if not rows:
            if upsert:
                return await self.update_one(query, update, upsert=True)
            return mc.UpdateResult(0, 0)
        for before in rows:
            await self._sb_patch_doc(before, update)
        if self._mongo_write():
            try:
                await self._mongo.update_many(query, update)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s connect_store mongo mirror update_many failed: %s", storage_flags.STORE_DRIFT, exc)
        return mc.UpdateResult(len(rows), len(rows))

    async def delete_one(self, query: Dict[str, Any], **_: Any):
        return await self._delete(query, many=False)

    async def delete_many(self, query: Dict[str, Any], **_: Any):
        return await self._delete(query, many=True)

    async def _delete(self, query: Dict[str, Any], *, many: bool):
        if not self._sb():
            docs = await self._mongo.find(query, {"_id": 0, "workspace_id": 1, "provider": 1}).to_list(None if many else 1)
            res = await (self._mongo.delete_many(query) if many else self._mongo.delete_one(query))
            if is_integrations_dual_write_enabled():
                for d in docs:
                    key = {"workspace_id": d.get("workspace_id"), "provider": d.get("provider")}
                    if not key["workspace_id"] or not key["provider"]:
                        continue
                    # Mongo may hold legacy duplicates of one (workspace, provider);
                    # the shadow row goes only when none is left.
                    if await self._mongo.find_one(key, {"_id": 1}):
                        continue
                    resp = await secrets_store._sb_request(
                        "DELETE", f"/rest/v1/{TABLE_INTEGRATIONS}",
                        params={"workspace_id": f"eq.{key['workspace_id']}", "provider": f"eq.{key['provider']}"},
                        prefer="return=minimal",
                    )
                    if resp is None or resp.status_code >= 400:
                        logger.warning("%s connect_store integrations_config shadow delete failed (Supabase kept the row)",
                                       storage_flags.STORE_DRIFT)
            return res
        rows = await self._rows(query)
        rows = rows if many else rows[:1]
        for r in rows:
            resp = await secrets_store._sb_request(
                "DELETE", f"/rest/v1/{TABLE_INTEGRATIONS}",
                params={"id": f"eq.{r['_row_id']}"}, prefer="return=minimal",
            )
            if resp is None or resp.status_code >= 400:
                raise SupabaseStoreError("integrations_config delete failed", table=TABLE_INTEGRATIONS)
        if rows and self._mongo_write():
            try:
                for r in rows:
                    await self._mongo.delete_many({"workspace_id": r.get("workspace_id"), "provider": r.get("provider")})
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s connect_store mongo mirror delete failed: %s", storage_flags.STORE_DRIFT, exc)
        return mc.DeleteResult(len(rows))

    async def _sb_patch_doc(self, before: Dict[str, Any], update: Dict[str, Any]) -> None:
        after = mc.apply_update({k: v for k, v in before.items() if k != "_row_id"}, update)
        row = config_doc_to_row(after)
        resp = await secrets_store._sb_request(
            "PATCH",
            f"/rest/v1/{TABLE_INTEGRATIONS}",
            json=row,
            params={"id": f"eq.{before['_row_id']}"},
            prefer="return=minimal",
        )
        if resp is None or resp.status_code >= 400:
            raise SupabaseStoreError("integrations_config update failed", table=TABLE_INTEGRATIONS)

    async def _mirror(self, query: Dict[str, Any], update: Dict[str, Any], *, upsert: bool) -> None:
        try:
            await self._mongo.update_one(query, update, upsert=upsert)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s connect_store mongo mirror update failed: %s", storage_flags.STORE_DRIFT, exc)


def _as_facade(mongo_col: Any) -> IntegrationsConfigCollection:
    if isinstance(mongo_col, IntegrationsConfigCollection):
        return mongo_col
    return IntegrationsConfigCollection(mongo_col)


async def list_integrations_config(
    *,
    workspace_id: str,
    mongo_col,
    projection: Optional[Dict[str, int]] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    return await _as_facade(mongo_col).find_many(
        {"workspace_id": workspace_id}, projection, limit=limit,
    )


async def get_integrations_config(
    *,
    workspace_id: str,
    provider: str,
    mongo_col,
    projection: Optional[Dict[str, int]] = None,
) -> Optional[Dict[str, Any]]:
    return await _as_facade(mongo_col).find_one(
        {"workspace_id": workspace_id, "provider": provider}, projection,
    )


async def update_integrations_config(
    *,
    workspace_id: str,
    provider: str,
    mongo_col,
    fields: Dict[str, Any],
) -> Any:
    """Partial update (no upsert). Returns a Motor-like result with matched_count."""
    facade = _as_facade(mongo_col)
    if is_integrations_supabase_primary():
        return await facade.update_one(
            {"workspace_id": workspace_id, "provider": provider},
            {"$set": fields},
        )

    raw = facade._mongo
    result = await raw.update_one(
        {"workspace_id": workspace_id, "provider": provider},
        {"$set": fields},
    )
    matched = getattr(result, "matched_count", None)
    if matched is None:
        # FakeAsyncCollection / some drivers return None — confirm via read.
        existing = await raw.find_one(
            {"workspace_id": workspace_id, "provider": provider},
            {"_id": 1},
        )
        matched = 1 if existing else 0
        result = mc.UpdateResult(matched, matched)

    if is_integrations_dual_write_enabled():
        payload = _config_mongo_to_sb(workspace_id, provider, fields)
        # Upsert so the shadow lands even if the SB row was never seeded.
        resp = await secrets_store._sb_request(
            "POST",
            "/rest/v1/integrations_config",
            json=payload,
            params={"on_conflict": "workspace_id,provider"},
            prefer="resolution=merge-duplicates,return=minimal",
        )
        if resp is not None and resp.status_code >= 400:
            logger.warning(
                "%s connect_store integrations_config upsert %s: %s",
                storage_flags.MONGO_ONLY, resp.status_code, (resp.text or "")[:200],
            )
    return result
