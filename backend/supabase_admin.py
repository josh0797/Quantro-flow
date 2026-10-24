"""Supabase REST helpers for identity/tenancy (Phase 7c → Phase 1 → O12).

This module is the single place the FastAPI server talks to Supabase
for org membership, invites, and audit (outside of the AI billing
wrapper in ai_billing.py). It uses ``httpx`` directly against
PostgREST and never imports ``supabase-py``.

Membership belongs to Quantro OS People OS (owner decision O12, konta
RBAC PR 6): ``team_members`` is the membership table and a trigger mirrors
it into ``org_members``. Flow therefore only READS ``org_members`` and
``invitations``; every membership change is a People OS RPC called with the
CALLER's JWT (``call_rpc`` never uses the service role), so Quantro OS
checks the People keys, the roles the caller may grant, seats and plan, and
writes its own audit row. See docs/people-os-membership.md.

Tables / functions touched:
  * organizations            (read-only)
  * org_members              (read-only; mirror of team_members)
  * invitations              (read-only; legacy, no longer created)
  * team_members             (read-only, caller's JWT: People OS rows)
  * org_audit_logs           (read + insert)
  * people_onboarding_steps  (read + upsert + update)
  * rpc: invite_member, get_invitation_preview, accept_team_invite,
         accept_invitation(p_token), change_member_role,
         revoke_member_access, delete_member  (caller's JWT only)

Auth modes:
  * "user"    — caller's Supabase JWT (RLS enforced). Every RPC above.
  * "service" — SUPABASE_SERVICE_ROLE_KEY; bypasses RLS for RBAC
                lookups (org_members reads) and audit fan-out. Never for
                a membership write.

Phase 1: ``QUANTRO_DB_PRIMARY`` defaults to ``supabase``. Set it to
``mongo`` to roll back reads. ``QUANTRO_MONGO_MIRROR`` (default OFF since
the Mongo exit) is read by server.py's ``_local_identity_writes``: Flow's
own workspace_members / invites / audit docs now live in Supabase
(``flow_documents``) and are always written; the flag only matters while
those docs are still on Mongo (``QUANTRO_DOCS_PRIMARY=mongo``).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, NamedTuple, Optional

import httpx

import storage_flags

logger = logging.getLogger("quantro.supabase_admin")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# Phase 1 identity SoT switch. Values:
#   "supabase"  — default. Read/write org_members / invitations /
#                 org_audit_logs as source of truth. Optional Mongo
#                 mirror via QUANTRO_MONGO_MIRROR (default on).
#   "mongo"     — rollback. Read Mongo; still shadow-write Supabase
#                 when configured (Phase 7c dual-write).
DB_PRIMARY = (os.environ.get("QUANTRO_DB_PRIMARY") or "supabase").lower().strip()

# Optional Mongo mirror for identity collections. Unset → off (fail-safe
# default since the Mongo exit; see storage_flags.py).
MONGO_MIRROR = storage_flags.parse_mirror(None)

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
    return await lookup_orgs_for_user(user_id) or []


async def lookup_orgs_for_user(user_id: str) -> Optional[List[Dict[str, Any]]]:
    """Like ``list_orgs_for_user``, but ``None`` when Supabase did not
    answer (no service role, transport error, non-200): only a list —
    possibly empty — says which organizations the user belongs to."""
    if not SUPABASE_SERVICE_ROLE_KEY or not user_id:
        return None
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
    return _answered_rows(resp)


def _answered_rows(resp: Optional[httpx.Response]) -> Optional[List[Dict[str, Any]]]:
    """The rows of a 200 PostgREST read, or ``None`` when there was no
    real answer (no request, transport error, non-200, not a JSON list)."""
    if resp is None or resp.status_code != 200:
        return None
    try:
        rows = resp.json()
    except Exception:  # noqa: BLE001 — empty or non-JSON body
        return None
    if rows is None:
        return []
    return rows if isinstance(rows, list) else None


class OrgMemberLookup(NamedTuple):
    """Outcome of an ``org_members`` lookup.

    ``answered`` is True only when Supabase answered (service role, HTTP
    200); then ``row`` is None exactly when the person is NOT a member —
    revoked or deleted in Quantro OS (the People OS mirror removes the
    org_members row), or never joined. ``answered`` False means nobody
    knows (no service role, transport error, non-200)."""

    answered: bool
    row: Optional[Dict[str, Any]]


async def lookup_org_member(org_id: str, user_id: str) -> OrgMemberLookup:
    """The ``org_members`` row of ``(org_id, user_id)``, read with the
    service role (RBAC checks have no user JWT for a target user).

    Without a row, ``organizations.owner_id`` still makes the person the
    owner (org_role_for rule 1; the mirror never writes the owner's row,
    which comes from organization creation), so an owner whose row is
    missing is never shut out of their own workspace."""
    if not org_id or not user_id or not SUPABASE_SERVICE_ROLE_KEY:
        return OrgMemberLookup(False, None)
    resp = await _request(
        "GET",
        "/rest/v1/org_members",
        access_token=None,
        use_service=True,
        params={
            "org_id": f"eq.{org_id}",
            "user_id": f"eq.{user_id}",
            "select": "id,org_id,user_id,role,joined_at",
            "limit": "1",
        },
    )
    rows = _answered_rows(resp)
    if rows is None:
        if resp is not None:
            logger.warning("supabase_admin.lookup_org_member status=%s", resp.status_code)
        return OrgMemberLookup(False, None)
    if rows and isinstance(rows[0], dict):
        return OrgMemberLookup(True, rows[0])
    owner_resp = await _request(
        "GET",
        "/rest/v1/organizations",
        access_token=None,
        use_service=True,
        params={"id": f"eq.{org_id}", "select": "owner_id", "limit": "1"},
    )
    orgs = _answered_rows(owner_resp)
    if orgs is None:
        if owner_resp is not None:
            logger.warning("supabase_admin.lookup_org_member owner status=%s", owner_resp.status_code)
        return OrgMemberLookup(False, None)
    owner_id = (orgs[0] or {}).get("owner_id") if orgs and isinstance(orgs[0], dict) else None
    if owner_id and str(owner_id) == str(user_id):
        return OrgMemberLookup(True, {"org_id": org_id, "user_id": user_id, "role": "owner", "joined_at": None})
    return OrgMemberLookup(True, None)


async def get_org_member(org_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Return one ``org_members`` row for ``(org_id, user_id)``, or None
    when there is none OR the read failed. Membership decisions must use
    ``lookup_org_member``, which tells the two apart."""
    return (await lookup_org_member(org_id, user_id)).row


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


