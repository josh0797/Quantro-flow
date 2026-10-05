"""Flow manages Quantro OS membership only through the People OS RPCs (O12).

An organization workspace's membership lives in Quantro OS (team_members,
mirrored into the org_members rows Flow reads). Flow must:

* invite with ``invite_member`` and hand out the Quantro OS ``?invite=`` link;
* accept with ``accept_team_invite`` / ``accept_invitation`` as the INVITEE;
* change roles / remove people with ``change_member_role`` /
  ``revoke_member_access`` / ``delete_member`` as the CALLER;
* never write org_members / invitations / team_members itself, never use the
  service role for any of the above, and never transfer ownership;
* translate People OS refusals into stable error codes (no database text).

Flow-only workspaces (no org_id) keep Flow's own invite docs. Everything runs
with Supabase-only flags and a Mongo tripwire (the ``app`` fixture).
"""
from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import pytest

from fake_postgrest import FakeResponse, TableSpec
from test_activity_workspace import Client, _tenants, app  # noqa: F401  (fixture)

BACKEND = Path(__file__).resolve().parents[1]
ORG = "11111111-1111-4111-8111-111111111111"
JWT = "Bearer test-token"          # the caller's token (Client.call)
SERVICE = "Bearer service-test"    # storage_helpers.SB_KEY
TOKEN = "22222222-2222-4222-8222-222222222222"
MEMBERSHIP_TABLES = ("/rest/v1/org_members", "/rest/v1/invitations", "/rest/v1/team_members")


# ── static ──────────────────────────────────────────────────────────────

def _membership_write_calls(source: str) -> List[str]:
    """``_request(<write method>, "/rest/v1/<membership table>", …)`` calls."""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "_request"):
            continue
        if len(node.args) < 2 or not all(isinstance(a, ast.Constant) for a in node.args[:2]):
            continue
        method, path = node.args[0].value, node.args[1].value
        if method in ("POST", "PATCH", "PUT", "DELETE") and str(path).startswith(MEMBERSHIP_TABLES):
            bad.append(f"{method} {path} (line {node.lineno})")
    return bad


def test_flow_has_no_direct_membership_write_path():
    import supabase_admin

    src = (BACKEND / "supabase_admin.py").read_text()
    assert _membership_write_calls(src) == []
    for name in ("insert_org_member", "insert_invitation", "update_invitation", "update_member_role",
                 "delete_member", "get_invitation_by_token"):
        assert not hasattr(supabase_admin, name), name
    # Every RPC goes out with the caller's JWT: the helper cannot reach the service role.
    assert "use_service" not in inspect.getsource(supabase_admin.call_rpc)
    # The guard itself is not vacuous.
    assert _membership_write_calls('_request("POST", "/rest/v1/org_members", json={})') != []
    assert _membership_write_calls('_request("PATCH", "/rest/v1/invitations", json={})') != []
    # No other backend module (nor the operator scripts) talks to the membership tables.
    scripts = sorted((BACKEND.parent / "scripts").glob("*.py"))
    assert scripts, "root scripts/ not found"
    for path in [*BACKEND.rglob("*.py"), *scripts]:
        rel = path.relative_to(BACKEND.parent)
        if rel.parts[:2] in (("backend", "tests"), ("backend", ".venv")) or rel.name == "supabase_admin.py":
            continue
        text = path.read_text()
        assert "/rest/v1/org_members" not in text and "/rest/v1/invitations" not in text, rel
        assert "/rest/v1/team_members" not in text, rel


def test_frontend_translates_every_error_code():
    """backend/people_os.py ERRORS == frontend/src/lib/peopleOsErrors.js
    PEOPLE_OS_ERROR_CODES (the frontend test checks es/en copy for each)."""
    import re

    import people_os

    src = (BACKEND.parent / "frontend" / "src" / "lib" / "peopleOsErrors.js").read_text()
    block = re.search(r"PEOPLE_OS_ERROR_CODES = \[(.*?)\];", src, re.S).group(1)
    assert set(re.findall(r"'([a-z_]+)'", block)) == set(people_os.ERRORS)


