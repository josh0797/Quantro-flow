"""Shared wiring for storage tests: Supabase-only flags + fake PostgREST +
a Mongo tripwire that fails the test on any access."""
from __future__ import annotations

import sys
from typing import Any, List, Optional, Tuple

import pytest

from fake_postgrest import FakePostgrest

SB_URL = "https://example.supabase.co"
SB_KEY = "service-test"

FLAG_ENV = {
    "QUANTRO_DB_PRIMARY": "supabase",
    "QUANTRO_SECRETS_PRIMARY": "supabase",
    "QUANTRO_INTEGRATIONS_CONFIG_PRIMARY": "supabase",
    "QUANTRO_ACTIONS_PRIMARY": "supabase",
    "QUANTRO_INBOX_PRIMARY": "supabase",
    "QUANTRO_ACTIVITY_PRIMARY": "supabase",
    "QUANTRO_CONTENT_PRIMARY": "supabase",
    "QUANTRO_CONTACTS_PRIMARY": "supabase",
    "QUANTRO_CALENDAR_PRIMARY": "supabase",
    "QUANTRO_DOCS_PRIMARY": "supabase",
    "QUANTRO_MONGO_MIRROR": "0",
    "QUANTRO_ACTIONS_MONGO_MIRROR": "0",
    "QUANTRO_INBOX_MONGO_MIRROR": "0",
    "QUANTRO_ACTIVITY_MONGO_MIRROR": "0",
    "QUANTRO_CONTENT_MONGO_MIRROR": "0",
    "QUANTRO_CONTACTS_MONGO_MIRROR": "0",
    "QUANTRO_CALENDAR_MONGO_MIRROR": "0",
    "QUANTRO_DOCS_MONGO_MIRROR": "0",
}


class MongoTouched(AssertionError):
    pass


class TripwireMongo:
    """Stands in for a Motor collection; any use is a test failure."""

    def __init__(self, name: str, log: Optional[List[Tuple[str, str]]] = None):
        self._name = name
        self._log = log if log is not None else []

    def __getattr__(self, attr: str) -> Any:
        if attr.startswith("__"):
            raise AttributeError(attr)
        self._log.append((self._name, attr))
        raise MongoTouched(f"Mongo touched: {self._name}.{attr}")


def _variants(module: Any, holders: List[Tuple[str, str]]) -> List[Any]:
    """The module plus any older copy other modules still reference (some
    tests re-import provider_secrets_store, leaving stale references)."""
    out = [module]
    for holder_name, attr in holders:
        holder = sys.modules.get(holder_name)
        obj = getattr(holder, attr, None) if holder is not None else None
        if obj is not None and all(obj is not o for o in out):
            out.append(obj)
    return out


def supabase_only(monkeypatch: pytest.MonkeyPatch, *, mirror: bool = False) -> FakePostgrest:
    """All storage domains → Supabase (mirror off unless asked); returns the fake."""
    import doc_store
    import inbox_store
    import product_domain_store as pds
    import provider_secrets_store as pss
    import connect_store
    import sb_rest
    import supabase_admin
    from actions import store as actions_store

    monkeypatch.setenv("SUPABASE_URL", SB_URL)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", SB_KEY)
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-test")
    for k, v in FLAG_ENV.items():
        monkeypatch.setenv(k, ("1" if mirror else "0") if "MIRROR" in k else v)

    pss_all = _variants(pss, [
        ("connect_store", "secrets_store"), ("server", "secrets_store"),
        ("actions.handlers.google", "provider_secrets_store"),
        ("actions.handlers.microsoft", "provider_secrets_store"),
    ])
    connect_all = _variants(connect_store, [("server", "connect_store"),
                                            ("integrations.providers.facturapi", "connect_store")])

    # Modules that snapshot flags/config at import.
    for mod in (inbox_store, pds, actions_store, *pss_all):
        monkeypatch.setattr(mod, "SUPABASE_URL", SB_URL, raising=False)
        monkeypatch.setattr(mod, "SUPABASE_SERVICE_ROLE_KEY", SB_KEY, raising=False)
        monkeypatch.setattr(mod, "MONGO_MIRROR", mirror, raising=False)
    monkeypatch.setattr(inbox_store, "INBOX_PRIMARY", "supabase")
    monkeypatch.setattr(actions_store, "ACTIONS_PRIMARY", "supabase")
    for mod in pss_all:
        monkeypatch.setattr(mod, "SECRETS_PRIMARY", "supabase")
    for mod in connect_all:
        monkeypatch.setattr(mod, "INTEGRATIONS_CONFIG_PRIMARY", "supabase")
    monkeypatch.setattr(supabase_admin, "SUPABASE_URL", SB_URL)
    monkeypatch.setattr(supabase_admin, "SUPABASE_ANON_KEY", "anon-test")
    monkeypatch.setattr(supabase_admin, "SUPABASE_SERVICE_ROLE_KEY", SB_KEY)
    monkeypatch.setattr(supabase_admin, "DB_PRIMARY", "supabase")
    monkeypatch.setattr(supabase_admin, "MONGO_MIRROR", mirror)

    fake = FakePostgrest(base_url=SB_URL)
    for mod in (doc_store, inbox_store, pds, actions_store, *pss_all):
        monkeypatch.setattr(mod, "_sb_request", fake.request)
    monkeypatch.setattr(sb_rest, "request", fake.request)
    return fake
