"""Google / Microsoft SDK calls never run on the event loop.

The API is one uvicorn worker. googleapiclient (httplib2), MSAL and the
sync ``httpx.Client`` block the thread they run on, and a Gmail sync is
~50 sequential HTTPS round-trips. Called straight from async code they
froze every request for every customer while one workspace synced —
/api/health included, whose Fly check times out at 5 s (launch audit
FLOW-1). Every such call now goes through ``asyncio.to_thread``.

Two layers:

* static — the blocking functions of google_oauth.py / microsoft_oauth.py
  are derived from their bodies (``.execute()``, ``fetch_token``,
  ``creds.refresh``, ``httpx.Client``/``httpx.post``, the MSAL client…),
  and no ``async def`` in server.py or the action handlers calls one
  directly (the guard is itself tested against a re-introduced call);
* dynamic — boot the real app, make the provider fetch/refresh sleep
  for real (``time.sleep``), and check that the loop keeps ticking and
  /api/health answers fast while the sync is still running.
"""
from __future__ import annotations

import ast
import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import httpx
import pytest

import _import_stubs
from storage_helpers import supabase_only

BACKEND = Path(__file__).resolve().parents[1]
PROVIDER_MODULES = {"goog": "google_oauth.py", "msoa": "microsoft_oauth.py"}
CALLER_FILES = ["server.py", "actions/handlers/google.py", "actions/handlers/microsoft.py"]

# Attribute calls / names that mean "this function does network I/O".
_BLOCKING_ATTRS = {"execute", "fetch_token", "refresh", "acquire_token_by_authorization_code",
                   "acquire_token_by_refresh_token"}
_BLOCKING_NAMES = {"_msal_client"}


def _is_blocking_call(node: ast.Call) -> bool:
    fn = node.func
    if isinstance(fn, ast.Attribute):
        if fn.attr in _BLOCKING_ATTRS:
            return True
        # httpx.Client(...), httpx.post(...), httpx.get(...)
        if isinstance(fn.value, ast.Name) and fn.value.id == "httpx" and fn.attr in {
            "Client", "post", "get", "put", "patch", "delete", "request",
        }:
            return True
    return isinstance(fn, ast.Name) and fn.id in _BLOCKING_NAMES


def blocking_functions(source: str) -> Set[str]:
    """Top-level functions of a provider module that block: they make a
    network call themselves or call another blocking function of it."""
    tree = ast.parse(source)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    blocking = {name for name, fn in funcs.items()
                if any(isinstance(c, ast.Call) and _is_blocking_call(c) for c in ast.walk(fn))}
    changed = True
    while changed:
        changed = False
        for name, fn in funcs.items():
            if name in blocking:
                continue
            for c in ast.walk(fn):
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in blocking:
                    blocking.add(name)
                    changed = True
                    break
    return {n for n in blocking if not n.startswith("_")}


def _blocking_by_alias() -> Dict[str, Set[str]]:
    return {alias: blocking_functions((BACKEND / path).read_text())
            for alias, path in PROVIDER_MODULES.items()}


def direct_calls_on_loop(source: str, blocking: Dict[str, Set[str]]) -> List[Tuple[int, str]]:
    """``goog.fetch_recent_gmail(...)``-style calls inside an ``async def``.
    Passing the function to ``asyncio.to_thread`` is not a call of it."""
    tree = ast.parse(source)
    bad: List[Tuple[int, str]] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            owner = node.func.value
            if isinstance(owner, ast.Name) and node.func.attr in blocking.get(owner.id, set()):
                bad.append((node.lineno, f"{owner.id}.{node.func.attr}"))
    return bad


def _offloaded(source: str) -> Set[str]:
    """``module.func`` names handed to ``asyncio.to_thread``."""
    out: Set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "to_thread" and node.args
                and isinstance(node.args[0], ast.Attribute) and isinstance(node.args[0].value, ast.Name)):
            out.add(f"{node.args[0].value.id}.{node.args[0].attr}")
    return out


# ── static ──────────────────────────────────────────────────────────────

def test_blocking_provider_functions_are_detected():
    blocking = _blocking_by_alias()
    assert {
        "fetch_recent_gmail", "fetch_upcoming_calendar", "exchange_code_for_tokens",
        "maybe_refresh", "revoke_token", "send_gmail", "create_calendar_event",
    } <= blocking["goog"]
    assert {
        "build_authorization_url", "build_incremental_authorization_url", "exchange_code_for_tokens",
        "refresh_access_token", "fetch_recent_outlook", "fetch_upcoming_outlook_events",
        "send_mail", "create_calendar_event",
    } <= blocking["msoa"]
    # Pure helpers stay callable inline (no thread hop for local work).
    assert "build_authorization_url" not in blocking["goog"]
    assert not {"encrypt_token", "decrypt_token", "resolve_redirect_uri",
                "missing_required_scopes", "credentials_from_tokens"} & blocking["goog"]
    # msoa.revoke_token is a documented no-op (no public revoke endpoint).
    assert "revoke_token" not in blocking["msoa"]


def test_no_async_code_calls_a_blocking_provider_function_directly():
    blocking = _blocking_by_alias()
    for rel in CALLER_FILES:
        assert direct_calls_on_loop((BACKEND / rel).read_text(), blocking) == [], rel


