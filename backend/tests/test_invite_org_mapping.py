"""Invite acceptance never maps an unknown org to the "default" workspace.

Same bug class as the activity leak (a tenant-scoped value silently falling
back to DEFAULT_WORKSPACE_ID): invite acceptance once started from
``workspace_id = DEFAULT_WORKSPACE_ID`` and kept it whenever the invitation's
org had no Flow workspace, so any Quantro OS invitation token made its holder
a member of Flow's default workspace with the invitation's role.

Since O12 an invitation is accepted by People OS (accept_team_invite /
accept_invitation, with the invitee's JWT), which binds it to the invitee's
email. Flow then maps the organization the RPC answers to its workspace: the
existing one, a new one (as at login), or "default" only when the org IS the
configured default org. A token People OS does not recognise joins nothing.
"""
from __future__ import annotations

import httpx
import pytest

from fake_postgrest import FakeResponse
from test_activity_workspace import Client, _tenants, app  # noqa: F401  (fixture)
from test_people_os_membership import _accepting, _declare_membership_tables, _preview


@pytest.mark.asyncio
async def test_invite_of_an_org_without_a_flow_workspace_never_joins_default(app, monkeypatch):
    fake, server, RealAsyncClient = app
    await _tenants(server)
    _declare_membership_tables(fake)
    import supabase_admin

    monkeypatch.setattr(supabase_admin, "DEFAULT_ORG_ID", "org-default")
    tokens = {
        "44444444-4444-4444-8444-444444444441": "org-quantro-os-only",
        "44444444-4444-4444-8444-444444444442": "org-default",
    }
    unknown = "44444444-4444-4444-8444-444444444443"

    def preview(args, auth):
        if args["p_token"] in tokens:
            return _preview("team")(args, auth)
        return FakeResponse(200, {"status": "invalid"})

    def accept(args, auth):
        return _accepting(fake, tokens[args["p_token"]], "u-b")(args, auth)

    fake.rpc_handlers["get_invitation_preview"] = preview
    fake.rpc_handlers["accept_team_invite"] = accept

    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=True)
    async with RealAsyncClient(transport=transport, base_url="http://test") as http:
        c = Client(server, http)
        assert (await c.call("u-b", "ws_b", "GET", f"/api/invites/{unknown}")).status_code == 404
        assert (await c.call("u-b", "ws_b", "POST", f"/api/invites/{unknown}/accept")).status_code == 404
        assert "accept_team_invite" not in [fn for fn, _, _ in fake.rpc_calls]

        # A real invitation of an org Flow has no workspace for: the person
        # joined it in Quantro OS, and Flow gives the org its own workspace.
        foreign = await c.call("u-b", "ws_b", "POST", "/api/invites/44444444-4444-4444-8444-444444444441/accept")
        assert foreign.status_code == 200, foreign.text
        ws_id = foreign.json()["workspace_id"]
        assert ws_id and ws_id != "default"
        ws = await server.workspaces_col.find_one({"workspace_id": ws_id})
        assert ws["org_id"] == "org-quantro-os-only"
        assert await server.workspace_members_col.find_one({"workspace_id": "default", "user_id": "u-b"}) is None

        # The configured default org still maps to the default workspace.
        ok = await c.call("u-b", "ws_b", "POST", "/api/invites/44444444-4444-4444-8444-444444444442/accept")
        assert ok.status_code == 200 and ok.json()["workspace_id"] == "default"
