"""Phase 4 — Facturapi Connect + webhook inbox + integrations_config dual-write.

Reuses Phase 2 vault flags / HTTP helpers from ``provider_secrets_store``
for Facturapi secrets (``provider_connections``). Adds thin dual-write for:

* ``webhook_events`` (append-only receipts)
* ``integrations_config`` (Connect UI catalog — non-secret)

Flags
-----
``QUANTRO_SECRETS_PRIMARY`` / ``QUANTRO_MONGO_MIRROR`` — Facturapi secrets
and webhook receipts (same as Phase 2 OAuth vault).

``QUANTRO_INTEGRATIONS_CONFIG_PRIMARY`` (default ``mongo``) — independent
soft flip for the UI catalog only. Dual-write whenever Supabase is
configured; never auto-flips.

Never logs ciphertext/plaintext keys. Graceful degrade if tables missing.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

import provider_secrets_store as secrets_store
from integrations.secrets import SECRET_FIELD_NAMES

logger = logging.getLogger("quantro.connect_store")

_INTEGRATIONS_PRIMARY_RAW = (
    os.environ.get("QUANTRO_INTEGRATIONS_CONFIG_PRIMARY") or "mongo"
).lower().strip()
INTEGRATIONS_CONFIG_PRIMARY = (
    _INTEGRATIONS_PRIMARY_RAW
    if _INTEGRATIONS_PRIMARY_RAW in {"mongo", "supabase"}
    else "mongo"
)


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


def _strip_secrets_from_config(config: Any) -> Dict[str, Any]:
    """Drop known secret fields from UI config before Supabase write."""
    if not isinstance(config, dict):
        return {}
    out: Dict[str, Any] = {}
    for k, v in config.items():
        if k in SECRET_FIELD_NAMES:
            continue
        if isinstance(k, str) and k.startswith("has_"):
            # Redaction flags are fine (boolean presence markers).
            out[k] = v
            continue
        out[k] = v
    return out


# ── Facturapi connection (delegates to Phase 2 vault) ─────────────────
async def get_facturapi_connection(
    *,
    workspace_id: Optional[str] = None,
    connection_id: Optional[str] = None,
    mongo_col,
    projection: Optional[Dict[str, int]] = None,
) -> Optional[Dict[str, Any]]:
    if connection_id:
        return await secrets_store.get_connection_by_connection_id(
            provider="facturapi",
            connection_id=connection_id,
            mongo_col=mongo_col,
            projection=projection,
        )
    if not workspace_id:
        return None
    return await secrets_store.get_connection(
        provider="facturapi",
        workspace_id=workspace_id,
        mongo_col=mongo_col,
        projection=projection,
    )


async def upsert_facturapi_connection(
    *,
    workspace_id: str,
    mongo_col,
    fields: Dict[str, Any],
) -> None:
    await secrets_store.upsert_connection(
        provider="facturapi",
        workspace_id=workspace_id,
        mongo_col=mongo_col,
        fields=fields,
    )


async def patch_facturapi_connection(
    *,
    workspace_id: str,
    mongo_col,
    fields: Dict[str, Any],
) -> None:
    await secrets_store.patch_connection(
        provider="facturapi",
        workspace_id=workspace_id,
        mongo_col=mongo_col,
        fields=fields,
    )


async def delete_facturapi_connection(
    *,
    workspace_id: str,
    mongo_col,
) -> None:
    await secrets_store.delete_connection(
        provider="facturapi",
        workspace_id=workspace_id,
        mongo_col=mongo_col,
    )


# ── webhook_events ────────────────────────────────────────────────────
async def _sb_get_webhook_by_event_id(
    provider: str, event_id: str,
) -> Optional[Dict[str, Any]]:
    resp = await secrets_store._sb_request(
        "GET",
        "/rest/v1/webhook_events",
        params={
            "provider": f"eq.{provider}",
            "event_id": f"eq.{event_id}",
            "select": "*",
            "limit": "1",
        },
    )
    if resp is None or resp.status_code != 200:
        return None
    rows = resp.json() or []
    return rows[0] if rows else None


async def find_webhook_event(
    *,
    provider: str,
    event_id: str,
    mongo_col,
) -> Optional[Dict[str, Any]]:
    """Idempotent dedup lookup (Mongo primary by default)."""
    if secrets_store.is_secrets_supabase_primary():
        row = await _sb_get_webhook_by_event_id(provider, event_id)
        if row:
            return {
                "event_id": row.get("event_id"),
                "workspace_id": row.get("workspace_id"),
                "connection_id": row.get("connection_id"),
                "event_type": row.get("event_type"),
                "received_at": _parse_dt(row.get("received_at")),
                "payload_summary": (row.get("payload") or {}).get("summary"),
                "livemode": (row.get("headers_meta") or {}).get("livemode"),
                "signature_valid": (row.get("headers_meta") or {}).get("signature_valid"),
                "status": row.get("status"),
            }
        return await mongo_col.find_one({"event_id": event_id})

    return await mongo_col.find_one({"event_id": event_id})


async def insert_webhook_event(
    *,
    provider: str,
    mongo_col,
    doc: Dict[str, Any],
) -> None:
    """Append one webhook receipt (dual-write). Never logs payload bodies."""
    if secrets_store.is_secrets_mongo_write_enabled():
        await mongo_col.insert_one(dict(doc))

    if secrets_store.is_secrets_dual_write_enabled():
        payload_summary = doc.get("payload_summary") or {}
        headers_meta = {
            k: doc.get(k)
            for k in ("livemode", "signature_valid")
            if k in doc
        }
        sb_row = {
            "workspace_id": doc.get("workspace_id"),
            "provider": provider,
            "connection_id": doc.get("connection_id"),
            "event_id": doc.get("event_id"),
            "event_type": doc.get("event_type"),
            "payload": {"summary": payload_summary},
            "headers_meta": headers_meta,
            "received_at": _iso(doc.get("received_at")) or _iso(datetime.now(timezone.utc)),
            "status": doc.get("status") or "received",
        }
        resp = await secrets_store._sb_request(
            "POST",
            "/rest/v1/webhook_events",
            json=sb_row,
            prefer="return=minimal",
        )
        if resp is not None and resp.status_code >= 400:
            # Unique violation on (provider, event_id) → treat as duplicate OK.
            text = (resp.text or "").lower()
            if resp.status_code in (409, 23505) or "duplicate" in text or "23505" in text:
                logger.info(
                    "connect_store webhook_events duplicate event_id (ok)"
                )
            else:
                logger.warning(
                    "connect_store insert webhook_events %s: %s",
                    resp.status_code, (resp.text or "")[:200],
                )


# ── integrations_config (UI catalog) ──────────────────────────────────
def _config_row_to_mongo(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "workspace_id": row.get("workspace_id"),
        "provider": row.get("provider"),
        "category": row.get("category"),
        "display_name": row.get("display_name"),
        "status": row.get("status"),
        "last_sync_at": _parse_dt(row.get("last_sync_at")),
        "config": row.get("config") or {},
        "created_at": _parse_dt(row.get("created_at")),
        "updated_at": _parse_dt(row.get("updated_at")),
    }


def _config_mongo_to_sb(workspace_id: str, provider: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "workspace_id": workspace_id,
        "provider": provider,
    }
    for key in ("category", "display_name", "status"):
        if key in fields:
            out[key] = fields[key]
    if "last_sync_at" in fields:
        out["last_sync_at"] = _iso(fields.get("last_sync_at"))
    if "created_at" in fields:
        out["created_at"] = _iso(fields.get("created_at"))
    if "updated_at" in fields:
        out["updated_at"] = _iso(fields.get("updated_at"))
    if "config" in fields:
        out["config"] = _strip_secrets_from_config(fields.get("config"))
    return out


async def list_integrations_config(
    *,
    workspace_id: str,
    mongo_col,
    projection: Optional[Dict[str, int]] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    if is_integrations_supabase_primary():
        resp = await secrets_store._sb_request(
            "GET",
            "/rest/v1/integrations_config",
            params={
                "workspace_id": f"eq.{workspace_id}",
                "select": "*",
                "limit": str(limit),
            },
        )
        if resp is not None and resp.status_code == 200:
            rows = resp.json() or []
            if rows:
                return [_config_row_to_mongo(r) for r in rows]
        # fall through to Mongo

    cursor = mongo_col.find({"workspace_id": workspace_id}, projection)
    return await cursor.to_list(limit)


async def get_integrations_config(
    *,
    workspace_id: str,
    provider: str,
    mongo_col,
    projection: Optional[Dict[str, int]] = None,
) -> Optional[Dict[str, Any]]:
    if is_integrations_supabase_primary():
        resp = await secrets_store._sb_request(
            "GET",
            "/rest/v1/integrations_config",
            params={
                "workspace_id": f"eq.{workspace_id}",
                "provider": f"eq.{provider}",
                "select": "*",
                "limit": "1",
            },
        )
        if resp is not None and resp.status_code == 200:
            rows = resp.json() or []
            if rows:
                return _config_row_to_mongo(rows[0])
        return await mongo_col.find_one(
            {"workspace_id": workspace_id, "provider": provider},
            projection,
        )

    return await mongo_col.find_one(
        {"workspace_id": workspace_id, "provider": provider},
        projection,
    )


async def update_integrations_config(
    *,
    workspace_id: str,
    provider: str,
    mongo_col,
    fields: Dict[str, Any],
) -> Any:
    """Partial update (no upsert). Returns a Motor-like result with matched_count."""
    matched = 0
    result = None

    if is_integrations_mongo_write_enabled():
        result = await mongo_col.update_one(
            {"workspace_id": workspace_id, "provider": provider},
            {"$set": fields},
        )
        matched = getattr(result, "matched_count", None)
        if matched is None:
            # FakeAsyncCollection / some drivers return None — confirm via read.
            existing = await mongo_col.find_one(
                {"workspace_id": workspace_id, "provider": provider},
                {"_id": 1},
            )
            matched = 1 if existing else 0

            class _CompatResult:
                matched_count = matched
                modified_count = matched

            result = _CompatResult()
        else:
            matched = matched or 0

    if is_integrations_dual_write_enabled():
        payload = _config_mongo_to_sb(workspace_id, provider, fields)
        # Prefer upsert so dual-write lands even if SB row was never seeded.
        resp = await secrets_store._sb_request(
            "POST",
            "/rest/v1/integrations_config",
            json=payload,
            params={"on_conflict": "workspace_id,provider"},
            prefer="resolution=merge-duplicates,return=minimal",
        )
        if resp is not None and resp.status_code >= 400:
            logger.warning(
                "connect_store integrations_config upsert %s: %s",
                resp.status_code, (resp.text or "")[:200],
            )

    if result is not None:
        return result

    # Mongo writes disabled (supabase primary + mirror off) — synthesize.
    class _R:
        matched_count = 1 if matched or is_integrations_supabase_primary() else 0
        modified_count = matched
    # If we only wrote SB, assume match when primary is supabase.
    if is_integrations_supabase_primary():
        _R.matched_count = 1
    return _R()
