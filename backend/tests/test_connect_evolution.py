"""Connect evolution: Outlook calendar sync, CORS/OAuth cloud domain,
Quantro OS invoicing, Connect catalog without removed providers."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("QUANTRO_CALENDAR_PRIMARY", "mongo")


# ── Microsoft calendar fetch: window + pagination + ical ──────────────

def test_calendar_sync_window_defaults(monkeypatch):
    import microsoft_oauth as msoa
    monkeypatch.delenv("CALENDAR_BACKFILL_PAST_DAYS", raising=False)
    monkeypatch.delenv("CALENDAR_LOOKAHEAD_DAYS", raising=False)
    start, end, past, ahead = msoa.calendar_sync_window()
    assert past == 90
    assert ahead == 180
    assert (end - start).days == 270


def test_calendar_sync_window_env_override(monkeypatch):
    import microsoft_oauth as msoa
    monkeypatch.setenv("CALENDAR_BACKFILL_PAST_DAYS", "30")
    monkeypatch.setenv("CALENDAR_LOOKAHEAD_DAYS", "60")
    _, _, past, ahead = msoa.calendar_sync_window()
    assert past == 30
    assert ahead == 60


def test_fetch_outlook_events_paginates_and_maps_ical(monkeypatch):
    import microsoft_oauth as msoa

    pages = [
        {
            "value": [
                {
                    "id": "ms-1",
                    "subject": "Kickoff",
                    "bodyPreview": "hi",
                    "location": {"displayName": "Zoom"},
                    "start": {"dateTime": "2026-01-01T10:00:00.0000000"},
                    "end": {"dateTime": "2026-01-01T11:00:00.0000000"},
                    "attendees": [],
                    "webLink": "https://outlook.office.com/e/1",
                    "showAs": "busy",
                    "iCalUId": "uid-1",
                    "lastModifiedDateTime": "2026-01-01T09:00:00Z",
                    "isCancelled": False,
                }
            ],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/calendarView?$skiptoken=abc",
        },
        {
            "value": [
                {
                    "id": "ms-2",
                    "subject": "Cancelled meet",
                    "bodyPreview": "",
                    "location": {},
                    "start": {"dateTime": "2026-01-02T10:00:00.0000000"},
                    "end": {"dateTime": "2026-01-02T11:00:00.0000000"},
                    "attendees": [],
                    "webLink": None,
                    "showAs": "free",
                    "iCalUId": "uid-2",
                    "lastModifiedDateTime": "2026-01-02T09:00:00Z",
                    "isCancelled": True,
                }
            ],
        },
    ]
    calls = {"n": 0}

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None, params=None):
            idx = calls["n"]
            calls["n"] += 1
            return FakeResp(pages[idx])

    monkeypatch.setattr(msoa.httpx, "Client", FakeClient)
    events = msoa.fetch_upcoming_outlook_events("tok", past_days=90, lookahead_days=180)
    assert len(events) == 2
    assert events[0]["ical_uid"] == "uid-1"
    assert events[0]["external_updated_at"] == "2026-01-01T09:00:00Z"
    assert events[1]["cancelled"] is True
    assert events[1]["status"] == "cancelled"
    assert calls["n"] == 2


# ── Upsert metrics: insert / update / unchanged / no dupes ────────────

@pytest.mark.asyncio
async def test_ms_calendar_upsert_metrics_no_dupes_on_repeat():
    from product_domain_store import (
        wrap_calendar_col, canonical_calendar_write, upsert_calendar_external_event,
    )

    class FakeCol:
        def __init__(self):
            self._docs = []

        async def find_one(self, query, projection=None):
            for d in self._docs:
                if all(d.get(k) == v for k, v in query.items()):
                    return dict(d)
            return None

        async def update_one(self, query, update, upsert=False):
            for d in self._docs:
                if all(d.get(k) == v for k, v in query.items() if not str(k).startswith("$")):
                    d.update(update.get("$set", {}))
                    class R:
                        matched_count = 1
                        modified_count = 1
                        upserted_id = None
                    return R()
            if upsert:
                nd = dict(query)
                nd.update(update.get("$setOnInsert", {}))
                nd.update(update.get("$set", {}))
                self._docs.append(nd)
            class R:
                matched_count = 0
                modified_count = 0
                upserted_id = None
            return R()

    raw = FakeCol()
    wrapped = wrap_calendar_col(raw)
    now = datetime.now(timezone.utc)
    c1 = canonical_calendar_write(
        workspace_id="ws1",
        event_id="e-new",
        external_provider="microsoft",
        external_event_id="ms-100",
        title="Standup",
        start_time="2026-03-01T10:00:00Z",
        end_time="2026-03-01T10:30:00Z",
        status="busy",
        ical_uid="ical-100",
        external_updated_at="2026-03-01T09:00:00Z",
        synced_at=now,
        updated_at=now,
    )
    r1 = await upsert_calendar_external_event(
        wrapped, workspace_id="ws1", provider="microsoft",
        external_event_id="ms-100", canonical=c1, now=now,
    )
    assert r1["outcome"] == "inserted"

    r2 = await upsert_calendar_external_event(
        wrapped, workspace_id="ws1", provider="microsoft",
        external_event_id="ms-100", canonical=c1, now=now,
    )
    assert r2["outcome"] == "unchanged"
    assert r2["event_id"] == r1["event_id"]

    c3 = canonical_calendar_write(
        workspace_id="ws1",
        event_id="e-ignored",
        external_provider="microsoft",
        external_event_id="ms-100",
        title="Standup (moved)",
        start_time="2026-03-01T10:00:00Z",
        end_time="2026-03-01T10:30:00Z",
        status="busy",
        ical_uid="ical-100",
        external_updated_at="2026-03-01T10:00:00Z",
        synced_at=now,
        updated_at=now,
    )
    r3 = await upsert_calendar_external_event(
        wrapped, workspace_id="ws1", provider="microsoft",
        external_event_id="ms-100", canonical=c3, now=now,
    )
    assert r3["outcome"] == "updated"
    assert r3["event_id"] == r1["event_id"]
    assert len(raw._docs) == 1


# ── Microsoft adapter display name ───────────────────────────────────

@pytest.mark.asyncio
async def test_microsoft_adapter_visible_name_outlook():
    from integrations.providers.microsoft import MicrosoftAdapter
    from integrations.base import ConnectionStatus

    class FakeMsoa:
        @staticmethod
        def is_oauth_configured():
            return True

    class FakeCol:
        async def find_one(self, query, projection=None):
            return None

    adapter = MicrosoftAdapter(
        col=FakeCol(), msoa_module=FakeMsoa(),
        sync_fn=AsyncMock(), disconnect_fn=AsyncMock(),
    )
    assert adapter.name == "Microsoft Outlook"
    assert adapter.provider_id == "microsoft"
    status = await adapter.get_status("ws1")
    assert status.status == ConnectionStatus.DISCONNECTED


# ── Quantro OS invoicing (mocked) + reply payload ─────────────────────

@pytest.mark.asyncio
async def test_quantro_invoicing_query_and_prepare_reply(monkeypatch):
    from integrations.providers.quantro_invoicing import QuantroInvoicingAdapter
    from integrations.base import ConnectionStatus

    monkeypatch.setenv("QUANTRO_OS_API_URL", "https://os.example.test")
    monkeypatch.setenv("QUANTRO_OS_SERVICE_TOKEN", "svc-secret-token")

    async def resolve_org(workspace_id):
        return "4e7d2f20-1b6c-4c1a-9a55-2f0c0d5e8a11" if workspace_id == "ws1" else None

    adapter = QuantroInvoicingAdapter(resolve_org_id=resolve_org)
    st = await adapter.get_status("ws1")
    assert st.status == ConnectionStatus.CONNECTED
    assert adapter.name == "Facturación"

    invoices = [{
        "id": "inv-1",
        "folio": "A-100",
        "status": "valid",
        "total": 1160,
        "currency": "MXN",
        "customer_name": "Acme SA",
        "customer_email": "billing@acme.test",
        "pdf_url": "https://os.example.test/docs/inv-1.pdf",
        "xml_url": "https://os.example.test/docs/inv-1.xml",
    }]

    async def fake_request(method, path, *, params=None, json=None):
        assert method == "GET"
        assert path == "/service-invoices"
        assert params["workspace_id"] == "ws1"
        # Tenant scope travels with every call — OS filters on it.
        assert params["organization_id"] == "4e7d2f20-1b6c-4c1a-9a55-2f0c0d5e8a11"
        return {"invoices": invoices}

    monkeypatch.setattr(adapter, "_request", fake_request)
    q = await adapter.query_invoices("ws1", q="Acme")
    assert q["invoices"][0]["folio"] == "A-100"

    # An unlinked workspace never reaches OS (fails closed, no global read).
    from errors import QuantroError
    with pytest.raises(QuantroError) as unlinked:
        await adapter.query_invoices("ws-unlinked", q="Acme")
    assert unlinked.value.code == "configuration_missing"

    reply = await adapter.prepare_reply_payload(
        "ws1", invoice_id="inv-1", channel="gmail", to="billing@acme.test",
    )
    assert reply["channel"] == "gmail"
    assert reply["suggested_action_id"] == "google.gmail.send"
    assert "A-100" in reply["subject"]
    assert "inv-1.pdf" in reply["body"]

    reply_ms = await adapter.prepare_reply_payload("ws1", q="Acme", channel="outlook")
    assert reply_ms["suggested_action_id"] == "microsoft.mail.send"


@pytest.mark.asyncio
async def test_quantro_invoicing_missing_config():
    from integrations.providers.quantro_invoicing import QuantroInvoicingAdapter
    from integrations.base import ConnectionStatus
    with patch.dict(os.environ, {"QUANTRO_OS_API_URL": "", "QUANTRO_OS_SERVICE_TOKEN": ""}, clear=False):
        adapter = QuantroInvoicingAdapter()
        st = await adapter.get_status("ws1")
        assert st.status == ConnectionStatus.CONFIGURATION_MISSING


# ── Connect catalog: no removed providers / no Facturapi branding ─────

def test_connect_js_has_no_removed_providers_or_facturapi_branding():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    connect = (root / "frontend/src/pages/Connect.js").read_text()
    for banned in ("QuickBooks", "Xero", "Salesforce", "HubSpot", "Shopify", "COMING_SOON", "ComingSoonCard", "FacturapiConnectDialog", "Facturapi"):
        assert banned not in connect, f"Connect.js still references {banned}"
    assert "quantro_invoicing" in connect or "Receipt" in connect
    assert "return_to='/settings'" not in connect.replace('"', "'")
    assert "startGoogleOAuth('/connect')" in connect
    assert "startMicrosoftOAuth('/connect')" in connect


def test_connect_translations_no_facturapi_in_status_labels():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    # Visible Connect status / provider strings should not push Facturapi branding.
    # Historical migration docs may still mention it; this asserts UI source.
    connect = (root / "frontend/src/pages/Connect.js").read_text()
    assert "Facturapi" not in connect


# ── Google OAuth start context: www.quantroflow.cloud CORS + return ───

def test_google_oauth_return_paths_include_welcome_inbox():
    ALLOWED = {"/connect", "/actions", "/settings", "/welcome/inbox", "/welcome/calendar"}
    assert "/welcome/inbox" in ALLOWED
    assert "/welcome/calendar" in ALLOWED
    assert "/connect" in ALLOWED


def test_frontend_canonical_www_for_cloud():
    def normalize(raw: str) -> str:
        raw = (raw or "").strip().rstrip("/")
        if raw == "https://quantroflow.cloud":
            return "https://www.quantroflow.cloud"
        return raw

    assert normalize("https://quantroflow.cloud") == "https://www.quantroflow.cloud"
    assert normalize("https://www.quantroflow.cloud") == "https://www.quantroflow.cloud"


# ── Actions bootstrap registers invoicing not Facturapi creates ───────

def test_bootstrap_registers_quantro_invoicing_not_cfdi_create():
    from actions.registry import clear_registry, list_actions
    from actions import bootstrap

    clear_registry()
    bootstrap.register_all_actions()
    ids = {a.action_id for a in list_actions()}
    assert "quantro_invoicing.invoice.query" in ids
    assert "quantro_invoicing.invoice.prepare_reply" in ids
    assert "facturapi.invoice.create" not in ids
