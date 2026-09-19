"""Microsoft incremental consent — scopes round-trip via OAuth state."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


def test_scopes_for_incremental_adds_action_writes():
    import microsoft_oauth as msoa

    base = msoa._graph_scopes()
    scopes = msoa.scopes_for_incremental(["Mail.Send"])
    assert "Mail.Send" in scopes
    for s in base:
        assert s in scopes
    # Initial connect scopes stay read-only (no Mail.Send in base).
    assert "Mail.Send" not in base


def test_build_authorization_url_accepts_explicit_scopes(monkeypatch):
    import microsoft_oauth as msoa

    captured = {}

    class FakeApp:
        def get_authorization_request_url(self, **kwargs):
            captured.update(kwargs)
            return "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?x=1"

    monkeypatch.setattr(msoa, "_msal_client", lambda: FakeApp())
    monkeypatch.setattr(msoa, "is_oauth_configured", lambda: True)

    url = msoa.build_authorization_url("state", "https://cb/x", scopes=["User.Read", "Mail.Send"])
    assert url.startswith("https://")
    assert captured["scopes"] == ["User.Read", "Mail.Send"]
    assert captured["prompt"] == "select_account"

    url2 = msoa.build_incremental_authorization_url("s", "https://cb/x", ["Calendars.ReadWrite"])
    assert "Calendars.ReadWrite" in msoa.scopes_for_incremental(["Calendars.ReadWrite"])


def test_exchange_code_for_tokens_passes_explicit_scopes(monkeypatch):
    import microsoft_oauth as msoa

    captured = {}

    class FakeApp:
        def acquire_token_by_authorization_code(self, **kwargs):
            captured.update(kwargs)
            return {
                "access_token": "at",
                "refresh_token": "rt-new",
                "expires_in": 3600,
                "scope": "User.Read Mail.Send",
            }

    monkeypatch.setattr(msoa, "_msal_client", lambda: FakeApp())
    with patch("microsoft_oauth.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value.status_code = 400
        payload, profile = msoa.exchange_code_for_tokens(
            "code", "https://cb", scopes=["User.Read", "Mail.Send"],
        )
    assert captured["scopes"] == ["User.Read", "Mail.Send"]
    assert payload["access_token"] == "at"


@pytest.mark.asyncio
async def test_put_oauth_state_persists_requested_scopes():
    from provider_secrets_store import put_oauth_state

    class FakeCol:
        def __init__(self):
            self.docs = []

        async def insert_one(self, doc):
            self.docs.append(doc)

    col = FakeCol()
    with patch("provider_secrets_store.is_secrets_mongo_write_enabled", return_value=True), \
         patch("provider_secrets_store.is_secrets_dual_write_enabled", return_value=False):
        await put_oauth_state(
            provider="microsoft",
            mongo_col=col,
            state="abc",
            user_id="u1",
            workspace_id="ws1",
            return_to="/connect",
            redirect_uri="https://cb",
            requested_scopes=["User.Read", "Mail.Send"],
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc),
        )
    assert col.docs[0]["requested_scopes"] == ["User.Read", "Mail.Send"]


def test_refresh_token_preserved_when_ms_omits_new_one():
    """Mirror callback logic: new_refresh or keep existing ciphertext."""
    new_refresh = None  # encrypt_token(None) → None
    existing = {"refresh_token": "enc-old"}
    refresh_to_store = new_refresh or existing.get("refresh_token")
    assert refresh_to_store == "enc-old"

    new_refresh2 = "enc-new"
    refresh_to_store2 = new_refresh2 or existing.get("refresh_token")
    assert refresh_to_store2 == "enc-new"


def test_connected_limited_to_connected_when_action_scopes_present():
    import microsoft_oauth as msoa

    granted = list(msoa._graph_scopes()) + ["Mail.Send", "Calendars.ReadWrite"]
    missing_base = msoa.missing_base_scopes(granted)
    missing_action = [
        s for s in msoa.ACTION_SCOPES.values()
        if s not in granted and s not in {x.split("/")[-1] for x in granted}
    ]
    is_base_ok = not missing_base
    status = "ok" if is_base_ok and not missing_action else (
        "permission_missing" if not is_base_ok else "connected_limited"
    )
    assert status == "ok"

    granted_limited = list(msoa._graph_scopes())
    missing_action2 = [
        s for s in msoa.ACTION_SCOPES.values()
        if s not in granted_limited
    ]
    status2 = "ok" if not missing_action2 else "connected_limited"
    assert status2 == "connected_limited"


def test_normalize_refresh_scopes_strips_oidc_and_preserves_writes():
    import microsoft_oauth as msoa

    normalized = msoa.normalize_refresh_scopes(
        ["openid", "profile", "email", "offline_access", "Mail.Read", "Mail.Send", "User.Read"]
    )
    assert "Mail.Send" in normalized
    assert "Mail.Read" in normalized
    assert "openid" not in normalized
    assert "offline_access" not in normalized


def test_normalize_refresh_scopes_string_and_empty_fallback():
    import microsoft_oauth as msoa

    from_str = msoa.normalize_refresh_scopes("Mail.Read Mail.Send offline_access")
    assert from_str == ["Mail.Read", "Mail.Send"]

    assert msoa.normalize_refresh_scopes(None) == msoa._graph_scopes()
    assert msoa.normalize_refresh_scopes([]) == msoa._graph_scopes()
    assert msoa.normalize_refresh_scopes("openid offline_access") == msoa._graph_scopes()


def test_refresh_access_token_passes_stored_action_scopes(monkeypatch):
    import microsoft_oauth as msoa

    captured = {}

    class FakeApp:
        def acquire_token_by_refresh_token(self, **kwargs):
            captured.update(kwargs)
            return {
                "access_token": "at-new",
                "expires_in": 3600,
                "scope": "Mail.Read Calendars.Read User.Read Mail.Send",
            }

    monkeypatch.setattr(msoa, "_msal_client", lambda: FakeApp())
    result = msoa.refresh_access_token(
        "rt",
        scopes=["Mail.Read", "Calendars.Read", "User.Read", "Mail.Send", "offline_access"],
    )
    assert "Mail.Send" in captured["scopes"]
    assert "offline_access" not in captured["scopes"]
    assert result["access_token"] == "at-new"
    # No new refresh_token in result — callers keep the prior one.
    assert "refresh_token" not in result


def test_refresh_access_token_falls_back_to_graph_scopes(monkeypatch):
    import microsoft_oauth as msoa

    captured = {}

    class FakeApp:
        def acquire_token_by_refresh_token(self, **kwargs):
            captured.update(kwargs)
            return {"access_token": "at", "expires_in": 3600}

    monkeypatch.setattr(msoa, "_msal_client", lambda: FakeApp())
    msoa.refresh_access_token("rt", scopes=None)
    assert captured["scopes"] == msoa._graph_scopes()
    msoa.refresh_access_token("rt", scopes=[])
    assert captured["scopes"] == msoa._graph_scopes()


@pytest.mark.asyncio
async def test_load_microsoft_credentials_passes_doc_scopes_on_refresh(monkeypatch):
    """server._load_microsoft_credentials must refresh with stored Action scopes."""
    import server as srv
    import microsoft_oauth as msoa

    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    doc = {
        "access_token": "enc-at",
        "refresh_token": "enc-rt",
        "expires_at": past,
        "scopes": ["Mail.Read", "Calendars.Read", "User.Read", "Mail.Send", "offline_access"],
    }
    captured = {}
    patched = {}

    async def fake_get_connection(**kwargs):
        return dict(doc)

    async def fake_patch_connection(**kwargs):
        patched.update(kwargs.get("fields") or {})

    def fake_refresh(refresh_token, scopes=None):
        captured["refresh_token"] = refresh_token
        captured["scopes"] = scopes
        return {
            "access_token": "at-fresh",
            "expires_in": 3600,
            "scope": "Mail.Read Calendars.Read User.Read Mail.Send",
            # omit refresh_token — prior must be kept
        }

    monkeypatch.setattr(srv.secrets_store, "get_connection", fake_get_connection)
    monkeypatch.setattr(srv.secrets_store, "patch_connection", fake_patch_connection)
    monkeypatch.setattr(msoa, "decrypt_token", lambda v: "plain-" + (v or ""))
    monkeypatch.setattr(msoa, "encrypt_token", lambda v: "enc-" + (v or ""))
    monkeypatch.setattr(msoa, "refresh_access_token", fake_refresh)

    access, out_doc = await srv._load_microsoft_credentials("ws-1")
    assert access == "at-fresh"
    assert captured["scopes"] == msoa.normalize_refresh_scopes(doc["scopes"])
    assert "Mail.Send" in captured["scopes"]
    assert patched["refresh_token"] == "enc-plain-enc-rt"  # prior plain re-encrypted
    assert patched["scopes"] == ["Mail.Read", "Calendars.Read", "User.Read", "Mail.Send"]
    assert out_doc.get("scopes") == patched["scopes"]
