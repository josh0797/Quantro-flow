#!/usr/bin/env python3
"""Phase 1 identity SoT unit tests — Supabase-primary without Mongo member docs."""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import types
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend/ is importable
ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _reload_supabase_admin(**env):
    """Reload supabase_admin with a controlled env (defaults baked at import)."""
    base = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_ANON_KEY": "anon-test",
        "SUPABASE_SERVICE_ROLE_KEY": "service-test",
        "QUANTRO_DB_PRIMARY": "supabase",
        "QUANTRO_MONGO_MIRROR": "0",
        "QUANTRO_DEFAULT_ORG_ID": "1250ff9b-ac04-4370-8fd3-f846f34d1159",
    }
    base.update(env)
    with patch.dict(os.environ, base, clear=False):
        if "supabase_admin" in sys.modules:
            del sys.modules["supabase_admin"]
        import supabase_admin as sa
        importlib.reload(sa)
        return sa


class TestSupabaseAdminFlags:
    def test_default_primary_is_supabase(self):
        sa = _reload_supabase_admin()
        assert sa.DB_PRIMARY == "supabase"
        assert sa.is_supabase_primary() is True
        assert sa.is_mongo_mirror_enabled() is False
        assert sa.is_mongo_identity_primary() is False

    def test_rollback_to_mongo(self):
        sa = _reload_supabase_admin(QUANTRO_DB_PRIMARY="mongo", QUANTRO_MONGO_MIRROR="1")
        assert sa.is_supabase_primary() is False
        assert sa.is_mongo_identity_primary() is True
        assert sa.is_mongo_mirror_enabled() is True

    def test_health_includes_mongo_mirror(self):
        sa = _reload_supabase_admin(QUANTRO_MONGO_MIRROR="1")

        async def _run():
            return await sa.health_check()

        out = asyncio.run(_run())
        assert out["configured"] is True
        assert out["primary"] == "supabase"
        assert out["mongo_mirror"] is True


