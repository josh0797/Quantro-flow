"""A workspace's OWN OpenAI key ("conectar su propia API"), end to end.

Owner decision (2026-09-30): Quantro Flow genuinely supports a customer's
own OpenAI key. The source of truth is the workspace's integrations_config
row for provider 'openai' (status 'connected' + Fernet-encrypted api_key,
saved by a leader in Settings → Integrations):

  * the key is looked up per workspace (no cross-workspace leak) and
    decrypted server-side only;
  * with an own key, run_ai_request calls OpenAI with THAT key and the
    saved (allowlisted) model, never debits Quantro credits and logs usage
    as 'user_api';
  * key problems (invalid/revoked, no quota, model not available) answer a
    clear ES/EN error pointing to Settings → Integrations — no silent
    fallback to Quantro's key;
  * without an own key the Quantro-credits path is unchanged;
  * "Probar conexión" really calls OpenAI (mocked here) with a timeout;
  * disconnect deletes the ciphertext; a new key replaces the old one.

OpenAI is always mocked (ai_billing._make_openai_client), never called.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import httpx
import openai
import pytest
from fastapi import HTTPException

import _import_stubs
import ai_billing
import connect_store
from integrations import secrets as integration_secrets
from storage_helpers import TripwireMongo, supabase_only

REPO_ROOT = Path(__file__).resolve().parents[2]
USER_ID = "11111111-1111-1111-1111-111111111111"
KEY_A = "sk-proj-AAAAaaaa1111bbbbCCCCdddd2222eeee"
KEY_B = "sk-proj-BBBBzzzz9999yyyyXXXXwwww8888vvvv"
QUANTRO_KEY = "sk-quantro-env-key-000000000000000000"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


# ---------- OpenAI mock ----------------------------------------------
class FakeOpenAI:
    """Stands in for openai.AsyncOpenAI. Records the key/kwargs it was
    built with; ``error`` makes every call raise that exception."""

    instances: List["FakeOpenAI"] = []
    error: Optional[BaseException] = None
    text: str = '{"ok": true}'

    def __init__(self, api_key: str, **kwargs: Any):
        self.api_key = api_key
        self.kwargs = kwargs
        self.create_calls: List[Dict[str, Any]] = []
        self.retrieve_calls: List[str] = []
        self.closed = False
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(retrieve=self._retrieve)
        FakeOpenAI.instances.append(self)

    async def _create(self, **kw: Any):
        self.create_calls.append(kw)
        if FakeOpenAI.error is not None:
            raise FakeOpenAI.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=FakeOpenAI.text))],
            usage=SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=1_000_000),
        )

    async def _retrieve(self, model: str):
        self.retrieve_calls.append(model)
        if FakeOpenAI.error is not None:
            raise FakeOpenAI.error
        return SimpleNamespace(id=model)

    async def close(self):
        self.closed = True


def _status_error(cls, status: int, body: Dict[str, Any]):
    req = httpx.Request("POST", OPENAI_URL)
    return cls(body.get("message", "error"), response=httpx.Response(status, request=req), body=body)


def _auth_error():
    # OpenAI echoes a masked key in the message — it must never reach a user.
    return _status_error(openai.AuthenticationError, 401, {
        "message": f"Incorrect API key provided: {KEY_A[:8]}****{KEY_A[-4:]}",
        "type": "invalid_request_error", "code": "invalid_api_key",
    })


@pytest.fixture
def fake_openai(monkeypatch):
    FakeOpenAI.instances = []
    FakeOpenAI.error = None
    FakeOpenAI.text = '{"ok": true}'
    monkeypatch.setattr(ai_billing, "_make_openai_client", lambda api_key, **kw: FakeOpenAI(api_key, **kw))
    monkeypatch.setenv("OPENAI_API_KEY", QUANTRO_KEY)
    return FakeOpenAI


@pytest.fixture
def billing_spy(monkeypatch):
    """Credit RPC / usage log / profile fetch recorders (no network)."""
    spy: Dict[str, List[Any]] = {"decrement": [], "usage": [], "profile": []}
    profile: Dict[str, Any] = {"id": USER_ID, "plan": "pro", "ai_credits_total": 10,
                               "ai_credits_used": 1, "ai_credits_remaining": 9}

    async def fake_fetch_profile(user_id, access_token):
        spy["profile"].append(user_id)
        return dict(profile)

    async def fake_decrement(user_id, amount, access_token):
        spy["decrement"].append((user_id, amount))

    async def fake_usage(**kw):
        spy["usage"].append(kw)

    monkeypatch.setattr(ai_billing, "fetch_profile", fake_fetch_profile)
    monkeypatch.setattr(ai_billing, "rpc_decrement_credits", fake_decrement)
    monkeypatch.setattr(ai_billing, "insert_credit_usage", fake_usage)
    spy["profile_row"] = profile  # type: ignore[assignment]
    return spy


@pytest.fixture
def store(monkeypatch):
    """Supabase-only integrations_config (fake PostgREST, Mongo tripwire),
    registered as the store ai_billing reads."""
    sb = supabase_only(monkeypatch)
    col = connect_store.IntegrationsConfigCollection(TripwireMongo("integrations_config"))
    monkeypatch.setattr(ai_billing, "_integrations_store", col)
    return sb, col


async def _seed(col, workspace_id: str, *, status: str = "connected", key: Optional[str] = None,
                model: Optional[str] = "gpt-4o", ciphertext: Optional[str] = None) -> None:
    config: Dict[str, Any] = {}
    if key or ciphertext:
        config["api_key"] = ciphertext or integration_secrets.encrypt_secret(key)
    if model is not None:
        config["model"] = model
    await col.insert_one({"integration_id": f"i-{workspace_id}", "workspace_id": workspace_id,
                          "provider": "openai", "category": "ai", "status": status, "config": config})


async def _run(workspace_id: Optional[str], language: str = "es", **kw: Any) -> Dict[str, Any]:
    return await ai_billing.run_ai_request(
        user_id=USER_ID, email="owner@example.com", access_token="user-jwt",
        system_prompt="s", user_prompt="u", language=language, workspace_id=workspace_id, **kw,
    )


# ---------- key lookup ------------------------------------------------
async def test_key_lookup_is_per_workspace_and_decrypted(store):
    sb, col = store
    await _seed(col, "ws_a", key=KEY_A, model="gpt-4o")
    await _seed(col, "ws_b", key=KEY_B, model="gpt-4.1-mini")
    await _seed(col, "ws_off", key=KEY_A, status="disconnected")
    await _seed(col, "ws_nokey", key=None)

    a = await ai_billing.get_user_api_key("ws_a")
    b = await ai_billing.get_user_api_key("ws_b")
    assert (a.api_key, a.model, a.workspace_id) == (KEY_A, "gpt-4o", "ws_a")
    assert (b.api_key, b.model, b.workspace_id) == (KEY_B, "gpt-4.1-mini", "ws_b")
    # Disconnected, keyless, unknown and missing workspaces have no own key.
    for ws in ("ws_off", "ws_nokey", "ws_other", None, ""):
        assert await ai_billing.get_user_api_key(ws) is None
    # Only ciphertext is stored; the plaintext never reaches the table.
    assert KEY_A not in json.dumps(sb.rows["integrations_config"])
    # The dataclass never prints the key.
    assert KEY_A not in repr(a) and KEY_A not in str(a)


@pytest.mark.parametrize("saved,expected", [
    ("gpt-4o", "gpt-4o"),
    ("gpt-4o-mini", "gpt-4o-mini"),
    ("gpt-4.1-mini", "gpt-4.1-mini"),
    ("gpt-4-turbo", ai_billing.OWN_KEY_DEFAULT_MODEL),   # legacy option, not allowlisted
    ("o1-pro", ai_billing.OWN_KEY_DEFAULT_MODEL),
    (None, ai_billing.OWN_KEY_DEFAULT_MODEL),
    ("", ai_billing.OWN_KEY_DEFAULT_MODEL),
])
def test_own_key_model_allowlist(saved, expected):
    assert ai_billing.resolve_own_key_model(saved) == expected


async def test_undecryptable_key_is_reported_not_skipped(store, fake_openai, billing_spy, monkeypatch):
    sb, col = store
    # Ciphertext made with another Fernet key (e.g. the encryption key rotated).
    from cryptography.fernet import Fernet
    foreign = Fernet(Fernet.generate_key()).encrypt(KEY_A.encode()).decode()
    await _seed(col, "ws_a", ciphertext=foreign)

    own = await ai_billing.get_user_api_key("ws_a")
    assert own is not None and own.api_key is None

    monkeypatch.setattr(ai_billing, "get_quantro_api_key", lambda: pytest.fail("no fallback to Quantro's key"))
    with pytest.raises(HTTPException) as exc:
        await _run("ws_a")
    assert exc.value.status_code == 402
    assert exc.value.detail["reason"] == "own_key_unreadable"
    assert "Configuración → Integraciones" in exc.value.detail["message"]
    assert fake_openai.instances == []


# ---------- own-key request path ----------------------------------------
async def test_own_key_path_uses_customer_key_and_does_not_debit(store, fake_openai, billing_spy, monkeypatch):
    sb, col = store
    await _seed(col, "ws_a", key=KEY_A, model="gpt-4o")
    monkeypatch.setattr(ai_billing, "get_quantro_api_key", lambda: pytest.fail("Quantro key must not be read"))

    out = await _run("ws_a", model_requested="gpt-4.1-mini")

    (client,) = fake_openai.instances
    assert client.api_key == KEY_A
    assert client.kwargs == {"timeout": ai_billing.OWN_KEY_REQUEST_TIMEOUT_S, "max_retries": 1}
    assert client.create_calls[0]["model"] == "gpt-4o"   # saved model wins over model_requested
    assert client.closed is True
    assert out["source"] == "user_api" and out["model"] == "gpt-4o"
    assert out["text"] == '{"ok": true}'
    # No Quantro credits are touched; usage is logged as the customer's.
    assert billing_spy["decrement"] == []
    assert billing_spy["profile"] == []
    (usage,) = billing_spy["usage"]
    assert usage["source"] == "user_api" and usage["model"] == "gpt-4o"
    assert usage["cost_usd"] == pytest.approx(12.5)       # informational: 1M in + 1M out on gpt-4o


@pytest.mark.parametrize("profile_cols", [
    {"plan": "essential", "ai_credits_total": 0, "ai_credits_used": 0, "ai_credits_remaining": 0},
    {"plan": "pro", "has_coupon": True},
    {"plan": "pro", "ai_credits_total": 10, "ai_credits_used": 10, "ai_credits_remaining": 0},
])
async def test_own_key_unblocks_plans_without_quantro_credits(store, fake_openai, billing_spy, profile_cols):
    sb, col = store
    billing_spy["profile_row"].clear()
    billing_spy["profile_row"].update({"id": USER_ID, **profile_cols})
    await _seed(col, "ws_a", key=KEY_A, model=None)

    out = await _run("ws_a")
    assert out["source"] == "user_api"
    assert fake_openai.instances[0].api_key == KEY_A
    assert fake_openai.instances[0].create_calls[0]["model"] == ai_billing.OWN_KEY_DEFAULT_MODEL
    assert billing_spy["decrement"] == []


async def test_quantro_path_unchanged_without_own_key_and_no_cross_workspace_leak(store, fake_openai, billing_spy):
    sb, col = store
    await _seed(col, "ws_b", key=KEY_B)            # another tenant's key
    await _seed(col, "ws_a", key=None, status="disconnected")

    out = await _run("ws_a")

    (client,) = fake_openai.instances
    assert client.api_key == QUANTRO_KEY
    assert client.kwargs == {}
    assert client.create_calls[0]["model"] == ai_billing.QUANTRO_FORCED_MODEL
    assert out["source"] == "quantro"
    assert billing_spy["profile"] == [USER_ID]
    (decrement,) = billing_spy["decrement"]
    assert decrement[0] == USER_ID and decrement[1] == pytest.approx(0.75)   # gpt-4o-mini 1M+1M
    assert billing_spy["usage"][0]["source"] == "quantro"


async def test_request_without_workspace_id_keeps_the_quantro_path(store, fake_openai, billing_spy):
    sb, col = store
    await _seed(col, "ws_a", key=KEY_A)
    out = await _run(None)
    assert out["source"] == "quantro" and fake_openai.instances[0].api_key == QUANTRO_KEY


async def test_blocked_without_own_key_still_402s_with_integrations_hint(store, fake_openai, billing_spy):
    sb, col = store
    billing_spy["profile_row"].update({"plan": "essential", "ai_credits_total": 0,
                                       "ai_credits_used": 0, "ai_credits_remaining": 0})
    with pytest.raises(HTTPException) as exc:
        await _run("ws_a", language="en")
    assert exc.value.status_code == 402
    assert exc.value.detail["reason"] == "plan_no_credits"
    assert "Settings → Integrations" in exc.value.detail["message"]
    assert fake_openai.instances == []


@pytest.mark.parametrize("error,reason,status", [
    (_auth_error(), "own_key_invalid", 402),
    (_status_error(openai.RateLimitError, 429, {"message": "You exceeded your current quota",
                                                "type": "insufficient_quota", "code": "insufficient_quota"}),
     "own_key_quota_exhausted", 402),
    (_status_error(openai.RateLimitError, 429, {"message": "Rate limit reached", "type": "requests",
                                                "code": "rate_limit_exceeded"}),
     "own_key_rate_limited", 429),
    (_status_error(openai.NotFoundError, 404, {"message": "The model does not exist", "type": "invalid_request_error",
                                               "code": "model_not_found"}),
     "own_key_model_not_allowed", 402),
    (_status_error(openai.PermissionDeniedError, 403, {"message": "Country not supported",
                                                       "code": "unsupported_country_region_territory"}),
     "own_key_forbidden", 402),
    (openai.APITimeoutError(request=httpx.Request("POST", OPENAI_URL)), "own_key_unreachable", 504),
    (openai.APIConnectionError(request=httpx.Request("POST", OPENAI_URL)), "own_key_unreachable", 502),
    (_status_error(openai.InternalServerError, 500, {"message": "boom"}), "own_key_provider_error", 502),
], ids=["invalid", "quota", "rate_limit", "model", "forbidden", "timeout", "connection", "server"])
@pytest.mark.parametrize("language", ["es", "en"])
async def test_own_key_errors_are_clear_and_never_fall_back(store, fake_openai, billing_spy, monkeypatch,
                                                           error, reason, status, language):
    sb, col = store
    await _seed(col, "ws_a", key=KEY_A, model="gpt-4o")
    fake_openai.error = error
    monkeypatch.setattr(ai_billing, "get_quantro_api_key", lambda: pytest.fail("no silent fallback"))

    with pytest.raises(HTTPException) as exc:
        await _run("ws_a", language=language)

    assert exc.value.status_code == status and exc.value.status_code != 401
    detail = exc.value.detail
    assert detail["error"] == "ai_own_key_error"
    assert detail["reason"] == reason
    assert detail["source"] == "user_api"
    assert detail["settings_path"] == "/settings/integrations"
    assert detail["message"] == ai_billing.own_key_message(reason, language, "gpt-4o")
    # Only the customer's key was tried, once; nothing billed or logged as usage.
    assert [c.api_key for c in fake_openai.instances] == [KEY_A]
    assert billing_spy["decrement"] == [] and billing_spy["usage"] == []
    dumped = json.dumps(detail)
    assert KEY_A not in dumped and KEY_A[-4:] not in dumped


@pytest.mark.parametrize("reason", [
    "own_key_invalid", "own_key_quota_exhausted", "own_key_model_not_allowed",
    "own_key_forbidden", "own_key_unreadable",
])
def test_fixable_key_errors_point_to_integrations_in_both_languages(reason):
    assert "Configuración → Integraciones" in ai_billing.own_key_message(reason, "es")
    assert "Settings → Integrations" in ai_billing.own_key_message(reason, "en")


async def test_store_failure_is_503_not_a_fallback(monkeypatch, fake_openai, billing_spy):
    class BrokenStore:
        async def find_one(self, *a, **k):
            raise connect_store.SupabaseStoreError("down", table="integrations_config")

    monkeypatch.setattr(ai_billing, "_integrations_store", BrokenStore())
    with pytest.raises(HTTPException) as exc:
        await _run("ws_a")
    assert exc.value.status_code == 503
    assert exc.value.detail["reason"] == "ai_config_unavailable"
    assert fake_openai.instances == []


# ---------- credits state -------------------------------------------------
def test_legacy_profile_key_flags_are_ignored():
    for flag in ({"has_user_api_key": True}, {"user_openai_api_key_encrypted": "x"}):
        state = ai_billing.resolve_credits_state(profile={"plan": "essential", **flag})
        assert state.source == "blocked" and state.has_own_api_key is False


def test_workspace_own_key_wins_over_quantro_credits_and_coupon():
    rich = ai_billing.resolve_credits_state(profile={"plan": "pro", "ai_credits_remaining": 9, "ai_credits_total": 10},
                                            own_key_active=True)
    assert (rich.source, rich.reason, rich.blocked, rich.has_own_api_key) == (
        "user_api", "workspace_openai_key", False, True)
    assert rich.remaining == pytest.approx(9.0)   # the bag stays for display, untouched
    coupon = ai_billing.resolve_credits_state(profile={"plan": "pro", "has_coupon": True}, own_key_active=True)
    assert coupon.source == "user_api" and coupon.total == 0.0


# ---------- connection check -----------------------------------------------
async def test_check_openai_key_retrieves_the_model_with_a_timeout(fake_openai):
    ok, reason = await ai_billing.check_openai_key(KEY_A, "gpt-4o")
    assert (ok, reason) == (True, None)
    (client,) = fake_openai.instances
    assert client.api_key == KEY_A and client.retrieve_calls == ["gpt-4o"]
    assert client.kwargs == {"timeout": ai_billing.OWN_KEY_TEST_TIMEOUT_S, "max_retries": 0}
    assert client.create_calls == []          # no tokens spent
    assert client.closed is True


async def test_check_openai_key_maps_failures(fake_openai):
    fake_openai.error = _auth_error()
    assert await ai_billing.check_openai_key(KEY_A, "gpt-4o") == (False, "own_key_invalid")
    fake_openai.error = openai.APITimeoutError(request=httpx.Request("GET", OPENAI_URL))
    assert await ai_billing.check_openai_key(KEY_A, "gpt-4o") == (False, "own_key_unreachable")


# ---------- lock-step with the Settings card ----------------------------------
def test_frontend_model_options_match_the_allowlist():
    src = (REPO_ROOT / "frontend/src/lib/billing.js").read_text(encoding="utf-8")
    block = re.search(r"OPENAI_MODEL_OPTIONS\s*=\s*\[(.*?)\];", src, re.S)
    assert block, "OPENAI_MODEL_OPTIONS not found in frontend/src/lib/billing.js"
    values = re.findall(r"value:\s*'([^']+)'", block.group(1))
    assert tuple(sorted(values)) == tuple(sorted(ai_billing.OWN_KEY_ALLOWED_MODELS))
    default = re.search(r"OPENAI_DEFAULT_MODEL\s*=\s*'([^']+)'", src)
    assert default and default.group(1) == ai_billing.OWN_KEY_DEFAULT_MODEL


# ---------- routes: save / test / disconnect / AI endpoint ------------------
WS = "ws_a"
ROLES = ("viewer", "member", "accountant", "leader", "owner")


@pytest.fixture
def app(monkeypatch, fake_openai):
    _import_stubs.install()
    fake = supabase_only(monkeypatch)
    monkeypatch.setenv("MONGO_URL", "mongodb://tripwire.invalid:27017")
    import mongo_legacy
    import server

    def no_connect():
        raise AssertionError("Mongo client requested while every flag says Supabase")

    monkeypatch.setattr(mongo_legacy, "_get_client", no_connect)
    monkeypatch.setattr(ai_billing, "_integrations_store", server.integrations_config_col)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", fake.async_client_factory(real_async_client))
    yield fake, server, real_async_client
    server.app.dependency_overrides.clear()


async def _tenants(server: Any) -> None:
    for ws in (WS, "ws_b"):
        await server.workspaces_col.insert_one({"workspace_id": ws, "name": ws, "owner_user_id": f"u-owner-{ws}", "claimed": True})
        for provider in ("openai", "crm"):
            await server.integrations_config_col.insert_one({
                "integration_id": f"{ws}-{provider}", "workspace_id": ws, "provider": provider,
                "category": "ai" if provider == "openai" else "crm", "status": "disconnected", "config": {},
            })
    for role in ROLES:
        await server.workspace_members_col.insert_one({"workspace_id": WS, "user_id": f"u-{role}", "role": role})
    await server.workspace_members_col.insert_one({"workspace_id": "ws_b", "user_id": "u-b-owner", "role": "owner"})


class Client:
    def __init__(self, server: Any, http: httpx.AsyncClient):
        self.server, self.http = server, http

    async def call(self, user_id: str, method: str, url: str, workspace_id: str = WS, **kw: Any) -> httpx.Response:
        user = self.server.User(user_id=user_id, email=f"{user_id}@example.com", name=user_id,
                                current_workspace_id=workspace_id, access_token="test-token")
        self.server.app.dependency_overrides[self.server.get_current_user] = lambda: user
        return await self.http.request(method, url, headers={"X-Workspace-Id": workspace_id,
                                                             "Authorization": "Bearer t"}, **kw)


def _row(fake, ws: str, provider: str = "openai") -> Dict[str, Any]:
    (row,) = [r for r in fake.rows["integrations_config"] if r["workspace_id"] == ws and r["provider"] == provider]
    return row


async def _client(app):
    fake, server, RealAsyncClient = app
    await _tenants(server)
    return RealAsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test")


async def test_save_test_and_disconnect_roundtrip(app):
    fake, server, _ = app
    async with await _client(app) as http:
        c = Client(server, http)
        r = await c.call("u-leader", "PUT", "/api/integrations/openai",
                         json={"status": "connected", "config": {"api_key": f"  {KEY_A} ", "model": "gpt-4o"}})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "connected"
        assert body["config"] == {"has_api_key": True, "model": "gpt-4o"}
        assert KEY_A not in r.text
        row = _row(fake, WS)
        assert integration_secrets.decrypt_secret(row["secrets_enc"]["api_key"]) == KEY_A   # stripped
        assert "api_key" not in row["config"]
        assert (await ai_billing.get_user_api_key(WS)).api_key == KEY_A
        assert await ai_billing.get_user_api_key("ws_b") is None                         # no leak

        # Probar conexión: a real (mocked) OpenAI call with the saved key.
        r = await c.call("u-owner", "POST", "/api/integrations/openai/test")
        assert r.status_code == 200, r.text
        res = r.json()
        assert (res["success"], res["status"], res["reason"], res["model"]) == (True, "ok", None, "gpt-4o")
        assert "gpt-4o" in res["message"] and KEY_A not in r.text
        assert fake_openai_last().api_key == KEY_A and fake_openai_last().retrieve_calls == ["gpt-4o"]
        listed = (await c.call("u-viewer", "GET", "/api/integrations")).json()
        (openai_row,) = [i for i in listed if i["provider"] == "openai"]
        assert openai_row["last_test_ok"] is True and openai_row["last_test_reason"] is None
        assert openai_row["last_test_at"]
        assert KEY_A not in json.dumps(listed)

        # Disconnect deletes the ciphertext (the UI sends config {}).
        r = await c.call("u-leader", "PUT", "/api/integrations/openai", json={"status": "disconnected", "config": {}})
        assert r.status_code == 200, r.text
        assert r.json()["config"] == {"model": "gpt-4o"}
        row = _row(fake, WS)
        assert row["secrets_enc"] == {} and row["status"] == "disconnected"
        assert row["extra"].get("last_test_ok") is None
        assert await ai_billing.get_user_api_key(WS) is None
        # Reconnecting needs a key again — the old one is gone.
        r = await c.call("u-leader", "PUT", "/api/integrations/openai", json={"status": "connected", "config": {"model": "gpt-4o"}})
        assert r.status_code == 400 and r.json()["detail"]["error"] == "openai_key_required"


def fake_openai_last() -> FakeOpenAI:
    return FakeOpenAI.instances[-1]


async def test_new_key_replaces_old_and_blank_keeps_it(app):
    fake, server, _ = app
    async with await _client(app) as http:
        c = Client(server, http)
        assert (await c.call("u-leader", "PUT", "/api/integrations/openai",
                             json={"status": "connected", "config": {"api_key": KEY_A}})).status_code == 200
        # "Actualizar configuración" with the secret input left empty keeps the key.
        assert (await c.call("u-leader", "PUT", "/api/integrations/openai",
                             json={"status": "connected", "config": {"api_key": "", "model": "gpt-4.1-mini"}})).status_code == 200
        own = await ai_billing.get_user_api_key(WS)
        assert (own.api_key, own.model) == (KEY_A, "gpt-4.1-mini")
        assert (await c.call("u-leader", "PUT", "/api/integrations/openai",
                             json={"status": "connected", "config": {"api_key": KEY_B}})).status_code == 200
        assert (await ai_billing.get_user_api_key(WS)).api_key == KEY_B
        assert KEY_A not in json.dumps(fake.rows)


@pytest.mark.parametrize("config,error", [
    ({"api_key": "not-a-key"}, "invalid_openai_key_format"),
    ({"api_key": "sk-short"}, "invalid_openai_key_format"),
    ({"api_key": KEY_A + " extra"}, "invalid_openai_key_format"),
    ({}, "openai_key_required"),
    ({"api_key": KEY_A, "model": "gpt-4-turbo"}, "model_not_allowed"),
])
async def test_openai_save_validation(app, config, error):
    fake, server, _ = app
    async with await _client(app) as http:
        c = Client(server, http)
        r = await c.call("u-owner", "PUT", "/api/integrations/openai", json={"status": "connected", "config": config})
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert detail["error"] == error and detail["message"] == ai_billing.own_key_message(error, "es")
        assert _row(fake, WS)["secrets_enc"] == {} and _row(fake, WS)["status"] == "disconnected"


async def test_below_leader_cannot_save_or_test_the_key(app):
    fake, server, _ = app
    async with await _client(app) as http:
        c = Client(server, http)
        for role in ("viewer", "member", "accountant"):
            r = await c.call(f"u-{role}", "PUT", "/api/integrations/openai",
                             json={"status": "connected", "config": {"api_key": KEY_A}})
            assert r.status_code == 403, (role, r.text)
            r = await c.call(f"u-{role}", "POST", "/api/integrations/openai/test")
            assert r.status_code == 403, (role, r.text)
        assert _row(fake, WS)["secrets_enc"] == {}


async def test_connection_test_failure_is_reported_and_persisted(app):
    fake, server, _ = app
    async with await _client(app) as http:
        c = Client(server, http)
        # Not connected: no OpenAI call at all.
        r = await c.call("u-leader", "POST", "/api/integrations/openai/test")
        assert r.json()["success"] is False and r.json()["reason"] == "not_connected"
        assert FakeOpenAI.instances == []

        await c.call("u-leader", "PUT", "/api/integrations/openai", json={"status": "connected", "config": {"api_key": KEY_A}})
        FakeOpenAI.error = _auth_error()
        r = await c.call("u-leader", "POST", "/api/integrations/openai/test")
        assert r.status_code == 200
        res = r.json()
        assert (res["success"], res["status"], res["reason"]) == (False, "failed", "own_key_invalid")
        assert res["message"] == ai_billing.own_key_message("own_key_invalid", "es", ai_billing.OWN_KEY_DEFAULT_MODEL)
        assert KEY_A not in r.text and KEY_A[-4:] not in r.text
        assert _row(fake, WS)["extra"]["last_test_ok"] is False
        assert _row(fake, WS)["extra"]["last_test_reason"] == "own_key_invalid"


async def test_other_providers_keep_the_simulated_test_and_disconnect_clears_their_secret(app):
    fake, server, _ = app
    async with await _client(app) as http:
        c = Client(server, http)
        r = await c.call("u-leader", "PUT", "/api/integrations/crm",
                         json={"status": "connected", "config": {"provider": "hubspot", "api_key": "crm-secret-123"}})
        assert r.status_code == 200
        r = await c.call("u-leader", "POST", "/api/integrations/crm/test")
        assert r.json() == {"success": True, "message": "Crm connection is healthy"}
        assert FakeOpenAI.instances == []
        await c.call("u-leader", "PUT", "/api/integrations/crm", json={"status": "disconnected", "config": {}})
        assert _row(fake, WS, "crm")["secrets_enc"] == {}


async def test_ai_endpoint_runs_on_the_workspace_key(app, monkeypatch):
    """/api/content/generate passes the active workspace to run_ai_request:
    ws_a (own key) runs on the customer's key without touching credits;
    ws_b (no key) stays on Quantro's key."""
    fake, server, _ = app
    decrements: List[Any] = []

    async def fake_decrement(user_id, amount, access_token):
        decrements.append(amount)

    async def fake_profile(user_id, access_token):
        return {"id": user_id, "plan": "pro", "ai_credits_total": 10, "ai_credits_remaining": 10}

    monkeypatch.setattr(ai_billing, "rpc_decrement_credits", fake_decrement)
    monkeypatch.setattr(ai_billing, "fetch_profile", fake_profile)
    FakeOpenAI.text = json.dumps({"social_post": {"text": "Post", "hashtags": [], "platform": "instagram"}})
    async with await _client(app) as http:
        c = Client(server, http)
        assert (await c.call("u-owner", "PUT", "/api/integrations/openai",
                             json={"status": "connected", "config": {"api_key": KEY_A, "model": "gpt-4o"}})).status_code == 200

        r = await c.call("u-member", "POST", "/api/content/generate", json={"prompt": "Launch", "type": "social_post"})
        assert r.status_code == 200, r.text
        client = fake_openai_last()
        assert client.api_key == KEY_A and client.create_calls[0]["model"] == "gpt-4o"
        assert decrements == []

        r = await c.call("u-b-owner", "POST", "/api/content/generate", workspace_id="ws_b",
                         json={"prompt": "Launch", "type": "social_post"})
        assert r.status_code == 200, r.text
        client = fake_openai_last()
        assert client.api_key == QUANTRO_KEY and client.create_calls[0]["model"] == "gpt-4o-mini"
        assert len(decrements) == 1

        # A revoked key: clear 402 for the member, no Quantro fallback.
        FakeOpenAI.error = _auth_error()
        before = len(FakeOpenAI.instances)
        r = await c.call("u-member", "POST", "/api/content/generate", json={"prompt": "Launch", "type": "social_post"})
        assert r.status_code == 402, r.text
        assert r.json()["detail"]["reason"] == "own_key_invalid"
        assert [i.api_key for i in FakeOpenAI.instances[before:]] == [KEY_A]


