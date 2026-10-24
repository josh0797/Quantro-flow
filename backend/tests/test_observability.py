"""Sentry wiring for the Flow API: no-op without DSN, secrets never leave."""
from __future__ import annotations

import sentry_sdk

import observability
from observability import (
    FILTERED,
    init_sentry,
    resolve_environment,
    resolve_release,
    scrub_breadcrumb,
    scrub_event,
    scrub_text,
)

# Obviously fake JWT-shaped value (header.payload.signature) — not a real token.
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmYWtlLXRlc3QtdXNlciJ9.ZmFrZS1zaWduYXR1cmUtZm9yLXRlc3Rz"


def test_init_is_noop_without_dsn():
    assert init_sentry({}) is False
    assert init_sentry({"SENTRY_DSN": "   "}) is False
    assert sentry_sdk.get_client().is_active() is False


def test_init_with_dsn_uses_privacy_safe_options(monkeypatch):
    captured = {}

    def fake_init(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(sentry_sdk, "init", fake_init)
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *a, **k: None)
    ok = init_sentry({
        "SENTRY_DSN": "https://public@o0.ingest.us.sentry.io/1",
        "FLY_APP_NAME": "quantro-flow-api",
        "FLY_IMAGE_REF": "registry.fly.io/quantro-flow-api:deployment-abc",
    })
    assert ok is True
    assert captured["send_default_pii"] is False
    assert captured["include_local_variables"] is False
    assert captured["max_request_body_size"] == "never"
    assert captured["environment"] == "production"
    assert captured["release"] == "registry.fly.io/quantro-flow-api:deployment-abc"
    assert 0 < captured["traces_sample_rate"] <= 0.1
    assert captured["before_send"] is scrub_event


def test_environment_and_release_resolution():
    assert resolve_environment({}) == "development"
    assert resolve_environment({"FLY_APP_NAME": "x"}) == "production"
    assert resolve_environment({"SENTRY_ENVIRONMENT": "staging", "FLY_APP_NAME": "x"}) == "staging"
    assert resolve_release({"GIT_SHA": "abc", "FLY_IMAGE_REF": "img"}) == "abc"
    assert resolve_release({}) is None


def test_scrub_text_redacts_tokens_and_pii():
    out = scrub_text(
        f"jwt {FAKE_JWT} Bearer abcdefghijklmnopqrstuv mail ana.perez@example.com "
        "rfc GODE561231GR8 curp GODE561231HDFRRN09 card 4111 1111 1111 1111"
    )
    for secret in (FAKE_JWT, "abcdefghijklmnopqrstuv", "ana.perez@example.com",
                   "GODE561231GR8", "GODE561231HDFRRN09", "4111 1111 1111 1111"):
        assert secret not in out
    assert "[EMAIL]" in out and "[CARD]" in out and "[JWT]" in out


def test_scrub_event_removes_secrets():
    event = {
        "event_id": "e1",
        "message": "failed for ana.perez@example.com",
        "request": {
            "url": "https://api.test/api/x#frag",
            "query_string": "code=abc&tab=home&access_token=zzz",
            "headers": {"Authorization": f"Bearer {FAKE_JWT}", "Cookie": "sb=1",
                        "X-Api-Key": "k", "User-Agent": "UA"},
            "cookies": {"sb": "1"},
            "data": {"password": "hunter2"},
        },
        "user": {"id": "u-1", "email": "ana.perez@example.com", "ip_address": "1.2.3.4"},
        "extra": {"supabase_service_role_key": "x", "nested": {"client_secret": "y", "note": "RFC GODE561231GR8"}},
        "exception": {"values": [{"type": "ValueError", "value": f"bad {FAKE_JWT}",
                                  "stacktrace": {"frames": [{"filename": "server.py", "lineno": 1, "vars": {"token": "t"}}]}}]},
        "breadcrumbs": {"values": [{"category": "httplib", "data": {"url": "https://x/y?apikey=1", "body": "{}"}}]},
    }
    out = scrub_event(event)
    blob = repr(out)
    for secret in (FAKE_JWT, "hunter2", "ana.perez@example.com", "GODE561231GR8", "zzz", "abc&"):
        assert secret not in blob
    assert out["request"]["headers"]["Authorization"] == FILTERED
    assert out["request"]["headers"]["Cookie"] == FILTERED
    assert out["request"]["headers"]["X-Api-Key"] == FILTERED
    assert out["request"]["headers"]["User-Agent"] == "UA"
    assert "cookies" not in out["request"] and "data" not in out["request"]
    assert out["request"]["query_string"] == f"code={FILTERED}&tab=home&access_token={FILTERED}"
    assert out["user"] == {"id": "u-1"}
    assert out["extra"]["supabase_service_role_key"] == FILTERED
    assert out["extra"]["nested"]["client_secret"] == FILTERED
    assert "vars" not in out["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert out["breadcrumbs"]["values"][0]["data"] == {"url": "https://x/y"}


def test_scrub_breadcrumb_drops_bodies():
    crumb = scrub_breadcrumb({"message": "sent to ana@example.com", "data": {"body": "x", "status_code": 500}})
    assert crumb == {"message": "sent to [EMAIL]", "data": {"status_code": 500}}


def test_module_has_no_side_effects_on_import():
    # Importing server-side helpers must never initialise the SDK by itself.
    assert observability.init_sentry is init_sentry
    assert sentry_sdk.get_client().is_active() is False
