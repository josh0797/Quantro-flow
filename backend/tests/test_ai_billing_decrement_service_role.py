"""
ai_billing.rpc_decrement_credits must call the ``decrement_ai_credits``
RPC with the Supabase **service-role** key, never with the end user's
JWT. This is the prerequisite for
``REVOKE EXECUTE ON FUNCTION public.decrement_ai_credits(uuid, numeric)
FROM authenticated`` (the function is SECURITY DEFINER and charges any
``p_user_id`` it receives, so it must not be callable by end users).

httpx.AsyncClient is replaced with an in-memory fake; no network I/O.
"""
from __future__ import annotations

import base64
import json
import sys
import types
from typing import Any, Dict, List

import pytest

import ai_billing

SUPABASE_URL = "https://example-project.supabase.co"
SERVICE_KEY = "service-role-key-XYZ"
ANON_KEY = "anon-key-ABC"
USER_ID = "11111111-2222-3333-4444-555555555555"
OTHER_USER_ID = "99999999-8888-7777-6666-555555555555"


def _make_jwt(sub: str) -> str:
    def b64(obj: Dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'HS256', 'typ': 'JWT'})}.{b64({'sub': sub, 'role': 'authenticated'})}.sig"


USER_JWT = _make_jwt(USER_ID)


class _FakeResponse:
    def __init__(self, status_code: int = 204, body: Any = None):
        self.status_code = status_code
        self._body = body
        self.text = "" if body is None else json.dumps(body)

    def json(self):
        return self._body


class _FakeAsyncClient:
    calls: List[Dict[str, Any]] = []
    post_status: int = 204
    raise_on_post: bool = False
    get_body: Any = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):  # noqa: A002
        type(self).calls.append({"method": "POST", "url": url, "headers": dict(headers or {}), "json": json})
        if type(self).raise_on_post:
            raise RuntimeError("boom")
        return _FakeResponse(type(self).post_status)

    async def get(self, url, headers=None):
        type(self).calls.append({"method": "GET", "url": url, "headers": dict(headers or {}), "json": None})
        return _FakeResponse(200, type(self).get_body or [])


@pytest.fixture
def fake_httpx(monkeypatch):
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.post_status = 204
    _FakeAsyncClient.raise_on_post = False
    _FakeAsyncClient.get_body = None
    monkeypatch.setattr(ai_billing, "SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setattr(ai_billing, "SUPABASE_ANON_KEY", ANON_KEY)
    monkeypatch.setattr(ai_billing, "SUPABASE_SERVICE_ROLE_KEY", SERVICE_KEY)
    monkeypatch.setattr(ai_billing.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


def _rpc_calls(fake):
    return [c for c in fake.calls if c["url"].endswith("/rest/v1/rpc/decrement_ai_credits")]


def _assert_no_user_jwt(headers: Dict[str, str]):
    for value in headers.values():
        assert USER_JWT not in value
        assert ANON_KEY not in value


async def test_decrement_uses_service_role_headers_not_user_jwt(fake_httpx):
    await ai_billing.rpc_decrement_credits(USER_ID, 0.0123, USER_JWT)

    calls = _rpc_calls(fake_httpx)
    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "POST"
    assert call["url"] == f"{SUPABASE_URL}/rest/v1/rpc/decrement_ai_credits"
    assert call["headers"] == ai_billing._service_headers()
    assert call["headers"]["apikey"] == SERVICE_KEY
    assert call["headers"]["Authorization"] == f"Bearer {SERVICE_KEY}"
    _assert_no_user_jwt(call["headers"])
    # Same payload / RPC args as before.
    assert call["json"] == {"p_user_id": USER_ID, "p_amount": 0.0123}


async def test_decrement_skips_when_token_subject_mismatches_user(fake_httpx):
    await ai_billing.rpc_decrement_credits(OTHER_USER_ID, 0.5, USER_JWT)
    assert _rpc_calls(fake_httpx) == []


async def test_decrement_skips_for_non_jwt_token(fake_httpx):
    await ai_billing.rpc_decrement_credits(USER_ID, 0.5, "not-a-jwt")
    assert _rpc_calls(fake_httpx) == []


async def test_decrement_does_not_fall_back_to_user_jwt_without_service_key(fake_httpx, monkeypatch):
    monkeypatch.setattr(ai_billing, "SUPABASE_SERVICE_ROLE_KEY", "")
    await ai_billing.rpc_decrement_credits(USER_ID, 0.5, USER_JWT)
    assert _rpc_calls(fake_httpx) == []


@pytest.mark.parametrize(
    "user_id,amount,token",
    [
        (USER_ID, 0.0, USER_JWT),
        (USER_ID, None, USER_JWT),
        (USER_ID, -1.0, USER_JWT),
        ("", 0.5, USER_JWT),
        (USER_ID, 0.5, ""),
    ],
)
async def test_decrement_noop_guards_unchanged(fake_httpx, user_id, amount, token):
    await ai_billing.rpc_decrement_credits(user_id, amount, token)
    assert fake_httpx.calls == []


async def test_decrement_noop_without_supabase_url(fake_httpx, monkeypatch):
    monkeypatch.setattr(ai_billing, "SUPABASE_URL", "")
    await ai_billing.rpc_decrement_credits(USER_ID, 0.5, USER_JWT)
    assert fake_httpx.calls == []


async def test_decrement_non_2xx_is_swallowed(fake_httpx):
    fake_httpx.post_status = 403
    result = await ai_billing.rpc_decrement_credits(USER_ID, 0.5, USER_JWT)
    assert result is None
    assert len(_rpc_calls(fake_httpx)) == 1


async def test_decrement_exception_is_swallowed(fake_httpx):
    fake_httpx.raise_on_post = True
    result = await ai_billing.rpc_decrement_credits(USER_ID, 0.5, USER_JWT)
    assert result is None


async def test_run_ai_request_charges_via_service_role(fake_httpx, monkeypatch):
    """End-to-end through run_ai_request: profile read still uses the
    user's JWT (RLS), but the credit decrement uses the service role."""
    fake_httpx.get_body = [{
        "id": USER_ID,
        "plan": "pro",
        "ai_credits_total": 10,
        "ai_credits_used": 1,
        "ai_credits_remaining": 9,
    }]
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class _Usage:
        prompt_tokens = 1_000_000
        completion_tokens = 0

    class _Msg:
        content = "hola"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        usage = _Usage()

    class _Completions:
        async def create(self, **kwargs):
            return _Resp()

    class _Chat:
        completions = _Completions()

    class _AsyncOpenAI:
        def __init__(self, api_key=None):
            self.chat = _Chat()

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(AsyncOpenAI=_AsyncOpenAI))

    out = await ai_billing.run_ai_request(
        user_id=USER_ID,
        email="someone@example.com",
        access_token=USER_JWT,
        system_prompt="sys",
        user_prompt="usr",
    )
    assert out["source"] == "quantro"
    assert out["usage"]["cost_usd"] == pytest.approx(0.15)

    profile_gets = [c for c in fake_httpx.calls if c["method"] == "GET"]
    assert profile_gets and profile_gets[0]["headers"]["Authorization"] == f"Bearer {USER_JWT}"

    rpc = _rpc_calls(fake_httpx)
    assert len(rpc) == 1
    assert rpc[0]["headers"] == ai_billing._service_headers()
    _assert_no_user_jwt(rpc[0]["headers"])
    assert rpc[0]["json"] == {"p_user_id": USER_ID, "p_amount": pytest.approx(0.15)}
