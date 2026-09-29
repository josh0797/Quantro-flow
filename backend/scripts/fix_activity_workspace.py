"""Give activity events that leaked into workspace "default" back to their workspace.

Until the fix in this branch, ``log_activity`` defaulted ``workspace_id`` to
``"default"`` and most of its call sites did not pass one, so events about
other tenants' inbox items, contacts, agents, policies and business profiles
were stored under ``"default"`` — and shown to that workspace's members.

Run it ON the Fly machine, like the backfill (same environment)::

    fly ssh console -a quantro-flow-api -C "sh -c 'cd /app && python -m scripts.fix_activity_workspace'"            # dry run
    fly ssh console -a quantro-flow-api -C "sh -c 'cd /app && python -m scripts.fix_activity_workspace --apply'"    # write
    fly ssh console -a quantro-flow-api -C "sh -c 'cd /app && python -m scripts.fix_activity_workspace --verify'"   # check

What it does, for every ``activity_events`` row under ``"default"``:

* **Resolve** the row's true workspace from ``related_type`` / ``related_id``
  (inbox item, calendar event, contact, agent, automation policy, content
  item, template, escalation rule; ``profile`` rows carry the workspace id
  itself), reading each entity through the app's own store facades, so it
  is found wherever it lives right now (Supabase, or Mongo while that domain
  is still Mongo-primary/mirrored).
* **Keep** it when the entity belongs to ``"default"`` (the default
  workspace's own events), and keep rows that no leaking call site could
  have written (seed / simulation-generator rows without a related entity).
* **Re-attribute** it when the entity belongs to another workspace:
  ``workspace_id`` and ``is_simulation`` are taken from that entity (or that
  workspace's current mode when the entity has no flag).
* **Quarantine** it when it cannot be resolved (entity deleted since, or a
  leaking call site that logged no entity): the row moves to the sentinel
  workspace ``__unattributed__`` that nobody can be a member of. Reversible:
  a later run re-resolves quarantined rows (their entity may have been
  backfilled since) and moves them to their workspace, or back to
  ``"default"`` when that is where they belong.

Guarantees
----------
* **Dry run by default.** Nothing is written without ``--apply``.
* **Never deletes**, anywhere. Every change is an ``update_one`` keyed on
  ``(workspace_id, event_id)``.
* **Cutover-safe at any point.** Writes go through the same dual-write
  facade as the app (``product_domain_store.wrap_activity_col``): while the
  activity Mongo mirror is on, the Mongo copy of each row moves with the
  Supabase row, and Mongo copies still under ``"default"`` are found and
  moved too. So the backfill (``scripts/mongo_to_supabase.py``, key
  ``(workspace_id, event_id)``) sees the same rows on both sides. If a mirror
  write fails anyway (``STORE_DRIFT``), the backfill matches activity rows by
  ``event_id`` as well and never inserts a second copy under ``"default"``.
  Once the mirrors are off Mongo is not touched at all.
* **Idempotent and re-runnable**; ``--verify`` exits 1 while anything is left
  to move.
* **Prints counts and ids only** — event ids, workspace ids and related
  types; never titles, descriptions, names, emails or tokens.

Exit code: 0 ok · 1 errors, or anything left to move under ``--verify`` /
after ``--apply`` · 2 missing env.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# /app (the backend root) on sys.path when run as `python -m scripts.…` from /app.
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import doc_store  # noqa: E402
import inbox_store  # noqa: E402
import mongo_legacy  # noqa: E402
import product_domain_store as pds  # noqa: E402
import sb_rest  # noqa: E402
import storage_flags  # noqa: E402
from actions import store as actions_store  # noqa: E402
from scripts import mongo_to_supabase as backfill  # noqa: E402

DEFAULT_WORKSPACE_ID = "default"          # server.py DEFAULT_WORKSPACE_ID
QUARANTINE_WORKSPACE_ID = "__unattributed__"  # no member row can ever name it
SCANNED_WORKSPACES = (DEFAULT_WORKSPACE_ID, QUARANTINE_WORKSPACE_ID)
MAX_IDS_PRINTED = 20

# related_type → (store attribute, field holding related_id). These are the
# related_type values log_activity's call sites use (server.py and
# actions/handlers/quantro_internal.py) for which the entity is looked up.
RESOLVERS: Dict[str, Tuple[str, str]] = {
    "inbox": ("inbox", "inbox_id"),
    "calendar": ("calendar", "event_id"),
    "contact": ("contacts", "contact_id"),
    "agent": ("agents", "agent_id"),            # onboarding events log the agent id
    "policy": ("policies", "policy_id"),
    "content": ("content_items", "content_id"),
    "template": ("templates", "template_id"),
    "escalation": ("escalation_rules", "rule_id"),
}
PROFILE = "profile"   # "Business Profile updated": related_id IS the workspace id

# Leaking call sites that logged no entity: (event_type, related_type,
# related_id). Rows of any other entity-less shape were written with an
# explicit workspace (seed, simulation generator, integration updates) and
# are left alone.
LEAK_SHAPES_WITHOUT_ENTITY = frozenset({
    ("ai", "inbox", None),              # Batch triage complete
    ("system", "inbox", None),          # Batch approval complete
    ("content", "content", None),       # Content generated
    ("system", "system", "simulation"),  # Simulation data generated / auto-generated / cleared
})

# Collections the script reads or writes → storage domain (for MONGO_URL).
DOMAINS = backfill.dataset_domains()
_USED = ("activity_events", "inbox_items", "calendar_events", "contacts", "content_items",
         "content_templates", "automation_policies", "agents", "escalation_rules", "workspaces",
         "workspace_members", "business_profile")


# ── stores ─────────────────────────────────────────────────────────────

@dataclass
class Stores:
    """The app's own facades (same routing as server.py for the same flags)."""
    activity: Any
    inbox: Any
    calendar: Any
    contacts: Any
    content_items: Any
    templates: Any
    policies: Any
    agents: Any
    escalation_rules: Any
    workspaces: Any
    members: Any
    business_profile: Any

    @classmethod
    def build(cls, db: Any) -> "Stores":
        """``db[name]`` → a Motor-like collection (mongo_legacy.LazyDatabase in
        production: it never connects unless a flag still routes to Mongo)."""
        return cls(
            activity=pds.wrap_activity_col(db["activity_events"]),
            inbox=inbox_store.wrap_inbox_col(db["inbox_items"]),
            calendar=pds.wrap_calendar_col(db["calendar_events"]),
            contacts=pds.wrap_contacts_col(db["contacts"]),
            content_items=pds.wrap_content_items_col(db["content_items"]),
            templates=pds.wrap_content_templates_col(db["content_templates"]),
            policies=actions_store.wrap_automation_policies_col(db["automation_policies"]),
            agents=doc_store.wrap("agents", db["agents"]),
            escalation_rules=doc_store.wrap("escalation_rules", db["escalation_rules"]),
            workspaces=doc_store.wrap("workspaces", db["workspaces"]),
            members=doc_store.wrap("workspace_members", db["workspace_members"]),
            business_profile=doc_store.wrap("business_profile", db["business_profile"]),
        )


