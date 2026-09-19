"""Google/Microsoft adapters must use provider_secrets_store when primary=supabase."""
from __future__ import annotations

import importlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _reload_secrets(**env):
    base = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-test",
        "QUANTRO_SECRETS_PRIMARY": "supabase",
        "QUANTRO_MONGO_MIRROR": "0",
        "GOOGLE_CLIENT_ID": "cid",
        "GOOGLE_CLIENT_SECRET": "sec",
        "GOOGLE_TOKENS_ENCRYPTION_KEY": "x" * 44,  # placeholder; is_oauth may still fail length
    }
    base.update(env)
    with patch.dict(os.environ, base, clear=False):
        for mod in ("provider_secrets_store",):
            if mod in list(__import__("sys").modules):
                del __import__("sys").modules[mod]
        import provider_secrets_store as store
        importlib.reload(store)
        return store


class FakeMongo:
    def __init__(self):
        self.rows = []
        self.find_calls = 0

    async def find_one(self, filt, projection=None):
        self.find_calls += 1
        return None  # Mongo empty


@pytest.mark.asyncio
async def test_google_status_uses_secrets_store_when_sb_has_connection(monkeypatch):
    store = _reload_secrets(QUANTRO_SECRETS_PRIMARY="supabase", QUANTRO_MONGO_MIRROR="0")

    async def fake_get(**kwargs):
        return {
            "workspace_id": "ws1",
            "account_email": "a@b.co",
            "scopes": [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/calendar.readonly",
            ],
            "connected": True,
            "reauthorization_required": False,
        }

    monkeypatch.setattr(store, "get_connection", fake_get)

    from integrations.providers.google import GoogleAdapter
    from integrations.base import ConnectionStatus as CS

    class Goog:
        @staticmethod
        def is_oauth_configured():
            return True

        @staticmethod
        def missing_required_scopes(scopes):
            return []

    mongo = FakeMongo()
    adapter = GoogleAdapter(mongo, Goog, AsyncMock(), AsyncMock(), secrets_store=store)
    status = await adapter.get_status("ws1")
    assert status.status == CS.CONNECTED_LIMITED  # base only → limited
    assert mongo.find_calls == 0  # must not hit empty mongo first when store works


@pytest.mark.asyncio
async def test_google_status_works_with_mirror_disabled(monkeypatch):
    store = _reload_secrets(QUANTRO_SECRETS_PRIMARY="supabase", QUANTRO_MONGO_MIRROR="0")
    assert store.is_secrets_mongo_write_enabled() is False

    async def fake_get(**kwargs):
        return {
            "workspace_id": "ws1",
            "account_email": "a@b.co",
            "scopes": [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/calendar.events",
            ],
        }

    monkeypatch.setattr(store, "get_connection", fake_get)
    from integrations.providers.google import GoogleAdapter
    from integrations.base import ConnectionStatus as CS

    class Goog:
        @staticmethod
        def is_oauth_configured():
            return True

    adapter = GoogleAdapter(FakeMongo(), Goog, AsyncMock(), AsyncMock(), secrets_store=store)
    status = await adapter.get_status("ws1")
    assert status.status == CS.CONNECTED


@pytest.mark.asyncio
async def test_microsoft_base_only_connected_limited(monkeypatch):
    store = _reload_secrets()
    async def fake_get(**kwargs):
        return {
            "workspace_id": "ws1",
            "account_email": "m@b.co",
            "scopes": ["Mail.Read", "Calendars.Read", "User.Read", "offline_access"],
        }
    monkeypatch.setattr(store, "get_connection", fake_get)
    from integrations.providers.microsoft import MicrosoftAdapter
    from integrations.base import ConnectionStatus as CS

    class Msoa:
        @staticmethod
        def is_oauth_configured():
            return True

    adapter = MicrosoftAdapter(FakeMongo(), Msoa, AsyncMock(), AsyncMock(), secrets_store=store)
    status = await adapter.get_status("ws1")
    assert status.status == CS.CONNECTED_LIMITED
    assert "Mail.Send" in status.missing_scopes or "Calendars.ReadWrite" in status.missing_scopes
