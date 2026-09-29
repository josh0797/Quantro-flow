"""Activity events land in the workspace they belong to — never "default".

Regression for the cross-tenant leak: ``log_activity`` defaulted
``workspace_id`` to DEFAULT_WORKSPACE_ID and 30 of its call sites did not
pass one, so other tenants' inbox senders, subjects and AI summaries were
shown in the "default" workspace's activity feed (with ``is_simulation``
computed from the default workspace's mode).

Two layers:

* static — every ``log_activity(...)`` call in the backend passes
  ``workspace_id=`` explicitly with a value that never involves the default
  workspace, ``log_activity`` has no default for it and is never reachable
  under another name, and no value anywhere in the backend silently falls
  back to the default workspace (each guard is itself tested against
  one-line re-introductions of the leak);
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

Sources = Dict[str, str]   # backend-relative path → source text


def _backend_sources(root: Path = BACKEND) -> Sources:
    skip = {"tests", ".venv", "__pycache__"}
    return {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*.py"))
            if not (set(p.relative_to(root).parts) & skip)}


def _is_default_ws(node: ast.AST) -> bool:
    return (isinstance(node, ast.Name) and node.id == "DEFAULT_WORKSPACE_ID") or (
        isinstance(node, ast.Constant) and node.value == "default"
    )


def _mentions_default_ws(node: ast.AST) -> bool:
    """The default workspace appears anywhere in the expression (``x or
    DEFAULT_WORKSPACE_ID``, ``d.get(k, "default")``, ``a if c else "default"``…)."""
    return any(_is_default_ws(n) for n in ast.walk(node))


def _parents(tree: ast.AST) -> Dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _enclosing_function(node: ast.AST, parents: Dict[ast.AST, ast.AST]) -> str:
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return "<module>"


def _is_dep_binding(node: ast.AST, parents: Dict[ast.AST, ast.AST]) -> bool:
    """``log_activity = ctx.dep("log_activity")`` (the handlers' binding)."""
    assign = parents.get(node)
    while assign is not None and not isinstance(assign, ast.Assign):
        assign = parents.get(assign)
    if assign is None or len(assign.targets) != 1:
        return False
    target, value = assign.targets[0], assign.value
    return (isinstance(target, ast.Name) and target.id == "log_activity"
            and isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "dep"
            and len(value.args) == 1 and isinstance(value.args[0], ast.Constant) and value.args[0].value == "log_activity")


def _log_activity_violations(sources: Sources) -> Tuple[List[Tuple[str, int, str]], Dict[str, int]]:
    """(violations, calls per file). Every ``log_activity(...)`` call passes
    ``workspace_id=`` explicitly and its value never involves the default
    workspace; the function is never reachable under another name (only
    server.py's deps registration and the handlers' ``log_activity =
    ctx.dep("log_activity")`` binding refer to it without calling it)."""
    bad: List[Tuple[str, int, str]] = []
    calls: Dict[str, int] = {}
    for rel, src in sources.items():
        tree = ast.parse(src)
        parents = _parents(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
                if name != "log_activity":
                    continue
                calls[rel] = calls.get(rel, 0) + 1
                # A **kwargs splat or a positional argument could hide it: not explicit.
                kw = next((k for k in node.keywords if k.arg == "workspace_id"), None)
                if kw is None:
                    bad.append((rel, node.lineno, "log_activity without workspace_id="))
                elif _mentions_default_ws(kw.value):
                    bad.append((rel, node.lineno, "log_activity(workspace_id=<default workspace>)"))
            elif isinstance(node, (ast.Name, ast.Attribute)):
                name = node.id if isinstance(node, ast.Name) else node.attr
                if name != "log_activity":
                    continue
                parent = parents.get(node)
                if isinstance(parent, ast.Call) and parent.func is node:
                    continue
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and _is_dep_binding(node, parents):
                    continue
                if (rel == "server.py" and isinstance(parent, ast.Dict) and node in parent.values
                        and isinstance(parent.keys[parent.values.index(node)], ast.Constant)):
                    continue   # deps={"log_activity": log_activity}
                bad.append((rel, node.lineno, "log_activity referenced without being called"))
            elif isinstance(node, ast.Constant) and node.value == "log_activity":
                parent = parents.get(node)
                if rel == "server.py" and isinstance(parent, ast.Dict) and node in parent.keys:
                    continue
                if isinstance(parent, ast.Call) and _is_dep_binding(parent, parents):
                    continue
                bad.append((rel, node.lineno, 'log_activity dependency bound under another name'))
            elif isinstance(node, ast.alias) and node.name == "log_activity" and node.asname:
                bad.append((rel, getattr(node, "lineno", 0), "log_activity imported under another name"))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "log_activity" and rel != "server.py":
                bad.append((rel, node.lineno, "second log_activity definition"))
    return bad, calls


def test_every_log_activity_call_passes_workspace_id():
    bad, calls = _log_activity_violations(_backend_sources())
    assert bad == []
    # Not vacuous: the scan sees server.py's endpoints and the Actions handlers.
    assert calls.get("server.py", 0) >= 37
    assert calls.get("actions/handlers/quantro_internal.py", 0) >= 6


def _function(tree: ast.AST, name: str) -> ast.AsyncFunctionDef:
    return next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def test_log_activity_workspace_id_is_keyword_only_without_default():
    fn = _function(ast.parse((BACKEND / "server.py").read_text()), "log_activity")
    names = [a.arg for a in fn.args.kwonlyargs]
    assert "workspace_id" in names
    assert fn.args.kw_defaults[names.index("workspace_id")] is None   # required
    assert "workspace_id" not in [a.arg for a in fn.args.args]


# Functions that assign legacy / seed rows to the default workspace on
# purpose (explicit literals, never a fallback for a missing tenant).
DEFAULT_WORKSPACE_WRITERS = {
    ("server.py", "seed_database"),                        # the default workspace's demo seed
    ("server.py", "claim_or_create_workspace_for_user"),   # audit of claiming "default" itself
}


def _default_fallback_violations(sources: Sources) -> List[Tuple[str, int, str]]:
    """The bug class (R3): a value that silently falls back to the default
    workspace — ``def f(x=DEFAULT_WORKSPACE_ID)``, ``d.get(k, "default")``,
    ``x or DEFAULT_WORKSPACE_ID``, ``a if c else DEFAULT_WORKSPACE_ID``,
    ``f(workspace_id=DEFAULT_WORKSPACE_ID)`` — anywhere in the backend.
    Startup repairs / the backfill assign legacy rows with plain literals
    (``{"$set": {"workspace_id": DEFAULT_WORKSPACE_ID}}``), which stay allowed."""
    bad: List[Tuple[str, int, str]] = []
    for rel, src in sources.items():
        tree = ast.parse(src)
        parents = _parents(tree)
        for node in ast.walk(tree):
            kind = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
                if any(_is_default_ws(d) for d in defaults):
                    kind = f"def {node.name}(…=default)"
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in ("get", "setdefault", "pop") and len(node.args) == 2 \
                    and _is_default_ws(node.args[1]):
                kind = f".{node.func.attr}(key, default)"
            elif isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) \
                    and any(_is_default_ws(v) for v in node.values[1:]):
                kind = "… or default"
            elif isinstance(node, ast.IfExp) and (_is_default_ws(node.body) or _is_default_ws(node.orelse)):
                kind = "… if … else default"
            elif isinstance(node, ast.keyword) and node.arg == "workspace_id" and _mentions_default_ws(node.value):
                kind = "workspace_id=default"
            if kind and (rel, _enclosing_function(node, parents)) not in DEFAULT_WORKSPACE_WRITERS:
                bad.append((rel, getattr(node, "lineno", 0), kind))
    return bad


def test_no_tenant_value_falls_back_to_the_default_workspace():
    assert _default_fallback_violations(_backend_sources()) == []


# One-line re-introductions of the leak (or of an alias that escapes the
# scan). Each must trip at least one of the two static guards.
REINTRODUCED = {
    "call_site_or_default": (
        "server.py",
        '"inbox", workspace_id=item.get("workspace_id") or workspace_id)\n    return {"success": True}',
        '"inbox", workspace_id=item.get("workspace_id") or DEFAULT_WORKSPACE_ID)\n    return {"success": True}',
    ),
    "ws_id_or_default": (   # approve_inbox_action
        "server.py",
        '    ws_id = item.get("workspace_id") or workspace_id\n    \n    # Execute action based on type\n',
        '    ws_id = item.get("workspace_id") or DEFAULT_WORKSPACE_ID\n    \n    # Execute action based on type\n',
    ),
    "explicit_default_constant": (
        "server.py",
        'rule["rule_id"], "escalation", workspace_id=workspace_id)',
        'rule["rule_id"], "escalation", workspace_id=DEFAULT_WORKSPACE_ID)',
    ),
    "ifexp_default": (
        "server.py",
        'rule["rule_id"], "escalation", workspace_id=workspace_id)',
        'rule["rule_id"], "escalation", workspace_id=workspace_id if workspace_id else "default")',
    ),
    "handler_or_default_literal": (
        "actions/handlers/quantro_internal.py",
        '"Flagged for manual review",\n        await _own_inbox_id(ctx, input.get("related_id")), "inbox", workspace_id=ctx.workspace_id,',
        '"Flagged for manual review",\n        await _own_inbox_id(ctx, input.get("related_id")), "inbox", workspace_id=ctx.workspace_id or "default",',
    ),
    "handler_alias": (
        "actions/handlers/quantro_internal.py",
        'async def review_flag(ctx: ActionContext, input: dict) -> ActionResult:\n    log_activity = ctx.dep("log_activity")',
        'async def review_flag(ctx: ActionContext, input: dict) -> ActionResult:\n    log_activity = ctx.dep("log_activity")\n    log = ctx.dep("log_activity")',
    ),
    "deps_subscript": (
        "actions/handlers/quantro_internal.py",
        'async def inbox_ignore(ctx: ActionContext, input: dict) -> ActionResult:\n    log_activity = ctx.dep("log_activity")',
        'async def inbox_ignore(ctx: ActionContext, input: dict) -> ActionResult:\n    log_activity = ctx.deps["log_activity"]',
    ),
    "helper_default_elsewhere": (
        "scripts/mongo_to_supabase.py",
        "def template_workspaces(docs: Iterable[Dict[str, Any]]) -> Dict[str, Set[str]]:",
        "def template_workspaces(docs: Iterable[Dict[str, Any]], ws: str = DEFAULT_WORKSPACE_ID) -> Dict[str, Set[str]]:",
    ),
    "dropped_keyword": (
        "server.py",
        'rule["rule_id"], "escalation", workspace_id=workspace_id)',
        'rule["rule_id"], "escalation")',
    ),
}


@pytest.mark.parametrize("case", sorted(REINTRODUCED))
def test_static_guards_catch_a_reintroduced_default_fallback(case):
    rel, old, new = REINTRODUCED[case]
    sources = _backend_sources()
    assert sources[rel].count(old) == 1, f"anchor for {case} not found exactly once"
    sources[rel] = sources[rel].replace(old, new)
    caught = _log_activity_violations(sources)[0] + _default_fallback_violations(sources)
    assert caught, f"{case}: re-introduced default-workspace fallback passes the static guards"


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
        # Every event written since the fix says so (the repair never moves it).
        assert all(r["extra"].get(server.ACTIVITY_WORKSPACE_EXPLICIT) is True for r in live_rows)

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
async def test_actions_cannot_link_another_workspaces_inbox_item(app):
    """quantro.review.flag / followup.send / inbox.ignore take related_id from
    the caller's input (any member, POST /api/actions/{id}/execute): an id of
    another workspace's inbox item is dropped from the caller's activity row;
    the caller's own item stays linked."""
    from actions.base import ActionContext
    from actions.handlers import quantro_internal

    fake, server, _ = app
    await _tenants(server)
    handlers = (quantro_internal.review_flag, quantro_internal.followup_send, quantro_internal.inbox_ignore)

    def ctx(ws: str) -> ActionContext:
        return ActionContext(workspace_id=ws, requested_by="u", source="manual", dry_run=False,
                             deps=server.action_executor.deps)

    for handler in handlers:
        await handler(ctx("default"), {"related_id": "a-flag", "reason": "INJECTED", "from_name": "x"})
    rows = _activity_rows(fake)
    assert len(rows) == 3 and {r["workspace_id"] for r in rows} == {"default"}
    assert {r["related_id"] for r in rows} == {None}
    for handler in handlers:
        await handler(ctx("ws_a"), {"related_id": "a-flag"})
    own = [r for r in _activity_rows(fake) if r["workspace_id"] == "ws_a"]
    assert len(own) == 3 and {r["related_id"] for r in own} == {"a-flag"}


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