def _activity_mongo_in_use() -> bool:
    """Mongo still holds a live copy of activity (primary or mirror)."""
    return storage_flags.domain_uses_mongo("activity")


# ── model ──────────────────────────────────────────────────────────────

@dataclass
class Event:
    """One event id and where its copies are (never its title/description)."""
    event_id: str
    event_type: Optional[str] = None
    related_type: Optional[str] = None
    related_id: Optional[str] = None
    copies: List[Tuple[str, str]] = field(default_factory=list)   # (store, workspace_id)

    def add(self, store: str, doc: Dict[str, Any]) -> None:
        self.copies.append((store, doc.get("workspace_id")))
        if store == "supabase" or self.event_type is None:
            self.event_type = doc.get("event_type")
            self.related_type = doc.get("related_type")
            rid = doc.get("related_id")
            self.related_id = str(rid) if rid not in (None, "") else None

    @property
    def workspaces(self) -> List[str]:
        return sorted({ws for _store, ws in self.copies})


@dataclass
class Decision:
    target: str                      # workspace the event belongs to
    reason: str
    is_simulation: Optional[bool] = None   # None = leave the flag as it is


@dataclass
class Move:
    event_id: str
    source: str
    target: str
    fields: Dict[str, Any]
    stores: Tuple[str, ...]


