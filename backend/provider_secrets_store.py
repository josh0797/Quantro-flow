"""Phase 2/4 — Provider secrets dual-write (Mongo ↔ Supabase).

Central persistence for Google/Microsoft OAuth docs, Facturapi Connect
secrets (Phase 4), and short-lived OAuth CSRF state. Ciphertext only
(Fernet); this module never encrypts/decrypts and never logs token or
API-key values.

Flags
-----
``QUANTRO_SECRETS_PRIMARY`` (default ``mongo``):
  * ``mongo``     — reads from Mongo; dual-write Supabase when configured.
  * ``supabase``  — reads from Supabase first (Mongo fallback); Mongo
                    writes gated by ``QUANTRO_MONGO_MIRROR`` (default on).

Safest Phase 2 first-PR default: dual-write ON, read still Mongo, so
deploys that have not applied the migration / backfill keep working.

All Supabase calls use the **service role** only (RLS: no anon/
authenticated policies on secret tables). Missing tables / transport
errors degrade gracefully: log + keep Mongo.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("quantro.provider_secrets_store")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# Phase 2 secrets SoT. Default mongo until backfill + migration are live.
_SECRETS_PRIMARY_RAW = (os.environ.get("QUANTRO_SECRETS_PRIMARY") or "mongo").lower().strip()
SECRETS_PRIMARY = _SECRETS_PRIMARY_RAW if _SECRETS_PRIMARY_RAW in {"mongo", "supabase"} else "mongo"

_MONGO_MIRROR_RAW = (os.environ.get("QUANTRO_MONGO_MIRROR") or "1").lower().strip()
MONGO_MIRROR = _MONGO_MIRROR_RAW not in {"0", "false", "no", "off"}

VALID_PROVIDERS = frozenset({"google", "microsoft", "facturapi"})
OAUTH_PROVIDERS = frozenset({"google", "microsoft"})  # CSRF state providers

def _is_sb_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def is_secrets_supabase_primary() -> bool:
    return SECRETS_PRIMARY == "supabase" and _is_sb_configured()


def is_secrets_dual_write_enabled() -> bool:
    """True when Supabase shadow/primary writes should fire."""
    return _is_sb_configured()


def is_secrets_mongo_write_enabled() -> bool:
    """True when Mongo integration/state writes should fire.

    Always True when Supabase is not configured. When secrets primary is
    supabase, honour QUANTRO_MONGO_MIRROR (default on) so rollback stays
    safe.
    """
    if not _is_sb_configured():
        return True
    if SECRETS_PRIMARY != "supabase":
        return True
    return MONGO_MIRROR


def secrets_health() -> Dict[str, Any]:
    return {
        "secrets_primary": SECRETS_PRIMARY,
        "supabase_configured": _is_sb_configured(),
        "dual_write": is_secrets_dual_write_enabled(),
        "mongo_write": is_secrets_mongo_write_enabled(),
        "mongo_mirror": MONGO_MIRROR,
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
    # PostgREST unknown relation
    text = (resp.text or "").lower()
    return resp.status_code in (400, 404) and (
        "could not find the table" in text
        or "pgrst205" in text
        or "does not exist" in text
    )


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
                "provider_secrets_store: Supabase table missing for %s %s — "
                "apply Phase 2/4 provider_connections migrations",
                method, path,
            )
            return None
        return resp
    except Exception as exc:  # noqa: BLE001
        logger.warning("provider_secrets_store %s %s failed: %s", method, path, exc)
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


def _connection_mongo_to_sb(provider: str, workspace_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Map a Mongo-shaped patch/upsert into a Supabase row (ciphertext keys)."""
    out: Dict[str, Any] = {
        "workspace_id": workspace_id,
        "provider": provider,
    }
    for mongo_key, value in fields.items():
        if mongo_key in {"_id", "workspace_id", "provider"}:
            continue
        if mongo_key == "access_token":
            out["access_token_enc"] = value
        elif mongo_key == "refresh_token":
            out["refresh_token_enc"] = value
        elif mongo_key in {"google_user_id", "ms_user_id"}:
            if value is not None:
                out["provider_user_id"] = value
        elif mongo_key == "secret_key_encrypted":
            out["api_key_enc"] = value
        elif mongo_key == "webhook_token_encrypted":
            out["webhook_token_enc"] = value
        elif mongo_key == "webhook_signing_secret_encrypted":
            out["webhook_secret_enc"] = value
        elif mongo_key in {
            "connection_id", "environment", "organization_id", "legal_name",
            "is_production_ready", "timezone", "webhook_id",
        }:
            out[mongo_key] = value
        elif mongo_key == "last_error":
            meta = dict(out.get("meta") or {})
            meta["last_error"] = value
            out["meta"] = meta
        elif mongo_key == "meta" and isinstance(value, dict):
            merged = dict(out.get("meta") or {})
            merged.update(value)
            out["meta"] = merged
        elif mongo_key in {
            "org_id", "account_email", "account_name", "user_id", "scopes",
            "expires_at", "connected", "status", "reauthorization_required",
            "missing_scopes", "connected_at", "last_sync_at",
            "last_sync_attempt_at", "auto_sync_paused", "last_sync_error",
            "updated_at",
        }:
            if mongo_key in {
                "expires_at", "connected_at", "last_sync_at",
                "last_sync_attempt_at", "updated_at",
            }:
                out[mongo_key] = _iso(value)
            elif mongo_key in {"scopes", "missing_scopes"}:
                out[mongo_key] = list(value) if value is not None else []
            else:
                out[mongo_key] = value
        # Ignore unknown keys quietly (e.g. legacy fields).
    # Facturapi: derive connected from status when not explicit.
    if provider == "facturapi" and "connected" not in out and "status" in out:
        out["connected"] = out.get("status") == "connected"
    return out


