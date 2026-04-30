"""Supabase REST helpers for Phase 7c — read/write through PostgREST.

This module is the single place the FastAPI server talks to Supabase
(outside of the AI billing wrapper in ai_billing.py). It uses ``httpx``
directly against the PostgREST endpoints and never imports
``supabase-py`` so we keep the dependency surface small.

Tables touched:
  * organizations            (read-only)
  * org_members              (read + insert + update + delete)
  * invitations              (read + insert + update)
  * org_audit_logs           (read + insert)  — append-only from app
  * people_onboarding_steps  (read + upsert + update)

Auth modes:
  * "user"    — uses the caller's Supabase JWT (RLS enforced).
                Adequate for reads + most writes governed by policies.
  * "service" — uses SUPABASE_SERVICE_ROLE_KEY when available; bypasses
                RLS. Only used for fan-out events that can't be
                expressed cleanly as a user-side policy (e.g. logging
                an audit event when a webhook removes a member).

Every function is intentionally **best-effort**: failures log a
warning and return None / empty list. The backend always has the
MongoDB fallback during the dual-write transition.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException

logger = logging.getLogger("quantro.supabase_admin")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# Phase 7c rollout switch. Values:
#   "mongo"     — default. Read/write Mongo, shadow-write Supabase
#                 best-effort. UI behavior is unchanged.
#   "supabase"  — read from Supabase, dual-write to both. Used once
#                 the migration has been applied and the backfill ran.
DB_PRIMARY = (os.environ.get("QUANTRO_DB_PRIMARY") or "mongo").lower().strip()

# Default Quantro org for the legacy single-tenant workspace. Surfaced
# so the workspace-id mapping helper can resolve ``DEFAULT_WORKSPACE_ID``
# to a real Supabase organisation row without a Mongo round-trip.
DEFAULT_ORG_ID = os.environ.get("QUANTRO_DEFAULT_ORG_ID", "")


def _is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def _user_headers(access_token: str, prefer: Optional[str] = None) -> Dict[str, str]:
    h = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


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


async def _request(
    method: str,
    path: str,
    *,
    access_token: Optional[str],
    use_service: bool = False,
    json: Optional[Any] = None,
    params: Optional[Dict[str, Any]] = None,
    prefer: Optional[str] = None,
) -> Optional[httpx.Response]:
    """Low-level HTTP call. Returns ``None`` on connection-level
    failures (best-effort semantics). 4xx/5xx responses are returned
    as-is so callers can decide how to react."""
    if not _is_configured():
        return None
    headers = (
        _service_headers(prefer)
        if use_service and SUPABASE_SERVICE_ROLE_KEY
        else (_user_headers(access_token, prefer) if access_token else None)
    )
    if not headers:
        return None
    url = f"{SUPABASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(method, url, headers=headers, json=json, params=params)
        return resp
    except Exception as exc:  # noqa: BLE001
        logger.warning("supabase_admin %s %s failed: %s", method, path, exc)
        return None


# ── Reads ─────────────────────────────────────────────────────────────
async def list_org_members(org_id: str, access_token: str) -> List[Dict[str, Any]]:
    """Return the org_members rows for ``org_id`` plus inline auth
    metadata via PostgREST embedded resources. Falls back to a plain
    list if the embed is rejected (older PostgREST or missing FK)."""
    resp = await _request(
        "GET",
        "/rest/v1/org_members",
        access_token=access_token,
        params={
            "org_id": f"eq.{org_id}",
            "select": "user_id,role,joined_at,id",
        },
    )
    if resp is None or resp.status_code != 200:
        return []
    return resp.json() or []


async def list_orgs_for_user(user_id: str) -> List[Dict[str, Any]]:
    """Return every ``org_members`` row for ``user_id``.

    Uses the service-role key to bypass RLS, so it can be safely called
    from the login hook *before* we have a user JWT for RLS context. If
    the service-role key isn't configured, this silently returns ``[]``
    — callers must fall back to Mongo-only behaviour.

    Shape: ``[{org_id, role, joined_at, id}, ...]``.
    """
    if not SUPABASE_SERVICE_ROLE_KEY:
        return []
    resp = await _request(
        "GET",
        "/rest/v1/org_members",
        access_token=None,
        use_service=True,
        params={
            "user_id": f"eq.{user_id}",
            "select": "id,org_id,role,joined_at",
            "order": "joined_at.asc",
        },
    )
    if resp is None or resp.status_code != 200:
        return []
    return resp.json() or []


async def list_invitations(org_id: str, access_token: str) -> List[Dict[str, Any]]:
    resp = await _request(
        "GET",
        "/rest/v1/invitations",
        access_token=access_token,
        params={
            "org_id": f"eq.{org_id}",
            "select": "id,email,role,token,accepted,expires_at,created_at,full_name,job_title,invited_by",
            "order": "created_at.desc",
        },
    )
    if resp is None or resp.status_code != 200:
        return []
    return resp.json() or []


async def get_invitation_by_token(token: str, access_token: str) -> Optional[Dict[str, Any]]:
    """Look up a single invite by its UUID token."""
    resp = await _request(
        "GET",
        "/rest/v1/invitations",
        access_token=access_token,
        params={
            "token": f"eq.{token}",
            "select": "id,org_id,email,role,token,accepted,expires_at,created_at,full_name,invited_by",
            "limit": "1",
        },
    )
    if resp is None or resp.status_code != 200:
        return None
    rows = resp.json() or []
    return rows[0] if rows else None


async def list_audit_logs(
    org_id: str,
    access_token: str,
    limit: int = 100,
    target_user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {
        "org_id": f"eq.{org_id}",
        "select": "id,actor_user_id,target_user_id,action,old_role,new_role,metadata,created_at",
        "order": "created_at.desc",
        "limit": str(max(1, min(int(limit or 100), 500))),
    }
    if target_user_id:
        params["target_user_id"] = f"eq.{target_user_id}"
    resp = await _request(
        "GET",
        "/rest/v1/org_audit_logs",
        access_token=access_token,
        params=params,
    )
    if resp is None or resp.status_code != 200:
        return []
    return resp.json() or []


async def list_onboarding_steps(org_id: str, access_token: str) -> List[Dict[str, Any]]:
    resp = await _request(
        "GET",
        "/rest/v1/people_onboarding_steps",
        access_token=access_token,
        params={
            "org_id": f"eq.{org_id}",
            "select": "id,member_id,step_key,status,completed_at,metadata",
        },
    )
    if resp is None or resp.status_code != 200:
        return []
    return resp.json() or []


async def get_organization(org_id: str, access_token: str) -> Optional[Dict[str, Any]]:
    resp = await _request(
        "GET",
        "/rest/v1/organizations",
        access_token=access_token,
        params={"id": f"eq.{org_id}", "select": "id,name,owner_id,created_at", "limit": "1"},
    )
    if resp is None or resp.status_code != 200:
        return None
    rows = resp.json() or []
    return rows[0] if rows else None


# ── Writes (best-effort) ──────────────────────────────────────────────
async def insert_invitation(
    *,
    org_id: str,
    role: str,
    invited_by: str,
    access_token: str,
    email: Optional[str] = None,
    full_name: Optional[str] = None,
    job_title: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    payload: Dict[str, Any] = {
        "org_id": org_id,
        "role": role,
        "invited_by": invited_by,
        # `email` is NOT NULL on Supabase. Use a placeholder when the
        # user wants an email-free invite (matches the legacy Mongo flow).
        "email": (email or f"pending+{org_id[:8]}@quantro.invite").lower().strip(),
    }
    if full_name:
        payload["full_name"] = full_name
    if job_title:
        payload["job_title"] = job_title
    if expires_at:
        payload["expires_at"] = expires_at

    resp = await _request(
        "POST",
        "/rest/v1/invitations",
        access_token=access_token,
        json=payload,
        prefer="return=representation",
    )
    if resp is None or resp.status_code >= 400:
        if resp is not None:
            logger.warning(
                "supabase_admin.insert_invitation %s: %s",
                resp.status_code, resp.text[:200],
            )
        return None
    rows = resp.json() or []
    return rows[0] if isinstance(rows, list) and rows else rows


async def update_invitation(
    invite_id: str,
    patch: Dict[str, Any],
    access_token: str,
) -> bool:
    resp = await _request(
        "PATCH",
        "/rest/v1/invitations",
        access_token=access_token,
        json=patch,
        params={"id": f"eq.{invite_id}"},
        prefer="return=minimal",
    )
    return bool(resp is not None and resp.status_code < 400)


async def update_member_role(
    *,
    org_id: str,
    member_user_id: str,
    new_role: str,
    access_token: str,
) -> bool:
    resp = await _request(
        "PATCH",
        "/rest/v1/org_members",
        access_token=access_token,
        json={"role": new_role},
        params={"org_id": f"eq.{org_id}", "user_id": f"eq.{member_user_id}"},
        prefer="return=minimal",
    )
    return bool(resp is not None and resp.status_code < 400)


async def delete_member(
    *,
    org_id: str,
    member_user_id: str,
    access_token: str,
) -> bool:
    resp = await _request(
        "DELETE",
        "/rest/v1/org_members",
        access_token=access_token,
        params={"org_id": f"eq.{org_id}", "user_id": f"eq.{member_user_id}"},
        prefer="return=minimal",
    )
    return bool(resp is not None and resp.status_code < 400)


async def insert_audit_log(
    *,
    org_id: str,
    action: str,
    target_user_id: str,
    actor_user_id: Optional[str],
    access_token: Optional[str],
    old_role: Optional[str] = None,
    new_role: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Insert a row into org_audit_logs. Tries service-role first
    (bypasses RLS) and falls back to user JWT (subject to RLS)."""
    payload: Dict[str, Any] = {
        "org_id": org_id,
        "action": action,
        "target_user_id": target_user_id,
        "actor_user_id": actor_user_id,
        "metadata": metadata or {},
    }
    if old_role is not None:
        payload["old_role"] = old_role
    if new_role is not None:
        payload["new_role"] = new_role

    # Try service first.
    if SUPABASE_SERVICE_ROLE_KEY:
        resp = await _request(
            "POST",
            "/rest/v1/org_audit_logs",
            access_token=None,
            use_service=True,
            json=payload,
            prefer="return=minimal",
        )
        if resp is not None and resp.status_code < 400:
            return True
    if access_token:
        resp = await _request(
            "POST",
            "/rest/v1/org_audit_logs",
            access_token=access_token,
            json=payload,
            prefer="return=minimal",
        )
        if resp is not None and resp.status_code < 400:
            return True
    return False