def test_the_sync_oauth_and_action_paths_offload_their_provider_calls():
    offloaded = set().union(*(_offloaded((BACKEND / rel).read_text()) for rel in CALLER_FILES))
    assert {
        "goog.fetch_recent_gmail", "goog.fetch_upcoming_calendar", "goog.exchange_code_for_tokens",
        "goog.maybe_refresh", "goog.revoke_token", "goog.send_gmail", "goog.create_calendar_event",
        "msoa.build_authorization_url", "msoa.build_incremental_authorization_url",
        "msoa.exchange_code_for_tokens", "msoa.refresh_access_token", "msoa.fetch_recent_outlook",
        "msoa.fetch_upcoming_outlook_events", "msoa.send_mail", "msoa.create_calendar_event",
    } <= offloaded


@pytest.mark.parametrize("before,after", [
    ("emails = await asyncio.to_thread(goog.fetch_recent_gmail, creds, limit=50)",
     "emails = goog.fetch_recent_gmail(creds, limit=50)"),
    ("if await asyncio.to_thread(goog.maybe_refresh, creds):",
     "if goog.maybe_refresh(creds):"),
    ("emails = await asyncio.to_thread(msoa.fetch_recent_outlook, access, limit=50)",
     "emails = msoa.fetch_recent_outlook(access, limit=50)"),
])
def test_guard_catches_a_reintroduced_blocking_call(before, after):
    src = (BACKEND / "server.py").read_text()
    assert before in src
    bad = direct_calls_on_loop(src.replace(before, after, 1), _blocking_by_alias())
    assert len(bad) == 1


# ── dynamic ─────────────────────────────────────────────────────────────

BLOCK_SECS = 0.6
MAX_LOOP_GAP = 0.25     # a blocked loop would stall for >= BLOCK_SECS


@pytest.fixture
def app(monkeypatch):
    _import_stubs.install()
    fake = supabase_only(monkeypatch)
    monkeypatch.setenv("MONGO_URL", "mongodb://tripwire.invalid:27017")
    import mongo_legacy
    import server

    def no_connect():
        raise AssertionError("Mongo client requested while every flag says Supabase")

    monkeypatch.setattr(mongo_legacy, "_get_client", no_connect)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", fake.async_client_factory(real_async_client))

    async def no_patch(**_kw):
        return None

    monkeypatch.setattr(server.secrets_store, "patch_connection", no_patch)
    yield server, real_async_client
    server.app.dependency_overrides.clear()


def _slow(result):
    def fetch(*_a, **_k):
        time.sleep(BLOCK_SECS)      # a real, thread-blocking wait like httplib2
        return result
    return fetch


async def _loop_stays_responsive(server, RealAsyncClient, work) -> Any:
    """Run ``work`` while a heartbeat measures the loop's longest stall and
    /api/health is called mid-sync."""
    gaps: List[float] = []
    stop = asyncio.Event()

    async def heartbeat():
        last = time.perf_counter()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    beat = asyncio.create_task(heartbeat())
    task = asyncio.create_task(work)
    await asyncio.sleep(0.05)       # let the work reach its provider call
    transport = httpx.ASGITransport(app=server.app)
    async with RealAsyncClient(transport=transport, base_url="http://test") as http:
        t0 = time.perf_counter()
        health = await http.get("/api/health")
        health_secs = time.perf_counter() - t0
    assert not task.done(), "the provider call should still be running"
    result = await task
    stop.set()
    await beat

    assert health.status_code == 200
    assert health_secs < MAX_LOOP_GAP, health_secs
    assert max(gaps) < MAX_LOOP_GAP, max(gaps)
    return result


@pytest.mark.asyncio
async def test_google_sync_does_not_freeze_the_api(app, monkeypatch):
    server, RealAsyncClient = app

    async def creds(_ws):
        return object(), {"workspace_id": "ws_a"}

    monkeypatch.setattr(server, "_load_google_credentials", creds)
    monkeypatch.setattr(server.goog, "fetch_recent_gmail", _slow([]))
    monkeypatch.setattr(server.goog, "fetch_upcoming_calendar", _slow([]))
    res = await _loop_stays_responsive(
        server, RealAsyncClient, server._perform_google_sync_for_workspace("ws_a"))
    assert res == {"workspace_id": "ws_a", "ok": True, "counts": {"emails": 0, "events": 0}}


@pytest.mark.asyncio
async def test_microsoft_sync_does_not_freeze_the_api(app, monkeypatch):
    server, RealAsyncClient = app

    async def creds(_ws):
        return "access-token", {"workspace_id": "ws_a"}

    monkeypatch.setattr(server, "_load_microsoft_credentials", creds)
    monkeypatch.setattr(server.msoa, "fetch_recent_outlook", _slow([]))
    monkeypatch.setattr(server.msoa, "fetch_upcoming_outlook_events", _slow([]))
    res = await _loop_stays_responsive(
        server, RealAsyncClient, server._perform_microsoft_sync_for_workspace("ws_a"))
    assert res["ok"] is True and res["counts"]["emails"] == 0


@pytest.mark.asyncio
async def test_google_token_refresh_does_not_freeze_the_api(app, monkeypatch):
    server, RealAsyncClient = app

    async def get_connection(**_kw):
        return {"workspace_id": "ws_a", "access_token": "enc-a", "refresh_token": "enc-r",
                "expires_at": None, "scopes": []}

    monkeypatch.setattr(server.secrets_store, "get_connection", get_connection)
    monkeypatch.setattr(server.goog, "decrypt_token", lambda v: v)
    monkeypatch.setattr(server.goog, "credentials_from_tokens", lambda **_kw: object())
    monkeypatch.setattr(server.goog, "maybe_refresh", _slow(False))
    creds, doc = await _loop_stays_responsive(
        server, RealAsyncClient, server._load_google_credentials("ws_a"))
    assert creds is not None and doc["workspace_id"] == "ws_a"