def test_invite_link_is_the_quantro_os_app(monkeypatch):
    import people_os

    monkeypatch.delenv("QUANTRO_OS_APP_URL", raising=False)
    assert people_os.invite_url(TOKEN) == f"https://www.quantro.technology/?invite={TOKEN}"
    assert people_os.invite_url(None) is None
    monkeypatch.setenv("QUANTRO_OS_APP_URL", "https://staging.quantro.technology/")
    assert people_os.invite_url("a b") == "https://staging.quantro.technology/?invite=a%20b"
    for bad in ("http://www.quantro.technology", "javascript:alert(1)", "https://evil.example/path"):
        monkeypatch.setenv("QUANTRO_OS_APP_URL", bad)
        assert people_os.quantro_os_app_url() == "https://www.quantro.technology"


# ── dynamic fixtures ────────────────────────────────────────────────────

def _declare_membership_tables(fake) -> None:
    fake.specs["org_members"] = TableSpec(["id", "org_id", "user_id", "role", "joined_at"],
                                          uniques=[("org_id", "user_id")], not_null=["org_id", "user_id", "role"])
    fake.specs["team_members"] = TableSpec(
        ["id", "email", "full_name", "job_title", "role", "status", "auth_user_id", "invite_token",
         "invite_expires_at", "invited_by", "created_at", "organization_id", "invited_by_org_id"],
        not_null=["email", "role", "status"])
    fake.specs["invitations"] = TableSpec(
        ["id", "org_id", "email", "role", "token", "accepted", "expires_at", "created_at", "full_name",
         "job_title", "invited_by"])
    for name in ("org_members", "team_members", "invitations"):
        fake.rows[name] = []


def _tm(member_id: str, user_id: Optional[str], role: str, status: str = "active", **extra: Any) -> Dict[str, Any]:
    return {"id": member_id, "email": f"{member_id}@acme.example", "full_name": None, "job_title": None,
            "role": role, "status": status, "auth_user_id": user_id, "invite_token": None,
            "invite_expires_at": None, "invited_by": "u-owner", "created_at": "2026-10-01T00:00:00+00:00",
            "organization_id": ORG, "invited_by_org_id": ORG, **extra}


async def _org_workspace(server, fake) -> None:
    """Workspace ws_org ↔ Quantro OS org ORG: owner, leader, member."""
    _declare_membership_tables(fake)
    await server.workspaces_col.insert_one({"workspace_id": "ws_org", "name": "Acme", "owner_user_id": "u-owner",
                                            "org_id": ORG, "claimed": True})
    for uid, role in (("u-owner", "owner"), ("u-leader", "leader"), ("u-member", "member")):
        await server.workspace_members_col.insert_one({"workspace_id": "ws_org", "user_id": uid, "role": role})
        fake.rows["org_members"].append({"id": f"om-{uid}", "org_id": ORG, "user_id": uid, "role": role,
                                         "joined_at": "2026-10-01T00:00:00+00:00"})
    fake.rows["team_members"] += [_tm("tm-leader", "u-leader", "leader"), _tm("tm-member", "u-member", "member")]


def _direct_membership_writes(fake) -> List[Any]:
    return [c for c in fake.calls if c[0] in ("POST", "PATCH", "PUT", "DELETE") and c[1] in MEMBERSHIP_TABLES]


def _rpc_auth(fake) -> set:
    return {auth for _, _, auth in fake.rpc_calls}


def _err(code: str, message: str, status: int = 400, hint: Optional[str] = None) -> FakeResponse:
    return FakeResponse(status, {"code": code, "message": message, "hint": hint, "details": None})


@pytest.fixture
async def org(app):
    fake, server, RealAsyncClient = app
    await _tenants(server)
    await _org_workspace(server, fake)
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=True)
    async with RealAsyncClient(transport=transport, base_url="http://test") as http:
        yield fake, server, Client(server, http)