class TestInviteRoleAuditWithoutMongo:
    """Exercise invite / role / audit helpers with mocked PostgREST — no Mongo."""

    def setup_method(self):
        self.sa = _reload_supabase_admin(QUANTRO_MONGO_MIRROR="0")
        self.calls: List[Dict[str, Any]] = []

    def _mock_response(self, status: int, payload: Any):
        resp = MagicMock()
        resp.status_code = status
        resp.json.return_value = payload
        resp.text = str(payload)
        return resp

    def test_invite_member_rpc_and_audit(self):
        """Invites are People OS's invite_member, called with the caller's JWT (O12)."""
        sa = self.sa

        async def fake_request(method, path, **kwargs):
            self.calls.append({"method": method, "path": path, "kwargs": kwargs})
            if method == "POST" and path == "/rest/v1/rpc/invite_member":
                return self._mock_response(200, {
                    "id": "tm-1",
                    "invite_token": "33333333-3333-4333-8333-333333333333",
                    "role": kwargs["json"]["p_role"],
                })
            if method == "POST" and path.endswith("/org_audit_logs"):
                return self._mock_response(201, [])
            return self._mock_response(200, [])

        async def _run():
            with patch.object(sa, "_request", side_effect=fake_request):
                result = await sa.rpc_invite_member(
                    org_id="1250ff9b-ac04-4370-8fd3-f846f34d1159",
                    role="member",
                    access_token="jwt",
                    email=" New@Example.com ",
                )
                assert result.ok and result.data["invite_token"]
                ok = await sa.insert_audit_log(
                    org_id="1250ff9b-ac04-4370-8fd3-f846f34d1159",
                    action="invitation_created",
                    target_user_id="user-owner",
                    actor_user_id="user-owner",
                    access_token=None,
                    metadata={"invite_id": result.data["id"]},
                )
                assert ok is True

        asyncio.run(_run())
        rpc = next(c for c in self.calls if c["path"] == "/rest/v1/rpc/invite_member")
        assert rpc["kwargs"]["access_token"] == "jwt"
        assert not rpc["kwargs"].get("use_service")
        assert rpc["kwargs"]["json"]["p_email"] == "new@example.com"
        assert "/rest/v1/invitations" not in [c["path"] for c in self.calls]
        assert "/rest/v1/org_audit_logs" in [c["path"] for c in self.calls]

    def test_role_change_rpc_and_get_member(self):
        sa = self.sa

        async def fake_request(method, path, **kwargs):
            self.calls.append({"method": method, "path": path, "kwargs": kwargs})
            if method == "GET" and path.endswith("/org_members"):
                return self._mock_response(200, [{
                    "id": "m1",
                    "org_id": "1250ff9b-ac04-4370-8fd3-f846f34d1159",
                    "user_id": "user-target",
                    "role": "member",
                    "joined_at": "2026-01-01T00:00:00Z",
                }])
            if method == "POST" and path == "/rest/v1/rpc/change_member_role":
                return self._mock_response(200, {"id": kwargs["json"]["p_member_id"], "role": kwargs["json"]["p_role"]})
            return self._mock_response(200, [])

        async def _run():
            with patch.object(sa, "_request", side_effect=fake_request):
                member = await sa.get_org_member(
                    "1250ff9b-ac04-4370-8fd3-f846f34d1159", "user-target"
                )
                assert member is not None
                assert member["role"] == "member"
                # No Mongo document required — membership comes from Supabase.
                result = await sa.rpc_change_member_role("tm-target", "viewer", "jwt")
                assert result.ok and result.data["role"] == "viewer"

        asyncio.run(_run())
        assert not any(c["method"] in ("PATCH", "DELETE") for c in self.calls)
        rpc = next(c for c in self.calls if c["path"] == "/rest/v1/rpc/change_member_role")
        assert rpc["kwargs"]["access_token"] == "jwt" and not rpc["kwargs"].get("use_service")

    def test_accept_path_is_an_rpc_as_the_invitee(self):
        sa = self.sa

        async def fake_request(method, path, **kwargs):
            self.calls.append({"method": method, "path": path, "kwargs": kwargs})
            if path == "/rest/v1/rpc/accept_team_invite":
                return self._mock_response(200, {"success": True, "code": "accepted",
                                                 "organization_id": "1250ff9b-ac04-4370-8fd3-f846f34d1159"})
            if path == "/rest/v1/rpc/accept_invitation":
                return self._mock_response(400, {"code": "QSEAT", "message": "No seat is free", "hint": "seat_required"})
            return self._mock_response(200, [])

        async def _run():
            with patch.object(sa, "_request", side_effect=fake_request):
                team = await sa.rpc_accept_team_invite("join-tok", "invitee-jwt")
                assert team.ok and team.data["code"] == "accepted"
                legacy = await sa.rpc_accept_invitation("join-tok", "invitee-jwt")
                assert not legacy.ok and legacy.code == "QSEAT" and legacy.hint == "seat_required"
                # No JWT, no call: there is no service-role fallback.
                anon = await sa.call_rpc("accept_team_invite", {"p_token": "join-tok"}, None)
                assert not anon.ok and anon.status == 0

        asyncio.run(_run())
        assert [c["path"] for c in self.calls] == ["/rest/v1/rpc/accept_team_invite", "/rest/v1/rpc/accept_invitation"]
        assert all(c["kwargs"]["access_token"] == "invitee-jwt" and not c["kwargs"].get("use_service") for c in self.calls)
        assert self.calls[1]["kwargs"]["json"] == {"p_token": "join-tok"}
        assert not hasattr(sa, "insert_org_member")


class TestMembershipHelperLogic:
    """Pure logic stand-in for _membership_for supabase-primary branch."""

    def test_membership_from_org_members_shape(self):
        sa = _reload_supabase_admin()
        row = {"user_id": "u1", "role": "Leader", "joined_at": "2026-01-01T00:00:00Z"}
        # Normalize like server._normalize_role would for common aliases.
        role = (row.get("role") or "").lower()
        if role == "leader":
            normalized = "leader"
        else:
            normalized = role
        member = {
            "user_id": "u1",
            "workspace_id": "default",
            "role": normalized,
            "source": "supabase",
        }
        assert member["source"] == "supabase"
        assert member["role"] == "leader"
        assert sa.is_supabase_primary()


if __name__ == "__main__":
    # Allow running without pytest installed.
    t = TestSupabaseAdminFlags()
    t.test_default_primary_is_supabase()
    t.test_rollback_to_mongo()
    t.test_health_includes_mongo_mirror()
    t2 = TestInviteRoleAuditWithoutMongo()
    t2.setup_method()
    t2.test_invite_member_rpc_and_audit()
    t2.setup_method()
    t2.test_role_change_rpc_and_get_member()
    t2.setup_method()
    t2.test_accept_path_is_an_rpc_as_the_invitee()
    TestMembershipHelperLogic().test_membership_from_org_members_shape()
    print("ALL Phase 1 identity SoT tests passed")
