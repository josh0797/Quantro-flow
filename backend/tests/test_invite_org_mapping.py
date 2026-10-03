"""Invite acceptance never maps an unknown org to the "default" workspace.

Same bug class as the activity leak (a tenant-scoped value silently falling
back to DEFAULT_WORKSPACE_ID): ``_resolve_invite_by_token`` started from
``workspace_id = DEFAULT_WORKSPACE_ID`` and kept it whenever the Supabase
invitation's org had no Flow workspace. The shared ``invitations`` table also
holds Quantro OS invitations, so any such token (e.g. one a user minted for
their own Quantro OS org) made its holder a member of Flow's default
workspace with the invitation's role.
"""
from __future__ import annotations

import httpx
import pytest

from test_activity_workspace import Client, _tenants, app  # noqa: F401  (fixture)


@pytest.mark.asyncio
async def test_invite_of_an_org_without_a_flow_workspace_never_joins_default(app, monkeypatch):
    fake, server, RealAsyncClient = app
    await _tenants(server)
    import supabase_admin

    invitations = {
        "tok-foreign": {"id": "inv-1", "org_id": "org-quantro-os-only", "role": "admin", "token": "tok-foreign"},
        "tok-default": {"id": "inv-2", "org_id": "org-default", "role": "member", "token": "tok-default"},
        "tok-null": {"id": "inv-3", "org_id": None, "role": "admin", "token": "tok-null"},
    }

    async def get_invitation_by_token(token, access_token=None):
        return invitations.get(token)

    monkeypatch.setattr(supabase_admin, "get_invitation_by_token", get_invitation_by_token)
    monkeypatch.setattr(supabase_admin, "DEFAULT_ORG_ID", "org-default")

    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=True)
    async with RealAsyncClient(transport=transport, base_url="http://test") as http:
        c = Client(server, http)
        for token in ("tok-foreign", "tok-null"):
            assert (await c.call("u-b", "ws_b", "GET", f"/api/invites/{token}")).status_code == 404
            assert (await c.call("u-b", "ws_b", "POST", f"/api/invites/{token}/accept")).status_code == 404
        assert await server.workspace_members_col.find_one({"workspace_id": "default", "user_id": "u-b"}) is None

        # The configured default org still maps to the default workspace.
        ok = await c.call("u-b", "ws_b", "POST", "/api/invites/tok-default/accept")
        assert ok.status_code == 200 and ok.json()["workspace_id"] == "default"