async def organization_name(org_id: str, access_token: Optional[str] = None) -> Optional[str]:
    """The ``organizations.name`` of ``org_id``: read with the caller's JWT
    when given (RLS), else — or when that read shows nothing — with the
    service role. Only used to name the Flow workspace of a Quantro OS
    organization the caller belongs to. None when unknown."""
    if not org_id:
        return None
    params = {"id": f"eq.{org_id}", "select": "name", "limit": "1"}
    attempts = []
    if access_token:
        attempts.append(False)
    if SUPABASE_SERVICE_ROLE_KEY:
        attempts.append(True)
    for use_service in attempts:
        resp = await _request(
            "GET", "/rest/v1/organizations",
            access_token=None if use_service else access_token,
            use_service=use_service, params=params,
        )
        rows = _answered_rows(resp) or []
        name = str((rows[0] or {}).get("name") or "").strip() if rows and isinstance(rows[0], dict) else ""
        if name:
            return name[:80]
    return None


# ── People OS (Quantro OS membership) — caller's JWT only ─────────────
# Flow never writes org_members / invitations / team_members itself (O12).
# Each change below is a People OS RPC (konta migrations 20261012000000,
# 20261101100000, 20261101180000) run AS THE CALLER: Quantro OS decides
# whether they may do it (People keys, grantable roles, seats, plan) and
# audits it. There is deliberately no service-role variant.

