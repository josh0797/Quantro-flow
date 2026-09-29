"""Copy everything Quantro Flow still keeps only in MongoDB into Supabase.

Run it ON the Fly machine so MONGO_URL never leaves it::

    fly ssh console -a quantro-flow-api -C "sh -c 'cd /app && python -m scripts.mongo_to_supabase'"            # dry run
    fly ssh console -a quantro-flow-api -C "sh -c 'cd /app && python -m scripts.mongo_to_supabase --apply'"    # write
    fly ssh console -a quantro-flow-api -C "sh -c 'cd /app && python -m scripts.mongo_to_supabase --verify'"   # check

Guarantees
----------
* **Dry run by default.** Nothing is written without ``--apply``.
* **Idempotent while Mongo is still written.** Every write is keyed on the
  dataset's natural key; a second ``--apply`` reports everything as ``same``.
* **Refuses a stale Mongo.** Once a domain no longer mirrors to Mongo
  (runbook step 6b: primary Supabase, mirror off) its Mongo copy stops
  receiving writes and deletes; copying it again would re-insert rows users
  deleted since (members, provider connections with their tokens, contacts…)
  and fill values they changed. ``--apply`` therefore aborts (exit 2) when
  any selected dataset belongs to such a domain, unless
  ``--allow-stale-mongo`` is passed on purpose.
* **Never deletes.** Not in Supabase, not in Mongo (Mongo is only read).
  Rows that exist only in Supabase are REPORTED (``supabase_only``) for the
  access-granting datasets (workspace members / invites, provider
  connections); while those collections are still Mongo-primary such a row
  is a stale shadow and ``--verify`` fails until it is reviewed.
* **Prints counts and ids only** — never document bodies, emails, tokens or
  secrets. Ids are Mongo ``_id`` hex / app ids (inbox_id, event_id, …).
* **Schema preflight.** Every target table/column is checked first; ``--apply``
  refuses to write anything if the konta migration
  ``20261026090500_flow_off_mongo.sql`` is not applied.
* **Bounded memory.** Mongo is read with a cursor in batches of ``BATCH``;
  Supabase is indexed by key columns only and full rows are fetched per
  batch — nothing loads a whole collection or table into memory (the Fly VM
  that also serves the API has 512 MB).
* **Primary-aware merge policy** (per dataset, from the machine's own flags):
    - ``mongo_wins``  — the domain is still Mongo-primary (calendar,
      integrations_config, flow_documents): Supabase was only a shadow, so the
      Mongo document overwrites differing Supabase values.
    - ``fill``        — the domain is already Supabase-primary (inbox,
      contacts, activity, content, actions, secrets): Supabase wins; only
      rows missing in Supabase are inserted and only NULL/missing values are
      filled from Mongo — plus a column 20261026090500 added when it still
      holds that column's default (a value the app has written wins).
  Trigger-managed ``updated_at`` is never compared or patched (the
  ``before update`` trigger rewrites it, so a patch would never converge).
* Applies the same legacy defaults the startup repairs used to apply in
  Mongo (missing ``workspace_id`` → ``"default"``, missing ``is_simulation``
  → ``True`` on the operational collections).
* Plaintext secrets found in legacy ``integrations_config.config`` are
  encrypted with the machine's key before they are written (never stored in
  clear); if no key is configured they are skipped and counted.

Exit code: 0 ok · 1 errors / verification mismatches · 2 preflight failed,
stale Mongo refused, or missing env.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# /app (the backend root) on sys.path when run as `python -m scripts.…` from /app.
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import mongo_compat as mc  # noqa: E402
import sb_rest  # noqa: E402
import storage_flags  # noqa: E402
import doc_store  # noqa: E402
import connect_store  # noqa: E402
import provider_secrets_store as pss  # noqa: E402
import inbox_store  # noqa: E402
import product_domain_store as pds  # noqa: E402
from actions import store as actions_store  # noqa: E402

DEFAULT_WORKSPACE_ID = "default"  # server.py DEFAULT_WORKSPACE_ID
MAX_IDS_PRINTED = 20
BATCH = 500          # Mongo documents held in memory at a time
FETCH_CHUNK = 100    # ids per PostgREST ``in.(…)`` lookup (URL length)
MIGRATION = "20261026090500_flow_off_mongo.sql"

# Columns a ``before update`` trigger rewrites (tg_set_updated_at): comparing
# or patching them can never converge, so they are left to the database.
TRIGGER_COLS = frozenset({"updated_at"})

# Same lists as server.py's startup repairs.
WORKSPACE_SCOPED = {
    "contacts", "inbox_items", "calendar_events", "agents",
    "activity_events", "content_items", "onboarding_tasks",
    "automation_policies", "escalation_rules", "content_templates",
    "integrations_config", "business_profile", "system_health_events",
}
SIMULATION_FLAGGED = {
    "contacts", "inbox_items", "calendar_events", "agents",
    "activity_events", "content_items", "onboarding_tasks",
}

# Mongo collections deliberately not copied (and why).
NOT_MIGRATED = {
    "google_oauth_state": "short-lived OAuth CSRF state (10 min)",
    "microsoft_oauth_state": "short-lived OAuth CSRF state (10 min)",
    "sync_locks": "autosync leases; recreated in flow_sync_locks",
    "user_sessions": "frozen/unused since Phase 1 (Supabase JWT auth)",
}

# Datasets whose rows grant access. A row that exists only in Supabase is
# reported; while the dataset is still Mongo-primary it is a stale shadow
# (e.g. a removed member whose shadow delete failed) and fails --verify.
ACCESS_DATASETS = frozenset({
    "workspace_members", "workspace_invites",
    "google_integrations", "microsoft_integrations", "facturapi_connections",
})

Requester = Callable[..., Awaitable[Any]]


# ── sources ────────────────────────────────────────────────────────────

class MongoSource:
    """Read-only, streaming access to the legacy database (motor, lazy)."""

    def __init__(self, url: str, db_name: str, *, client: Any = None):
        if client is None:
            from motor.motor_asyncio import AsyncIOMotorClient  # noqa: WPS433

            client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=15000)
        self._client = client
        self._db = client[db_name]

    async def collection_names(self) -> List[str]:
        return sorted(await self._db.list_collection_names())

    async def batches(self, name: str, size: int = BATCH) -> AsyncIterator[List[Dict[str, Any]]]:
        """Every document, ``size`` at a time (cursor; never the whole collection)."""
        cursor = self._db[name].find({}).sort("_id", 1)
        if hasattr(cursor, "batch_size"):
            cursor = cursor.batch_size(size)
        batch: List[Dict[str, Any]] = []
        async for doc in cursor:
            batch.append(doc)
            if len(batch) >= size:
                yield batch
                batch = []
        if batch:
            yield batch

    def close(self) -> None:
        self._client.close()


async def _batches(source: Any, name: str, size: int = BATCH) -> AsyncIterator[List[Dict[str, Any]]]:
    if hasattr(source, "batches"):
        async for batch in source.batches(name, size):
            yield batch
        return
    docs = await source.docs(name)   # minimal sources (tests)
    for chunk in sb_rest.chunked(docs, size):
        yield list(chunk)


# ── helpers ────────────────────────────────────────────────────────────

def _canon(value: Any) -> Any:
    """Normalize for comparison across Mongo values and PostgREST JSON."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=(dt.microsecond // 1000) * 1000)
    if isinstance(value, str) and len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
        try:
            return _canon(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return value
    if isinstance(value, dict):
        return {k: _canon(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def same(a: Any, b: Any) -> bool:
    return _canon(a) == _canon(b)


def _doc_time(doc: Dict[str, Any]) -> float:
    """Recency used to pick a winner among Mongo duplicates of one key."""
    for key in ("updated_at", "synced_at", "last_login_at", "created_at", "timestamp", "received_at"):
        v = doc.get(key)
        if isinstance(v, str):
            try:
                v = datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                v = None
        if isinstance(v, datetime):
            return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).timestamp()
    oid_time = doc_store._object_id_time(doc.get("_id"))
    return oid_time.timestamp() if oid_time else 0.0


def _mongo_id(doc: Dict[str, Any]) -> str:
    return str(doc.get("_id")) if doc.get("_id") is not None else "?"


def apply_legacy_defaults(collection: str, doc: Dict[str, Any], stats: Optional["Stats"]) -> Dict[str, Any]:
    out = dict(doc)
    if collection in WORKSPACE_SCOPED and not out.get("workspace_id"):
        out["workspace_id"] = DEFAULT_WORKSPACE_ID
        if stats is not None:
            stats.bump("default_workspace_id")
    if collection in SIMULATION_FLAGGED and "is_simulation" not in out:
        out["is_simulation"] = True
        if stats is not None:
            stats.bump("default_is_simulation")
    return out


@dataclass
class Stats:
    dataset: str
    target: str
    policy: str
    mongo: int = 0
    insert: int = 0
    update: int = 0
    same: int = 0
    skip: int = 0
    error: int = 0
    supabase_only: int = 0
    notes: Dict[str, int] = field(default_factory=dict)
    skipped_ids: List[str] = field(default_factory=list)
    error_ids: List[str] = field(default_factory=list)
    insert_ids: List[str] = field(default_factory=list)
    supabase_only_ids: List[str] = field(default_factory=list)

    def bump(self, note: str, n: int = 1) -> None:
        self.notes[note] = self.notes.get(note, 0) + n

    def skipped(self, ident: str, reason: str) -> None:
        self.skip += 1
        self.bump(f"skip:{reason}")
        if len(self.skipped_ids) < MAX_IDS_PRINTED:
            self.skipped_ids.append(f"{ident} ({reason})")

    def failed(self, ident: str, reason: str) -> None:
        self.error += 1
        self.bump(f"error:{reason}")
        if len(self.error_ids) < MAX_IDS_PRINTED:
            self.error_ids.append(f"{ident} ({reason})")

    def inserted(self, ident: str) -> None:
        self.insert += 1
        if len(self.insert_ids) < MAX_IDS_PRINTED:
            self.insert_ids.append(ident)

    def only_in_supabase(self, idents: Iterable[str]) -> None:
        for ident in sorted(idents):
            self.supabase_only += 1
            if len(self.supabase_only_ids) < MAX_IDS_PRINTED:
                self.supabase_only_ids.append(ident)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset, "target": self.target, "policy": self.policy,
            "mongo": self.mongo, "insert": self.insert, "update": self.update,
            "same": self.same, "skip": self.skip, "error": self.error,
            "supabase_only": self.supabase_only,
            "notes": self.notes, "skipped_ids": self.skipped_ids, "error_ids": self.error_ids,
            "insert_ids": self.insert_ids, "supabase_only_ids": self.supabase_only_ids,
        }


# ── Supabase writer ────────────────────────────────────────────────────

class Supabase:
    def __init__(self, requester: Requester, *, apply: bool):
        self.req = requester
        self.apply = apply

    async def rows(self, table: str, params: Optional[Dict[str, str]] = None, *, order: str = "id.asc",
                   select: str = "*") -> List[Dict[str, Any]]:
        p = {"select": select}
        p.update(params or {})
        rows = await sb_rest.fetch_all(self.req, table, p, order=order, max_rows=10_000_000)
        if rows is None:
            raise sb_rest.SupabaseStoreError(f"read {table} failed", table=table)
        return rows

    async def index(self, table: str, cols: Sequence[str], params: Optional[Dict[str, str]] = None, *,
                    order: str = "id.asc") -> List[Dict[str, Any]]:
        """Key columns only, for every row — small enough to hold in memory."""
        return await self.rows(table, params, order=order, select=",".join(cols))

    async def rows_in(self, table: str, col: str, values: Iterable[Any],
                      params: Optional[Dict[str, str]] = None, *, order: str = "id.asc") -> List[Dict[str, Any]]:
        """Full rows whose ``col`` is one of ``values`` (chunked ``in.(…)``)."""
        out: List[Dict[str, Any]] = []
        vals = sorted({str(v) for v in values if v is not None})
        for chunk in sb_rest.chunked(vals, FETCH_CHUNK):
            p = {col: f"in.({','.join(sb_rest.quote(v) for v in chunk)})"}
            p.update(params or {})
            out.extend(await self.rows(table, p, order=order))
        return out

    async def insert(self, table: str, row: Dict[str, Any]) -> Optional[str]:
        """None on success, else a short error code.

        NULL values are left out so column defaults apply (a NULL sent
        explicitly into a NOT NULL DEFAULT column would be rejected)."""
        if not self.apply:
            return None
        body = {k: v for k, v in row.items() if v is not None}
        resp = await self.req("POST", f"/rest/v1/{table}", json=body, prefer="return=minimal")
        return _err(resp)

    async def upsert(self, table: str, rows: List[Dict[str, Any]], conflict: str) -> Optional[str]:
        if not self.apply or not rows:
            return None
        for chunk in sb_rest.chunked(rows, 200):
            resp = await self.req(
                "POST", f"/rest/v1/{table}?on_conflict={conflict}",
                json=list(chunk), prefer="resolution=merge-duplicates,return=minimal",
            )
            err = _err(resp)
            if err:
                return err
        return None

    async def patch(self, table: str, pk: Any, fields: Dict[str, Any]) -> Optional[str]:
        if not self.apply:
            return None
        resp = await self.req(
            "PATCH", f"/rest/v1/{table}", json=fields,
            params={"id": f"eq.{pk}"}, prefer="return=minimal",
        )
        return _err(resp)


def _err(resp: Any) -> Optional[str]:
    if resp is None:
        return "unreachable"
    if resp.status_code == 409:
        return "conflict"
    if resp.status_code >= 400:
        return f"http_{resp.status_code}"
    return None


# ── schema preflight ───────────────────────────────────────────────────

REQUIRED_SCHEMA: Dict[str, Sequence[str]] = {
    "flow_documents": ("collection", "doc_id", "workspace_id", "doc", "created_at", "updated_at"),
    "flow_sync_locks": ("lock_key", "provider", "workspace_id", "owner_id", "locked_at", "expires_at"),
    "integrations_config": ("id", "workspace_id", "provider", "category", "display_name", "status",
                            "last_sync_at", "config", "integration_id", "secrets_enc", "extra"),
    "calendar_events": tuple(sorted(pds.CALENDAR_CFG.known_cols | {"id"})),
    "inbox_items": tuple(sorted(inbox_store._KNOWN_COLS | {"id"})),
    "contacts": tuple(sorted(pds.CONTACTS_CFG.known_cols | {"id"})),
    "activity_events": tuple(sorted(pds.ACTIVITY_CFG.known_cols | {"id"})),
    "content_items": tuple(sorted(pds.CONTENT_ITEMS_CFG.known_cols | {"id"})),
    "content_templates": tuple(sorted(pds.CONTENT_TEMPLATES_CFG.known_cols | {"id"})),
    "action_executions": tuple(sorted(actions_store.EXEC_COLUMNS | {"id"})),
    "automation_policies": tuple(sorted(actions_store.POLICY_COLUMNS | {"id"})),
    "action_policies": tuple(sorted(actions_store.ACTION_POLICY_COLUMNS | {"id"})),
    "provider_connections": ("id", "workspace_id", "provider", "access_token_enc", "refresh_token_enc",
                             "api_key_enc", "meta", "updated_at", "connection_id"),
    "webhook_events": ("id", "workspace_id", "provider", "event_id", "payload", "headers_meta", "received_at"),
    "oauth_states": ("state", "provider", "code_verifier", "requested_scopes"),
}


async def preflight(requester: Requester) -> Dict[str, str]:
    """{table: problem} for every table/column set PostgREST rejects."""
    problems: Dict[str, str] = {}
    for table, cols in REQUIRED_SCHEMA.items():
        resp = await requester("GET", f"/rest/v1/{table}", params={"select": ",".join(cols), "limit": "0"})
        if resp is None:
            problems[table] = "unreachable"
        elif resp.status_code >= 400:
            text = ""
            try:
                body = resp.json()
                text = (body or {}).get("message") or ""
            except Exception:  # noqa: BLE001
                text = (getattr(resp, "text", "") or "")[:160]
            problems[table] = f"http_{resp.status_code}: {text[:160]}"
    return problems


# ── datasets ───────────────────────────────────────────────────────────

def _policy(domain: str) -> str:
    return "fill" if storage_flags.domain_on_supabase(domain) else "mongo_wins"


async def backfill_documents(sb: Supabase, source: Any, collection: str, policy: str) -> Stats:
    """Mongo-only collection → flow_documents (keyed collection + Mongo _id)."""
    st = Stats(collection, "flow_documents", policy)
    scope = {"collection": f"eq.{collection}"}
    known = {r["doc_id"] for r in await sb.index("flow_documents", ("doc_id",), scope, order="doc_id.asc")}
    seen: Set[str] = set()

    async for batch in _batches(source, collection):
        st.mongo += len(batch)
        targets: List[Dict[str, Any]] = []
        for raw in batch:
            if raw.get("_id") is None:
                st.skipped("?", "no_id")
                continue
            doc = apply_legacy_defaults(collection, raw, st)
            doc_id = str(doc["_id"])
            seen.add(doc_id)
            targets.append({**doc, "_id": doc_id})
        existing = {
            r["doc_id"]: doc_store.row_to_doc(r)
            for r in await sb.rows_in("flow_documents", "doc_id",
                                      [t["_id"] for t in targets if t["_id"] in known],
                                      scope, order="doc_id.asc")
        }
        planned: List[Tuple[Dict[str, Any], bool]] = []   # (doc, is_new)
        for target in targets:
            current = existing.get(target["_id"])
            if current is None:
                planned.append((target, True))
                continue
            if policy == "fill":
                merged = dict(current)
                for k, v in target.items():
                    if k not in merged or merged[k] is None:
                        merged[k] = v
                target = merged
            if same(mc.to_json({k: v for k, v in target.items() if k != "_id"}),
                    mc.to_json({k: v for k, v in current.items() if k != "_id"})):
                st.same += 1
                continue
            planned.append((target, False))
        await _write_documents(sb, collection, planned, st)

    st.only_in_supabase(known - seen)
    return st


async def _write_documents(sb: Supabase, collection: str, planned: List[Tuple[Dict[str, Any], bool]],
                           st: Stats) -> None:
    # New rows keep the Mongo insertion order (created_at from the ObjectId);
    # updates leave created_at alone. PostgREST needs identical keys in every
    # object of one bulk request, hence two groups.
    for is_new in (True, False):
        group = [d for d, n in planned if n is is_new]
        if not group:
            continue
        rows = [
            doc_store.doc_to_row(collection, d, created_at=doc_store._object_id_time(d["_id"]) if is_new else None)
            for d in group
        ]
        if is_new:
            with_ts = [r for r in rows if "created_at" in r]
            without = [r for r in rows if "created_at" not in r]
            batches = [b for b in (with_ts, without) if b]
        else:
            batches = [rows]
        for batch in batches:
            err = await sb.upsert("flow_documents", batch, "collection,doc_id")
            for r in batch:
                if err:
                    st.failed(r["doc_id"], err)
                elif is_new:
                    st.inserted(r["doc_id"])
                else:
                    st.update += 1


@dataclass
class TypedSpec:
    dataset: str
    mongo: str
    table: str
    domain: str
    to_row: Callable[[Dict[str, Any]], Dict[str, Any]]
    key: Callable[[Dict[str, Any]], Optional[Tuple]]           # natural key of a row
    key_cols: Tuple[str, ...]                                  # every column key/alt_keys read
    alt_keys: Tuple[Callable[[Dict[str, Any]], Optional[Tuple]], ...] = ()
    # Columns added by 20261026090500 → their column DEFAULT. Under ``fill``
    # such a column is taken from Mongo only while Supabase still holds the
    # default (i.e. the app has not written it yet).
    new_cols: Dict[str, Any] = field(default_factory=dict)
    ident: Callable[[Dict[str, Any]], str] = lambda row: "?"  # printable id
    prepare: Optional[Callable[[Dict[str, Any], Optional[Stats]], Optional[Dict[str, Any]]]] = None
    # (row, existing Supabase row) → row; lets a dataset keep equivalent
    # existing values (e.g. ciphertext of the same secret) so re-runs are no-ops.
    reconcile: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None


def _k(*cols: str) -> Callable[[Dict[str, Any]], Optional[Tuple]]:
    def key(row: Dict[str, Any]) -> Optional[Tuple]:
        vals = tuple(row.get(c) for c in cols)
        return vals if all(v not in (None, "") for v in vals) else None
    return key


def _fill_diff(existing: Dict[str, Any], row: Dict[str, Any], new_cols: Dict[str, Any]) -> Dict[str, Any]:
    diff: Dict[str, Any] = {}
    for c, v in row.items():
        if c in TRIGGER_COLS:
            continue
        if c == "extra":
            cur = dict(existing.get("extra") or {})
            added = {k: val for k, val in (v or {}).items() if k not in cur}
            if added:
                diff["extra"] = {**cur, **added}
            continue
        if v is None:
            continue
        cur = existing.get(c)
        if cur is None:
            diff[c] = v
        elif c in new_cols and same(cur, new_cols[c]) and not same(cur, v):
            # Still the migration's default: the app never wrote it.
            diff[c] = v
    return diff


def _wins_diff(existing: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    """Mongo wins — except that a Mongo NULL/missing never erases a value."""
    diff: Dict[str, Any] = {}
    for c, v in row.items():
        if v is None or c in TRIGGER_COLS:
            continue
        if c == "extra":
            merged = {**(existing.get("extra") or {}), **(v or {})}
            if not same(merged, existing.get("extra") or {}):
                diff["extra"] = merged
            continue
        if not same(existing.get(c), v):
            diff[c] = v
    return diff


def _map(spec: TypedSpec, raw: Dict[str, Any], st: Optional[Stats]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(row, None) or (None, reason) — ``st`` counts notes on the first pass only."""
    doc = apply_legacy_defaults(spec.mongo, raw, st)
    if spec.prepare:
        doc = spec.prepare(doc, st)
        if doc is None:
            return None, "unmappable"
    try:
        return spec.to_row(doc), None
    except Exception as exc:  # noqa: BLE001
        return None, f"map:{type(exc).__name__}"


async def backfill_typed(sb: Supabase, source: Any, spec: TypedSpec, policy: str) -> Stats:
    st = Stats(spec.dataset, spec.table, policy)

    # Supabase side: key columns of every row (id + natural/alt keys only).
    by_key: Dict[Tuple, Any] = {}
    by_alt: List[Dict[Tuple, Any]] = [dict() for _ in spec.alt_keys]
    for r in await sb.index(spec.table, ("id",) + spec.key_cols):
        k = spec.key(r)
        if k:
            by_key[k] = r["id"]
        for i, ak in enumerate(spec.alt_keys):
            a = ak(r)
            if a:
                by_alt[i][a] = r["id"]

    # Pass 1 — decide the winner (_id) of every natural key; nothing kept but
    # (key → time, _id). Mongo duplicates of one key: the latest wins.
    winners: Dict[Tuple, Tuple[float, str]] = {}
    async for batch in _batches(source, spec.mongo):
        for raw in batch:
            st.mongo += 1
            if raw.get("_id") is None:
                st.skipped("?", "no_id")
                continue
            row, problem = _map(spec, raw, st)
            if row is None:
                if problem == "unmappable":
                    st.skipped(_mongo_id(raw), problem)
                else:
                    st.failed(_mongo_id(raw), problem or "map")
                continue
            key = spec.key(row)
            if key is None:
                st.skipped(_mongo_id(raw), "missing_key")
                continue
            t = _doc_time(raw)
            prev = winners.get(key)
            if prev is not None:
                st.bump("mongo_duplicates")
                loser = _mongo_id(raw) if t < prev[0] else prev[1]
                if len(st.skipped_ids) < MAX_IDS_PRINTED:
                    st.skipped_ids.append(f"{loser} (older_duplicate_of_key)")
                if t < prev[0]:
                    continue
            winners[key] = (t, _mongo_id(raw))
    winner_ids = {mid for _t, mid in winners.values()}
    del winners

    # Pass 2 — stream again, write the winners batch by batch.
    async for batch in _batches(source, spec.mongo):
        items: List[Tuple[Dict[str, Any], Optional[Any]]] = []   # (row, existing pk)
        for raw in batch:
            if _mongo_id(raw) not in winner_ids:
                continue
            row, _problem = _map(spec, raw, None)
            key = spec.key(row) if row is not None else None
            if row is None or key is None:
                st.bump("changed_during_run")   # re-run picks it up
                continue
            pk = by_key.get(key)
            if pk is None:
                for i, ak in enumerate(spec.alt_keys):
                    a = ak(row)
                    if a and a in by_alt[i]:
                        pk = by_alt[i][a]
                        st.bump("matched_by_alt_key")
                        break
            items.append((row, pk))
        existing_rows = {r["id"]: r for r in await sb.rows_in(spec.table, "id", [pk for _, pk in items if pk is not None])}
        for row, pk in items:
            ident = spec.ident(row)
            existing = existing_rows.get(pk) if pk is not None else None
            if existing is None:
                err = await sb.insert(spec.table, row)
                if err:
                    st.failed(ident, err)
                else:
                    st.inserted(ident)
                continue
            if spec.reconcile:
                row = spec.reconcile(row, existing)
            diff = _fill_diff(existing, row, spec.new_cols) if policy == "fill" else _wins_diff(existing, row)
            # Never rewrite a row's identity columns through a PATCH.
            diff.pop("id", None)
            if not diff:
                st.same += 1
                continue
            err = await sb.patch(spec.table, existing["id"], diff)
            if err:
                st.failed(ident, err)
            else:
                st.update += 1
    return st


# Row mappers (full rows, reusing the app's own mappers) ────────────────

def _calendar_prepare(doc: Dict[str, Any], st: Optional[Stats]) -> Optional[Dict[str, Any]]:
    d = pds.normalize_calendar_doc(doc)
    if not d.get("event_id"):
        d["event_id"] = str(doc.get("_id"))
        if st is not None:
            st.bump("event_id_from_mongo_id")
    return d


def _inbox_prepare(doc: Dict[str, Any], st: Optional[Stats]) -> Optional[Dict[str, Any]]:
    d = dict(doc)
    if not (d.get("inbox_id") or d.get("id")):
        d["inbox_id"] = str(doc.get("_id"))
        if st is not None:
            st.bump("inbox_id_from_mongo_id")
    return d


def _product_row(cfg: pds.DomainConfig) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def to_row(doc: Dict[str, Any]) -> Dict[str, Any]:
        row = pds.mongo_to_sb(cfg, doc, full=True)
        for col, default in cfg.not_null_defaults:
            if row.get(col) is None:
                row[col] = default
        return row
    return to_row


def _encrypt_legacy_plaintext(doc: Dict[str, Any], st: Optional[Stats]) -> Optional[Dict[str, Any]]:
    """integrations_config: encrypt legacy plaintext secrets before copying."""
    from integrations import secrets as integration_secrets

    config = doc.get("config")
    if not isinstance(config, dict):
        return doc
    out = dict(config)
    for k in integration_secrets.SECRET_FIELD_NAMES:
        v = out.get(k)
        if isinstance(v, str) and v and not connect_store._looks_encrypted(v):
            if integration_secrets.is_encryption_configured():
                out[k] = integration_secrets.encrypt_secret(v)
                if st is not None:
                    st.bump("plaintext_secret_encrypted")
            else:
                out.pop(k)
                if st is not None:
                    st.bump("plaintext_secret_skipped_no_key")
    return {**doc, "config": out}


def _keep_equal_ciphertext(row: Dict[str, Any], existing: Dict[str, Any]) -> Dict[str, Any]:
    """Fernet ciphertext differs on every encryption; if the stored one
    decrypts to the same secret, keep it (idempotent re-runs)."""
    from integrations import secrets as integration_secrets

    new_enc = dict(row.get("secrets_enc") or {})
    old_enc = existing.get("secrets_enc") or {}
    for k, v in list(new_enc.items()):
        old = old_enc.get(k)
        if old and old != v:
            plain_new = integration_secrets.decrypt_secret(v)
            if plain_new is not None and plain_new == integration_secrets.decrypt_secret(old):
                new_enc[k] = old
    return {**row, "secrets_enc": new_enc} if "secrets_enc" in row else row


def _provider_row(provider: str) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def to_row(doc: Dict[str, Any]) -> Dict[str, Any]:
        fields = {k: v for k, v in doc.items() if k != "_id"}
        return pss._connection_mongo_to_sb(provider, doc.get("workspace_id"), fields)
    return to_row


# Column defaults from the konta migration (NULL-default columns are
# covered by the "missing value" rule and need no entry).
_PROD_NEW = {"hidden_by_real": False, "extra": {}}


def typed_specs() -> List[TypedSpec]:
    return [
        TypedSpec(
            "calendar_events", "calendar_events", "calendar_events", "calendar",
            _product_row(pds.CALENDAR_CFG),
            key=lambda r: (_k("workspace_id", "external_provider", "external_event_id")(r)
                           if r.get("external_event_id") else _k("workspace_id", "event_id")(r)),
            key_cols=("workspace_id", "external_provider", "external_event_id", "event_id"),
            alt_keys=(_k("workspace_id", "event_id"),),
            new_cols={"is_real": None, "extra": {}},
            ident=lambda r: str(r.get("event_id")),
            prepare=_calendar_prepare,
        ),
        TypedSpec(
            "integrations_config", "integrations_config", "integrations_config", "integrations",
            connect_store.config_doc_to_row,
            key=_k("workspace_id", "provider"),
            key_cols=("workspace_id", "provider"),
            new_cols={"integration_id": None, "secrets_enc": {}, "extra": {}},
            ident=lambda r: f"{r.get('workspace_id')}:{r.get('provider')}",
            prepare=_encrypt_legacy_plaintext,
            reconcile=_keep_equal_ciphertext,
        ),
        TypedSpec(
            "inbox_items", "inbox_items", "inbox_items", "inbox",
            lambda d: inbox_store.inbox_mongo_to_sb(d, full=True),
            key=_k("workspace_id", "inbox_id"),
            key_cols=("workspace_id", "inbox_id", "gmail_id", "ms_id"),
            alt_keys=(_k("workspace_id", "gmail_id"), _k("workspace_id", "ms_id")),
            new_cols={
                "policy_action": None, "escalation": None, "auto_executed": None, "auto_executed_at": None,
                "execution_source": None, "execution_results": None, "extra": {},
            },
            ident=lambda r: str(r.get("inbox_id")),
            prepare=_inbox_prepare,
        ),
        TypedSpec(
            "contacts", "contacts", "contacts", "contacts", _product_row(pds.CONTACTS_CFG),
            key=_k("workspace_id", "contact_id"), key_cols=("workspace_id", "contact_id"),
            new_cols=dict(_PROD_NEW), ident=lambda r: str(r.get("contact_id")),
        ),
        TypedSpec(
            "activity_events", "activity_events", "activity_events", "activity", _product_row(pds.ACTIVITY_CFG),
            key=_k("workspace_id", "event_id"), key_cols=("workspace_id", "event_id"),
            new_cols=dict(_PROD_NEW), ident=lambda r: str(r.get("event_id")),
        ),
        TypedSpec(
            "content_items", "content_items", "content_items", "content", _product_row(pds.CONTENT_ITEMS_CFG),
            key=_k("workspace_id", "content_id"), key_cols=("workspace_id", "content_id"),
            new_cols=dict(_PROD_NEW), ident=lambda r: str(r.get("content_id")),
        ),
        TypedSpec(
            "content_templates", "content_templates", "content_templates", "content",
            _product_row(pds.CONTENT_TEMPLATES_CFG),
            key=_k("workspace_id", "template_id"), key_cols=("workspace_id", "template_id"),
            new_cols={
                "template_type": None, "subject_template": None, "body_template": None, "variables": None,
                "tags": None, "status": None, "created_by": None, **_PROD_NEW,
            },
            ident=lambda r: str(r.get("template_id")),
        ),
        TypedSpec(
            "action_executions", "action_executions", "action_executions", "actions",
            lambda d: actions_store.execution_mongo_to_sb(d, full=True),
            key=_k("execution_id"), key_cols=("execution_id",), new_cols={"extra": {}},
            ident=lambda r: str(r.get("execution_id")),
        ),
        TypedSpec(
            "automation_policies", "automation_policies", "automation_policies", "actions",
            lambda d: actions_store.policy_mongo_to_sb(d, full=True),
            key=_k("policy_id"), key_cols=("policy_id",),
            ident=lambda r: str(r.get("policy_id")),
        ),
        TypedSpec(
            "action_policies", "action_policies", "action_policies", "actions",
            lambda d: actions_store.action_policy_mongo_to_sb(d, full=True),
            key=_k("workspace_id", "action_id"), key_cols=("workspace_id", "action_id"),
            new_cols={"extra": {}},
            ident=lambda r: f"{r.get('workspace_id')}:{r.get('action_id')}",
        ),
    ]


_TOKEN_COLS = {
    "google": ("access_token_enc", "refresh_token_enc"),
    "microsoft": ("access_token_enc", "refresh_token_enc"),
    "facturapi": ("api_key_enc",),
}


async def backfill_provider_connections(sb: Supabase, source: Any, provider: str, mongo_name: str) -> Stats:
    """google/microsoft/facturapi docs → provider_connections (tokens stay ciphertext).

    One document per workspace, so the collection is small; it is still read
    through the batched cursor."""
    policy = _policy("secrets")
    st = Stats(mongo_name, "provider_connections", policy)
    current = {
        r.get("workspace_id"): r
        for r in await sb.rows("provider_connections", {"provider": f"eq.{provider}"})
    }
    winners: Dict[str, Tuple[float, Dict[str, Any]]] = {}
    async for batch in _batches(source, mongo_name):
        for raw in batch:
            st.mongo += 1
            ws = raw.get("workspace_id")
            if not ws:
                st.skipped(_mongo_id(raw), "missing_workspace_id")
                continue
            t = _doc_time(raw)
            if ws in winners:
                st.bump("mongo_duplicates")
                if t < winners[ws][0]:
                    continue
            winners[ws] = (t, raw)
    to_row = _provider_row(provider)
    for ws, (_t, raw) in winners.items():
        row = to_row(raw)
        existing = current.get(ws)
        ident = f"{ws}:{provider}"
        if existing is None:
            err = await sb.insert("provider_connections", row)
            if err:
                st.failed(ident, err)
            else:
                st.inserted(ident)
            continue
        missing_secret = any(row.get(c) and not existing.get(c) for c in _TOKEN_COLS[provider])
        if missing_secret or policy == "mongo_wins":
            # A token-less Supabase row (partial shadow write) is replaced wholesale.
            diff = _wins_diff(existing, {k: v for k, v in row.items() if k not in ("workspace_id", "provider")})
            if missing_secret:
                st.bump("token_less_row_repaired")
        else:
            diff = {}
            for c, v in row.items():
                if c in ("workspace_id", "provider") or c in TRIGGER_COLS or v is None:
                    continue
                if c == "meta":
                    cur = dict(existing.get("meta") or {})
                    added = {k: val for k, val in (v or {}).items() if k not in cur}
                    if added:
                        diff["meta"] = {**cur, **added}
                elif existing.get(c) is None:
                    diff[c] = v
        if not diff:
            st.same += 1
            continue
        err = await sb.patch("provider_connections", existing["id"], diff)
        if err:
            st.failed(ident, err)
        else:
            st.update += 1
    st.only_in_supabase(f"{ws}:{provider}" for ws in set(current) - set(winners) if ws)
    return st


async def backfill_webhook_events(sb: Supabase, source: Any) -> Stats:
    st = Stats("facturapi_webhook_events", "webhook_events", "insert_only")
    current = await sb.index("webhook_events", ("id", "event_id", "workspace_id", "connection_id", "received_at"),
                             {"provider": "eq.facturapi"})
    seen_ids = {r.get("event_id") for r in current if r.get("event_id")}
    seen_composite = {
        (r.get("workspace_id"), r.get("connection_id"), same_key(r.get("received_at")))
        for r in current if not r.get("event_id")
    }
    del current
    async for batch in _batches(source, "facturapi_webhook_events"):
        for raw in batch:
            st.mongo += 1
            doc = dict(raw)
            if not doc.get("workspace_id"):
                st.skipped(_mongo_id(raw), "missing_workspace_id")
                continue
            row = connect_store.webhook_doc_to_row("facturapi", doc)
            eid = row.get("event_id")
            if eid and eid in seen_ids:
                st.same += 1
                continue
            comp = (row.get("workspace_id"), row.get("connection_id"), same_key(row.get("received_at")))
            if not eid and comp in seen_composite:
                st.same += 1
                continue
            err = await sb.insert("webhook_events", row)
            if err == "conflict":
                st.same += 1
                continue
            if err:
                st.failed(eid or _mongo_id(raw), err)
                continue
            st.inserted(eid or _mongo_id(raw))
            if eid:
                seen_ids.add(eid)
            else:
                seen_composite.add(comp)
    return st


def same_key(value: Any) -> Any:
    c = _canon(value)
    return c.isoformat() if isinstance(c, datetime) else c


# ── orchestration ──────────────────────────────────────────────────────

PROVIDER_COLLECTIONS = (
    ("google", "google_integrations"),
    ("microsoft", "microsoft_integrations"),
    ("facturapi", "facturapi_connections"),
)


def dataset_names() -> List[str]:
    names = list(doc_store.DOC_COLLECTIONS)
    names += [s.dataset for s in typed_specs()]
    names += [m for _, m in PROVIDER_COLLECTIONS]
    names.append("facturapi_webhook_events")
    return names


def dataset_domains() -> Dict[str, str]:
    """dataset → storage_flags domain (same mapping as server._MONGO_DOMAINS)."""
    out = {c: doc_store.DOMAIN for c in doc_store.DOC_COLLECTIONS}
    out.update({s.dataset: s.domain for s in typed_specs()})
    out.update({m: "secrets" for _, m in PROVIDER_COLLECTIONS})
    out["facturapi_webhook_events"] = "secrets"
    return out


def stale_domains(datasets: Iterable[str]) -> List[str]:
    """Domains whose Mongo copy no longer receives writes (Supabase primary,
    mirror off): Mongo there is stale, copying it would undo user changes."""
    domains = dataset_domains()
    return sorted({domains[d] for d in datasets if not storage_flags.domain_uses_mongo(domains[d])})


async def _guarded(stats_factory: Callable[[], Stats], coro: Awaitable[Stats]) -> Dict[str, Any]:
    """A Supabase read failure fails its dataset, not the whole run."""
    try:
        return (await coro).as_dict()
    except sb_rest.SupabaseStoreError as exc:
        st = stats_factory()
        st.failed("*", f"supabase_read:{getattr(exc, 'table', '?')}")
        return st.as_dict()


async def run(source: Any, requester: Requester, *, apply: bool, only: Optional[Set[str]] = None,
              skip_preflight: bool = False, allow_stale_mongo: bool = False) -> Dict[str, Any]:
    report: Dict[str, Any] = {"mode": "apply" if apply else "dry_run", "datasets": [], "preflight": {}}
    problems = {} if skip_preflight else await preflight(requester)
    report["preflight"] = problems
    if problems and apply:
        report["aborted"] = f"schema preflight failed — apply konta migration {MIGRATION} first"
        return report

    names = await source.collection_names()
    known = set(dataset_names()) | set(NOT_MIGRATED)
    report["unknown_collections"] = [n for n in names if n not in known and not n.startswith("system.")]
    report["not_migrated"] = {n: NOT_MIGRATED[n] for n in NOT_MIGRATED if n in names}

    def wanted(name: str) -> bool:
        return (not only or name in only) and name in names

    selected = [d for d in dataset_names() if wanted(d)]
    stale = stale_domains(selected)
    report["stale_mongo"] = stale
    if stale and apply and not allow_stale_mongo:
        report["aborted"] = (
            f"Mongo is no longer mirrored for: {', '.join(stale)} — its copy is stale. Copying it again "
            "would re-insert rows deleted since and fill values changed since. Nothing was written. "
            "The backfill belongs BEFORE runbook step 6b (mirrors still on); run it with the mirrors "
            "on, or narrow --only to domains still mirrored."
        )
        return report
    if stale and apply:
        report["allow_stale_mongo"] = True

    sb = Supabase(requester, apply=apply)
    for collection in doc_store.DOC_COLLECTIONS:
        if wanted(collection):
            policy = _policy(doc_store.DOMAIN)
            report["datasets"].append(await _guarded(
                lambda c=collection, p=policy: Stats(c, "flow_documents", p),
                backfill_documents(sb, source, collection, policy),
            ))
    for spec in typed_specs():
        if wanted(spec.dataset):
            policy = _policy(spec.domain)
            report["datasets"].append(await _guarded(
                lambda s=spec, p=policy: Stats(s.dataset, s.table, p),
                backfill_typed(sb, source, spec, policy),
            ))
    for provider, mongo_name in PROVIDER_COLLECTIONS:
        if wanted(mongo_name):
            report["datasets"].append(await _guarded(
                lambda m=mongo_name: Stats(m, "provider_connections", _policy("secrets")),
                backfill_provider_connections(sb, source, provider, mongo_name),
            ))
    if wanted("facturapi_webhook_events"):
        report["datasets"].append(await _guarded(
            lambda: Stats("facturapi_webhook_events", "webhook_events", "insert_only"),
            backfill_webhook_events(sb, source),
        ))
    return report


def _stale_shadows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Access-granting rows that exist only in Supabase while Mongo is still
    the source of truth for them (a failed shadow delete)."""
    return [
        d for d in report["datasets"]
        if d["dataset"] in ACCESS_DATASETS and d["policy"] == "mongo_wins" and d.get("supabase_only")
    ]


def exit_code(report: Dict[str, Any], *, verify: bool = False) -> int:
    if report.get("aborted"):
        return 2
    errors = sum(d["error"] for d in report["datasets"])
    if errors:
        return 1
    if verify:
        # After --apply, a dry run must find nothing left to write, and no
        # stale access-granting shadow row may be left to review.
        pending = sum(d["insert"] + d["update"] for d in report["datasets"])
        if pending or report.get("preflight") or _stale_shadows(report):
            return 1
    return 0


def render(report: Dict[str, Any], *, verify: bool = False) -> str:
    lines: List[str] = []
    mode = report["mode"]
    title = {
        "dry_run": "DRY RUN — nothing written (pass --apply to write)",
        "apply": "APPLY — rows written to Supabase",
    }[mode]
    if verify:
        title = "VERIFY — dry run; every dataset must show insert=0 update=0 error=0"
    lines.append(f"Mongo → Supabase backfill · {title}")
    if report.get("preflight"):
        lines.append("Schema preflight FAILED:")
        for table, problem in sorted(report["preflight"].items()):
            lines.append(f"  {table}: {problem}")
    if report.get("stale_mongo"):
        lines.append(
            "WARNING: Mongo is no longer mirrored for domain(s) "
            f"{', '.join(report['stale_mongo'])}; its copy there is stale "
            "(inserts below may be rows users deleted)."
        )
    if report.get("aborted"):
        lines.append(f"ABORTED: {report['aborted']}")
        return "\n".join(lines)
    header = (f"{'dataset':<26}{'target':<22}{'policy':<12}{'mongo':>7}{'insert':>8}{'update':>8}"
              f"{'same':>7}{'skip':>6}{'error':>7}{'sb_only':>9}")
    lines.append(header)
    lines.append("-" * len(header))
    for d in report["datasets"]:
        lines.append(
            f"{d['dataset']:<26}{d['target']:<22}{d['policy']:<12}{d['mongo']:>7}{d['insert']:>8}"
            f"{d['update']:>8}{d['same']:>7}{d['skip']:>6}{d['error']:>7}{d.get('supabase_only', 0):>9}"
        )
    for d in report["datasets"]:
        extra = []
        if d["notes"]:
            extra.append("notes: " + ", ".join(f"{k}={v}" for k, v in sorted(d["notes"].items())))
        if d.get("insert_ids"):
            extra.append("insert: " + "; ".join(d["insert_ids"]))
        if d["skipped_ids"]:
            extra.append("skipped: " + "; ".join(d["skipped_ids"]))
        if d["error_ids"]:
            extra.append("errors: " + "; ".join(d["error_ids"]))
        if d.get("supabase_only_ids"):
            extra.append("supabase_only: " + "; ".join(d["supabase_only_ids"]))
        if extra:
            lines.append(f"· {d['dataset']}: " + " | ".join(extra))
    for d in _stale_shadows(report):
        lines.append(
            f"REVIEW: {d['dataset']} has {d['supabase_only']} Supabase row(s) Mongo no longer has "
            "(stale shadow — e.g. a removed member). Delete them by hand before the flip; "
            "--verify fails until then."
        )
    if report.get("not_migrated"):
        lines.append("Not migrated (by design): " + ", ".join(f"{k} ({v})" for k, v in report["not_migrated"].items()))
    if report.get("unknown_collections"):
        lines.append("UNKNOWN Mongo collections (not handled — review!): " + ", ".join(report["unknown_collections"]))
    totals = {k: sum(d[k] for d in report["datasets"]) for k in ("mongo", "insert", "update", "same", "skip", "error")}
    lines.append("totals: " + " ".join(f"{k}={v}" for k, v in totals.items()))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write to Supabase (default: dry run)")
    parser.add_argument("--verify", action="store_true",
                        help="dry run that fails (exit 1) unless nothing is left to copy")
    parser.add_argument("--only", default="", help=f"comma-separated datasets: {', '.join(dataset_names())}")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--allow-stale-mongo", action="store_true",
                        help="DANGEROUS: --apply even for domains that no longer mirror to Mongo "
                             "(re-inserts rows deleted since, fills values changed since)")
    args = parser.parse_args(argv)
    if args.apply and args.verify:
        parser.error("--verify is a dry run; do not combine it with --apply")

    missing = [n for n in ("MONGO_URL", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY") if not (os.environ.get(n) or "").strip()]
    if missing:
        print(f"missing env: {', '.join(missing)} (run on the Fly machine)", file=sys.stderr)
        return 2
    only = {x.strip() for x in args.only.split(",") if x.strip()} or None
    unknown = (only or set()) - set(dataset_names())
    if unknown:
        parser.error(f"unknown dataset(s): {', '.join(sorted(unknown))}")

    async def _go() -> Dict[str, Any]:
        source = MongoSource(os.environ["MONGO_URL"], os.environ.get("DB_NAME", "quantro_os"))
        try:
            return await run(source, sb_rest.request, apply=args.apply, only=only,
                             allow_stale_mongo=args.allow_stale_mongo)
        finally:
            source.close()
            await sb_rest.aclose()

    report = asyncio.run(_go())
    print(json.dumps(report, indent=2, default=str) if args.json else render(report, verify=args.verify))
    return exit_code(report, verify=args.verify)


if __name__ == "__main__":
    sys.exit(main())