@dataclass
class Report:
    mode: str
    scanned: Counter = field(default_factory=Counter)
    decisions: Counter = field(default_factory=Counter)
    reasons: Counter = field(default_factory=Counter)
    related_types: Counter = field(default_factory=Counter)
    moves: Counter = field(default_factory=Counter)
    reattributed_to: Counter = field(default_factory=Counter)
    ids: Dict[str, List[str]] = field(default_factory=dict)
    errors: int = 0
    error_ids: List[str] = field(default_factory=list)
    applied: int = 0
    remaining_moves: Optional[int] = None
    default_workspace_members: Optional[int] = None
    flags: Dict[str, Any] = field(default_factory=dict)

    def note_id(self, bucket: str, text: str) -> None:
        lst = self.ids.setdefault(bucket, [])
        if len(lst) < MAX_IDS_PRINTED:
            lst.append(text)

    def failed(self, ident: str, reason: str) -> None:
        self.errors += 1
        if len(self.error_ids) < MAX_IDS_PRINTED:
            self.error_ids.append(f"{ident} ({reason})")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode, "flags": self.flags, "scanned": dict(self.scanned),
            "decisions": dict(self.decisions), "reasons": dict(self.reasons),
            "related_types": dict(self.related_types), "moves": dict(self.moves),
            "reattributed_to": dict(self.reattributed_to), "ids": self.ids,
            "applied": self.applied, "errors": self.errors, "error_ids": self.error_ids,
            "remaining_moves": self.remaining_moves,
            "default_workspace_members": self.default_workspace_members,
        }


# ── scan ───────────────────────────────────────────────────────────────

async def scan(stores: Stores, report: Optional[Report] = None) -> Dict[str, Event]:
    """Every copy of every event under "default" / the quarantine workspace:
    Supabase always, the Mongo copy too while activity still uses Mongo."""
    query = {"workspace_id": {"$in": list(SCANNED_WORKSPACES)}}
    events: Dict[str, Event] = {}
    sources: List[Tuple[str, List[Dict[str, Any]]]] = [
        ("supabase", await stores.activity._sb_rows(query)),   # raises SupabaseStoreError
    ]
    if _activity_mongo_in_use():
        sources.append(("mongo", await stores.activity._mongo.find(query).to_list(None)))
    for store, docs in sources:
        for doc in docs:
            if report is not None:
                report.scanned[store] += 1
            eid = doc.get("event_id")
            if not eid:
                if report is not None:
                    report.scanned[f"{store}_without_event_id"] += 1
                continue
            events.setdefault(str(eid), Event(str(eid))).add(store, doc)
    return events


# ── resolve ────────────────────────────────────────────────────────────

class Resolver:
    """related entity → its workspace (cached; one lookup per entity)."""

    def __init__(self, stores: Stores):
        self.stores = stores
        self._entities: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {}
        self._modes: Dict[str, bool] = {}

    async def entity(self, related_type: str, related_id: str) -> Optional[Dict[str, Any]]:
        key = (related_type, related_id)
        if key not in self._entities:
            attr, id_field = RESOLVERS[related_type]
            store = getattr(self.stores, attr)
            doc = await store.find_one({id_field: related_id})
            if doc is None and related_type == "inbox" and storage_flags.domain_uses_mongo("inbox"):
                # Gmail/Outlook-synced Mongo docs carry the app id in `id`
                # (Supabase always has it in inbox_id).
                doc = await store._mongo.find_one({"id": related_id})
            self._entities[key] = (
                {"workspace_id": doc.get("workspace_id") or DEFAULT_WORKSPACE_ID,   # legacy rows → default
                 "is_simulation": doc.get("is_simulation")} if doc is not None else None
            )
        return self._entities[key]

    async def workspace_exists(self, workspace_id: str) -> bool:
        key = ("workspace", workspace_id)
        if key not in self._entities:
            doc = await self.stores.workspaces.find_one({"workspace_id": workspace_id})
            self._entities[key] = {"workspace_id": workspace_id} if doc is not None else None
        return self._entities[key] is not None

    async def workspace_mode(self, workspace_id: str) -> bool:
        """The workspace's own Simulation Mode (no fallback to another profile)."""
        if workspace_id not in self._modes:
            profile = await self.stores.business_profile.find_one({"workspace_id": workspace_id})
            self._modes[workspace_id] = bool((profile or {}).get("simulation_mode", False))
        return self._modes[workspace_id]

    async def decide(self, ev: Event) -> Decision:
        rtype, rid = ev.related_type, ev.related_id
        if rtype == PROFILE and rid:
            if rid == DEFAULT_WORKSPACE_ID:
                return Decision(DEFAULT_WORKSPACE_ID, "profile_of_default")
            if await self.workspace_exists(rid):
                return Decision(rid, "profile_of_workspace", await self.workspace_mode(rid))
            return Decision(QUARANTINE_WORKSPACE_ID, "workspace_not_found")
        if rtype in RESOLVERS and rid:
            ent = await self.entity(rtype, rid)
            if ent is None:
                return Decision(QUARANTINE_WORKSPACE_ID, "related_entity_not_found")
            ws = ent["workspace_id"]
            if ws == DEFAULT_WORKSPACE_ID:
                return Decision(DEFAULT_WORKSPACE_ID, "entity_in_default")
            sim = ent["is_simulation"]
            if not isinstance(sim, bool):
                sim = await self.workspace_mode(ws)
            return Decision(ws, f"related_{rtype}", sim)
        if (ev.event_type, rtype, rid) in LEAK_SHAPES_WITHOUT_ENTITY:
            return Decision(QUARANTINE_WORKSPACE_ID, "no_related_entity")
        return Decision(DEFAULT_WORKSPACE_ID, "not_a_leak_shape")


