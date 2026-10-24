"""Fail-safe defaults: an unset storage flag means Supabase, no Mongo mirror."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import storage_flags

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _clear(monkeypatch):
    for k in list(os.environ):
        if k.startswith("QUANTRO_") and ("PRIMARY" in k or "MIRROR" in k):
            monkeypatch.delenv(k, raising=False)


def test_unset_primary_is_supabase_and_mirror_off(monkeypatch):
    _clear(monkeypatch)
    for domain in storage_flags.DOMAIN_FLAGS:
        assert storage_flags.domain_primary(domain) == "supabase", domain
        assert storage_flags.domain_mirror(domain) is False, domain
    assert storage_flags.parse_primary("QUANTRO_NOT_A_FLAG") == "supabase"
    monkeypatch.setenv("QUANTRO_CALENDAR_PRIMARY", "bogus")
    assert storage_flags.domain_primary("calendar") == "supabase"


def test_escape_hatch_and_mirror_precedence(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("QUANTRO_CALENDAR_PRIMARY", "mongo")
    assert storage_flags.domain_primary("calendar") == "mongo"
    monkeypatch.setenv("QUANTRO_MONGO_MIRROR", "1")
    assert storage_flags.domain_mirror("inbox") is True           # shared flag
    monkeypatch.setenv("QUANTRO_INBOX_MONGO_MIRROR", "0")
    assert storage_flags.domain_mirror("inbox") is False          # dedicated wins
    monkeypatch.setenv("QUANTRO_INBOX_MONGO_MIRROR", "")
    assert storage_flags.domain_mirror("inbox") is True           # blank → shared


def test_uses_mongo_requires_supabase_config(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    assert storage_flags.domain_uses_mongo("docs") is True  # no Supabase → Mongo only
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    assert storage_flags.domain_uses_mongo("docs") is False
    summary = storage_flags.summary()
    assert summary["mongo_required"] is False
    assert "MONGO_URL" not in json.dumps(summary)  # names only, never values


def test_import_time_defaults_of_every_store():
    """Modules that snapshot flags at import default to Supabase / no mirror."""
    env = {k: v for k, v in os.environ.items() if not (k.startswith("QUANTRO_") and ("PRIMARY" in k or "MIRROR" in k))}
    env.update({
        "SUPABASE_URL": "https://x.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "k",
        "SUPABASE_ANON_KEY": "a",
        "PYTHONPATH": BACKEND,
    })
    env.pop("MONGO_URL", None)
    code = """
import json
import inbox_store, provider_secrets_store as pss, connect_store, supabase_admin
import product_domain_store as pds
from actions import store as actions_store
print(json.dumps({
  "inbox": [inbox_store.INBOX_PRIMARY, inbox_store.MONGO_MIRROR, inbox_store.is_inbox_mongo_write_enabled()],
  "actions": [actions_store.ACTIONS_PRIMARY, actions_store.MONGO_MIRROR, actions_store.is_actions_mongo_write_enabled()],
  "secrets": [pss.SECRETS_PRIMARY, pss.MONGO_MIRROR, pss.is_secrets_mongo_write_enabled()],
  "integrations": [connect_store.INTEGRATIONS_CONFIG_PRIMARY, connect_store.is_integrations_mongo_write_enabled()],
  "identity": [supabase_admin.DB_PRIMARY, supabase_admin.is_mongo_mirror_enabled()],
  "calendar": [pds.is_supabase_primary(pds.CALENDAR_CFG), pds.is_mongo_write(pds.CALENDAR_CFG)],
  "contacts": [pds.is_supabase_primary(pds.CONTACTS_CFG), pds.is_mongo_write(pds.CONTACTS_CFG)],
}))
"""
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=BACKEND, capture_output=True, text=True, check=True)
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got == {
        "inbox": ["supabase", False, False],
        "actions": ["supabase", False, False],
        "secrets": ["supabase", False, False],
        "integrations": ["supabase", False],
        "identity": ["supabase", False],
        "calendar": [True, False],
        "contacts": [True, False],
    }