async def upsert_onboarding_step(
    *,
    org_id: str,
    member_id: str,
    step_key: str,
    status: str,
    metadata: Optional[Dict[str, Any]],
    access_token: str,
    completed_at_iso: Optional[str] = None,
) -> bool:
    payload: Dict[str, Any] = {
        "org_id": org_id,
        "member_id": member_id,
        "step_key": step_key,
        "status": status,
        "metadata": metadata or {},
    }
    if status == "completed" and completed_at_iso:
        payload["completed_at"] = completed_at_iso

    # PostgREST upsert via on_conflict.
    resp = await _request(
        "POST",
        "/rest/v1/people_onboarding_steps",
        access_token=access_token,
        json=payload,
        params={"on_conflict": "org_id,member_id,step_key"},
        prefer="resolution=merge-duplicates,return=minimal",
    )
    return bool(resp is not None and resp.status_code < 400)


# ── Workspace ↔ Org mapping ───────────────────────────────────────────
def resolve_default_org_id() -> Optional[str]:
    """Return the configured default Supabase org id (or None)."""
    return DEFAULT_ORG_ID or None


def is_supabase_primary() -> bool:
    return DB_PRIMARY == "supabase" and _is_configured()


def is_dual_write_enabled() -> bool:
    """True when shadow writes to Supabase should fire (regardless of
    which DB is the read primary)."""
    return _is_configured()


# Convenience: surface a one-shot health check the lifespan uses on boot.
async def health_check() -> Dict[str, Any]:
    if not _is_configured():
        return {"configured": False}
    out = {
        "configured": True,
        "primary": DB_PRIMARY,
        "service_role_available": bool(SUPABASE_SERVICE_ROLE_KEY),
        "default_org_id": DEFAULT_ORG_ID or None,
    }
    return out