def _bucket(ev: Event, decision: Decision) -> str:
    here = set(ev.workspaces)
    if decision.target == DEFAULT_WORKSPACE_ID:
        return "keep" if here <= {DEFAULT_WORKSPACE_ID} else "restore"
    if decision.target == QUARANTINE_WORKSPACE_ID:
        return "unattributed" if here <= {QUARANTINE_WORKSPACE_ID} else "quarantine"
    return "reattribute"


# ── plan ───────────────────────────────────────────────────────────────

async def _sb_has(stores: Stores, workspace_id: str, event_id: str) -> bool:
    return bool(await stores.activity._sb_rows({"workspace_id": workspace_id, "event_id": event_id}, limit=1))


async def plan_moves(stores: Stores, ev: Event, decision: Decision, report: Report) -> List[Move]:
    moves: List[Move] = []
    for source in ev.workspaces:
        if source == decision.target:
            continue
        in_stores = tuple(sorted({s for s, ws in ev.copies if ws == source}))
        target, fields = decision.target, {"workspace_id": decision.target}
        if decision.is_simulation is not None:
            fields["is_simulation"] = decision.is_simulation
        if "supabase" in in_stores and await _sb_has(stores, target, ev.event_id):
            # Supabase already has this event under its target (unique
            # (workspace_id, event_id)): this copy is a duplicate — hide it.
            if source == QUARANTINE_WORKSPACE_ID:
                continue
            if await _sb_has(stores, QUARANTINE_WORKSPACE_ID, ev.event_id):
                report.failed(ev.event_id, "duplicate_already_quarantined")
                continue
            target, fields = QUARANTINE_WORKSPACE_ID, {"workspace_id": QUARANTINE_WORKSPACE_ID}
            report.reasons["duplicate_of_reattributed_row"] += 1
        moves.append(Move(ev.event_id, source, target, fields, in_stores))
    return moves


async def plan(stores: Stores, report: Report) -> List[Move]:
    events = await scan(stores, report)
    resolver = Resolver(stores)
    moves: List[Move] = []
    for eid in sorted(events):
        ev = events[eid]
        report.related_types[ev.related_type or "none"] += 1
        decision = await resolver.decide(ev)
        bucket = _bucket(ev, decision)
        report.decisions[bucket] += 1
        report.reasons[decision.reason] += 1
        if bucket == "reattribute":
            report.reattributed_to[decision.target] += 1
            report.note_id(bucket, f"{eid} -> {decision.target} ({decision.reason})")
        elif bucket in ("quarantine", "restore", "unattributed"):
            report.note_id(bucket, f"{eid} ({decision.reason})")
        for mv in await plan_moves(stores, ev, decision, report):
            for store in mv.stores:
                report.moves[store] += 1
            moves.append(mv)
    return moves


# ── run ────────────────────────────────────────────────────────────────

