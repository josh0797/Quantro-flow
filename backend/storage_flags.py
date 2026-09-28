"""Storage routing flags for the Mongo → Supabase exit.

Every store picks its primary (``mongo`` | ``supabase``) and whether Mongo
is kept as a mirror from env flags. Since the Mongo exit the DEFAULTS are
fail-safe for the future: an unset primary flag means ``supabase`` and an
unset mirror flag means "no Mongo mirror". The flags stay as an escape hatch
(set ``QUANTRO_<DOMAIN>_PRIMARY=mongo`` to roll a domain back).

Supabase-primary still requires ``SUPABASE_URL`` + ``SUPABASE_SERVICE_ROLE_KEY``;
without them (local dev, most unit tests) every store keeps using Mongo.

Domains and their flags (identity = ``QUANTRO_DB_PRIMARY`` is handled by
supabase_admin; Flow's own member/invite/audit docs are the ``docs`` domain)::

    secrets         QUANTRO_SECRETS_PRIMARY               mirror: QUANTRO_MONGO_MIRROR
    integrations    QUANTRO_INTEGRATIONS_CONFIG_PRIMARY   mirror: QUANTRO_MONGO_MIRROR
    actions         QUANTRO_ACTIONS_PRIMARY               mirror: QUANTRO_ACTIONS_MONGO_MIRROR
    inbox           QUANTRO_INBOX_PRIMARY                 mirror: QUANTRO_INBOX_MONGO_MIRROR
    activity        QUANTRO_ACTIVITY_PRIMARY              mirror: QUANTRO_ACTIVITY_MONGO_MIRROR
    content         QUANTRO_CONTENT_PRIMARY               mirror: QUANTRO_CONTENT_MONGO_MIRROR
    contacts        QUANTRO_CONTACTS_PRIMARY              mirror: QUANTRO_CONTACTS_MONGO_MIRROR
    calendar        QUANTRO_CALENDAR_PRIMARY              mirror: QUANTRO_CALENDAR_MONGO_MIRROR
    docs            QUANTRO_DOCS_PRIMARY                  mirror: QUANTRO_DOCS_MONGO_MIRROR
                    (users, workspaces, members, invites, audit_log,
                     people_onboarding_steps, business_profile, agents,
                     onboarding_tasks, escalation_rules,
                     system_health_events, sync locks)

A dedicated ``*_MONGO_MIRROR`` flag wins; when it is unset the shared
``QUANTRO_MONGO_MIRROR`` applies; when both are unset there is no mirror.

Some modules snapshot their flags at import (inbox_store, actions.store,
provider_secrets_store, connect_store, supabase_admin) — they call the
parsers below at import time. doc_store / product_domain_store read per call.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

DEFAULT_PRIMARY = "supabase"
_PRIMARY_VALUES = {"mongo", "supabase"}
_FALSEY = {"0", "false", "no", "off"}

# Greppable WARNING tags for the cutover (docs/mongo-exit-runbook.md).
# Flow configures no logging, so only WARNING+ reaches `fly logs`.
#   MONGO_ONLY  — Mongo holds (or just received) data Supabase lacks: a
#                 Supabase write degraded to Mongo, a shadow copy failed, or
#                 a read was answered from Mongo. `--apply` repairs these.
#   STORE_DRIFT — the stores disagree in a way the backfill does NOT repair:
#                 a Mongo mirror write/delete failed while Supabase is
#                 primary (Mongo now stale), or a shadow delete failed while
#                 Mongo is primary (Supabase kept a row). Review by hand.
MONGO_ONLY = "MONGO_ONLY"
STORE_DRIFT = "STORE_DRIFT"

DOMAIN_FLAGS: Dict[str, Dict[str, Optional[str]]] = {
    "secrets": {"primary": "QUANTRO_SECRETS_PRIMARY", "mirror": None},
    "integrations": {"primary": "QUANTRO_INTEGRATIONS_CONFIG_PRIMARY", "mirror": None},
    "actions": {"primary": "QUANTRO_ACTIONS_PRIMARY", "mirror": "QUANTRO_ACTIONS_MONGO_MIRROR"},
    "inbox": {"primary": "QUANTRO_INBOX_PRIMARY", "mirror": "QUANTRO_INBOX_MONGO_MIRROR"},
    "activity": {"primary": "QUANTRO_ACTIVITY_PRIMARY", "mirror": "QUANTRO_ACTIVITY_MONGO_MIRROR"},
    "content": {"primary": "QUANTRO_CONTENT_PRIMARY", "mirror": "QUANTRO_CONTENT_MONGO_MIRROR"},
    "contacts": {"primary": "QUANTRO_CONTACTS_PRIMARY", "mirror": "QUANTRO_CONTACTS_MONGO_MIRROR"},
    "calendar": {"primary": "QUANTRO_CALENDAR_PRIMARY", "mirror": "QUANTRO_CALENDAR_MONGO_MIRROR"},
    "docs": {"primary": "QUANTRO_DOCS_PRIMARY", "mirror": "QUANTRO_DOCS_MONGO_MIRROR"},
}


def parse_primary(env_name: str) -> str:
    """``mongo`` or ``supabase``; unset/blank/invalid → ``supabase``."""
    raw = (os.environ.get(env_name) or "").lower().strip()
    return raw if raw in _PRIMARY_VALUES else DEFAULT_PRIMARY


def parse_mirror(dedicated_env: Optional[str] = None) -> bool:
    """Mongo mirror on/off. Dedicated flag → shared flag → default off."""
    raw: Optional[str] = None
    if dedicated_env:
        val = os.environ.get(dedicated_env)
        if val is not None and val.strip() != "":
            raw = val
    if raw is None:
        shared = os.environ.get("QUANTRO_MONGO_MIRROR")
        if shared is not None and shared.strip() != "":
            raw = shared
    if raw is None:
        return False
    return raw.lower().strip() not in _FALSEY


def supabase_configured() -> bool:
    return bool(
        (os.environ.get("SUPABASE_URL") or "").strip()
        and (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    )


def domain_primary(domain: str) -> str:
    return parse_primary(DOMAIN_FLAGS[domain]["primary"] or "")


def domain_mirror(domain: str) -> bool:
    return parse_mirror(DOMAIN_FLAGS[domain]["mirror"])


def domain_on_supabase(domain: str) -> bool:
    """Supabase is the read/write primary for ``domain`` (per-call read)."""
    return domain_primary(domain) == "supabase" and supabase_configured()


def domain_uses_mongo(domain: str) -> bool:
    """Whether ``domain`` may touch Mongo at all (primary or mirror)."""
    if not domain_on_supabase(domain):
        return True
    return domain_mirror(domain)


def summary() -> Dict[str, Any]:
    """Effective flags (no secrets) — surfaced by /api/ready."""
    out: Dict[str, Any] = {
        "supabase_configured": supabase_configured(),
        "identity": {"primary": parse_primary("QUANTRO_DB_PRIMARY")},
    }
    for domain, names in DOMAIN_FLAGS.items():
        out[domain] = {
            "primary": domain_primary(domain),
            "mongo_mirror": domain_mirror(domain),
            "uses_mongo": domain_uses_mongo(domain),
        }
    out["mongo_required"] = any(out[d]["uses_mongo"] for d in DOMAIN_FLAGS)
    out["mongo_url_configured"] = bool((os.environ.get("MONGO_URL") or "").strip())
    return out
