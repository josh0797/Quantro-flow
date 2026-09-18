#!/usr/bin/env python3
"""Phase 2 OAuth secrets unit tests — dual-write / primary flip / state consume.

No live Mongo, Supabase, or real tokens. Uses httpx mocks + fake mongo cols.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _reload_store(**env):
    base = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-test",
        "QUANTRO_SECRETS_PRIMARY": "mongo",
        "QUANTRO_MONGO_MIRROR": "1",
    }
    base.update(env)
    with patch.dict(os.environ, base, clear=False):
        if "provider_secrets_store" in sys.modules:
            del sys.modules["provider_secrets_store"]
        import provider_secrets_store as store
        importlib.reload(store)
        return store


class FakeCursor:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = rows

    def __aiter__(self):
        self._iter = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeMongoCol:
    def __init__(self, rows: Optional[List[Dict[str, Any]]] = None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.ops: List[Dict[str, Any]] = []

    async def find_one(self, filt, projection=None):
        self.ops.append({"op": "find_one", "filt": filt, "projection": projection})
        wid = filt.get("workspace_id")
        for r in self.rows:
            if r.get("workspace_id") == wid:
                if projection:
                    include = {k for k, v in projection.items() if v and k != "_id"}
                    return {k: r.get(k) for k in include}
                return dict(r)
        return None

    async def update_one(self, filt, update, upsert=False):
        self.ops.append({"op": "update_one", "filt": filt, "update": update, "upsert": upsert})
        wid = filt.get("workspace_id")
        fields = (update or {}).get("$set") or {}
        for r in self.rows:
            if r.get("workspace_id") == wid:
                r.update(fields)
                return MagicMock(matched_count=1, modified_count=1)
        if upsert:
            doc = {"workspace_id": wid, **fields}
            self.rows.append(doc)
        return MagicMock(matched_count=0, modified_count=0)

    async def delete_one(self, filt):
        self.ops.append({"op": "delete_one", "filt": filt})
        wid = filt.get("workspace_id")
        before = len(self.rows)
        self.rows = [r for r in self.rows if r.get("workspace_id") != wid]
        return MagicMock(deleted_count=before - len(self.rows))

    async def insert_one(self, doc):
        self.ops.append({"op": "insert_one", "doc": {k: v for k, v in doc.items() if k != "access_token"}})
        self.rows.append(dict(doc))
        return MagicMock(inserted_id="x")

    async def find_one_and_delete(self, filt):
        self.ops.append({"op": "find_one_and_delete", "filt": filt})
        state = filt.get("state")
        for i, r in enumerate(self.rows):
            if r.get("state") == state:
                return self.rows.pop(i)
        return None

    def find(self, filt, projection=None):
        self.ops.append({"op": "find", "filt": filt})
        out = []
        for r in self.rows:
            paused = r.get("auto_sync_paused")
            if filt.get("auto_sync_paused") == {"$ne": True} and paused is True:
                continue
            out.append({"workspace_id": r.get("workspace_id")})
        return FakeCursor(out)


def _mock_resp(status: int, payload: Any, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.text = text or str(payload)
    return resp


class TestSecretsFlags:
    def test_default_primary_is_mongo(self):
        store = _reload_store()
        assert store.SECRETS_PRIMARY == "mongo"
        assert store.is_secrets_supabase_primary() is False
        assert store.is_secrets_dual_write_enabled() is True
        assert store.is_secrets_mongo_write_enabled() is True

    def test_flip_to_supabase_primary(self):
        store = _reload_store(QUANTRO_SECRETS_PRIMARY="supabase", QUANTRO_MONGO_MIRROR="1")
        assert store.is_secrets_supabase_primary() is True
        assert store.is_secrets_mongo_write_enabled() is True

    def test_supabase_primary_mirror_off_skips_mongo_writes(self):
        store = _reload_store(QUANTRO_SECRETS_PRIMARY="supabase", QUANTRO_MONGO_MIRROR="0")
        assert store.is_secrets_supabase_primary() is True
        assert store.is_secrets_mongo_write_enabled() is False

    def test_health(self):
        store = _reload_store()
        h = store.secrets_health()
        assert h["secrets_primary"] == "mongo"
        assert h["dual_write"] is True


class TestDualWriteConnection:
    def setup_method(self):
        self.store = _reload_store(QUANTRO_SECRETS_PRIMARY="mongo")
        self.col = FakeMongoCol()
        self.http_calls: List[Dict[str, Any]] = []

    def _patch_http(self, handler):
        async def _request(method, url, headers=None, json=None, params=None):
            self.http_calls.append({
                "method": method, "url": url, "json": json, "params": params,
            })
            return handler(method, url, json, params)

        return patch("httpx.AsyncClient.request", new=AsyncMock(side_effect=_request))

    def test_upsert_writes_mongo_and_supabase_ciphertext_keys(self):
        async def _run():
            def handler(method, url, json, params):
                assert "provider_connections" in url
                # Never see plaintext field names in SB payload
                if json:
                    assert "access_token" not in json
                    assert "refresh_token" not in json
                    assert json.get("access_token_enc") == "enc-access"
                    assert json.get("refresh_token_enc") == "enc-refresh"
                return _mock_resp(201, None)

            with self._patch_http(handler):
                # Fake AsyncClient context manager
                mock_client = MagicMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.request = AsyncMock(side_effect=lambda *a, **k: handler(
                    a[0] if a else k.get("method"),
                    a[1] if len(a) > 1 else k.get("url"),
                    k.get("json"),
                    k.get("params"),
                ))
                with patch("httpx.AsyncClient", return_value=mock_client):
                    await self.store.upsert_connection(
                        provider="google",
                        workspace_id="ws1",
                        mongo_col=self.col,
                        fields={
                            "access_token": "enc-access",
                            "refresh_token": "enc-refresh",
                            "account_email": "a@example.com",
                            "connected": True,
                        },
                    )

        asyncio.run(_run())
        assert any(o["op"] == "update_one" for o in self.col.ops)
        assert self.col.rows[0]["access_token"] == "enc-access"

    def test_read_mongo_by_default(self):
        self.col.rows.append({
            "workspace_id": "ws1",
            "access_token": "enc-a",
            "account_email": "a@example.com",
        })

        async def _run():
            return await self.store.get_connection(
                provider="google", workspace_id="ws1", mongo_col=self.col,
            )

        doc = asyncio.run(_run())
        assert doc["account_email"] == "a@example.com"
        assert doc["access_token"] == "enc-a"

    def test_read_supabase_primary_with_mongo_fallback(self):
        store = _reload_store(QUANTRO_SECRETS_PRIMARY="supabase")
        col = FakeMongoCol([{
            "workspace_id": "ws1",
            "access_token": "mongo-enc",
            "account_email": "mongo@example.com",
        }])

        async def _run():
            # First: SB returns a row
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.request = AsyncMock(return_value=_mock_resp(200, [{
                "workspace_id": "ws1",
                "provider": "google",
                "access_token_enc": "sb-enc",
                "refresh_token_enc": "sb-ref",
                "account_email": "sb@example.com",
                "scopes": [],
                "connected": True,
            }]))
            with patch("httpx.AsyncClient", return_value=mock_client):
                return await store.get_connection(
                    provider="google", workspace_id="ws1", mongo_col=col,
                )

        doc = asyncio.run(_run())
        assert doc["account_email"] == "sb@example.com"
        assert doc["access_token"] == "sb-enc"

    def test_read_supabase_primary_falls_back_to_mongo_on_empty(self):
        store = _reload_store(QUANTRO_SECRETS_PRIMARY="supabase")
        col = FakeMongoCol([{
            "workspace_id": "ws1",
            "access_token": "mongo-enc",
            "account_email": "mongo@example.com",
        }])

        async def _run():
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.request = AsyncMock(return_value=_mock_resp(200, []))
            with patch("httpx.AsyncClient", return_value=mock_client):
                return await store.get_connection(
                    provider="google", workspace_id="ws1", mongo_col=col,
                )

        doc = asyncio.run(_run())
        assert doc["account_email"] == "mongo@example.com"

    def test_delete_dual_write(self):
        self.col.rows.append({"workspace_id": "ws1", "access_token": "x"})

        async def _run():
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.request = AsyncMock(return_value=_mock_resp(204, None))
            with patch("httpx.AsyncClient", return_value=mock_client):
                await self.store.delete_connection(
                    provider="microsoft", workspace_id="ws1", mongo_col=self.col,
                )

        asyncio.run(_run())
        assert self.col.rows == []


class TestOAuthState:
    def test_put_and_consume_mongo_primary(self):
        store = _reload_store(QUANTRO_SECRETS_PRIMARY="mongo")
        col = FakeMongoCol()

        async def _run():
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.request = AsyncMock(return_value=_mock_resp(201, None))
            with patch("httpx.AsyncClient", return_value=mock_client):
                await store.put_oauth_state(
                    provider="google",
                    mongo_col=col,
                    state="abc123",
                    user_id="u1",
                    workspace_id="ws1",
                    return_to="/welcome/inbox",
                    redirect_uri="https://api.example/callback",
                )
            # Consume from mongo; also delete SB twin
            mock_client.request = AsyncMock(return_value=_mock_resp(204, None))
            with patch("httpx.AsyncClient", return_value=mock_client):
                return await store.consume_oauth_state(
                    provider="google", mongo_col=col, state="abc123",
                )

        doc = asyncio.run(_run())
        assert doc is not None
        assert doc["workspace_id"] == "ws1"
        assert doc["state"] == "abc123"
        # Consumed from mongo
        assert col.rows == []

    def test_consume_falls_back_to_supabase(self):
        store = _reload_store(QUANTRO_SECRETS_PRIMARY="mongo")
        col = FakeMongoCol()  # empty — mongo miss
        expires = datetime.now(timezone.utc) + timedelta(minutes=5)

        async def _run():
            calls = {"n": 0}

            async def request(method, url, headers=None, json=None, params=None):
                calls["n"] += 1
                if method == "GET":
                    return _mock_resp(200, [{
                        "state": "st",
                        "provider": "microsoft",
                        "user_id": "u",
                        "workspace_id": "ws",
                        "return_to": "/welcome/inbox",
                        "redirect_uri": "https://x/cb",
                        "expires_at": expires.isoformat(),
                    }])
                return _mock_resp(204, None)

            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.request = AsyncMock(side_effect=request)
            with patch("httpx.AsyncClient", return_value=mock_client):
                return await store.consume_oauth_state(
                    provider="microsoft", mongo_col=col, state="st",
                )

        doc = asyncio.run(_run())
        assert doc is not None
        assert doc["workspace_id"] == "ws"
        assert doc["provider"] == "microsoft"

    def test_supabase_primary_consume(self):
        store = _reload_store(QUANTRO_SECRETS_PRIMARY="supabase")
        col = FakeMongoCol([{
            "state": "st", "workspace_id": "mongo-ws", "user_id": "u",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        }])

        async def _run():
            async def request(method, url, headers=None, json=None, params=None):
                if method == "GET":
                    return _mock_resp(200, [{
                        "state": "st",
                        "provider": "google",
                        "workspace_id": "sb-ws",
                        "user_id": "u",
                        "return_to": "/welcome/inbox",
                        "redirect_uri": "https://x/cb",
                        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                    }])
                return _mock_resp(204, None)

            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.request = AsyncMock(side_effect=request)
            with patch("httpx.AsyncClient", return_value=mock_client):
                return await store.consume_oauth_state(
                    provider="google", mongo_col=col, state="st",
                )

        doc = asyncio.run(_run())
        assert doc["workspace_id"] == "sb-ws"
        # Mongo twin cleaned up
        assert col.rows == []


class TestGracefulDegrade:
    def test_missing_table_does_not_raise(self):
        store = _reload_store()
        col = FakeMongoCol()

        async def _run():
            mock_client = MagicMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.request = AsyncMock(return_value=_mock_resp(
                404, None, text='{"code":"PGRST205","message":"Could not find the table"}',
            ))
            with patch("httpx.AsyncClient", return_value=mock_client):
                await store.upsert_connection(
                    provider="google",
                    workspace_id="ws1",
                    mongo_col=col,
                    fields={"access_token": "enc", "connected": True},
                )

        asyncio.run(_run())
        # Mongo still written
        assert len(col.rows) == 1


class TestFieldMapping:
    def test_mongo_to_sb_maps_token_fields(self):
        store = _reload_store()
        payload = store._connection_mongo_to_sb("google", "ws", {
            "access_token": "enc-a",
            "refresh_token": "enc-r",
            "google_user_id": "g-123",
            "scopes": ["a", "b"],
        })
        assert payload["access_token_enc"] == "enc-a"
        assert payload["refresh_token_enc"] == "enc-r"
        assert payload["provider_user_id"] == "g-123"
        assert "access_token" not in payload

    def test_sb_to_mongo_restores_aliases(self):
        store = _reload_store()
        doc = store._connection_sb_to_mongo({
            "workspace_id": "ws",
            "provider": "microsoft",
            "access_token_enc": "x",
            "refresh_token_enc": "y",
            "provider_user_id": "ms-9",
            "scopes": [],
            "connected": True,
        })
        assert doc["access_token"] == "x"
        assert doc["ms_user_id"] == "ms-9"
