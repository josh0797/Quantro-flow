"""Only a leader or owner can connect, disconnect or pause the workspace
mailbox (launch audit FLOW-7).

The Gmail / Outlook connection is the whole workspace's inbox and
calendar. The legacy /api/integrations/{google,microsoft} routes, the
auto-sync toggle and the incremental-consent routes used to accept any
member, viewers included, while DELETE /api/connect/providers/{provider}
already required leader. They now share that rule; reading the status
stays open to every member.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

import _import_stubs
from storage_helpers import supabase_only

WS = "ws_a"
ROLES = ("viewer", "member", "accountant", "leader", "owner")

GATED = [
    ("GET", "/api/integrations/google/start", {}),
    ("DELETE", "/api/integrations/google/disconnect", {}),
    ("GET", "/api/integrations/microsoft/start", {}),
    ("DELETE", "/api/integrations/microsoft/disconnect", {}),
    ("POST", "/api/integrations/google/auto-sync", {"json": {"paused": True}}),
    ("POST", "/api/integrations/microsoft/auto-sync", {"json": {"paused": False}}),
    ("GET", "/api/connect/providers/google/request-permission", {"params": {"action_id": "google.gmail.send"}}),
    ("GET", "/api/connect/providers/microsoft/request-permission", {"params": {"action_id": "microsoft.mail.send"}}),
]


@pytest.fixture
def app(monkeypatch):
    _import_stubs.install()
    fake = supabase_only(monkeypatch)
    monkeypatch.setenv("MONGO_URL", "mongodb://tripwire.invalid:27017")
    import mongo_legacy
    import server

    def no_connect():
        raise AssertionError("Mongo client requested while every flag says Supabase")

    monkeypatch.setattr(mongo_legacy, "_get_client", no_connect)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", fake.async_client_factory(real_async_client))
    yield server, real_async_client
    server.app.dependency_overrides.clear()


async def _members(server: Any) -> None:
    await server.workspaces_col.insert_one({"workspace_id": WS, "name": "A", "owner_user_id": "u-owner", "claimed": True})
    for role in ROLES:
        await server.workspace_members_col.insert_one({"workspace_id": WS, "user_id": f"u-{role}", "role": role})


async def _call(server: Any, http: httpx.AsyncClient, role: str, method: str, url: str, **kw: Any) -> httpx.Response:
    user = server.User(user_id=f"u-{role}", email=f"{role}@example.com", name=role,
                       current_workspace_id=WS, access_token="test-token")
    server.app.dependency_overrides[server.get_current_user] = lambda: user
    return await http.request(method, url, headers={"X-Workspace-Id": WS, "Authorization": "Bearer t"}, **kw)


@pytest.mark.asyncio
@pytest.mark.parametrize("method,url,kw", GATED)
async def test_below_leader_gets_403_on_mailbox_connect_routes(app, method, url, kw):
    server, RealAsyncClient = app
    await _members(server)
    transport = httpx.ASGITransport(app=server.app)
    async with RealAsyncClient(transport=transport, base_url="http://test") as http:
        for role in ("viewer", "member", "accountant"):
            r = await _call(server, http, role, method, url, **kw)
            assert r.status_code == 403, (role, r.status_code, r.text)
            detail = r.json()["detail"]      # what the frontend reads
            assert detail["error"] == "rbac_forbidden"
            assert detail["required_role"] == "leader"
            assert detail["your_role"] == role


@pytest.mark.asyncio
@pytest.mark.parametrize("method,url,kw", GATED)
async def test_leader_and_owner_pass_the_role_gate(app, method, url, kw):
    server, RealAsyncClient = app
    await _members(server)
    transport = httpx.ASGITransport(app=server.app)
    async with RealAsyncClient(transport=transport, base_url="http://test") as http:
        for role in ("leader", "owner"):
            r = await _call(server, http, role, method, url, **kw)
            # Past the gate the route answers on its own terms (OAuth not
            # configured → 503, nothing connected → 404, disconnect → 200).
            assert r.status_code != 403, (role, r.status_code, r.text)
            assert r.status_code in (200, 404, 503), (role, r.status_code, r.text)


@pytest.mark.asyncio
async def test_status_stays_readable_for_viewers(app):
    server, RealAsyncClient = app
    await _members(server)
    transport = httpx.ASGITransport(app=server.app)
    async with RealAsyncClient(transport=transport, base_url="http://test") as http:
        for url in ("/api/integrations/google/status", "/api/integrations/microsoft/status"):
            r = await _call(server, http, "viewer", "GET", url)
            assert r.status_code == 200, (url, r.text)
            assert r.json()["connected"] is False
