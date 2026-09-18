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

    def test_insert_invitation_and_audit(self):
        sa = self.sa

        async def fake_request(method, path, **kwargs):
            self.calls.append({"method": method, "path": path, "kwargs": kwargs})
            if method == "POST" and path.endswith("/invitations"):
                return self._mock_response(201, [{
                    "id": "inv-uuid-1",
                    "token": "tok-abc",
                    "org_id": kwargs["json"]["org_id"],
                    "role": kwargs["json"]["role"],
                }])
            if method == "POST" and path.endswith("/org_audit_logs"):
                return self._mock_response(201, [])
            return self._mock_response(200, [])

        async def _run():
            with patch.object(sa, "_request", side_effect=fake_request):
                invite = await sa.insert_invitation(
                    org_id="1250ff9b-ac04-4370-8fd3-f846f34d1159",
                    role="member",
                    invited_by="user-owner",
                    access_token="jwt",
                    email="new@example.com",
                )
                assert invite and invite["token"] == "tok-abc"
                ok = await sa.insert_audit_log(
                    org_id="1250ff9b-ac04-4370-8fd3-f846f34d1159",
                    action="invitation_created",
                    target_user_id="user-owner",
                    actor_user_id="user-owner",
                    access_token=None,
                    metadata={"invite_id": invite["id"]},
                )
                assert ok is True

        asyncio.run(_run())
        paths = [c["path"] for c in self.calls]
        assert "/rest/v1/invitations" in paths
        assert "/rest/v1/org_audit_logs" in paths

    def test_role_change_and_get_member(self):
        sa = self.sa

        async def fake_request(method, path, **kwargs):
            self.calls.append({"method": method, "path": path, "params": kwargs.get("params")})
            if method == "GET" and path.endswith("/org_members"):
                return self._mock_response(200, [{
                    "id": "m1",
                    "org_id": "1250ff9b-ac04-4370-8fd3-f846f34d1159",
                    "user_id": "user-target",
                    "role": "member",
                    "joined_at": "2026-01-01T00:00:00Z",
                }])
            if method == "PATCH" and path.endswith("/org_members"):
                return self._mock_response(204, None)
            if method == "POST" and path.endswith("/org_audit_logs"):
                return self._mock_response(201, [])
            return self._mock_response(200, [])

        async def _run():
            with patch.object(sa, "_request", side_effect=fake_request):
                member = await sa.get_org_member(
                    "1250ff9b-ac04-4370-8fd3-f846f34d1159", "user-target"
                )
                assert member is not None
                assert member["role"] == "member"
                # No Mongo document required — membership comes from Supabase.
                ok = await sa.update_member_role(
                    org_id="1250ff9b-ac04-4370-8fd3-f846f34d1159",
                    member_user_id="user-target",
                    new_role="leader",
                    access_token="jwt",
                )
                assert ok is True
                await sa.insert_audit_log(
                    org_id="1250ff9b-ac04-4370-8fd3-f846f34d1159",
                    action="role_changed",
                    target_user_id="user-target",
                    actor_user_id="user-owner",
                    access_token=None,
                    old_role="member",
                    new_role="leader",
                )

        asyncio.run(_run())
        assert any(c["method"] == "PATCH" for c in self.calls)

    def test_accept_path_insert_org_member_without_mongo(self):
        sa = self.sa

        async def fake_request(method, path, **kwargs):
            self.calls.append({"method": method, "path": path, "json": kwargs.get("json")})
            if method == "GET" and "invitations" in path:
                return self._mock_response(200, [{
                    "id": "inv-1",
                    "org_id": "1250ff9b-ac04-4370-8fd3-f846f34d1159",
                    "token": "join-tok",
                    "role": "member",
                    "accepted": False,
                    "expires_at": "2099-01-01T00:00:00Z",
                }])
            if method == "POST" and path.endswith("/org_members"):
                return self._mock_response(201, [{
                    "org_id": kwargs["json"]["org_id"],
                    "user_id": kwargs["json"]["user_id"],
                    "role": kwargs["json"]["role"],
                }])
            if method == "PATCH" and path.endswith("/invitations"):
                return self._mock_response(204, None)
            return self._mock_response(200, [])

        async def _run():
            with patch.object(sa, "_request", side_effect=fake_request):
                inv = await sa.get_invitation_by_token("join-tok", access_token=None)
                assert inv and inv["token"] == "join-tok"
                member = await sa.insert_org_member(
                    org_id=inv["org_id"],
                    user_id="user-newbie",
                    role=inv["role"],
                    access_token=None,
                )
                assert member and member["user_id"] == "user-newbie"
                assert await sa.update_invitation(inv["id"], {"accepted": True}, "")

        asyncio.run(_run())
        assert any(c["path"].endswith("/org_members") and c["method"] == "POST" for c in self.calls)


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
    t2.test_insert_invitation_and_audit()
    t2.setup_method()
    t2.test_role_change_and_get_member()
    t2.setup_method()
    t2.test_accept_path_insert_org_member_without_mongo()
    TestMembershipHelperLogic().test_membership_from_org_members_shape()
    print("ALL Phase 1 identity SoT tests passed")
