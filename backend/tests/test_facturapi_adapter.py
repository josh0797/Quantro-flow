"""
FacturapiAdapter — verified against Facturapi's real OpenAPI spec (see
the module's docstring). These tests mock the transport layer with
httpx.MockTransport so nothing here ever makes a real network call —
per the task spec: "No emitir facturas Live en tests."
"""
import json

import httpx
import pytest

from errors import QuantroError
from integrations.providers.facturapi import FacturapiAdapter, infer_environment


def test_infer_environment_from_key_prefix():
    assert infer_environment("sk_test_abc123") == "test"
    assert infer_environment("sk_live_abc123") == "live"


def test_infer_environment_rejects_unknown_prefix():
    with pytest.raises(QuantroError) as exc:
        infer_environment("not-a-facturapi-key")
    assert exc.value.code == "invalid_credentials"


def _adapter(fake_collection, webhook_events_col, handler, backend_url="https://backend.example.com"):
    transport = httpx.MockTransport(handler)
    adapter = FacturapiAdapter(fake_collection, webhook_events_col, lambda: backend_url)

    # Patch _client to route through the mock transport instead of a
    # real socket, without touching the adapter's production code path.
    def _client(secret_key):
        return httpx.AsyncClient(
            base_url="https://www.facturapi.io/v2",
            headers={"Authorization": f"Bearer {secret_key}"},
            transport=transport,
        )
    adapter._client = _client
    return adapter


async def test_connect_rejects_invalid_key_shape(fake_collection):
    def handler(request):  # pragma: no cover - should never be called
        raise AssertionError("should not reach the network for a malformed key")
    adapter = _adapter(fake_collection, fake_collection, handler)
    with pytest.raises(QuantroError) as exc:
        await adapter.connect("ws1", {"secret_key": "garbage"})
    assert exc.value.code == "invalid_credentials"


async def test_connect_success_persists_encrypted_key_and_registers_webhook(fake_collection):
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url.path)
        if request.url.path.endswith("/organizations/me"):
            return httpx.Response(200, json={
                "id": "org_123", "timezone": "America/Mexico_City", "is_production_ready": True,
                "legal": {"name": "Acme", "legal_name": "Acme SA de CV"},
            })
        if request.url.path.endswith("/webhooks"):
            return httpx.Response(201, json={"id": "wh_123", "secret": "wh_sec_abc"})
        raise AssertionError(f"unexpected path {request.url.path}")

    adapter = _adapter(fake_collection, fake_collection, handler)
    result = await adapter.connect("ws1", {"secret_key": "sk_test_abc123"})

    assert result["success"] is True
    assert result["environment"] == "test"
    assert result["organization_id"] == "org_123"
    assert result["webhook_registered"] is True
    assert any(c.endswith("/organizations/me") for c in calls)
    assert any(c.endswith("/webhooks") for c in calls)

    stored = await fake_collection.find_one({"workspace_id": "ws1"})
    assert stored["secret_key_encrypted"] != "sk_test_abc123"
    assert "sk_test_abc123" not in str(stored)


async def test_connect_invalid_credentials_raises_and_stores_nothing(fake_collection):
    def handler(request: httpx.Request):
        return httpx.Response(401, json={"message": "Invalid API key"})
    adapter = _adapter(fake_collection, fake_collection, handler)
    with pytest.raises(QuantroError) as exc:
        await adapter.connect("ws1", {"secret_key": "sk_test_bad"})
    assert exc.value.code == "invalid_credentials"
    assert await fake_collection.find_one({"workspace_id": "ws1"}) is None


async def test_get_status_reports_disconnected_when_no_connection(fake_collection):
    adapter = _adapter(fake_collection, fake_collection, lambda r: httpx.Response(500))
    status = await adapter.get_status("ws-none")
    assert status.status.value == "disconnected"


async def test_webhook_dedup_by_event_id(fake_collection):
    events_col = fake_collection
    adapter = _adapter(fake_collection, events_col, lambda r: httpx.Response(200, json={}))

    import datetime
    from integrations.secrets import encrypt_secret
    await fake_collection.insert_one({
        "workspace_id": "ws1", "connection_id": "conn-1",
        "webhook_token_encrypted": encrypt_secret("tok-abc"),
        "secret_key_encrypted": encrypt_secret("sk_test_abc"),
    })

    payload = json.dumps({"id": "evt_1", "type": "invoice.status_updated", "livemode": False, "data": {"id": "inv_1", "status": "valid"}}).encode()

    first = await adapter.handle_webhook("conn-1", "tok-abc", payload, signature_header=None)
    assert first["accepted"] is True
    assert first["duplicate"] is False

    second = await adapter.handle_webhook("conn-1", "tok-abc", payload, signature_header=None)
    assert second["accepted"] is True
    assert second["duplicate"] is True


async def test_webhook_rejects_wrong_token(fake_collection):
    from integrations.secrets import encrypt_secret
    adapter = _adapter(fake_collection, fake_collection, lambda r: httpx.Response(200, json={}))
    await fake_collection.insert_one({
        "workspace_id": "ws1", "connection_id": "conn-1",
        "webhook_token_encrypted": encrypt_secret("tok-correct"),
    })
    payload = json.dumps({"id": "evt_2", "type": "invoice.status_updated", "data": {}}).encode()
    result = await adapter.handle_webhook("conn-1", "tok-WRONG", payload, signature_header=None)
    assert result["accepted"] is False
    assert result["reason"] == "invalid_token"
