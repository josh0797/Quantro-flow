"""Activity events land in the workspace they belong to — never "default".

Regression for the cross-tenant leak: ``log_activity`` defaulted
``workspace_id`` to DEFAULT_WORKSPACE_ID and 30 of its call sites did not
pass one, so other tenants' inbox senders, subjects and AI summaries were
shown in the "default" workspace's activity feed (with ``is_simulation``
computed from the default workspace's mode).

Two layers:

* static — every ``log_activity(...)`` call in the backend passes
  ``workspace_id=`` explicitly, ``log_activity`` has no default for it, and
  no tenant-scoped helper defaults ``workspace_id`` to the default workspace;
* dynamic — boot the real app on the in-memory PostgREST, act as a member
  of workspace A through the endpoints that used to leak, and check that the
  events are stored under A (with A's mode) and that workspace B and
  "default" see none of them.
"""
from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
import pytest

import _import_stubs
from storage_helpers import supabase_only

BACKEND = Path(__file__).resolve().parents[1]


# ── static ──────────────────────────────────────────────────────────────

def _backend_py_files() -> List[Path]:
    skip = {"tests", ".venv", "__pycache__"}
    return sorted(p for p in BACKEND.rglob("*.py") if not (set(p.relative_to(BACKEND).parts) & skip))


def _log_activity_calls(path: Path) -> List[Tuple[int, bool]]:
    """(line, passes workspace_id= explicitly) for every log_activity(...) call."""
    out = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
        if name != "log_activity":
            continue
        # A **kwargs splat could hide a missing workspace_id: not explicit.
        explicit = any(kw.arg == "workspace_id" for kw in node.keywords)
        out.append((node.lineno, explicit))
    return out


def test_every_log_activity_call_passes_workspace_id():
    calls: Dict[str, List[Tuple[int, bool]]] = {}
    for path in _backend_py_files():
        found = _log_activity_calls(path)
        if found:
            calls[str(path.relative_to(BACKEND))] = found
    missing = [(f, line) for f, found in calls.items() for line, ok in found if not ok]
    assert missing == [], f"log_activity without workspace_id=: {missing}"
    # Not vacuous: the scan sees server.py's endpoints and the Actions handlers.
    assert len(calls.get("server.py", [])) >= 37
    assert len(calls.get("actions/handlers/quantro_internal.py", [])) >= 6


def _function(tree: ast.AST, name: str) -> ast.AsyncFunctionDef:
    return next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def test_log_activity_workspace_id_is_keyword_only_without_default():
    fn = _function(ast.parse((BACKEND / "server.py").read_text()), "log_activity")
    names = [a.arg for a in fn.args.kwonlyargs]
    assert "workspace_id" in names
    assert fn.args.kw_defaults[names.index("workspace_id")] is None   # required
    assert "workspace_id" not in [a.arg for a in fn.args.args]


def _is_default_ws(node: ast.AST) -> bool:
    return (isinstance(node, ast.Name) and node.id == "DEFAULT_WORKSPACE_ID") or (
        isinstance(node, ast.Constant) and node.value == "default"
    )