# ── invite ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invite_goes_through_invite_member_as_the_caller(org):
    fake, server, c = org

    def invite_member(body, auth):
        row = _tm("tm-new", None, body["p_role"], "invited", email=body["p_email"], full_name=body["p_full_name"],
                  invite_token=TOKEN, invite_expires_at="2099-01-08T00:00:00+00:00")
        fake.rows["team_members"].append(row)
        return FakeResponse(200, row)

    fake.rpc_handlers["invite_member"] = invite_member
    resp = await c.call("u-leader", "ws_org", "POST", "/api/workspaces/ws_org/invites",
                        json={"role": "member", "email": "  New.Person@Acme.example ", "full_name": "New Person",
                              "max_uses": 9, "expires_in_days": 30})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["url"] == f"https://www.quantro.technology/?invite={TOKEN}"
    assert body["source"] == "people_os" and body["max_uses"] == 1 and body["invite_id"] == "tm-new"
    assert body["expires_at"] == "2099-01-08T00:00:00+00:00"   # the server's 7 days, not the 30 asked

    (fn, args, auth), = fake.rpc_calls
    assert fn == "invite_member" and auth == JWT
    assert args == {"p_org_id": ORG, "p_email": "new.person@acme.example", "p_role": "member",
                    "p_full_name": "New Person", "p_job_title": None, "p_department_id": None,
                    "p_company_access": [ORG]}
    assert _direct_membership_writes(fake) == []
    # Flow's own record never stores the Quantro OS token.
    doc = await server.workspace_invites_col.find_one({"workspace_id": "ws_org", "invite_id": "tm-new"})
    assert doc and doc["token"] is None and doc["people_os_member_id"] == "tm-new"

    # The list reads the pending People OS rows with the caller's JWT.
    listed = await c.call("u-leader", "ws_org", "GET", "/api/workspaces/ws_org/invites")
    assert listed.status_code == 200
    (row,) = [i for i in listed.json()["invites"] if i["invite_id"] == "tm-new"]
    assert row["url"] == body["url"] and row["email"] == "new.person@acme.example" and row["revocable"] is True
    assert all(auth == JWT for m, route, auth in fake.auth_log if route == "/rest/v1/team_members")


@pytest.mark.asyncio
async def test_invite_needs_an_email_and_never_an_owner(org):
    fake, _, c = org
    no_email = await c.call("u-owner", "ws_org", "POST", "/api/workspaces/ws_org/invites", json={"role": "member"})
    assert no_email.status_code == 422 and no_email.json()["detail"]["error"] == "email_required"
    owner = await c.call("u-owner", "ws_org", "POST", "/api/workspaces/ws_org/invites",
                         json={"role": "owner", "email": "x@acme.example"})
    assert owner.status_code == 409 and owner.json()["detail"]["error"] == "ownership_transfer_disabled"
    assert fake.rpc_calls == []


@pytest.mark.parametrize("answer, status, error, permission", [
    (_err("QSEAT", "No seat is free (3 of 3 used).", hint="seat_required"), 409, "seat_required", None),
    (_err("QPLAN", "This plan does not include inviting people.", hint="plan_required"), 402, "plan_required", None),
    (_err("42501", "This needs the people.invite permission; ask the organization owner.", 403),
     403, "permission_required", "people.invite"),
    (_err("42501", "Only the organization owner can grant the leader and accountant roles, or a role with "
                   "permissions you do not have.", 403), 403, "role_not_grantable", None),
    (_err("23505", "This person already has an invitation or access in this organization.", 409),
     409, "duplicate_invite", None),
    (_err("22023", "Enter a valid email address."), 422, "invalid_email", None),
    (_err("PGRST202", "Could not find the function public.invite_member", 404), 503, "people_os_unavailable", None),
    (FakeResponse(500, {"message": "boom"}), 503, "people_os_unavailable", None),
])
@pytest.mark.asyncio
async def test_people_os_refusals_become_stable_error_codes(org, answer, status, error, permission):
    fake, _, c = org
    fake.rpc_handlers["invite_member"] = lambda body, auth: answer
    resp = await c.call("u-leader", "ws_org", "POST", "/api/workspaces/ws_org/invites",
                        json={"role": "member", "email": "x@acme.example"})
    assert resp.status_code == status
    detail = resp.json()["detail"]
    assert detail["error"] == error and detail.get("permission") == permission
    import people_os
    assert detail["message"] == people_os.ERRORS[error][1]   # Flow's own text, never the database's


