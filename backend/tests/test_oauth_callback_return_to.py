"""Every exit of the Google / Microsoft OAuth callback returns to the page
that started the flow.

Settings → Integrations starts OAuth with return_to="/settings". Only the
success path used to honour it: pressing Cancel on the consent screen
(``?error=access_denied&state=…``) or an expired state bounced to the
default /welcome/inbox and dropped an existing user into the Welcome
onboarding flow. The callback now consumes the state first and uses its
(allowlist-sanitized) return_to for errors too.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

FE = "https://www.quantroflow.cloud"


class _Req:
    base_url = "https://api.example.test/"


@pytest.fixture
def srv():
    import server as srv_mod
    return srv_mod


def _state_doc(return_to="/settings", *, expired=False):
    delta = timedelta(minutes=-1) if expired else timedelta(minutes=5)
    return {
        "state": "s1",
        "workspace_id": "ws_owner",
        "user_id": "owner",
        "return_to": return_to,
        "expires_at": datetime.now(timezone.utc) + delta,
    }


async def _google(srv, consume, **params):
    with patch.dict(os.environ, {"FRONTEND_PUBLIC_URL": FE}), \
         patch.object(srv.secrets_store, "consume_oauth_state", consume):
        resp = await srv.google_oauth_callback(
            _Req(), code=params.get("code"), state=params.get("state"), error=params.get("error"),
        )
    return resp.headers["location"]


async def _microsoft(srv, consume, **params):
    with patch.dict(os.environ, {"FRONTEND_PUBLIC_URL": FE}), \
         patch.object(srv.secrets_store, "consume_oauth_state", consume):
        resp = await srv.microsoft_oauth_callback(
            _Req(), code=params.get("code"), state=params.get("state"),
            error=params.get("error"), error_description=None,
        )
    return resp.headers["location"]


CALLBACKS = [("google", _google), ("microsoft", _microsoft)]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,call", CALLBACKS)
async def test_cancel_on_consent_returns_to_settings_and_consumes_state(srv, provider, call):
    consume = AsyncMock(return_value=_state_doc("/settings"))
    location = await call(srv, consume, state="s1", error="access_denied")
    assert location == f"{FE}/settings?{provider}_connected=error&reason=access_denied"
    # The cancelled state is single-use: consumed, cannot be replayed.
    consume.assert_awaited_once()
    assert consume.await_args.kwargs["state"] == "s1"
    assert consume.await_args.kwargs["provider"] == provider


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,call", CALLBACKS)
async def test_expired_state_returns_to_the_page_that_started_the_flow(srv, provider, call):
    consume = AsyncMock(return_value=_state_doc("/settings", expired=True))
    location = await call(srv, consume, code="c", state="s1")
    assert location == f"{FE}/settings?{provider}_connected=error&reason=state_expired"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,call", CALLBACKS)
async def test_welcome_flow_cancel_still_returns_to_its_step(srv, provider, call):
    consume = AsyncMock(return_value=_state_doc("/welcome/calendar"))
    location = await call(srv, consume, state="s1", error="access_denied")
    assert location == f"{FE}/welcome/calendar?{provider}_connected=error&reason=access_denied"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,call", CALLBACKS)
async def test_without_usable_state_the_default_path_is_kept(srv, provider, call):
    # No state at all: nothing to consume.
    consume = AsyncMock(return_value=None)
    location = await call(srv, consume, error="access_denied")
    assert location == f"{FE}/welcome/inbox?{provider}_connected=error&reason=access_denied"
    consume.assert_not_awaited()

    # Unknown / already consumed state.
    location = await call(srv, AsyncMock(return_value=None), code="c", state="nope")
    assert location == f"{FE}/welcome/inbox?{provider}_connected=error&reason=invalid_state"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,call", CALLBACKS)
async def test_state_return_to_is_still_allowlist_sanitized(srv, provider, call):
    consume = AsyncMock(return_value=_state_doc("https://evil.example/settings"))
    location = await call(srv, consume, state="s1", error="access_denied")
    assert location.startswith(f"{FE}/welcome/inbox?")


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,call", CALLBACKS)
async def test_state_store_failure_bounces_instead_of_500(srv, provider, call):
    consume = AsyncMock(side_effect=RuntimeError("storage_unavailable"))
    location = await call(srv, consume, code="c", state="s1")
    assert location == f"{FE}/welcome/inbox?{provider}_connected=error&reason=invalid_state"
    # And a cancel still reports the provider's error code.
    location = await call(srv, consume, state="s1", error="access_denied")
    assert location == f"{FE}/welcome/inbox?{provider}_connected=error&reason=access_denied"