def test_no_tenant_helper_defaults_workspace_id_to_default():
    """The bug class (R3): a request-path caller that omits the workspace
    silently reads/writes the "default" workspace. Forbid, in server.py:
    ``def f(workspace_id=DEFAULT_WORKSPACE_ID)``,
    ``x.get("workspace_id", DEFAULT_WORKSPACE_ID)`` and
    ``workspace_id or DEFAULT_WORKSPACE_ID``. Startup repairs and the seed
    assign legacy rows to "default" with explicit literals/setdefault, which
    stay allowed."""
    tree = ast.parse((BACKEND / "server.py").read_text())
    bad: List[Tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            positional = args.posonlyargs + args.args
            pairs = list(zip(positional[len(positional) - len(args.defaults):], args.defaults))
            pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None]
            for arg, default in pairs:
                if arg.arg == "workspace_id" and _is_default_ws(default):
                    bad.append((node.lineno, f"def {node.name}(workspace_id=default)"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            if (len(node.args) == 2 and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "workspace_id" and _is_default_ws(node.args[1])):
                bad.append((node.lineno, '.get("workspace_id", default)'))
        elif isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            if any(_is_default_ws(v) for v in node.values[1:]) and any(
                isinstance(v, ast.Name) and v.id in ("workspace_id", "ws_id") for v in node.values[:-1]
            ):
                bad.append((node.lineno, "workspace_id or default"))
    assert bad == []


# ── dynamic ─────────────────────────────────────────────────────────────

AI_TRIAGE = {
    "intent": "needs_review", "confidence": 0.4, "summary": "SECRET-SUMMARY about a deal",
    "entities": {"person_name": "Victim Sender"},
    "suggested_action": {"type": "flag_review", "description": "review"},
}
AI_CONTENT = {"social_post": {"text": "Post", "hashtags": [], "platform": "instagram"}}


@pytest.fixture
def app(monkeypatch):
    _import_stubs.install()
    fake = supabase_only(monkeypatch)
    monkeypatch.setenv("MONGO_URL", "mongodb://tripwire.invalid:27017")  # configured, must stay unused
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    import mongo_legacy
    import server

    def no_connect():
        raise AssertionError("Mongo client requested while every flag says Supabase")

    monkeypatch.setattr(mongo_legacy, "_get_client", no_connect)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", fake.async_client_factory(real_async_client))

    async def fake_ai(*, system_prompt: str, user_prompt: str, **_: Any) -> Dict[str, Any]:
        return {"text": json.dumps(AI_CONTENT if "content writer" in system_prompt else AI_TRIAGE)}

    monkeypatch.setattr(server, "run_ai_request", fake_ai)
    yield fake, server, real_async_client
    server.app.dependency_overrides.clear()


class Client:
    """Calls the app as a given member (X-Workspace-Id = their workspace)."""

    def __init__(self, server: Any, http: httpx.AsyncClient):
        self.server = server
        self.http = http

    async def call(self, user_id: str, workspace_id: str, method: str, url: str, **kw: Any) -> httpx.Response:
        user = self.server.User(user_id=user_id, email=f"{user_id}@example.com", name=user_id,
                                current_workspace_id=workspace_id, access_token="test-token")
        self.server.app.dependency_overrides[self.server.get_current_user] = lambda: user
        return await self.http.request(method, url, headers={"X-Workspace-Id": workspace_id,
                                                             "Authorization": "Bearer t"}, **kw)


async def _tenants(server: Any) -> None:
    """Workspaces A and B plus "default", one owner each. The default
    workspace is in Simulation Mode, A and B are live — so an event that
    borrowed the default workspace's mode would be tagged is_simulation."""
    for ws, user in (("default", "u-default"), ("ws_a", "u-a"), ("ws_b", "u-b")):
        await server.workspaces_col.insert_one({"workspace_id": ws, "name": ws, "owner_user_id": user, "claimed": True})
        await server.workspace_members_col.insert_one({"workspace_id": ws, "user_id": user, "role": "owner"})
        await server.seed_workspace_config(ws)
    await server.business_profile_col.update_one({"workspace_id": "default"}, {"$set": {"simulation_mode": True}})
    item = {"workspace_id": "ws_a", "from_name": "Victim Sender", "from_email": "victim@corp.example",
            "subject": "SECRET-SUBJECT", "body": "confidential", "status": "processed", "is_simulation": False,
            "ai_intent": {"intent": "follow_up", "confidence": 0.9, "summary": "SECRET-SUMMARY", "entities": {}}}
    for inbox_id, action in (("a-flag", "flag_review"), ("a-decline", "flag_review"), ("a-details", "flag_review"),
                             ("a-batch", "create_contact"), ("a-override", "send_follow_up"),
                             ("a-analyze", None), ("a-batch-analyze", None)):
        await server.inbox_col.insert_one({**item, "inbox_id": inbox_id,
                                           "ai_suggested_action": {"type": action, "description": "d"} if action else None})


def _activity_rows(fake) -> List[Dict[str, Any]]:
    return list(fake.rows["activity_events"])


@pytest.mark.asyncio
async def test_endpoint_events_land_in_the_callers_workspace_and_nowhere_else(app):
    fake, server, RealAsyncClient = app
    await _tenants(server)
    policy = await server.policies_col.find_one({"workspace_id": "ws_a"})

    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=True)
    async with RealAsyncClient(transport=transport, base_url="http://test") as http:
        c = Client(server, http)
        a = lambda method, url, **kw: c.call("u-a", "ws_a", method, url, **kw)  # noqa: E731

        # Every endpoint below used to call log_activity without workspace_id.
        assert (await a("POST", "/api/inbox/a-analyze/analyze")).status_code == 200
        assert (await a("POST", "/api/inbox/batch-analyze", json={"inbox_ids": ["a-batch-analyze"]})).status_code == 200
        assert (await a("POST", "/api/inbox/a-flag/approve")).status_code == 200
        assert (await a("POST", "/api/inbox/a-decline/decline")).status_code == 200
        assert (await a("PUT", "/api/inbox/a-details/details", json={"summary": "edited"})).status_code == 200
        assert (await a("POST", "/api/inbox/batch-approve", json={"inbox_ids": ["a-batch"]})).status_code == 200
        assert (await a("POST", "/api/inbox/a-override/approve-with-overrides", json={})).status_code == 200
        agent = (await a("POST", "/api/agents", json={"name": "New Hire", "email": "hire@corp.example"})).json()
        task_id = agent["onboarding_tasks"][0]["task_id"]
        assert (await a("PUT", f"/api/onboarding/{task_id}", json={"status": "completed"})).status_code == 200
        assert (await a("POST", "/api/content/generate", json={"prompt": "launch", "type": "social_post"})).status_code == 200
        assert (await a("PUT", f"/api/policies/{policy['policy_id']}",
                        json={"intent": "booking", "action": "require_approval"})).status_code == 200

        live_rows = _activity_rows(fake)
        assert len(live_rows) == 13
        assert {r["workspace_id"] for r in live_rows} == {"ws_a"}
        # is_simulation comes from A's (live) mode, not the default workspace's.
        assert {r["is_simulation"] for r in live_rows} == {False}

        # A sees its own feed…
        feed_a = (await a("GET", "/api/activity", params={"limit": 100})).json()
        assert {e["title"] for e in feed_a} >= {
            "AI processed inbox", "Batch triage classified", "Batch triage complete", "Flagged for review",
            "Action declined", "Details edited", "Contact created (batch)", "Batch approval complete",
            "Follow-up queued", "New agent added", "Task completed", "Content generated", "Policy updated",
        }
        # …and neither workspace B nor "default" sees any of it.
        for user, ws in (("u-b", "ws_b"), ("u-default", "default")):
            feed = (await c.call(user, ws, "GET", "/api/activity", params={"limit": 100})).json()
            assert feed == [], (ws, feed)
            assert "SECRET" not in json.dumps(feed)
            contact_feed = await c.call(user, ws, "GET", "/api/activity",
                                        params={"limit": 100, "event_type": "crm"})
            assert contact_feed.json() == []

        # Profile / simulation endpoints: the events follow A into Simulation
        # Mode. (Regenerating the sandbox wipes A's simulation activity, so
        # each event is checked right after the call that logs it.)
        def logged(title: str) -> Dict[str, Any]:
            (row,) = [r for r in _activity_rows(fake) if r["title"] == title]
            return row

        profile = {"industry": "real_estate", "entity_labels": {}, "simulation_mode": True}
        assert (await a("PUT", "/api/business-profile", json=profile)).status_code == 200
        assert logged("Simulation data auto-generated")["workspace_id"] == "ws_a"
        assert (await a("PUT", "/api/business-profile", json=profile)).status_code == 200   # no regeneration
        assert logged("Business Profile updated")["workspace_id"] == "ws_a"
        assert (await a("POST", "/api/simulation/generate")).status_code == 200
        assert logged("Simulation data generated")["workspace_id"] == "ws_a"
        assert (await a("POST", "/api/simulation/clear")).status_code == 200
        assert logged("Simulation data cleared")["workspace_id"] == "ws_a"

    rows = _activity_rows(fake)
    assert {r["workspace_id"] for r in rows} == {"ws_a"}
    assert {r["is_simulation"] for r in rows if r["title"].startswith("Simulation data")} == {True}
    assert not [r for r in rows if r["workspace_id"] == "default"]


@pytest.mark.asyncio
async def test_action_executor_events_use_the_items_workspace(app):
    """The Actions path (auto-run from analyze) logs through ctx.workspace_id."""
    fake, server, _ = app
    await _tenants(server)
    item = server._inbox_view(await server.inbox_col.find_one({"workspace_id": "ws_a", "inbox_id": "a-override"}))
    result = await server.execute_action_for_item(item, source="test")
    assert result["executed"] is True
    rows = _activity_rows(fake)
    assert rows and {r["workspace_id"] for r in rows} == {"ws_a"}
    # An item without a workspace is never executed against "default".
    orphan = {**item, "workspace_id": None}
    assert (await server.execute_action_for_item(orphan))["executed"] is False
    assert await server.evaluate_advanced_escalation(orphan, "escalation", 0.9, "auto_run") is None
    assert len(_activity_rows(fake)) == len(rows)


@pytest.mark.asyncio
async def test_log_activity_without_workspace_writes_nothing_and_warns(app, caplog):
    fake, server, _ = app
    with caplog.at_level(logging.WARNING, logger="quantro.activity"):
        assert await server.log_activity("inbox", "SECRET-TITLE", "SECRET-DESCRIPTION", "x", "inbox",
                                         workspace_id=None) is None
        assert await server.log_activity("inbox", "SECRET-TITLE", "d", workspace_id="") is None
    assert _activity_rows(fake) == []
    lines = [r.getMessage() for r in caplog.records if "ACTIVITY_NO_WORKSPACE" in r.getMessage()]
    assert len(lines) == 2 and all("event_type=inbox" in m for m in lines)
    assert "SECRET" not in caplog.text
    with pytest.raises(TypeError):
        await server.log_activity("inbox", "t", "d")   # workspace_id is required


@pytest.mark.asyncio
async def test_workspace_without_profile_does_not_borrow_the_default_profile(app):
    fake, server, _ = app
    # Legacy un-stamped default profile in Simulation Mode.
    await server.business_profile_col.insert_one({"profile_id": "default", "simulation_mode": True})
    assert await server.is_simulation_mode("default") is True
    assert await server.is_simulation_mode("ws_without_profile") is False
    mode = await server.get_mode_filter("ws_without_profile")
    assert mode["workspace_id"] == "ws_without_profile" and mode["is_simulation"] == {"$ne": True}