# ── role change / removal ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_role_change_calls_change_member_role_with_the_member_id(org):
    fake, server, c = org
    fake.rpc_handlers["change_member_role"] = lambda body, auth: FakeResponse(
        200, _tm(body["p_member_id"], "u-member", body["p_role"]))
    resp = await c.call("u-owner", "ws_org", "PATCH", "/api/workspaces/ws_org/members/u-member", json={"role": "viewer"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"success": True, "user_id": "u-member", "role": "viewer", "source": "people_os"}
    assert fake.rpc_calls == [("change_member_role", {"p_member_id": "tm-member", "p_role": "viewer"}, JWT)]
    assert _direct_membership_writes(fake) == []
    lookups = [a for m, r, a in fake.auth_log if r == "/rest/v1/team_members"]
    assert lookups and set(lookups) == {JWT}
    cached = await server.workspace_members_col.find_one({"workspace_id": "ws_org", "user_id": "u-member"})
    assert cached["role"] == "viewer"


@pytest.mark.asyncio
async def test_a_leader_refused_by_people_os_gets_the_reason(org):
    fake, server, c = org
    fake.rpc_handlers["change_member_role"] = lambda body, auth: _err(
        "42501", "Only the organization owner can manage a leader, an accountant, or someone whose role has "
                 "permissions you do not have.", 403)
    resp = await c.call("u-leader", "ws_org", "PATCH", "/api/workspaces/ws_org/members/u-member", json={"role": "viewer"})
    assert resp.status_code == 403 and resp.json()["detail"]["error"] == "owner_managed"
    cached = await server.workspace_members_col.find_one({"workspace_id": "ws_org", "user_id": "u-member"})
    assert cached["role"] == "member"   # nothing changed locally either


@pytest.mark.asyncio
async def test_ownership_never_changes_in_flow(org):
    fake, _, c = org
    for ws, target in (("ws_org", "u-leader"), ("ws_a", "u-a")):
        resp = await c.call("u-owner" if ws == "ws_org" else "u-a", ws, "PATCH",
                            f"/api/workspaces/{ws}/members/{target}", json={"role": "owner"})
        assert resp.status_code == 409 and resp.json()["detail"]["error"] == "ownership_transfer_disabled"
    demote = await c.call("u-leader", "ws_org", "PATCH", "/api/workspaces/ws_org/members/u-owner", json={"role": "member"})
    assert demote.status_code == 409 and demote.json()["detail"]["error"] == "owner_change_disabled"
    remove = await c.call("u-leader", "ws_org", "DELETE", "/api/workspaces/ws_org/members/u-owner")
    assert remove.status_code == 409 and remove.json()["detail"]["error"] == "owner_change_disabled"
    assert fake.rpc_calls == [] and _direct_membership_writes(fake) == []


@pytest.mark.asyncio
async def test_self_changes_and_unknown_people_are_refused_before_people_os(org):
    fake, _, c = org
    own = await c.call("u-leader", "ws_org", "PATCH", "/api/workspaces/ws_org/members/u-leader", json={"role": "member"})
    assert own.status_code == 409 and own.json()["detail"]["error"] == "self_change"
    leave = await c.call("u-member", "ws_org", "DELETE", "/api/workspaces/ws_org/members/u-member")
    assert leave.status_code == 409 and leave.json()["detail"]["error"] == "self_leave_unavailable"
    # In org_members (mirror) but no People OS row the caller can see.
    fake.rows["org_members"].append({"id": "om-x", "org_id": ORG, "user_id": "u-ghost", "role": "member"})
    ghost = await c.call("u-owner", "ws_org", "PATCH", "/api/workspaces/ws_org/members/u-ghost", json={"role": "viewer"})
    assert ghost.status_code == 404 and ghost.json()["detail"]["error"] == "member_not_found"
    assert fake.rpc_calls == []


@pytest.mark.asyncio
async def test_remove_revokes_and_permanent_deletes_through_people_os(org):
    fake, server, c = org
    fake.rpc_handlers["revoke_member_access"] = lambda body, auth: FakeResponse(200, _tm(body["p_member_id"], None, "member", "removed"))
    fake.rpc_handlers["delete_member"] = lambda body, auth: FakeResponse(200, {"id": body["p_member_id"], "deleted": True})

    revoked = await c.call("u-owner", "ws_org", "DELETE", "/api/workspaces/ws_org/members/u-member")
    assert revoked.status_code == 200 and revoked.json()["permanent"] is False
    deleted = await c.call("u-owner", "ws_org", "DELETE", "/api/workspaces/ws_org/members/u-leader",
                           params={"permanent": "true"})
    assert deleted.status_code == 200 and deleted.json()["permanent"] is True
    assert fake.rpc_calls == [("revoke_member_access", {"p_member_id": "tm-member"}, JWT),
                              ("delete_member", {"p_member_id": "tm-leader"}, JWT)]
    assert _direct_membership_writes(fake) == []
    assert await server.workspace_members_col.find_one({"workspace_id": "ws_org", "user_id": "u-member"}) is None

    fake.rpc_handlers["delete_member"] = lambda body, auth: _err(
        "42501", "This needs the people.delete permission; ask the organization owner.", 403)
    fake.rows["team_members"].append(_tm("tm-viewer", "u-viewer", "viewer"))
    fake.rows["org_members"].append({"id": "om-v", "org_id": ORG, "user_id": "u-viewer", "role": "viewer"})
    refused = await c.call("u-leader", "ws_org", "DELETE", "/api/workspaces/ws_org/members/u-viewer",
                           params={"permanent": "true"})
    assert refused.status_code == 403
    assert refused.json()["detail"] == {"error": "permission_required", "permission": "people.delete",
                                        "message": refused.json()["detail"]["message"]}


@pytest.mark.asyncio
async def test_cancel_invite_revokes_the_pending_row_only(org):
    fake, _, c = org
    fake.rows["team_members"].append(_tm("tm-pending", None, "viewer", "invited", invite_token=TOKEN,
                                         invite_expires_at="2099-01-01T00:00:00+00:00"))
    fake.rows["invitations"].append({"id": "inv-legacy", "org_id": ORG, "email": "old@acme.example", "role": "member",
                                     "token": "33333333-3333-4333-8333-333333333333", "accepted": False,
                                     "expires_at": "2099-01-01T00:00:00+00:00", "created_at": "2026-09-01T00:00:00+00:00"})
    fake.rpc_handlers["revoke_member_access"] = lambda body, auth: FakeResponse(200, _tm(body["p_member_id"], None, "viewer", "removed"))

    listed = (await c.call("u-owner", "ws_org", "GET", "/api/workspaces/ws_org/invites")).json()["invites"]
    by_id = {i["invite_id"]: i for i in listed}
    assert by_id["tm-pending"]["revocable"] is True and by_id["tm-pending"]["url"].endswith(TOKEN)
    assert by_id["inv-legacy"]["revocable"] is False and by_id["inv-legacy"]["source"] == "invitations"

    ok = await c.call("u-owner", "ws_org", "DELETE", "/api/workspaces/ws_org/invites/tm-pending")
    assert ok.status_code == 200
    joined = await c.call("u-owner", "ws_org", "DELETE", "/api/workspaces/ws_org/invites/tm-member")
    assert joined.status_code == 409 and joined.json()["detail"]["error"] == "invite_already_accepted"
    legacy = await c.call("u-owner", "ws_org", "DELETE", "/api/workspaces/ws_org/invites/inv-legacy")
    assert legacy.status_code == 409 and legacy.json()["detail"]["error"] == "legacy_invite_read_only"
    assert fake.rpc_calls == [("revoke_member_access", {"p_member_id": "tm-pending"}, JWT)]
    assert _direct_membership_writes(fake) == []


# ── accept ──────────────────────────────────────────────────────────────

def _preview(kind: str = "team", status: str = "valid"):
    body = {"status": status}
    if status == "valid":
        body.update({"kind": kind, "organization_name": "Acme", "role": "member",
                     "email_hint": "u***@example.com", "expires_at": "2099-01-01T00:00:00+00:00"})
    return lambda args, auth: FakeResponse(200, body)


def _accepting(fake, org_id: str, user_id: str, role: str = "member"):
    """An accept RPC that, like Quantro OS, writes the membership (the mirror
    fills org_members) and answers invite_result."""
    def handler(args, auth):
        fake.rows["org_members"].append({"id": f"om-{user_id}-{org_id}", "org_id": org_id, "user_id": user_id,
                                         "role": role, "joined_at": "2026-10-05T00:00:00+00:00"})
        return FakeResponse(200, {"success": True, "code": "accepted", "error": None,
                                  "organization_id": org_id, "role": role})
    return handler


@pytest.mark.asyncio
async def test_accept_claims_the_invite_as_the_invitee(org):
    fake, server, c = org
    fake.rpc_handlers["get_invitation_preview"] = _preview("team")
    fake.rpc_handlers["accept_team_invite"] = _accepting(fake, ORG, "u-new")

    peek = await c.call("u-new", "ws_b", "GET", f"/api/invites/{TOKEN}")
    assert peek.status_code == 200
    assert peek.json()["workspace_name"] == "Acme" and peek.json()["email_hint"] == "u***@example.com"

    resp = await c.call("u-new", "ws_b", "POST", f"/api/invites/{TOKEN}/accept")
    assert resp.status_code == 200, resp.text
    assert resp.json()["workspace_id"] == "ws_org" and resp.json()["role"] == "member"
    assert [(fn, args) for fn, args, _ in fake.rpc_calls] == [
        ("get_invitation_preview", {"p_token": TOKEN}),
        ("get_invitation_preview", {"p_token": TOKEN}),
        ("accept_team_invite", {"p_token": TOKEN, "p_full_name": None}),
    ]
    assert _rpc_auth(fake) == {JWT}
    assert _direct_membership_writes(fake) == []
    cached = await server.workspace_members_col.find_one({"workspace_id": "ws_org", "user_id": "u-new"})
    assert cached and cached["role"] == "member"


@pytest.mark.asyncio
async def test_a_legacy_invitations_row_is_accepted_with_accept_invitation(org):
    fake, _, c = org
    fake.rpc_handlers["get_invitation_preview"] = _preview("org")
    fake.rpc_handlers["accept_invitation"] = _accepting(fake, ORG, "u-new")
    resp = await c.call("u-new", "ws_b", "POST", f"/api/invites/{TOKEN}/accept")
    assert resp.status_code == 200 and resp.json()["workspace_id"] == "ws_org"
    # The argument NAME selects accept_invitation(p_token uuid), never the _token overload.
    assert fake.rpc_calls[-1] == ("accept_invitation", {"p_token": TOKEN}, JWT)


@pytest.mark.parametrize("preview_status, accept_answer, status, error", [
    ("expired", None, 410, "invite_expired"),
    ("used", None, 410, "invite_used"),
    ("invalid", None, 404, "invite_invalid"),
    ("rate_limited", None, 429, "rate_limited"),
    ("valid", FakeResponse(200, {"success": False, "code": "email_mismatch", "error": "Esta invitación fue enviada a otro correo"}),
     403, "email_mismatch"),
    ("valid", FakeResponse(200, {"success": False, "code": "revoked"}), 410, "invite_revoked"),
    ("valid", _err("QSEAT", "No seat is free (2 of 2 used).", hint="seat_required"), 409, "seat_required"),
])
@pytest.mark.asyncio
async def test_accept_refusals(org, preview_status, accept_answer, status, error):
    fake, server, c = org
    fake.rpc_handlers["get_invitation_preview"] = _preview("team", preview_status)
    fake.rpc_handlers["accept_team_invite"] = lambda args, auth: accept_answer
    resp = await c.call("u-new", "ws_b", "POST", f"/api/invites/{TOKEN}/accept")
    assert resp.status_code == status and resp.json()["detail"]["error"] == error
    if preview_status != "valid":
        assert [fn for fn, _, _ in fake.rpc_calls] == ["get_invitation_preview"]
    assert "otro correo" not in resp.text
    assert await server.workspace_members_col.find_one({"workspace_id": "ws_org", "user_id": "u-new"}) is None


# ── Flow-only workspaces keep Flow's own invites ────────────────────────

@pytest.mark.asyncio
async def test_flow_only_workspace_invites_stay_local(org):
    fake, server, c = org
    created = await c.call("u-a", "ws_a", "POST", "/api/workspaces/ws_a/invites", json={"role": "member"})
    assert created.status_code == 200 and created.json()["url"] is None   # no Origin header in tests
    token = created.json()["token"]
    peek = await c.call("u-b", "ws_b", "GET", f"/api/invites/{token}")
    assert peek.status_code == 200 and peek.json()["workspace_id"] == "ws_a"
    joined = await c.call("u-b", "ws_b", "POST", f"/api/invites/{token}/accept")
    assert joined.status_code == 200 and joined.json()["source"] == "local"
    member = await server.workspace_members_col.find_one({"workspace_id": "ws_a", "user_id": "u-b"})
    assert member and member["role"] == "member"
    assert fake.rpc_calls == []
    # A Flow doc of an ORGANIZATION workspace is never accepted locally.
    await server.workspace_invites_col.insert_one({"invite_id": "inv-old", "workspace_id": "ws_org",
                                                   "token": "old-flow-token", "role": "leader", "max_uses": 5})
    fake.rpc_handlers["get_invitation_preview"] = _preview("team", "invalid")
    stale = await c.call("u-b", "ws_b", "POST", "/api/invites/old-flow-token/accept")
    assert stale.status_code == 404
    assert await server.workspace_members_col.find_one({"workspace_id": "ws_org", "user_id": "u-b"}) is None


@pytest.mark.asyncio
async def test_members_list_says_who_manages_the_team(org):
    _, _, c = org
    mapped = (await c.call("u-owner", "ws_org", "GET", "/api/workspaces/ws_org/members")).json()
    assert mapped["people_os"] is True and mapped["people_os_url"] == "https://www.quantro.technology"
    local = (await c.call("u-a", "ws_a", "GET", "/api/workspaces/ws_a/members")).json()
    assert local["people_os"] is False
    assert json.dumps(mapped)   # serializable