# Columns of a team_members row Flow needs; RLS returns a row only when it
# is the caller's own or they hold people.view in its organization.
_TEAM_MEMBER_COLUMNS = "id,role,status,auth_user_id,organization_id,invited_by_org_id,created_at"
_TEAM_INVITE_COLUMNS = (
    "id,email,full_name,role,status,auth_user_id,invite_token,invite_expires_at,"
    "invited_by,created_at,organization_id,invited_by_org_id"
)


class RpcResult(NamedTuple):
    """Outcome of a People OS call. ``status`` 0 = not sent / no answer.

    ``code`` is PostgREST's error code (a SQLSTATE such as ``42501``,
    ``QSEAT``, ``QPLAN``, or ``PGRST202`` for a missing function) and
    ``message`` / ``hint`` its text. They are for classification and
    must never be returned to Flow's clients verbatim.
    """

    ok: bool
    status: int
    data: Any
    code: Optional[str] = None
    message: Optional[str] = None
    hint: Optional[str] = None


def _rpc_result(resp: Optional[httpx.Response]) -> RpcResult:
    if resp is None:
        return RpcResult(False, 0, None, "no_response")
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 — empty or non-JSON body
        body = None
    if resp.status_code < 400:
        return RpcResult(True, resp.status_code, body)
    err = body if isinstance(body, dict) else {}
    return RpcResult(
        False,
        resp.status_code,
        None,
        str(err.get("code") or "") or None,
        str(err.get("message") or "") or None,
        str(err.get("hint") or "") or None,
    )


async def call_rpc(fn: str, args: Dict[str, Any], access_token: Optional[str]) -> RpcResult:
    """POST /rest/v1/rpc/<fn> with the caller's JWT (never the service role)."""
    if not access_token:
        return RpcResult(False, 0, None, "auth_required")
    resp = await _request("POST", f"/rest/v1/rpc/{fn}", access_token=access_token, json=args)
    result = _rpc_result(resp)
    if not result.ok:
        logger.warning("supabase_admin.rpc %s failed: status=%s code=%s", fn, result.status, result.code)
    return result


async def rpc_invite_member(
    *,
    org_id: str,
    email: str,
    role: str,
    access_token: str,
    full_name: Optional[str] = None,
    job_title: Optional[str] = None,
) -> RpcResult:
    """invite_member: a People OS invitation (token + 7-day expiry made by
    the server). company_access lists the home organization first, as the
    Quantro OS app sends it (src/lib/peopleInvites.ts inviteCompanyAccess)."""
    return await call_rpc("invite_member", {
        "p_org_id": org_id,
        "p_email": email.strip().lower(),
        "p_role": role,
        "p_full_name": (full_name or "").strip() or None,
        "p_job_title": (job_title or "").strip() or None,
        "p_department_id": None,
        "p_company_access": [org_id],
    }, access_token)


async def rpc_invitation_preview(token: str, access_token: str) -> RpcResult:
    """get_invitation_preview: {status, kind, organization_name, role,
    email_hint, expires_at} for one token (no ids, rate-limited per IP)."""
    return await call_rpc("get_invitation_preview", {"p_token": token}, access_token)


async def rpc_accept_team_invite(token: str, access_token: str, full_name: Optional[str] = None) -> RpcResult:
    """accept_team_invite: claim a People OS invitation as the invitee
    (their confirmed email must match). Answers invite_result json."""
    return await call_rpc("accept_team_invite", {"p_token": token, "p_full_name": full_name}, access_token)


async def rpc_accept_invitation(token: str, access_token: str) -> RpcResult:
    """accept_invitation(p_token uuid): a legacy ``invitations`` row. The
    argument NAME picks this overload (``_token`` is the People OS one)."""
    return await call_rpc("accept_invitation", {"p_token": token}, access_token)


async def rpc_change_member_role(member_id: str, role: str, access_token: str) -> RpcResult:
    return await call_rpc("change_member_role", {"p_member_id": member_id, "p_role": role}, access_token)


async def rpc_revoke_member_access(member_id: str, access_token: str) -> RpcResult:
    return await call_rpc("revoke_member_access", {"p_member_id": member_id}, access_token)