def test_error_text_scrubs_openai_keys_including_the_masked_echo():
    text = f"AuthenticationError: Incorrect API key provided: {KEY_A[:8]}****{KEY_A[-4:]}. Raw {KEY_B} sk-abcd1234"
    scrubbed = integration_secrets.redact_error_text(text)
    assert "sk-" not in scrubbed
    assert KEY_A[-4:] not in scrubbed and KEY_B not in scrubbed
    assert "[redacted-key]" in scrubbed


async def test_changing_the_model_invalidates_the_last_test(app):
    fake, server, _ = app
    async with await _client(app) as http:
        c = Client(server, http)
        await c.call("u-leader", "PUT", "/api/integrations/openai",
                     json={"status": "connected", "config": {"api_key": KEY_A, "model": "gpt-4o"}})
        await c.call("u-leader", "POST", "/api/integrations/openai/test")
        assert _row(fake, WS)["extra"]["last_test_ok"] is True
        # Same model, blank key → the passing test still applies.
        await c.call("u-leader", "PUT", "/api/integrations/openai",
                     json={"status": "connected", "config": {"api_key": "", "model": "gpt-4o"}})
        assert _row(fake, WS)["extra"]["last_test_ok"] is True
        # Another model → the old result no longer says anything.
        await c.call("u-leader", "PUT", "/api/integrations/openai",
                     json={"status": "connected", "config": {"api_key": "", "model": "gpt-4.1-mini"}})
        assert _row(fake, WS)["extra"]["last_test_ok"] is None
        assert (await ai_billing.get_user_api_key(WS)).api_key == KEY_A