def _connection_sb_to_mongo(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a Supabase provider_connections row to Mongo field names."""
    if not row:
        return {}
    out: Dict[str, Any] = {
        "workspace_id": row.get("workspace_id"),
        "provider": row.get("provider"),
        "account_email": row.get("account_email"),
        "account_name": row.get("account_name"),
        "user_id": row.get("user_id"),
        "org_id": row.get("org_id"),
        "scopes": row.get("scopes") or [],
        "access_token": row.get("access_token_enc"),
        "refresh_token": row.get("refresh_token_enc"),
        "expires_at": _parse_dt(row.get("expires_at")),
        "connected": row.get("connected"),
        "status": row.get("status"),
        "reauthorization_required": row.get("reauthorization_required"),
        "missing_scopes": row.get("missing_scopes") or [],
        "connected_at": _parse_dt(row.get("connected_at")),
        "last_sync_at": _parse_dt(row.get("last_sync_at")),
        "last_sync_attempt_at": _parse_dt(row.get("last_sync_attempt_at")),
        "auto_sync_paused": row.get("auto_sync_paused"),
        "last_sync_error": row.get("last_sync_error"),
        "updated_at": _parse_dt(row.get("updated_at")),
        "provider_user_id": row.get("provider_user_id"),
        # Phase 4 Facturapi fields
        "secret_key_encrypted": row.get("api_key_enc"),
        "connection_id": row.get("connection_id"),
        "environment": row.get("environment"),
        "organization_id": row.get("organization_id"),
        "legal_name": row.get("legal_name"),
        "is_production_ready": row.get("is_production_ready"),
        "timezone": row.get("timezone"),
        "webhook_id": row.get("webhook_id"),
        "webhook_token_encrypted": row.get("webhook_token_enc"),
        "webhook_signing_secret_encrypted": row.get("webhook_secret_enc"),
    }
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    if meta.get("last_error") is not None:
        out["last_error"] = meta.get("last_error")
    # Restore provider-specific id aliases expected by existing callers.
    provider = row.get("provider")
    puid = row.get("provider_user_id")
    if puid and provider == "google":
        out["google_user_id"] = puid
    elif puid and provider == "microsoft":
        out["ms_user_id"] = puid
    # Drop Nones for cleaner merge with projections.
    return {k: v for k, v in out.items() if v is not None or k in {
        "workspace_id", "connected", "scopes", "missing_scopes",
    }}


def _apply_projection(doc: Dict[str, Any], projection: Optional[Dict[str, int]]) -> Dict[str, Any]:
    if not projection:
        return doc
    include = {k for k, v in projection.items() if v and k != "_id"}
    if not include:
        return doc
    return {k: doc.get(k) for k in include if k in doc or k in projection}


# ── Connections ───────────────────────────────────────────────────────
async def _sb_get_connection(provider: str, workspace_id: str) -> Optional[Dict[str, Any]]:
    resp = await _sb_request(
        "GET",
        "/rest/v1/provider_connections",
        params={
            "workspace_id": f"eq.{workspace_id}",
            "provider": f"eq.{provider}",
            "select": "*",
            "limit": "1",
        },
    )
    if resp is None or resp.status_code != 200:
        return None
    rows = resp.json() or []
    return rows[0] if rows else None


async def _sb_upsert_connection(payload: Dict[str, Any]) -> bool:
    resp = await _sb_request(
        "POST",
        "/rest/v1/provider_connections",
        json=payload,
        params={"on_conflict": "workspace_id,provider"},
        prefer="resolution=merge-duplicates,return=minimal",
    )
    if resp is None:
        return False
    if resp.status_code >= 400:
        logger.warning(
            "provider_secrets_store upsert connection %s: %s",
            resp.status_code, (resp.text or "")[:200],
        )
        return False
    return True


async def _sb_patch_connection(provider: str, workspace_id: str, patch: Dict[str, Any]) -> bool:
    if not patch:
        return True
    resp = await _sb_request(
        "PATCH",
        "/rest/v1/provider_connections",
        json=patch,
        params={
            "workspace_id": f"eq.{workspace_id}",
            "provider": f"eq.{provider}",
        },
        prefer="return=minimal",
    )
    if resp is None:
        return False
    if resp.status_code >= 400:
        logger.warning(
            "provider_secrets_store patch connection %s: %s",
            resp.status_code, (resp.text or "")[:200],
        )
        return False
    return True


async def _sb_delete_connection(provider: str, workspace_id: str) -> bool:
    resp = await _sb_request(
        "DELETE",
        "/rest/v1/provider_connections",
        params={
            "workspace_id": f"eq.{workspace_id}",
            "provider": f"eq.{provider}",
        },
        prefer="return=minimal",
    )
    if resp is None:
        return False
    return resp.status_code < 400


async def get_connection(
    *,
    provider: str,
    workspace_id: str,
    mongo_col,
    projection: Optional[Dict[str, int]] = None,
) -> Optional[Dict[str, Any]]:
    """Read one integration doc. Primary store first; Mongo fallback when
    secrets primary is supabase."""
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")

    if is_secrets_supabase_primary():
        row = await _sb_get_connection(provider, workspace_id)
        if row:
            return _apply_projection(_connection_sb_to_mongo(row), projection)
        # Fallback to Mongo (pre-backfill / dual-write lag).
        doc = await mongo_col.find_one({"workspace_id": workspace_id}, projection)
        return doc

    doc = await mongo_col.find_one({"workspace_id": workspace_id}, projection)
    return doc


async def upsert_connection(
    *,
    provider: str,
    workspace_id: str,
    mongo_col,
    fields: Dict[str, Any],
) -> None:
    """Upsert connection fields (Mongo-shaped, ciphertext already applied)."""
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")

    set_fields = dict(fields)
    set_fields.setdefault("workspace_id", workspace_id)

    if is_secrets_mongo_write_enabled():
        await mongo_col.update_one(
            {"workspace_id": workspace_id},
            {"$set": set_fields},
            upsert=True,
        )

    if is_secrets_dual_write_enabled():
        payload = _connection_mongo_to_sb(provider, workspace_id, set_fields)
        await _sb_upsert_connection(payload)


async def patch_connection(
    *,
    provider: str,
    workspace_id: str,
    mongo_col,
    fields: Dict[str, Any],
) -> None:
    """Partial update (no upsert). Used for token refresh / last_sync / pause."""
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")

    if is_secrets_mongo_write_enabled():
        await mongo_col.update_one(
            {"workspace_id": workspace_id},
            {"$set": fields},
        )

    if is_secrets_dual_write_enabled():
        patch = _connection_mongo_to_sb(provider, workspace_id, fields)
        # Don't send identity keys on patch — filter is workspace+provider.
        patch.pop("workspace_id", None)
        patch.pop("provider", None)
        ok = await _sb_patch_connection(provider, workspace_id, patch)
        # If no row yet (patch hit 0 rows / table empty), try upsert so
        # dual-write still lands after a Mongo-only historical connect.
        if not ok:
            full = dict(fields)
            full["workspace_id"] = workspace_id
            await _sb_upsert_connection(
                _connection_mongo_to_sb(provider, workspace_id, full)
            )


async def delete_connection(
    *,
    provider: str,
    workspace_id: str,
    mongo_col,
) -> None:
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")

    if is_secrets_mongo_write_enabled():
        await mongo_col.delete_one({"workspace_id": workspace_id})

    if is_secrets_dual_write_enabled():
        await _sb_delete_connection(provider, workspace_id)


async def list_autosync_workspace_ids(
    *,
    provider: str,
    mongo_col,
) -> List[str]:
    """Workspace ids with a connection and auto_sync_paused != True."""
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")

    if is_secrets_supabase_primary():
        resp = await _sb_request(
            "GET",
            "/rest/v1/provider_connections",
            params={
                "provider": f"eq.{provider}",
                "auto_sync_paused": "eq.false",
                "select": "workspace_id",
            },
        )
        if resp is not None and resp.status_code == 200:
            rows = resp.json() or []
            return [r["workspace_id"] for r in rows if r.get("workspace_id")]
        # fall through to Mongo

    out: List[str] = []
    cursor = mongo_col.find(
        {"auto_sync_paused": {"$ne": True}},
        {"_id": 0, "workspace_id": 1},
    )
    async for row in cursor:
        wid = row.get("workspace_id")
        if wid:
            out.append(wid)
    return out



async def _sb_get_connection_by_connection_id(
    provider: str, connection_id: str,
) -> Optional[Dict[str, Any]]:
    resp = await _sb_request(
        "GET",
        "/rest/v1/provider_connections",
        params={
            "provider": f"eq.{provider}",
            "connection_id": f"eq.{connection_id}",
            "select": "*",
            "limit": "1",
        },
    )
    if resp is None or resp.status_code != 200:
        return None
    rows = resp.json() or []
    return rows[0] if rows else None


async def get_connection_by_connection_id(
    *,
    provider: str,
    connection_id: str,
    mongo_col,
    projection: Optional[Dict[str, int]] = None,
) -> Optional[Dict[str, Any]]:
    """Lookup by provider connection_id (Facturapi webhook path)."""
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")

    if is_secrets_supabase_primary():
        row = await _sb_get_connection_by_connection_id(provider, connection_id)
        if row:
            return _apply_projection(_connection_sb_to_mongo(row), projection)
        doc = await mongo_col.find_one({"connection_id": connection_id}, projection)
        return doc

    doc = await mongo_col.find_one({"connection_id": connection_id}, projection)
    return doc


# ── OAuth state ───────────────────────────────────────────────────────
async def put_oauth_state(
    *,
    provider: str,
    mongo_col,
    state: str,
    user_id: Optional[str],
    workspace_id: Optional[str],
    return_to: Optional[str],
    redirect_uri: Optional[str],
    code_verifier: Optional[str] = None,
    created_at: Optional[datetime] = None,
    expires_at: Optional[datetime] = None,
) -> None:
    """Persist CSRF state. Dual-write always when Supabase is configured.

    ``code_verifier`` is the short-lived Google PKCE verifier (nullable for
    Microsoft / legacy rows). Deleted with the row on consume.
    """
    if provider not in OAUTH_PROVIDERS:
        raise ValueError(f"unknown oauth provider: {provider}")

    now = datetime.now(timezone.utc)
    created = created_at or now
    expires = expires_at if expires_at is not None else (now + timedelta(minutes=10))

    doc = {
        "state": state,
        "user_id": user_id,
        "workspace_id": workspace_id,
        "return_to": return_to,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "created_at": created,
        "expires_at": expires,
    }

    if is_secrets_mongo_write_enabled():
        await mongo_col.insert_one(doc)

    if is_secrets_dual_write_enabled():
        payload = {
            "state": state,
            "provider": provider,
            "user_id": user_id,
            "workspace_id": workspace_id,
            "return_to": return_to,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "created_at": _iso(created),
            "expires_at": _iso(expires),
        }
        resp = await _sb_request(
            "POST",
            "/rest/v1/oauth_states",
            json=payload,
            prefer="return=minimal",
        )
        if resp is not None and resp.status_code >= 400:
            logger.warning(
                "provider_secrets_store put_oauth_state %s: %s",
                resp.status_code, (resp.text or "")[:200],
            )


async def consume_oauth_state(
    *,
    provider: str,
    mongo_col,
    state: str,
) -> Optional[Dict[str, Any]]:
    """Atomically read+delete state. Tries primary then the other store.

    Short-lived rows: we dual-write on put, so consume checks both to
    tolerate partial writes / primary flip mid-flow.
    """
    if provider not in OAUTH_PROVIDERS:
        raise ValueError(f"unknown oauth provider: {provider}")

    async def _from_mongo() -> Optional[Dict[str, Any]]:
        return await mongo_col.find_one_and_delete({"state": state})

    async def _from_sb() -> Optional[Dict[str, Any]]:
        # SELECT then DELETE (PostgREST has no find_one_and_delete).
        resp = await _sb_request(
            "GET",
            "/rest/v1/oauth_states",
            params={
                "state": f"eq.{state}",
                "provider": f"eq.{provider}",
                "select": "*",
                "limit": "1",
            },
        )
        if resp is None or resp.status_code != 200:
            return None
        rows = resp.json() or []
        if not rows:
            return None
        row = rows[0]
        await _sb_request(
            "DELETE",
            "/rest/v1/oauth_states",
            params={"state": f"eq.{state}"},
            prefer="return=minimal",
        )
        return {
            "state": row.get("state"),
            "user_id": row.get("user_id"),
            "workspace_id": row.get("workspace_id"),
            "return_to": row.get("return_to"),
            "redirect_uri": row.get("redirect_uri"),
            "code_verifier": row.get("code_verifier"),
            "created_at": _parse_dt(row.get("created_at")),
            "expires_at": _parse_dt(row.get("expires_at")),
            "provider": row.get("provider"),
        }

    if is_secrets_supabase_primary():
        doc = await _from_sb()
        if doc:
            # Best-effort cleanup of Mongo twin.
            try:
                await mongo_col.find_one_and_delete({"state": state})
            except Exception:  # noqa: BLE001
                pass
            return doc
        return await _from_mongo()

    doc = await _from_mongo()
    if doc:
        # Best-effort cleanup of Supabase twin.
        if is_secrets_dual_write_enabled():
            await _sb_request(
                "DELETE",
                "/rest/v1/oauth_states",
                params={"state": f"eq.{state}"},
                prefer="return=minimal",
            )
        return doc
    # Mongo miss — try Supabase (dual-write only landed on SB, or primary flip).
    if is_secrets_dual_write_enabled():
        return await _from_sb()
    return None