async def run(stores: Stores, *, apply: bool) -> Report:
    report = Report("apply" if apply else "dry_run")
    report.flags = {
        "activity_primary": storage_flags.domain_primary("activity"),
        "activity_mongo_copy": _activity_mongo_in_use(),
    }
    try:
        report.default_workspace_members = await stores.members.count_documents({"workspace_id": DEFAULT_WORKSPACE_ID})
        moves = await plan(stores, report)
    except sb_rest.SupabaseStoreError as exc:
        report.failed("*", f"supabase_read:{getattr(exc, 'table', '?')}")
        return report
    except Exception as exc:  # noqa: BLE001 — a store outage: report the class only, write nothing
        report.failed("*", f"read:{type(exc).__name__}")
        return report
    if not apply:
        return report

    for mv in moves:
        try:
            # The app's dual-write facade: Supabase row + (mirror on) Mongo copy.
            await stores.activity.update_one(
                {"workspace_id": mv.source, "event_id": mv.event_id}, {"$set": mv.fields},
            )
            report.applied += 1
        except Exception as exc:  # noqa: BLE001 — one row failing must not stop the rest
            report.failed(mv.event_id, type(exc).__name__)

    # Post-check: a Supabase write that degraded (mirror on → no exception)
    # shows up here as a move still to do. Re-running --apply repairs it.
    try:
        check = Report("dry_run")
        report.remaining_moves = len(await plan(stores, check))
    except sb_rest.SupabaseStoreError as exc:
        report.failed("*", f"supabase_read:{getattr(exc, 'table', '?')}")
    except Exception as exc:  # noqa: BLE001
        report.failed("*", f"read:{type(exc).__name__}")
    return report


def exit_code(report: Report, *, verify: bool = False) -> int:
    if report.errors:
        return 1
    if report.mode == "apply" and report.remaining_moves:
        return 1
    if verify and sum(report.moves.values()):
        return 1
    return 0


def render(report: Report, *, verify: bool = False) -> str:
    title = {
        "dry_run": "DRY RUN — nothing written (pass --apply to write)",
        "apply": "APPLY — activity rows moved (Supabase + Mongo mirror copy)",
    }[report.mode]
    if verify:
        title = "VERIFY — dry run; nothing may be left to move"
    lines = [f"activity_events workspace repair · {title}"]
    lines.append(f"flags: activity primary={report.flags.get('activity_primary')} "
                 f"mongo_copy={'on' if report.flags.get('activity_mongo_copy') else 'off'}")
    lines.append(f"workspace '{DEFAULT_WORKSPACE_ID}' members: {report.default_workspace_members}")
    lines.append("scanned rows (under 'default' / quarantine): "
                 + (", ".join(f"{k}={v}" for k, v in sorted(report.scanned.items())) or "none"))
    lines.append("events by related_type: "
                 + (", ".join(f"{k}={v}" for k, v in sorted(report.related_types.items())) or "none"))
    order = ("keep", "reattribute", "quarantine", "restore", "unattributed")
    lines.append("decisions: " + " ".join(f"{k}={report.decisions.get(k, 0)}" for k in order))
    if report.reasons:
        lines.append("reasons: " + ", ".join(f"{k}={v}" for k, v in sorted(report.reasons.items())))
    if report.reattributed_to:
        lines.append("re-attributed to: " + ", ".join(f"{k}={v}" for k, v in sorted(report.reattributed_to.items())))
    lines.append("row moves: " + (" ".join(f"{k}={v}" for k, v in sorted(report.moves.items())) or "none"))
    for bucket in ("reattribute", "quarantine", "restore", "unattributed"):
        if report.ids.get(bucket):
            lines.append(f"· {bucket}: " + "; ".join(report.ids[bucket]))
    if report.mode == "apply":
        lines.append(f"applied: {report.applied} · remaining moves after apply: {report.remaining_moves}")
    if report.errors:
        lines.append(f"ERRORS: {report.errors} — " + "; ".join(report.error_ids))
    return "\n".join(lines)


def _missing_env() -> List[str]:
    missing = [n for n in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY") if not (os.environ.get(n) or "").strip()]
    if not missing and not (os.environ.get("MONGO_URL") or "").strip():
        # Only needed while a flag still routes one of our collections to Mongo.
        if any(storage_flags.domain_uses_mongo(DOMAINS[c]) for c in _USED):
            missing.append("MONGO_URL")
    return missing


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="move the rows (default: dry run)")
    parser.add_argument("--verify", action="store_true",
                        help="dry run that fails (exit 1) while anything is left to move")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    if args.apply and args.verify:
        parser.error("--verify is a dry run; do not combine it with --apply")

    missing = _missing_env()
    if missing:
        print(f"missing env: {', '.join(missing)} (run on the Fly machine)", file=sys.stderr)
        return 2

    async def _go() -> Report:
        stores = Stores.build(mongo_legacy.LazyDatabase(DOMAINS))
        try:
            return await run(stores, apply=args.apply)
        finally:
            mongo_legacy.close()
            await sb_rest.aclose()

    report = asyncio.run(_go())
    print(json.dumps(report.as_dict(), indent=2, default=str) if args.json else render(report, verify=args.verify))
    return exit_code(report, verify=args.verify)


if __name__ == "__main__":
    sys.exit(main())
