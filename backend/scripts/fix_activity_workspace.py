"""Give rows that leaked into workspace "default" back to their workspace.

Until the fixes in this branch, ``log_activity`` defaulted ``workspace_id``
to ``"default"`` and most of its call sites did not pass one, so events about
other tenants' inbox items, contacts, agents, policies and business profiles
were stored under ``"default"`` — and shown to that workspace's members. Same
bug class: content items generated from a template were stored without
``workspace_id`` and re-tagged ``"default"`` by the startup repair (and by the
backfill's legacy rule), although their template belongs to another tenant.

Run it ON the Fly machine, like the backfill (same environment)::

    fly ssh console -a quantro-flow-api -C "sh -c 'cd /app && python -m scripts.fix_activity_workspace'"            # dry run
    fly ssh console -a quantro-flow-api -C "sh -c 'cd /app && python -m scripts.fix_activity_workspace --apply'"    # write
    fly ssh console -a quantro-flow-api -C "sh -c 'cd /app && python -m scripts.fix_activity_workspace --verify'"   # check

What it does:

* **content_items** generated from a template (``template_id``) under
  ``"default"``, under the quarantine workspace or without a workspace: the
  item belongs to its template's workspace (templates are always
  workspace-scoped; the generate endpoint loaded the template scoped to the
  caller) — the same rule the backfill applies while copying
  (``mongo_to_supabase.template_content_workspace``). Template gone: an
  untagged item is quarantined, a ``"default"`` one stays.
* **activity_events** under ``"default"`` written BEFORE the fix — every
  event the fixed ``log_activity`` writes carries ``workspace_explicit``
  (server.py ``ACTIVITY_WORKSPACE_EXPLICIT``) and is never looked at, so the
  default workspace's own events written since the deploy always stay:

  - **Resolve** the row's true workspace from ``related_type`` /
    ``related_id`` (inbox item, calendar event, contact, agent, automation
    policy, content item — through its template, as above —, template,
    escalation rule; ``profile`` rows carry the workspace id itself),
    reading each entity through the app's own store facades, so it is found
    wherever it lives right now.
  - **Keep** it when the entity belongs to ``"default"``, and keep rows that
    no leaking call site could have written (seed / simulation-generator
    rows without a related entity).
  - **Re-attribute** it when the entity belongs to another workspace:
    ``workspace_id`` and ``is_simulation`` are taken from that entity (or that
    workspace's current mode when the entity has no flag).
  - **Quarantine** it when it cannot be resolved (entity deleted since or
    without a workspace, or a leaking call site that logged no entity): the
    row moves to the sentinel workspace ``__unattributed__`` that nobody can
    be a member of. Reversible: a later run re-resolves quarantined rows.

Guarantees
----------
* **Dry run by default.** Nothing is written without ``--apply``.
* **Never deletes**, anywhere. Every change is an ``update_one`` keyed on
  ``(workspace_id, app id)``.
* **Provenance on every moved row**: ``leak_remediation = {"from", "to",
  "reason", "at"}`` (Supabase ``extra``; the Mongo copy gets the same field)
  — ``from`` stays the workspace the row originally sat in. No content, only
  workspace ids. So the full list of leaked rows survives in the data::

      select event_id, workspace_id, extra->'leak_remediation' from activity_events
       where extra ? 'leak_remediation';

* **The owner's review sticks**: a row tagged ``leak_review = "kept_default"``
  (see the runbook's manual revert) is kept in ``"default"`` by every run.
* **Cutover-safe at any point.** Writes go through the same dual-write
  facades as the app (``product_domain_store.wrap_activity_col`` /
  ``wrap_content_items_col``): while a Mongo mirror is on, the Mongo copy of
  each row moves with the Supabase row, and Mongo copies still under
  ``"default"`` (or untagged) are found and moved too. So the backfill
  (``scripts/mongo_to_supabase.py``) sees the same rows on both sides. If a
  mirror write fails anyway (``STORE_DRIFT``), the backfill matches activity
  rows by ``event_id`` as well and resolves template items by their template,
  so it never inserts a second copy under ``"default"``. Once the mirrors are
  off Mongo is not touched at all.
* **Idempotent and re-runnable**; ``--verify`` exits 1 while anything is left
  to move.
* **Prints counts and ids only** — event/content ids, workspace ids and
  related types; never titles, descriptions, bodies, names, emails or tokens.

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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

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
QUARANTINE_WORKSPACE_ID = backfill.QUARANTINE_WORKSPACE_ID   # no member row can ever name it
SCANNED_WORKSPACES = (DEFAULT_WORKSPACE_ID, QUARANTINE_WORKSPACE_ID)
MAX_IDS_PRINTED = 20

# server.py ACTIVITY_WORKSPACE_EXPLICIT: set on every event written since
# the fix — such a row sits in the workspace it was written for.
WRITTEN_AFTER_FIX = "workspace_explicit"
# Set on every row this script moves: {"from", "to", "reason", "at"}.
PROVENANCE = "leak_remediation"
# The owner's decision on a reviewed row ("kept_default": it stays in "default").
REVIEW = "leak_review"
KEPT_DEFAULT = "kept_default"

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


@dataclass(frozen=True)
class Dataset:
    name: str        # collection / table
    store: str       # Stores attribute (the app's facade)
    id_field: str    # app id


CONTENT = Dataset("content_items", "content_items", "content_id")
ACTIVITY = Dataset("activity_events", "activity", "event_id")
DATASETS = (CONTENT, ACTIVITY)   # content first: "Content from template" rows follow their item


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


def _mongo_in_use(collection: str) -> bool:
    """Mongo still holds a live copy of the collection (primary or mirror)."""
    return storage_flags.domain_uses_mongo(DOMAINS[collection])


# ── model ──────────────────────────────────────────────────────────────

def _ws_order(ws: Optional[str]) -> Tuple[bool, str]:
    return (ws is not None, ws or "")


@dataclass
class Item:
    """One row id and where its copies are (never its title/description/body)."""
    item_id: str
    event_type: Optional[str] = None
    related_type: Optional[str] = None
    related_id: Optional[str] = None
    template_id: Optional[str] = None
    provenance: Optional[Dict[str, Any]] = None
    review: Optional[str] = None
    copies: List[Tuple[str, Optional[str]]] = field(default_factory=list)   # (store, workspace_id|None)

    def add(self, store: str, doc: Dict[str, Any]) -> None:
        self.copies.append((store, doc.get("workspace_id") or None))
        if store == "supabase" or len(self.copies) == 1:
            self.event_type = doc.get("event_type")
            self.related_type = doc.get("related_type")
            rid = doc.get("related_id")
            self.related_id = str(rid) if rid not in (None, "") else None
            self.template_id = str(doc["template_id"]) if doc.get("template_id") else None
        if isinstance(doc.get(PROVENANCE), dict) and (store == "supabase" or self.provenance is None):
            self.provenance = doc[PROVENANCE]
        if doc.get(REVIEW):
            self.review = self.review or doc.get(REVIEW)

    @property
    def workspaces(self) -> List[Optional[str]]:
        return sorted({ws for _store, ws in self.copies}, key=_ws_order)

    def origin(self, source: Optional[str]) -> Optional[str]:
        """The workspace the row sat in before this script first moved it."""
        if self.provenance and "from" in self.provenance:
            return self.provenance["from"]
        return source


@dataclass
class Decision:
    target: str                      # workspace the row belongs to
    reason: str
    is_simulation: Optional[bool] = None   # None = leave the flag as it is


@dataclass
class Move:
    dataset: Dataset
    item_id: str
    source: Optional[str]            # None = a Mongo copy without workspace_id
    target: str
    fields: Dict[str, Any]
    stores: Tuple[str, ...]


@dataclass
class Part:
    """Counters for one dataset."""
    scanned: Counter = field(default_factory=Counter)
    decisions: Counter = field(default_factory=Counter)
    reasons: Counter = field(default_factory=Counter)
    related_types: Counter = field(default_factory=Counter)
    moves: Counter = field(default_factory=Counter)
    reattributed_to: Counter = field(default_factory=Counter)
    ids: Dict[str, List[str]] = field(default_factory=dict)

    def note_id(self, bucket: str, text: str) -> None:
        lst = self.ids.setdefault(bucket, [])
        if len(lst) < MAX_IDS_PRINTED:
            lst.append(text)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "scanned": dict(self.scanned), "decisions": dict(self.decisions), "reasons": dict(self.reasons),
            "related_types": dict(self.related_types), "moves": dict(self.moves),
            "reattributed_to": dict(self.reattributed_to), "ids": self.ids,
        }


@dataclass
class Report:
    mode: str
    parts: Dict[str, Part] = field(default_factory=lambda: {ds.name: Part() for ds in DATASETS})
    errors: int = 0
    error_ids: List[str] = field(default_factory=list)
    applied: int = 0
    remaining_moves: Optional[int] = None
    default_workspace_members: Optional[int] = None
    flags: Dict[str, Any] = field(default_factory=dict)

    @property
    def activity(self) -> Part:
        return self.parts[ACTIVITY.name]

    @property
    def content(self) -> Part:
        return self.parts[CONTENT.name]

    @property
    def total_moves(self) -> int:
        return sum(sum(p.moves.values()) for p in self.parts.values())

    def failed(self, ident: str, reason: str) -> None:
        self.errors += 1
        if len(self.error_ids) < MAX_IDS_PRINTED:
            self.error_ids.append(f"{ident} ({reason})")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode, "flags": self.flags,
            "datasets": {name: part.as_dict() for name, part in self.parts.items()},
            "applied": self.applied, "errors": self.errors, "error_ids": self.error_ids,
            "remaining_moves": self.remaining_moves,
            "default_workspace_members": self.default_workspace_members,
        }


# ── scan ───────────────────────────────────────────────────────────────

def _content_in_scope(doc: Dict[str, Any]) -> bool:
    """A template-generated item whose own workspace cannot be trusted."""
    return bool(doc.get("template_id")) and (doc.get("workspace_id") or None) in (None, *SCANNED_WORKSPACES)


async def scan(ds: Dataset, stores: Stores, part: Optional[Part] = None) -> Dict[str, Item]:
    """Every copy of every candidate row: Supabase always, the Mongo copy too
    while the collection still uses Mongo."""
    facade = getattr(stores, ds.store)
    sources: List[Tuple[str, List[Dict[str, Any]]]] = [
        ("supabase", await facade._sb_rows({"workspace_id": {"$in": list(SCANNED_WORKSPACES)}})),   # raises SupabaseStoreError
    ]
    if _mongo_in_use(ds.name):
        mongo_query = ({"template_id": {"$exists": True}} if ds is CONTENT
                       else {"workspace_id": {"$in": list(SCANNED_WORKSPACES)}})
        sources.append(("mongo", await facade._mongo.find(mongo_query).to_list(None)))
    items: Dict[str, Item] = {}
    for store, docs in sources:
        for doc in docs:
            if ds is CONTENT and not _content_in_scope(doc):
                continue
            if part is not None:
                part.scanned[store] += 1
            if ds is ACTIVITY and doc.get(WRITTEN_AFTER_FIX):
                # Written by the fixed log_activity: in its own workspace by construction.
                if part is not None:
                    part.scanned[f"{store}_written_after_fix"] += 1
                continue
            iid = doc.get(ds.id_field)
            if not iid:
                if part is not None:
                    part.scanned[f"{store}_without_{ds.id_field}"] += 1
                continue
            items.setdefault(str(iid), Item(str(iid))).add(store, doc)
    return items


# ── resolve ────────────────────────────────────────────────────────────

class Resolver:
    """related entity → its workspace (cached; one lookup per entity)."""

    def __init__(self, stores: Stores):
        self.stores = stores
        self._entities: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {}
        self._modes: Dict[str, bool] = {}
        self._templates: Optional[Dict[str, Set[str]]] = None

    async def templates(self) -> Dict[str, Set[str]]:
        """template_id → workspace(s), from the same stores the backfill reads."""
        if self._templates is None:
            docs = list(await self.stores.templates._sb_rows({}))
            if _mongo_in_use("content_templates"):
                docs += await self.stores.templates._mongo.find({}).to_list(None)
            self._templates = backfill.template_workspaces(docs)
        return self._templates

    async def entity(self, related_type: str, related_id: str) -> Optional[Dict[str, Any]]:
        """{"workspace_id": its workspace (None: it has none), "is_simulation"},
        or None when the entity does not exist."""
        key = (related_type, related_id)
        if key not in self._entities:
            attr, id_field = RESOLVERS[related_type]
            store = getattr(self.stores, attr)
            doc = await store.find_one({id_field: related_id})
            if doc is None and related_type == "inbox" and storage_flags.domain_uses_mongo("inbox"):
                # Gmail/Outlook-synced Mongo docs carry the app id in `id`
                # (Supabase always has it in inbox_id).
                doc = await store._mongo.find_one({"id": related_id})
            value = None
            if doc is not None:
                # A missing workspace_id is the bug class itself, not "default".
                ws = doc.get("workspace_id") or None
                if related_type == "content":
                    ws = backfill.template_content_workspace(doc, await self.templates()) or ws
                value = {"workspace_id": ws, "is_simulation": doc.get("is_simulation")}
            self._entities[key] = value
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

    async def decide(self, ds: Dataset, item: Item) -> Decision:
        if item.review == KEPT_DEFAULT:
            return Decision(DEFAULT_WORKSPACE_ID, "kept_default_by_owner")
        if ds is CONTENT:
            return await self.decide_content(item)
        return await self.decide_event(item)

    async def decide_content(self, item: Item) -> Decision:
        probe: Dict[str, Any] = {"template_id": item.template_id}
        if DEFAULT_WORKSPACE_ID in item.workspaces:
            # A copy under "default" vouches for "default" when the template is gone.
            probe["workspace_id"] = DEFAULT_WORKSPACE_ID
        target = backfill.template_content_workspace(probe, await self.templates())
        if target is None:          # template gone; the item's "default" copy stays
            return Decision(DEFAULT_WORKSPACE_ID, "template_not_found")
        if target == QUARANTINE_WORKSPACE_ID:
            return Decision(target, "template_not_found")
        if target == DEFAULT_WORKSPACE_ID:
            return Decision(target, "template_in_default")
        return Decision(target, "template_workspace")

    async def decide_event(self, ev: Item) -> Decision:
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
            if ws is None:
                return Decision(QUARANTINE_WORKSPACE_ID, "related_entity_without_workspace")
            if ws == QUARANTINE_WORKSPACE_ID:
                return Decision(QUARANTINE_WORKSPACE_ID, f"related_{rtype}_unattributed")
            if ws == DEFAULT_WORKSPACE_ID:
                return Decision(DEFAULT_WORKSPACE_ID, "entity_in_default")
            sim = ent["is_simulation"]
            if not isinstance(sim, bool):
                sim = await self.workspace_mode(ws)
            return Decision(ws, f"related_{rtype}", sim)
        if (ev.event_type, rtype, rid) in LEAK_SHAPES_WITHOUT_ENTITY:
            return Decision(QUARANTINE_WORKSPACE_ID, "no_related_entity")
        return Decision(DEFAULT_WORKSPACE_ID, "not_a_leak_shape")


def _bucket(item: Item, decision: Decision) -> str:
    here = set(item.workspaces)
    if decision.target == DEFAULT_WORKSPACE_ID:
        return "keep" if here <= {DEFAULT_WORKSPACE_ID} else "restore"
    if decision.target == QUARANTINE_WORKSPACE_ID:
        return "unattributed" if here <= {QUARANTINE_WORKSPACE_ID} else "quarantine"
    return "reattribute"


# ── plan ───────────────────────────────────────────────────────────────

async def _sb_has(stores: Stores, ds: Dataset, workspace_id: str, item_id: str) -> bool:
    facade = getattr(stores, ds.store)
    return bool(await facade._sb_rows({"workspace_id": workspace_id, ds.id_field: item_id}, limit=1))


async def plan_moves(stores: Stores, ds: Dataset, item: Item, decision: Decision, report: Report,
                     at: str) -> List[Move]:
    part = report.parts[ds.name]
    moves: List[Move] = []
    for source in item.workspaces:
        if source == decision.target:
            continue
        in_stores = tuple(sorted({s for s, ws in item.copies if ws == source}))
        target, reason, sim = decision.target, decision.reason, decision.is_simulation
        if "supabase" in in_stores and await _sb_has(stores, ds, target, item.item_id):
            # Supabase already has this row under its target (unique
            # (workspace_id, app id)): this copy is a duplicate — hide it.
            if source == QUARANTINE_WORKSPACE_ID:
                continue
            if await _sb_has(stores, ds, QUARANTINE_WORKSPACE_ID, item.item_id):
                report.failed(item.item_id, "duplicate_already_quarantined")
                continue
            target, reason, sim = QUARANTINE_WORKSPACE_ID, "duplicate_of_reattributed_row", None
            part.reasons[reason] += 1
        fields: Dict[str, Any] = {"workspace_id": target}
        if sim is not None:
            fields["is_simulation"] = sim
        fields[PROVENANCE] = {"from": item.origin(source), "to": target, "reason": reason, "at": at}
        moves.append(Move(ds, item.item_id, source, target, fields, in_stores))
    return moves


async def plan(stores: Stores, report: Report) -> List[Move]:
    at = datetime.now(timezone.utc).isoformat()
    resolver = Resolver(stores)
    moves: List[Move] = []
    for ds in DATASETS:
        part = report.parts[ds.name]
        items = await scan(ds, stores, part)
        for iid in sorted(items):
            item = items[iid]
            if ds is ACTIVITY:
                part.related_types[item.related_type or "none"] += 1
            decision = await resolver.decide(ds, item)
            bucket = _bucket(item, decision)
            part.decisions[bucket] += 1
            part.reasons[decision.reason] += 1
            if bucket == "reattribute":
                part.reattributed_to[decision.target] += 1
                part.note_id(bucket, f"{iid} -> {decision.target} ({decision.reason})")
            elif bucket in ("quarantine", "restore", "unattributed"):
                part.note_id(bucket, f"{iid} ({decision.reason})")
            for mv in await plan_moves(stores, ds, item, decision, report, at):
                for store in mv.stores:
                    part.moves[store] += 1
                moves.append(mv)
    return moves


# ── run ────────────────────────────────────────────────────────────────

async def run(stores: Stores, *, apply: bool) -> Report:
    report = Report("apply" if apply else "dry_run")
    report.flags = {
        ds.name: {"primary": storage_flags.domain_primary(DOMAINS[ds.name]), "mongo_copy": _mongo_in_use(ds.name)}
        for ds in DATASETS
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
            await getattr(stores, mv.dataset.store).update_one(
                {"workspace_id": mv.source, mv.dataset.id_field: mv.item_id}, {"$set": mv.fields},
            )
            report.applied += 1
        except Exception as exc:  # noqa: BLE001 — one row failing must not stop the rest
            report.failed(mv.item_id, type(exc).__name__)

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
    if verify and report.total_moves:
        return 1
    return 0


def render(report: Report, *, verify: bool = False) -> str:
    title = {
        "dry_run": "DRY RUN — nothing written (pass --apply to write)",
        "apply": "APPLY — rows moved (Supabase + Mongo mirror copy)",
    }[report.mode]
    if verify:
        title = "VERIFY — dry run; nothing may be left to move"
    lines = [f"leaked-row workspace repair · {title}"]
    lines.append("flags: " + "; ".join(
        f"{name} primary={f.get('primary')} mongo_copy={'on' if f.get('mongo_copy') else 'off'}"
        for name, f in report.flags.items()))
    lines.append(f"workspace '{DEFAULT_WORKSPACE_ID}' members: {report.default_workspace_members}")
    order = ("keep", "reattribute", "quarantine", "restore", "unattributed")
    for ds in DATASETS:
        part = report.parts[ds.name]
        lines.append(f"[{ds.name}]")
        lines.append("  scanned rows: " + (", ".join(f"{k}={v}" for k, v in sorted(part.scanned.items())) or "none"))
        if ds is ACTIVITY:
            lines.append("  events by related_type: "
                         + (", ".join(f"{k}={v}" for k, v in sorted(part.related_types.items())) or "none"))
        lines.append("  decisions: " + " ".join(f"{k}={part.decisions.get(k, 0)}" for k in order))
        if part.reasons:
            lines.append("  reasons: " + ", ".join(f"{k}={v}" for k, v in sorted(part.reasons.items())))
        if part.reattributed_to:
            lines.append("  re-attributed to: " + ", ".join(f"{k}={v}" for k, v in sorted(part.reattributed_to.items())))
        lines.append("  row moves: " + (" ".join(f"{k}={v}" for k, v in sorted(part.moves.items())) or "none"))
        for bucket in ("reattribute", "quarantine", "restore", "unattributed"):
            if part.ids.get(bucket):
                lines.append(f"  · {bucket}: " + "; ".join(part.ids[bucket]))
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
