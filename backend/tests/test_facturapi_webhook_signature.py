"""Facturapi webhook: signing secret requires valid signature."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_invalid_signature_rejects_no_business_processing():
    from integrations.providers import facturapi as mod

    adapter = mod.FacturapiAdapter(MagicMock(), MagicMock(), "https://api.example", log_audit_fn=AsyncMock())
    adapter._load_connection = AsyncMock(return_value={
        "workspace_id": "ws1",
        "webhook_token_encrypted": "enc-token",
        "webhook_signing_secret_encrypted": "enc-sign",
        "secret_key_encrypted": "enc-key",
    })

    with patch.object(mod, "decrypt_secret", side_effect=lambda v: {
        "enc-token": "tok",
        "enc-sign": "sign",
        "enc-key": "sk_test_x",
    }.get(v)):
        # Force validate-signature to fail
        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def post(self, *a, **k):
                r = MagicMock()
                r.status_code = 400
                return r

        adapter._client = lambda key: FakeClient()
        adapter.webhook_events_col = MagicMock()
        adapter.webhook_events_col.find_one = AsyncMock(return_value=None)
        adapter.webhook_events_col.insert_one = AsyncMock()

        body = json.dumps({"id": "evt_1", "type": "invoice.created", "data": {"id": "inv_1"}}).encode()
        result = await adapter.handle_webhook("conn1", "tok", body, "bad-sig")
        assert result["accepted"] is False
        assert result["reason"] == "invalid_signature"
        adapter.webhook_events_col.insert_one.assert_not_called()
        adapter._log_audit.assert_awaited()


@pytest.mark.asyncio
async def test_legacy_without_signing_secret_token_ok_audits_upgrade():
    from integrations.providers import facturapi as mod

    adapter = mod.FacturapiAdapter(MagicMock(), MagicMock(), "https://api.example", log_audit_fn=AsyncMock())
    adapter._load_connection = AsyncMock(return_value={
        "workspace_id": "ws1",
        "webhook_token_encrypted": "enc-token",
        "webhook_signing_secret_encrypted": None,
        "secret_key_encrypted": "enc-key",
    })
    with patch.object(mod, "decrypt_secret", side_effect=lambda v: "tok" if v == "enc-token" else None):
        with patch.object(mod, "connect_store", None):
            adapter.webhook_events_col = MagicMock()
            adapter.webhook_events_col.find_one = AsyncMock(return_value=None)
            adapter.webhook_events_col.insert_one = AsyncMock()
            body = json.dumps({"id": "evt_2", "type": "invoice.created", "data": {"id": "inv_2"}}).encode()
            result = await adapter.handle_webhook("conn1", "tok", body, None)
            assert result["accepted"] is True
            # upgrade audit fired
            calls = [c.args[0] for c in adapter._log_audit.await_args_list]
            assert "facturapi.webhook.legacy_token_only" in calls
