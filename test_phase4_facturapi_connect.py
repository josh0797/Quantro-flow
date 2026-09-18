#!/usr/bin/env python3
"""Phase 4 Facturapi Connect dual-write unit tests (no live Supabase)."""
from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _reload_secrets(**env):
    base = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-test",
        "QUANTRO_SECRETS_PRIMARY": "mongo",
        "QUANTRO_MONGO_MIRROR": "1",
        "QUANTRO_INTEGRATIONS_CONFIG_PRIMARY": "mongo",
    }
    base.update(env)
    with patch.dict(os.environ, base, clear=False):
        for mod in ("provider_secrets_store", "connect_store"):
            if mod in sys.modules:
                del sys.modules[mod]
        import provider_secrets_store as secrets_store
        importlib.reload(secrets_store)
        import connect_store
        importlib.reload(connect_store)
        return secrets_store, connect_store


class FakeMongoCol:
    def __init__(self, rows: Optional[List[Dict[str, Any]]] = None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.ops: List[Dict[str, Any]] = []

    async def find_one(self, filt, projection=None):
        self.ops.append({"op": "find_one", "filt": filt})
        for r in self.rows:
            if all(r.get(k) == v for k, v in filt.items()):
                if projection:
                    include = {k for k, v in projection.items() if v and k != "_id"}
                    exclude = {k for k, v in projection.items() if v == 0}
                    if exclude and not include:
                        return {k: val for k, val in r.items() if k not in exclude}
                    return {k: r.get(k) for k in include}
                return dict(r)
        return None

    async def update_one(self, filt, update, upsert=False):
        self.ops.append({"op": "update_one", "filt": filt, "upsert": upsert})
        fields = (update or {}).get("$set") or {}
        for r in self.rows:
            if all(r.get(k) == v for k, v in filt.items()):
                r.update(fields)
                return MagicMock(matched_count=1, modified_count=1)
        if upsert:
            self.rows.append({**filt, **fields})
            return MagicMock(matched_count=0, modified_count=0)
        return MagicMock(matched_count=0, modified_count=0)

    async def delete_one(self, filt):
        self.ops.append({"op": "delete_one", "filt": filt})
        before = len(self.rows)
        self.rows = [r for r in self.rows if not all(r.get(k) == v for k, v in filt.items())]
        return MagicMock(deleted_count=before - len(self.rows))

    async def insert_one(self, doc):
        self.ops.append({"op": "insert_one"})
        self.rows.append(dict(doc))
        return MagicMock(inserted_id="x")

    def find(self, filt, projection=None):
        self.ops.append({"op": "find", "filt": filt})
        matched = [dict(r) for r in self.rows if all(r.get(k) == v for k, v in filt.items())]

        class _C:
            async def to_list(self, n):
                return matched[:n]

        return _C()


def _mock_resp(status: int, payload: Any = None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload if payload is not None else []
    resp.text = text or str(payload)
    return resp


class TestProviderCheckAcceptsFacturapi:
    def test_valid_providers_include_facturapi(self):
        secrets_store, _ = _reload_secrets()
        assert "facturapi" in secrets_store.VALID_PROVIDERS
        assert "google" in secrets_store.VALID_PROVIDERS
        assert "microsoft" in secrets_store.VALID_PROVIDERS

    def test_oauth_providers_exclude_facturapi(self):
        secrets_store, _ = _reload_secrets()
        assert "facturapi" not in secrets_store.OAUTH_PROVIDERS

    def test_upsert_accepts_facturapi(self):
        secrets_store, _ = _reload_secrets()
        col = FakeMongoCol()

        async def run():
            with patch.object(
                secrets_store, "_sb_request", new_callable=AsyncMock,
                return_value=_mock_resp(201),
            ) as sb:
                await secrets_store.upsert_connection(
                    provider="facturapi",
                    workspace_id="ws1",
                    mongo_col=col,
                    fields={
                        "secret_key_encrypted": "enc-cipher",
                        "status": "connected",
                        "connection_id": "c1",
                        "environment": "test",
                    },
                )
                assert sb.await_count >= 1
                payload = sb.await_args.kwargs.get("json") or sb.await_args.args[2] if len(sb.await_args.args) > 2 else None
                # Prefer kwargs json=
                call_kwargs = sb.await_args.kwargs
                body = call_kwargs.get("json")
                assert body is not None
                assert body["provider"] == "facturapi"
                assert body["api_key_enc"] == "enc-cipher"
                assert "secret_key_encrypted" not in body
                assert body.get("connected") is True

        import asyncio
        asyncio.run(run())
        assert any(o["op"] == "update_one" for o in col.ops)


class TestFacturapiDualWrite:
    def setup_method(self):
        self.secrets_store, self.connect_store = _reload_secrets()

    def test_upsert_facturapi_dual_writes(self):
        col = FakeMongoCol()

        async def run():
            with patch.object(
                self.secrets_store, "_sb_request", new_callable=AsyncMock,
                return_value=_mock_resp(201),
            ) as sb:
                await self.connect_store.upsert_facturapi_connection(
                    workspace_id="ws1",
                    mongo_col=col,
                    fields={
                        "secret_key_encrypted": "cipher-x",
                        "status": "connected",
                        "legal_name": "Acme",
                        "webhook_token_encrypted": "tok-enc",
                    },
                )
                assert sb.await_count >= 1
                body = sb.await_args.kwargs["json"]
                assert body["api_key_enc"] == "cipher-x"
                assert body["webhook_token_enc"] == "tok-enc"
                assert body["legal_name"] == "Acme"
                # Never leak mongo field names for secrets into SB payload keys beyond enc columns
                assert "secret_key_encrypted" not in body

        import asyncio
        asyncio.run(run())
        assert col.rows[0]["secret_key_encrypted"] == "cipher-x"

    def test_insert_webhook_dual_write(self):
        col = FakeMongoCol()

        async def run():
            with patch.object(
                self.secrets_store, "_sb_request", new_callable=AsyncMock,
                return_value=_mock_resp(201),
            ) as sb:
                await self.connect_store.insert_webhook_event(
                    provider="facturapi",
                    mongo_col=col,
                    doc={
                        "event_id": "evt_1",
                        "workspace_id": "ws1",
                        "connection_id": "c1",
                        "event_type": "invoice.status_updated",
                        "livemode": False,
                        "signature_valid": True,
                        "received_at": datetime.now(timezone.utc),
                        "payload_summary": {"id": "inv_1"},
                    },
                )
                assert sb.await_count >= 1
                body = sb.await_args.kwargs["json"]
                assert body["provider"] == "facturapi"
                assert body["event_id"] == "evt_1"
                assert body["payload"]["summary"]["id"] == "inv_1"

        import asyncio
        asyncio.run(run())
        assert col.rows[0]["event_id"] == "evt_1"


class TestIntegrationsConfigDualWrite:
    def setup_method(self):
        self.secrets_store, self.connect_store = _reload_secrets()

    def test_update_strips_secrets_and_dual_writes(self):
        col = FakeMongoCol([
            {"workspace_id": "ws1", "provider": "openai", "status": "disconnected", "config": {}},
        ])

        async def run():
            with patch.object(
                self.secrets_store, "_sb_request", new_callable=AsyncMock,
                return_value=_mock_resp(201),
            ) as sb:
                result = await self.connect_store.update_integrations_config(
                    workspace_id="ws1",
                    provider="openai",
                    mongo_col=col,
                    fields={
                        "status": "connected",
                        "config": {"api_key": "sk-should-not-land", "model": "gpt-4"},
                        "updated_at": "2026-09-18T12:00:00Z",
                    },
                )
                assert result.matched_count == 1
                body = sb.await_args.kwargs["json"]
                assert body["status"] == "connected"
                assert "api_key" not in body["config"]
                assert body["config"]["model"] == "gpt-4"

        import asyncio
        asyncio.run(run())
        # Mongo keeps encrypted/local secrets for the UI path
        assert col.rows[0]["config"]["api_key"] == "sk-should-not-land"

    def test_default_primary_mongo(self):
        _, connect_store = _reload_secrets()
        assert connect_store.INTEGRATIONS_CONFIG_PRIMARY == "mongo"
        assert connect_store.is_integrations_supabase_primary() is False


class TestFacturapiAdapterStillPersists:
    """Existing adapter tests stay green; also assert store dual-write hook."""

    def test_connect_calls_upsert_store(self, monkeypatch):
        from cryptography.fernet import Fernet

        monkeypatch.setenv("INTEGRATIONS_ENCRYPTION_KEY", Fernet.generate_key().decode())
        # Ensure backend path + fresh modules
        secrets_store, connect_store = _reload_secrets()

        from integrations.providers import facturapi as facturapi_mod
        importlib.reload(facturapi_mod)

        col = FakeMongoCol()
        wh = FakeMongoCol()
        calls = {"upsert": 0}

        async def fake_upsert(**kwargs):
            calls["upsert"] += 1
            await secrets_store.upsert_connection(
                provider="facturapi",
                workspace_id=kwargs["workspace_id"],
                mongo_col=kwargs["mongo_col"],
                fields=kwargs["fields"],
            )

        monkeypatch.setattr(connect_store, "upsert_facturapi_connection", fake_upsert)
        monkeypatch.setattr(facturapi_mod, "connect_store", connect_store)

        import httpx

        def handler(request: httpx.Request):
            if request.url.path.endswith("/organizations/me"):
                return httpx.Response(200, json={
                    "id": "org_1",
                    "timezone": "America/Mexico_City",
                    "is_production_ready": False,
                    "legal": {"legal_name": "Test SA"},
                })
            if request.url.path.endswith("/webhooks"):
                return httpx.Response(201, json={"id": "wh_1", "secret": "wh_sec_x"})
            raise AssertionError(request.url.path)

        transport = httpx.MockTransport(handler)
        adapter = facturapi_mod.FacturapiAdapter(col, wh, lambda: "https://backend.example.com")

        def _client(secret_key):
            return httpx.AsyncClient(
                base_url="https://www.facturapi.io/v2",
                headers={"Authorization": f"Bearer {secret_key}"},
                transport=transport,
            )

        adapter._client = _client

        import asyncio

        async def run():
            with patch.object(
                secrets_store, "_sb_request", new_callable=AsyncMock,
                return_value=_mock_resp(201),
            ):
                result = await adapter.connect("ws1", {"secret_key": "sk_test_abc"})
                assert result["success"] is True

        asyncio.run(run())
        assert calls["upsert"] >= 1
        assert col.rows and col.rows[0]["status"] == "connected"
