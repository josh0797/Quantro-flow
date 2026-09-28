"""With every storage flag on Supabase (mirror off), nothing touches Mongo.

Two layers:

* static — only mongo_legacy.py may construct a Motor client, and server.py
  may only index ``db[...]`` where it binds collections (plus the legacy
  sync-lock branch that runs only while docs are Mongo-primary);
* dynamic — boot the real app against an in-memory PostgREST, run every
  startup job, the auth/upsert path, the autosync helpers, and call EVERY
  registered route. A tripwire on mongo_legacy records any Mongo access
  (and refuses to connect). The test fails if a single access happened.

The dynamic sweep is only as deep as empty-ish data lets each handler go,
so it is paired with the per-store Supabase-only tests
(test_supabase_only_stores.py, test_doc_store.py).
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
import pytest

import _import_stubs
from storage_helpers import SB_URL, supabase_only

BACKEND = Path(__file__).resolve().parents[1]


# ── static ──────────────────────────────────────────────────────────────

# Legacy ad-hoc QA script from the Emergent era (reads /app/backend/.env and
# talks to a live Mongo). Not imported by the app; kept out of the scan.
LEGACY_SCRIPTS = {"backend_test.py"}


def _py_files() -> List[Path]:
    skip = {"tests", "scripts", ".venv", "__pycache__"}
    return [
        p for p in BACKEND.rglob("*.py")
        if not (set(p.relative_to(BACKEND).parts) & skip) and p.name not in LEGACY_SCRIPTS
    ]


def test_only_mongo_legacy_opens_a_client():
    offenders = []
    for path in _py_files():
        text = path.read_text()
        if path.name == "mongo_legacy.py":
            continue
        if re.search(r"AsyncIOMotorClient|MongoClient\(|from motor|import motor", text):
            offenders.append(str(path.relative_to(BACKEND)))
    assert offenders == []


def test_pymongo_only_optional_or_legacy_branch():
    allowed = {"mongo_compat.py", "mongo_legacy.py", "sync_lock.py"}
    offenders = [
        str(p.relative_to(BACKEND)) for p in _py_files()
        if p.name not in allowed and re.search(r"^\s*(from|import) (pymongo|bson)", p.read_text(), re.M)
    ]
    assert offenders == []


def test_server_indexes_db_only_where_collections_are_bound():
    tree = ast.parse((BACKEND / "server.py").read_text())
    allowed_functions = {"_doc_col", "_acquire_sync_lock"}
    bad: List[Tuple[int, str]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.stack: List[str] = []

        def visit_FunctionDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Subscript(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == "db":
                fn = self.stack[-1] if self.stack else "<module>"
                if fn != "<module>" and fn not in allowed_functions:
                    bad.append((node.lineno, fn))
            self.generic_visit(node)

    Visitor().visit(tree)
    assert bad == []


# ── dynamic ─────────────────────────────────────────────────────────────

class Tripwire:
    def __init__(self):
        self.events: List[Tuple[str, str, Any, bool]] = []

    def __call__(self, event):
        self.events.append(event)


def _example(schema: Dict[str, Any], components: Dict[str, Any], depth: int = 0) -> Any:
    if depth > 6:
        return None
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return _example(components.get(name, {}), components, depth + 1)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [s for s in schema[key] if s.get("type") != "null"]
            return _example(options[0], components, depth + 1) if options else None
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        return {k: _example(v, components, depth + 1) for k, v in (schema.get("properties") or {}).items()}
    if t == "array":
        return []
    if t == "integer":
        return 1
    if t == "number":
        return 0.9
    if t == "boolean":
        return False
    if schema.get("format") == "date-time":
        return "2026-09-29T10:00:00+00:00"
    return "x"


PATH_VALUES = {
    "workspace_id": "ws_test", "inbox_id": "inbox-1", "provider": "openai", "token": "tok-1",
    "invite_id": "inv-1", "member_user_id": "u-test", "target_user_id": "u-other", "step_key": "first_login",
    "event_id": "ev-1", "contact_id": "c-1", "task_id": "t-1", "content_id": "ct-1", "policy_id": "p-1",
    "rule_id": "r-1", "template_id": "tpl-1", "execution_id": "e-1", "action_id": "quantro.review.flag",
    "connection_id": "conn-1", "webhook_token": "wh-1",
}


@pytest.fixture
def app_env(monkeypatch):
    _import_stubs.install()
    fake = supabase_only(monkeypatch)
    monkeypatch.setenv("MONGO_URL", "mongodb://tripwire.invalid:27017")  # configured, must stay unused
    monkeypatch.setenv("FRONTEND_PUBLIC_URL", "https://www.quantroflow.cloud")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    import mongo_legacy
    import server

    trip = Tripwire()
    mongo_legacy.add_listener(trip)

    def no_connect():
        raise AssertionError("Mongo client requested while every flag says Supabase")

    monkeypatch.setattr(mongo_legacy, "_get_client", no_connect)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", fake.async_client_factory(real_async_client))
    yield fake, trip, server, real_async_client
    mongo_legacy.remove_listener(trip)
    server.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_no_request_path_touches_mongo_when_flags_say_supabase(app_env):
    fake, trip, server, RealAsyncClient = app_env
    import mongo_legacy

    # Startup (seed + repairs + role migration + automations backfill).
    outcome = await server.run_startup_jobs()
    assert outcome and all(v == "ok" for v in outcome.values()), outcome

    # The real auth upsert path (first login → claims the default workspace).
    user_doc = await server._upsert_user_from_claims({"sub": "u-test", "email": "tester@example.com"})
    assert user_doc["current_workspace_id"]
    await server._upsert_user_from_claims({"sub": "u-test", "email": "tester@example.com"})  # returning user

    # A second workspace with data so handlers go past their 404s.
    await server.workspaces_col.insert_one({"workspace_id": "ws_test", "name": "Test", "owner_user_id": "u-test", "claimed": True})
    await server.workspace_members_col.insert_one({"workspace_id": "ws_test", "user_id": "u-test", "role": "owner"})
    await server.seed_workspace_config("ws_test")
    await server.inbox_col.insert_one({
        "inbox_id": "inbox-1", "workspace_id": "ws_test", "from_name": "Sarah", "from_email": "s@x.com",
        "subject": "Viewing", "body": "Hi", "status": "processed", "is_simulation": False,
        "ai_intent": {"intent": "booking", "confidence": 0.95, "summary": "s", "entities": {}},
        "ai_suggested_action": {"type": "flag_review", "description": "d"},
    })
    await server.workspace_invites_col.insert_one({"invite_id": "inv-1", "workspace_id": "ws_test", "token": "tok-1",
                                                   "role": "member", "max_uses": 5, "used_count": 0, "accepted_by": []})
    # One entity per id the sweep uses, so update/delete handlers run for real.
    await server.workspace_members_col.insert_one({"workspace_id": "ws_test", "user_id": "u-other", "role": "member"})
    await server.calendar_col.insert_one({"event_id": "ev-1", "workspace_id": "ws_test", "title": "E", "external_provider": "internal"})
    await server.contacts_col.insert_one({"contact_id": "c-1", "workspace_id": "ws_test", "name": "C", "is_simulation": False})
    await server.onboarding_col.insert_one({"task_id": "t-1", "agent_id": "a-1", "workspace_id": "ws_test", "title": "T", "status": "pending"})
    await server.content_col.insert_one({"content_id": "ct-1", "workspace_id": "ws_test", "type": "social_post", "title": "C"})
    await server.policies_col.insert_one({"policy_id": "p-1", "workspace_id": "ws_test", "intent": "booking", "action": "auto_run", "enabled": True})
    await server.escalation_col.insert_one({"rule_id": "r-1", "workspace_id": "ws_test", "name": "R", "condition_type": "intent",
                                            "condition_value": "booking", "route_to": "Lead", "priority": "high", "enabled": True})
    await server.templates_col.insert_one({"template_id": "tpl-1", "workspace_id": "ws_test", "name": "W", "category": "welcome",
                                           "template_type": "email", "body_template": "Hi {{contact_name}}", "tags": []})
    await server.action_executions_col.insert_one({"execution_id": "e-1", "workspace_id": "ws_test", "action_id": "quantro.review.flag",
                                                   "status": "pending_approval", "input": {}, "result_metadata": {}})

    # Autosync helpers (the loop itself sleeps 60 s first).
    assert await server._acquire_sync_lock("google", "ws_test")
    await server._perform_google_sync_for_workspace("ws_test")
    await server._perform_microsoft_sync_for_workspace("ws_test")
    for prov, col in (("google", server.google_integrations_col), ("microsoft", server.microsoft_integrations_col)):
        await server.secrets_store.list_autosync_workspace_ids(provider=prov, mongo_col=col)

    user = server.User(user_id="u-test", email="tester@example.com", name="Tester",
                       current_workspace_id="ws_test", access_token="test-token")
    server.app.dependency_overrides[server.get_current_user] = lambda: user

    spec = server.app.openapi()
    components = spec.get("components", {}).get("schemas", {})
    statuses: Dict[str, int] = {}
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=False)
    async with RealAsyncClient(transport=transport, base_url="http://test") as client:
        for path, methods in spec["paths"].items():
            for method, op in methods.items():
                url = re.sub(r"\{(\w+)\}", lambda m: PATH_VALUES.get(m.group(1), "x"), path)
                params = {
                    p["name"]: _example(p.get("schema", {}), components)
                    for p in op.get("parameters", [])
                    if p.get("in") == "query" and p.get("required")
                }
                body = None
                content = (op.get("requestBody") or {}).get("content", {})
                if "application/json" in content:
                    body = _example(content["application/json"].get("schema", {}), components)
                resp = await client.request(method.upper(), url, params=params, json=body,
                                            headers={"X-Workspace-Id": "ws_test", "Authorization": "Bearer t"})
                statuses[f"{method.upper()} {path}"] = resp.status_code

    if os.environ.get("SWEEP_DEBUG"):
        from collections import Counter
        print("\nSTATUS COUNTS", Counter(statuses.values()))
        for k, v in sorted(statuses.items()):
            print(v, k)
    assert len(statuses) >= 90  # every route was called
    assert trip.events == [], f"Mongo touched: {trip.events[:10]}"
    assert mongo_legacy.client_created() is False
    # Most handlers must actually succeed against Supabase, not just avoid Mongo.
    server_errors = {k: v for k, v in statuses.items() if v >= 500 and v != 503}
    unavailable = {k: v for k, v in statuses.items() if v == 503}
    assert not [k for k in unavailable if "storage" in k], unavailable
    assert len(server_errors) <= 6, server_errors


@pytest.mark.asyncio
async def test_tripwire_is_not_vacuous(app_env, monkeypatch):
    """Flip one domain back to Mongo: the same tripwire must fire."""
    fake, trip, server, _ = app_env
    monkeypatch.setenv("QUANTRO_DOCS_PRIMARY", "mongo")
    with pytest.raises(AssertionError, match="Mongo client requested"):
        await server.users_col.find_one({"user_id": "u-test"})
    assert trip.events and trip.events[0][0] == "users"