async def rpc_delete_member(member_id: str, access_token: str) -> RpcResult:
    return await call_rpc("delete_member", {"p_member_id": member_id}, access_token)


def _org_filter(org_id: str) -> str:
    # coalesce(organization_id, invited_by_org_id) = org: the two columns
    # never disagree (team_members_org_columns_agree), so either matching
    # is the same row set.
    return f"(organization_id.eq.{org_id},invited_by_org_id.eq.{org_id})"


async def find_team_members(org_id: str, user_id: str, access_token: str) -> Optional[List[Dict[str, Any]]]:
    """The People OS rows of ``user_id`` in ``org_id`` that the caller can
    see (their own, or every row with people.view). ``None`` when the read
    itself failed (not configured, refused, no answer)."""
    if not (org_id and user_id and access_token):
        return None
    resp = await _request(
        "GET",
        "/rest/v1/team_members",
        access_token=access_token,
        params={
            "auth_user_id": f"eq.{user_id}",
            "or": _org_filter(org_id),
            "select": _TEAM_MEMBER_COLUMNS,
            "order": "created_at.asc",
        },
    )
    if resp is None or resp.status_code != 200:
        if resp is not None:
            logger.warning("supabase_admin.find_team_members status=%s", resp.status_code)
        return None
    rows = resp.json()
    return rows if isinstance(rows, list) else []


async def get_team_member(org_id: str, member_id: str, access_token: str) -> Optional[Dict[str, Any]]:
    """One People OS row of ``org_id`` by id, if the caller can see it."""
    if not (org_id and member_id and access_token):
        return None
    resp = await _request(
        "GET",
        "/rest/v1/team_members",
        access_token=access_token,
        params={
            "id": f"eq.{member_id}",
            "or": _org_filter(org_id),
            "select": _TEAM_MEMBER_COLUMNS,
            "limit": "1",
        },
    )
    if resp is None or resp.status_code != 200:
        return None
    rows = resp.json() or []
    return rows[0] if isinstance(rows, list) and rows else None


async def list_team_invites(org_id: str, access_token: str) -> Optional[List[Dict[str, Any]]]:
    """Pending People OS invitations of ``org_id`` the caller can see
    (people.view). ``None`` when the read failed."""
    if not (org_id and access_token):
        return None
    resp = await _request(
        "GET",
        "/rest/v1/team_members",
        access_token=access_token,
        params={
            "or": _org_filter(org_id),
            "status": "eq.invited",
            "auth_user_id": "is.null",
            "select": _TEAM_INVITE_COLUMNS,
            "order": "created_at.desc",
        },
    )
    if resp is None or resp.status_code != 200:
        if resp is not None:
            logger.warning("supabase_admin.list_team_invites status=%s", resp.status_code)
        return None
    rows = resp.json()
    return rows if isinstance(rows, list) else []


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
    """True when writes to Supabase should fire (SoT or shadow)."""
    return _is_configured()


def is_mongo_mirror_enabled() -> bool:
    """True when identity writes should also hit Mongo collections.

    Always True when Supabase is not configured (Mongo is the only store).
    When Supabase is SoT, defaults to True so rollback stays safe; set
    QUANTRO_MONGO_MIRROR=0 to freeze/deprecate the Mongo mirror.
    """
    if not _is_configured():
        return True
    return MONGO_MIRROR


def is_mongo_identity_primary() -> bool:
    """True when Mongo is still the identity read primary (rollback)."""
    return not is_supabase_primary()


# Convenience: surface a one-shot health check the lifespan uses on boot.
async def health_check() -> Dict[str, Any]:
    if not _is_configured():
        return {"configured": False, "primary": DB_PRIMARY, "mongo_mirror": True}
    out = {
        "configured": True,
        "primary": DB_PRIMARY,
        "mongo_mirror": is_mongo_mirror_enabled(),
        "service_role_available": bool(SUPABASE_SERVICE_ROLE_KEY),
        "default_org_id": DEFAULT_ORG_ID or None,
    }
    return out
