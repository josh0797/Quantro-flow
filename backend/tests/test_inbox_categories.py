"""Industry-aware inbox categories.

A real-estate workspace classifies its mail as "Agendar visita",
"Oferta o negociación"…; a store as "Estado de pedido", "Devolución o
reembolso"… and never the other's categories. Industries without a list
(or none chosen yet) use the generic list.

* unit — list selection per industry value (aliases), list invariants,
  validation of the model's answer (unknown key → "otro"), stored fields;
* prompt — the triage prompt carries ONLY the workspace's own keys;
* dynamic — boot the real app on the in-memory PostgREST: analyze /
  batch-analyze store ai_category, GET /api/inbox/categories serves the
  workspace's list, "Reclasificar" and an industry change re-categorize
  recent items through the same AI-credit path without re-running actions.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List

import httpx
import pytest
from fastapi import HTTPException

import _import_stubs
import inbox_categories as ic
from storage_helpers import supabase_only

ALL_SETS = sorted(ic.CATEGORY_SETS)


# ── unit: list selection ────────────────────────────────────────────────

@pytest.mark.parametrize("industry,expected", [
    # Values the UI stores today (Settings → Business Profile / Welcome).
    ("real_estate", "real_estate"),
    ("ecommerce", "retail"),
    ("consulting", "professional_services"),
    ("healthcare", "healthcare"),
    ("other", ic.GENERIC),
    # onboarding_lite's list.
    ("retail", "retail"),
    ("technology", "software"),
    ("finance", "professional_services"),
    ("education", "education"),
    ("manufacturing", "manufacturing"),
    ("hospitality", "hospitality"),
    ("legal", "professional_services"),
    ("marketing", "professional_services"),
    ("construction", "professional_services"),
    ("agriculture", "manufacturing"),
    ("logistics", "manufacturing"),
    ("automotive", ic.GENERIC),
    ("nonprofit", ic.GENERIC),
    # Free-text spellings.
    ("Bienes Raíces", "real_estate"),
    (" REAL-ESTATE ", "real_estate"),
    ("E-commerce", "retail"),
    ("Restaurante", "hospitality"),
    ("SaaS", "software"),
    ("Clínica", "healthcare"),
    # Unknown / missing → generic.
    ("", ic.GENERIC),
    (None, ic.GENERIC),
    (42, ic.GENERIC),
    ("underwater basket weaving", ic.GENERIC),
])
def test_industry_resolves_to_its_category_list(industry, expected):
    assert ic.resolve_category_set(industry) == expected
    assert ic.categories_for(industry) is ic.CATEGORY_SETS[expected]["categories"]


@pytest.mark.parametrize("industry,chosen", [
    ("real_estate", True), ("automotive", True), ("other", False), ("", False), (None, False), ("  Other ", False),
])
def test_has_industry_is_false_until_a_line_of_business_is_chosen(industry, chosen):
    assert ic.has_industry(industry) is chosen


@pytest.mark.parametrize("set_key", ALL_SETS)
def test_every_list_is_well_formed(set_key):
    spec = ic.CATEGORY_SETS[set_key]
    keys = [c["key"] for c in spec["categories"]]
    assert len(keys) == len(set(keys)), "duplicate key"
    assert keys[-2:] == ["spam_promocion", "otro"], "every list ends with spam/promoción + otro"
    for field in ("label_es", "label_en", "business_context", "asset_hint"):
        assert spec[field]
    for c in spec["categories"]:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", c["key"]), c["key"]
        assert c["label_es"] and c["label_en"] and c["description"]
        assert c["suggested_action"] is None or c["suggested_action"] in ic.ACTION_TYPES


def test_the_owner_examples_land_in_the_right_lists():
    real_estate = ic.allowed_keys("real_estate")
    retail = ic.allowed_keys("ecommerce")
    assert "agendar_visita" in real_estate
    assert {"devolucion_reembolso", "pedido_entregado", "estado_pedido"} <= set(retail)
    assert "agendar_visita" not in retail
    assert not {"devolucion_reembolso", "pedido_entregado", "estado_pedido"} & set(real_estate)


def test_every_alias_points_at_a_real_list():
    assert set(ic.INDUSTRY_ALIASES.values()) <= set(ic.CATEGORY_SETS) - {ic.GENERIC}
    for alias in ic.INDUSTRY_ALIASES:
        assert ic._norm(alias) == alias, f"alias {alias!r} is not in normalised form (never matches)"


# ── unit: validation + stored fields ────────────────────────────────────

@pytest.mark.parametrize("answer,expected", [
    ("agendar_visita", ("agendar_visita", True)),
    ("  AGENDAR_VISITA ", ("agendar_visita", True)),
    ("Agendar visita", ("agendar_visita", True)),          # ES label
    ("Schedule a viewing", ("agendar_visita", True)),      # EN label
    ("otro", ("otro", True)),
    ("devolucion_reembolso", ("otro", False)),             # another industry's key
    ("made_up", ("otro", False)),
    ("", ("otro", False)),
    (None, ("otro", False)),
    (["agendar_visita"], ("otro", False)),
])
def test_normalize_category_only_accepts_the_workspaces_keys(answer, expected):
    assert ic.normalize_category(answer, "real_estate") == expected


def test_category_fields_valid_answer():
    now = datetime(2026, 9, 30, 12, 0)
    fields = ic.category_fields({"category": "devolucion_reembolso", "category_confidence": 0.91, "confidence": 0.5},
                                "ecommerce", now=now)
    assert fields == {
        "ai_category": "devolucion_reembolso",
        "ai_category_confidence": 0.91,
        "ai_category_set": "retail",
        "ai_categorized_at": now,
    }


@pytest.mark.parametrize("ai_result,expected_conf", [
    ({"category": "estado_pedido", "confidence": 0.7}, 0.7),                 # falls back to intent confidence
    ({"category": "estado_pedido", "category_confidence": "0.8"}, 0.8),
    ({"category": "estado_pedido", "category_confidence": 7}, 1.0),          # clamped
    ({"category": "estado_pedido", "category_confidence": True}, 0.0),       # bool is not a number here
    ({"category": "estado_pedido"}, 0.0),
])
def test_category_fields_confidence(ai_result, expected_conf):
    fields = ic.category_fields(ai_result, "retail")
    assert fields["ai_category"] == "estado_pedido"
    assert fields["ai_category_confidence"] == expected_conf


@pytest.mark.parametrize("ai_result", [
    {"category": "agendar_visita", "category_confidence": 0.99},   # real-estate key in a store
    {"intent": "booking", "confidence": 0.9},                      # no category at all
    None,                                                          # unparseable answer
    ["not", "a", "dict"],
])
def test_category_fields_fall_back_to_otro_with_zero_confidence(ai_result):
    fields = ic.category_fields(ai_result, "retail")
    assert fields["ai_category"] == "otro"
    assert fields["ai_category_confidence"] == 0.0
    assert fields["ai_category_set"] == "retail"


def test_public_payload_serves_labels_but_not_model_descriptions():
    payload = ic.public_payload("real_estate")
    assert payload["category_set"] == "real_estate"
    assert payload["has_industry"] is True
    assert [c["key"] for c in payload["categories"]] == ic.allowed_keys("real_estate")
    assert all(set(c) == {"key", "label_es", "label_en", "suggested_action"} for c in payload["categories"])
    other = ic.public_payload(None)
    assert other["category_set"] == ic.GENERIC and other["has_industry"] is False and other["industry"] is None


# ── prompt ──────────────────────────────────────────────────────────────

def _foreign_keys(set_key: str) -> List[str]:
    own = {c["key"] for c in ic.CATEGORY_SETS[set_key]["categories"]}
    return sorted({c["key"] for s in ic.CATEGORY_SETS.values() for c in s["categories"]} - own)


def _mentions(prompt: str, key: str) -> bool:
    return re.search(rf"(?<![a-z0-9_]){re.escape(key)}(?![a-z0-9_])", prompt) is not None


@pytest.fixture
def server_module(monkeypatch):
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
    yield fake, server, real_async_client
    for task in list(server._inbox_reclassify_tasks.values()):
        task.cancel()
    server._inbox_reclassify_tasks.clear()
    server.app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("industry", ["real_estate", "ecommerce", "retail", "consulting", "healthcare",
                                      "education", "manufacturing", "technology", "hospitality", "other"])
async def test_prompt_carries_only_the_workspaces_categories(server_module, industry):
    _, server, _ = server_module
    set_key = ic.resolve_category_set(industry)
    prompt = await server.build_intent_prompt({"industry": industry, "language": "es"}, workspace_id="ws_x")
    for key in ic.allowed_keys(industry):
        assert _mentions(prompt, key), f"{industry}: own key {key} missing"
    for key in _foreign_keys(set_key):
        assert not _mentions(prompt, key), f"{industry}: foreign key {key} leaked into the prompt"
    assert ic.CATEGORY_SETS[set_key]["business_context"] in prompt
    # The existing contract is intact (policies / actions read these).
    for field in ('"intent"', '"confidence"', '"summary"', '"entities"', '"suggested_action"',
                  '"category"', '"category_confidence"'):
        assert field in prompt
    assert "Respond in Spanish" in prompt


@pytest.mark.asyncio
async def test_prompt_asset_hint_follows_the_industry_unless_a_label_is_set(server_module):
    _, server, _ = server_module
    retail = await server.build_intent_prompt({"industry": "ecommerce"}, workspace_id="ws_x")
    assert '"asset": "<order number or product or null>"' in retail
    assert "property" not in retail.lower()
    custom = await server.build_intent_prompt({"industry": "ecommerce", "entity_labels": {"services": "Productos"}},
                                              workspace_id="ws_x")
    assert '"asset": "<Productos or null>"' in custom


# ── dynamic ─────────────────────────────────────────────────────────────

WS = "ws_cat"


class Recorder:
    """Stands in for ai_billing.run_ai_request: records prompts, answers per subject."""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self.answers: Dict[str, Dict[str, Any]] = {}
        self.default: Dict[str, Any] = {"category": "otro", "category_confidence": 0.3}
        self.raise_after: int | None = None

    async def __call__(self, *, system_prompt: str, user_prompt: str, **kw: Any) -> Dict[str, Any]:
        if self.raise_after is not None and len(self.calls) >= self.raise_after:
            raise HTTPException(status_code=402, detail={"error": "ai_blocked", "reason": "no_credits",
                                                          "message": "Sin créditos"})
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt, **kw})
        subject = re.search(r"Subject: (.*)", user_prompt).group(1)
        answer = {"intent": "inquiry", "confidence": 0.8, "summary": f"about {subject}", "entities": {},
                  "suggested_action": {"type": "flag_review", "description": "review"}}
        answer.update(self.default)
        answer.update(self.answers.get(subject, {}))
        return {"text": json.dumps(answer)}


@pytest.fixture
def app(server_module, monkeypatch):
    fake, server, real_async_client = server_module
    ai = Recorder()
    monkeypatch.setattr(server, "run_ai_request", ai)
    return fake, server, real_async_client, ai


async def _workspace(server: Any, industry: str) -> None:
    await server.workspaces_col.insert_one({"workspace_id": WS, "name": WS, "owner_user_id": "u-owner", "claimed": True})
    await server.workspace_members_col.insert_one({"workspace_id": WS, "user_id": "u-owner", "role": "owner"})
    await server.seed_workspace_config(WS, industry=industry)


async def _item(server: Any, inbox_id: str, subject: str, *, hours_ago: int = 1, **fields: Any) -> None:
    await server.inbox_col.insert_one({
        "workspace_id": WS, "inbox_id": inbox_id, "from_name": "Cliente", "from_email": "cliente@example.com",
        "subject": subject, "body": "…", "status": "new", "read": False, "is_simulation": False,
        "received_at": datetime.utcnow() - timedelta(hours=hours_ago), "ai_intent": None,
        "ai_suggested_action": None, **fields,
    })


def _client(server: Any, transport: httpx.ASGITransport, real_async_client: Any):
    user = server.User(user_id="u-owner", email="owner@example.com", name="Owner",
                       current_workspace_id=WS, access_token="test-token")
    server.app.dependency_overrides[server.get_current_user] = lambda: user
    return real_async_client(transport=transport, base_url="http://test",
                             headers={"X-Workspace-Id": WS, "Authorization": "Bearer t"})


async def _stored(server: Any, inbox_id: str) -> Dict[str, Any]:
    return await server.inbox_col.find_one({"workspace_id": WS, "inbox_id": inbox_id})


@pytest.mark.asyncio
async def test_categories_endpoint_serves_the_workspaces_list_and_is_not_an_inbox_id(app):
    _, server, RealAsyncClient, _ = app
    await _workspace(server, "real_estate")
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=True)
    async with _client(server, transport, RealAsyncClient) as http:
        r = await http.get("/api/inbox/categories")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["category_set"] == "real_estate" and body["has_industry"] is True
        keys = [c["key"] for c in body["categories"]]
        assert "agendar_visita" in keys and "devolucion_reembolso" not in keys
        labels = {c["key"]: (c["label_es"], c["label_en"]) for c in body["categories"]}
        assert labels["agendar_visita"] == ("Agendar visita", "Schedule a viewing")
        assert "description" not in body["categories"][0]

        await server.business_profile_col.update_one({"workspace_id": WS}, {"$set": {"industry": "ecommerce"}})
        body = (await http.get("/api/inbox/categories")).json()
        keys = [c["key"] for c in body["categories"]]
        assert body["category_set"] == "retail"
        assert "devolucion_reembolso" in keys and "agendar_visita" not in keys

        await server.business_profile_col.update_one({"workspace_id": WS}, {"$set": {"industry": "other"}})
        body = (await http.get("/api/inbox/categories")).json()
        assert body["category_set"] == ic.GENERIC and body["has_industry"] is False


@pytest.mark.asyncio
async def test_analyze_stores_the_category_from_the_workspaces_list(app):
    _, server, RealAsyncClient, ai = app
    await _workspace(server, "ecommerce")
    await _item(server, "i-return", "Quiero devolver mi pedido")
    ai.answers["Quiero devolver mi pedido"] = {"category": "devolucion_reembolso", "category_confidence": 0.93}
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=True)
    async with _client(server, transport, RealAsyncClient) as http:
        r = await http.post("/api/inbox/i-return/analyze")
        assert r.status_code == 200, r.text
        body = r.json()
    assert body["ai_category"] == "devolucion_reembolso"
    assert body["ai_category_confidence"] == 0.93
    assert body["ai_category_set"] == "retail"
    # Backward compatible: intent + suggested action still stored as before.
    assert body["ai_intent"]["intent"] == "inquiry"
    assert body["ai_suggested_action"]["type"] == "flag_review"
    assert body["status"] == "processed"
    # One model call, prompt with the store's list only.
    (call,) = ai.calls
    assert _mentions(call["system_prompt"], "devolucion_reembolso")
    assert not _mentions(call["system_prompt"], "agendar_visita")
    # Persisted (served back by the list endpoint the UI polls).
    stored = await _stored(server, "i-return")
    assert stored["ai_category"] == "devolucion_reembolso" and stored["ai_category_set"] == "retail"


@pytest.mark.asyncio
async def test_a_key_from_another_industry_is_stored_as_otro(app):
    _, server, RealAsyncClient, ai = app
    await _workspace(server, "real_estate")
    await _item(server, "i-x", "Mi pedido no llega")
    ai.answers["Mi pedido no llega"] = {"category": "estado_pedido", "category_confidence": 0.95}
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=True)
    async with _client(server, transport, RealAsyncClient) as http:
        assert (await http.post("/api/inbox/i-x/analyze")).status_code == 200
    stored = await _stored(server, "i-x")
    assert stored["ai_category"] == "otro"
    assert stored["ai_category_confidence"] == 0.0
    assert stored["ai_category_set"] == "real_estate"


@pytest.mark.asyncio
async def test_batch_analyze_stores_categories(app):
    _, server, RealAsyncClient, ai = app
    await _workspace(server, "real_estate")
    await _item(server, "i-visit", "Quiero ver la casa el sábado")
    await _item(server, "i-offer", "Ofrezco 2.1 millones")
    ai.answers["Quiero ver la casa el sábado"] = {"category": "agendar_visita", "category_confidence": 0.9}
    ai.answers["Ofrezco 2.1 millones"] = {"category": "Oferta o negociación", "category_confidence": 0.8}  # label
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=True)
    async with _client(server, transport, RealAsyncClient) as http:
        r = await http.post("/api/inbox/batch-analyze", json={"inbox_ids": ["i-visit", "i-offer"]})
        assert r.status_code == 200, r.text
        assert r.json()["classified"] == 2
    assert (await _stored(server, "i-visit"))["ai_category"] == "agendar_visita"
    assert (await _stored(server, "i-offer"))["ai_category"] == "oferta_negociacion"
    assert len(ai.calls) == 2  # one model call per email, no extra


async def _analyzed(server: Any, inbox_id: str, subject: str, *, category_set: str, category: str,
                    hours_ago: int = 1, status: str = "actioned") -> None:
    await _item(server, inbox_id, subject, hours_ago=hours_ago, status=status, read=True,
                ai_intent={"intent": "booking", "confidence": 0.9, "summary": "orig", "entities": {}},
                ai_suggested_action={"type": "schedule_meeting", "description": "orig"},
                policy_action="auto_run", auto_executed=True,
                ai_category=category, ai_category_set=category_set, ai_category_confidence=0.9)


@pytest.mark.asyncio
async def test_reclassify_recategorizes_stale_items_only_and_touches_nothing_else(app):
    _, server, RealAsyncClient, ai = app
    await _workspace(server, "real_estate")
    await _analyzed(server, "i-old", "Devolución de la orden 881", category_set="real_estate", category="otro")
    await _analyzed(server, "i-legacy", "Pedido entregado", category_set=None, category=None, hours_ago=2)
    await _analyzed(server, "i-current", "Estado de mi pedido", category_set="retail", category="estado_pedido",
                    hours_ago=3)
    await _item(server, "i-new", "Nunca analizado")  # not analyzed → not re-run (analyze does that)
    await server.business_profile_col.update_one({"workspace_id": WS}, {"$set": {"industry": "retail"}})
    ai.answers["Devolución de la orden 881"] = {"category": "devolucion_reembolso", "category_confidence": 0.9}
    ai.answers["Pedido entregado"] = {"category": "pedido_entregado", "category_confidence": 0.85,
                                      "intent": "spam", "suggested_action": {"type": "ignore", "description": "x"}}
    before = await _stored(server, "i-legacy")

    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=True)
    async with _client(server, transport, RealAsyncClient) as http:
        r = await http.post("/api/inbox/reclassify", json={})
        assert r.status_code == 200, r.text
        body = r.json()
    assert body == {"success": True, "category_set": "retail", "considered": 3, "reclassified": 2,
                    "skipped_up_to_date": 1, "failed": 0}
    assert sorted(re.search(r"Subject: (.*)", c["user_prompt"]).group(1) for c in ai.calls) == \
        ["Devolución de la orden 881", "Pedido entregado"]
    assert all(_mentions(c["system_prompt"], "pedido_entregado") and not _mentions(c["system_prompt"], "agendar_visita")
               for c in ai.calls)

    old = await _stored(server, "i-old")
    assert (old["ai_category"], old["ai_category_set"]) == ("devolucion_reembolso", "retail")
    legacy = await _stored(server, "i-legacy")
    assert (legacy["ai_category"], legacy["ai_category_set"]) == ("pedido_entregado", "retail")
    # Only the category moved: intent, action, status, policy and trail are untouched.
    for field in ("ai_intent", "ai_suggested_action", "status", "policy_action", "auto_executed", "read"):
        assert legacy[field] == before[field], field
    assert (await _stored(server, "i-current"))["ai_category"] == "estado_pedido"
    assert (await _stored(server, "i-new")).get("ai_category") is None

    # force=True re-runs the up-to-date one too; limit caps the run.
    ai.calls.clear()
    async with _client(server, transport, RealAsyncClient) as http:
        body = (await http.post("/api/inbox/reclassify", json={"force": True, "limit": 1})).json()
    assert body["considered"] == 1 and body["reclassified"] == 1 and len(ai.calls) == 1
    async with _client(server, transport, RealAsyncClient) as http:
        assert (await http.post("/api/inbox/reclassify", json={"limit": 51})).status_code == 422


@pytest.mark.asyncio
async def test_reclassify_stops_on_the_first_billing_block(app):
    _, server, RealAsyncClient, ai = app
    await _workspace(server, "retail")
    for n in range(6):
        await _analyzed(server, f"i-{n}", f"Pedido {n}", category_set="real_estate", category="otro", hours_ago=n + 1)
    ai.answers.update({f"Pedido {n}": {"category": "estado_pedido"} for n in range(6)})
    ai.raise_after = 2
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=True)
    async with _client(server, transport, RealAsyncClient) as http:
        r = await http.post("/api/inbox/reclassify")
    assert r.status_code == 402
    assert r.json()["detail"]["error"] == "ai_blocked"
    # First chunk (4 in flight): 2 charged + stored, the rest untouched; the second chunk never ran.
    assert len(ai.calls) == 2
    stored = [await _stored(server, f"i-{n}") for n in range(6)]
    assert sum(1 for s in stored if s["ai_category_set"] == "retail") == 2
    assert all(s["ai_category_set"] == "real_estate" for s in stored[4:])


@pytest.mark.asyncio
async def test_industry_change_recategorizes_recent_items_in_the_background(app):
    _, server, RealAsyncClient, ai = app
    await _workspace(server, "real_estate")
    await _analyzed(server, "i-1", "Quiero cambiar la talla", category_set="real_estate", category="otro")
    ai.answers["Quiero cambiar la talla"] = {"category": "cambio_producto", "category_confidence": 0.88}
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=True)
    profile = {"industry": "ecommerce", "entity_labels": {}, "simulation_mode": False}
    async with _client(server, transport, RealAsyncClient) as http:
        r = await http.put("/api/business-profile", json=profile)
        assert r.status_code == 200, r.text
        assert r.json()["inbox_reclassify_queued"] is True
        assert r.json()["industry"] == "ecommerce"
        task = server._inbox_reclassify_tasks.get(WS)
        assert task is not None
        await asyncio.wait_for(task, timeout=5)
        await asyncio.sleep(0)  # let the done-callback run
        stored = await _stored(server, "i-1")
        assert (stored["ai_category"], stored["ai_category_set"]) == ("cambio_producto", "retail")
        assert WS not in server._inbox_reclassify_tasks  # forgotten once done

        # Same list (ecommerce → retail) → nothing to redo.
        r = await http.put("/api/business-profile", json={**profile, "industry": "retail"})
        assert r.json()["inbox_reclassify_queued"] is False
        assert WS not in server._inbox_reclassify_tasks


@pytest.mark.asyncio
async def test_industry_change_without_analyzed_items_queues_nothing(app):
    _, server, RealAsyncClient, ai = app
    await _workspace(server, "other")
    await _item(server, "i-new", "Hola")
    transport = httpx.ASGITransport(app=server.app, raise_app_exceptions=True)
    async with _client(server, transport, RealAsyncClient) as http:
        r = await http.put("/api/business-profile",
                           json={"industry": "real_estate", "entity_labels": {}, "simulation_mode": False})
        assert r.status_code == 200, r.text
        assert r.json()["inbox_reclassify_queued"] is False
    assert WS not in server._inbox_reclassify_tasks
    assert ai.calls == []


@pytest.mark.asyncio
async def test_background_job_swallows_a_billing_block(app, caplog):
    _, server, RealAsyncClient, ai = app
    await _workspace(server, "real_estate")
    await _analyzed(server, "i-1", "Algo", category_set="retail", category="estado_pedido")  # stale
    ai.raise_after = 0
    user = server.User(user_id="u-owner", email="owner@example.com", name="Owner", access_token="t")
    with caplog.at_level(logging.WARNING, logger="quantro.inbox.reclassify"):
        assert await server._queue_inbox_reclassify(WS, user) is True
        await asyncio.wait_for(server._inbox_reclassify_tasks[WS], timeout=5)  # no exception escapes
    assert "inbox reclassify stopped" in caplog.text
    assert "Algo" not in caplog.text  # never customer data in logs
    assert (await _stored(server, "i-1"))["ai_category_set"] == "retail"  # previous category kept
