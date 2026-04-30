#!/usr/bin/env python3
"""Phase 7c — One-shot backfill Mongo → Supabase.

Reads the three legacy MongoDB collections that today hold members,
invites and audit events, and pushes them into the corresponding
Supabase tables (`org_members`, `invitations`, `org_audit_logs`).

Safety guarantees
-----------------
* **Dry-run by default.** You must pass ``--execute`` to actually write
  anything. Without it, the script only inspects, validates and prints
  what *would* happen.
* **Dedup on the Supabase side.** Every insert is preceded by a SELECT
  on the natural keys we care about (``(org_id, user_id)`` for
  members; ``token`` for invitations; ``(org_id, action,
  target_user_id, created_at)`` for audit). Rows already present are
  reported as ``skipped:duplicate``.
* **Workspace ↔ Org mapping.** Reads ``QUANTRO_DEFAULT_ORG_ID`` from
  the backend ``.env`` and honours per-workspace overrides stored on
  ``workspaces`` documents (``workspaces.org_id``). Rows whose
  workspace can't be resolved are reported as ``skipped:no_mapping``.
* **Service-role aware.** Uses ``SUPABASE_SERVICE_ROLE_KEY`` when
  available (lets us bypass RLS so one operator can backfill data
  owned by other users). Falls back to ``SUPABASE_ANON_KEY`` as a last
  resort, in which case rows the policy doesn't permit will fail —
  those are reported as ``error:rls`` so you can decide what to do.
* **Idempotent.** Re-running after a partial run picks up where it
  left off. No row is updated; only inserted-if-missing.
* **Granular --table flag.** You can run only the table you want
  (``members``, ``invites``, ``audit``, ``all``).

Examples
--------
    # 1) See exactly what would happen for everything (default mode).
    python backfill_mongo_to_supabase.py

    # 2) Dry-run only the members migration, limit 50 rows.
    python backfill_mongo_to_supabase.py --table members --limit 50

    # 3) Real run for invites only.
    python backfill_mongo_to_supabase.py --table invites --execute

    # 4) Full real run after dry-run looks clean.
    python backfill_mongo_to_supabase.py --execute
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv

# Load /app/backend/.env so MONGO_URL + SUPABASE_* are visible.
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.normpath(os.path.join(HERE, "..", "backend"))
load_dotenv(os.path.join(BACKEND_DIR, ".env"))
sys.path.insert(0, BACKEND_DIR)

# We import only the read-only Mongo collections from server.py — but
# server.py boots a lot of FastAPI machinery, so we connect to Mongo
# directly here to keep this script standalone.
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "quantro_os")
SUPABASE_URL = (os.environ.get("SUPABASE_URL", "") or "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
DEFAULT_ORG_ID = os.environ.get("QUANTRO_DEFAULT_ORG_ID", "")
DEFAULT_WORKSPACE_ID = "default_workspace"

# Phase 7c — Option A consolidation:
# When a workspace has no explicit mapping on `workspaces.org_id`, fall back
# to QUANTRO_DEFAULT_ORG_ID for rows whose user_id is a real Supabase UUID.
# Legacy test seeds (`user_test_*`) still fall through `skip:bad_uuid`.
FALLBACK_TO_DEFAULT_ORG = True

# Per-user role overrides applied AFTER `normalize_role`. Keys are Supabase
# auth user IDs. Use sparingly — this is the manual knob for the one-shot
# consolidation, not a long-term policy.
ROLE_OVERRIDES: Dict[str, str] = {
    # Josias Mont — demoted from "owner" to "leader" (admin) in the
    # consolidated default org, per the Phase 7c migration decision.
    "2c6c39bc-7a3f-41f1-be32-3e81904a8de1": "leader",
}

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def is_uuid(value: Any) -> bool:
    return isinstance(value, str) and bool(UUID_RE.match(value))


# ── Role + audit-action mapping (lock-step with server.py) ───────────
ROLE_ALIASES = {
    "agent": "viewer",
    "operator": "member",
    "manager": "accountant",
    "admin": "leader",
    "owner": "owner",
    "viewer": "viewer",
    "member": "member",
    "accountant": "accountant",
    "leader": "leader",
}

AUDIT_EVENT_MAP = {
    "members.role_changed": "role_changed",
    "members.removed": "access_revoked",
    "invites.created": "invitation_created",
    "invites.revoked": "access_revoked",
    "invites.accepted": "invitation_accepted",
    "onboarding.completed": "onboarding_completed",
    "onboarding.step_updated": "permissions_modified",
}


def normalize_role(role: Optional[str]) -> str:
    return ROLE_ALIASES.get((role or "").lower().strip(), "viewer")


# ── Supabase HTTP helpers (httpx) ────────────────────────────────────
class SupabaseClient:
    """Thin wrapper around PostgREST for the backfill script. Uses
    service-role key when available (to bypass RLS), otherwise falls
    back to the anon key."""

    def __init__(self) -> None:
        if not SUPABASE_URL:
            raise SystemExit("[abort] SUPABASE_URL is not set; cannot continue.")
        if not (SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY):
            raise SystemExit(
                "[abort] No Supabase auth key found. "
                "Set SUPABASE_SERVICE_ROLE_KEY (recommended) or SUPABASE_ANON_KEY."
            )
        self.use_service = bool(SUPABASE_SERVICE_ROLE_KEY)
        self.key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    async def get(self, path: str, params: Dict[str, Any]) -> Tuple[int, Any]:
        url = f"{SUPABASE_URL}{path}"
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(url, headers=self.headers, params=params)
        try:
            return r.status_code, (r.json() if r.text else None)
        except Exception:
            return r.status_code, r.text

    async def post(
        self, path: str, payload: Any, *, prefer: str = "return=representation"
    ) -> Tuple[int, Any]:
        url = f"{SUPABASE_URL}{path}"
        h = dict(self.headers)
        h["Prefer"] = prefer
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(url, headers=h, json=payload)
        try:
            return r.status_code, (r.json() if r.text else None)
        except Exception:
            return r.status_code, r.text


# ── Reporter ─────────────────────────────────────────────────────────
class Reporter:
    """Small in-memory tally of what happened, printed at the end as
    a markdown table so it's pasteable into your run notes."""

    def __init__(self) -> None:
        self.counts: Dict[str, Dict[str, int]] = {}
        self.errors: List[Dict[str, Any]] = []

    def bump(self, table: str, status: str) -> None:
        self.counts.setdefault(table, {}).setdefault(status, 0)
        self.counts[table][status] += 1

    def error(self, table: str, row_key: str, reason: str) -> None:
        self.errors.append({"table": table, "row": row_key, "reason": reason})

    def print_summary(self) -> None:
        print("\n" + "=" * 70)
        print("BACKFILL SUMMARY")
        print("=" * 70)
        for table, statuses in self.counts.items():
            total = sum(statuses.values())
            print(f"\n[{table}] total seen: {total}")
            for k, v in sorted(statuses.items()):
                print(f"   - {k:25s} {v:>5}")
        if self.errors:
            print(f"\n[errors] {len(self.errors)} rows recorded:")
            for e in self.errors[:25]:
                print(f"   - {e['table']:8s} {e['row']:40s} :: {e['reason']}")
            if len(self.errors) > 25:
                print(f"   …and {len(self.errors) - 25} more (see --json-out for full list)")


# ── Workspace mapping ────────────────────────────────────────────────
async def build_workspace_org_map(db) -> Dict[str, str]:
    """Return ``{workspace_id: org_id}`` for every workspace we know
    how to translate. The default workspace falls back to the env
    var; per-workspace overrides come from ``workspaces.org_id``."""
    mapping: Dict[str, str] = {}
    if DEFAULT_ORG_ID:
        mapping[DEFAULT_WORKSPACE_ID] = DEFAULT_ORG_ID

    cursor = db["workspaces"].find({}, {"_id": 0, "workspace_id": 1, "org_id": 1})
    async for w in cursor:
        wid = w.get("workspace_id")
        oid = w.get("org_id")
        if wid and oid and is_uuid(oid):
            mapping[wid] = oid
    return mapping


# ── Migrators ────────────────────────────────────────────────────────
async def migrate_members(
    db, sb: SupabaseClient, ws_org: Dict[str, str], reporter: Reporter, *,
    execute: bool, limit: Optional[int],
) -> None:
    print("\n--- workspace_members → org_members ---")
    cursor = db["workspace_members"].find({}, {"_id": 0})
    seen = 0
    # Local dedup so dry-run numbers reflect what a real run would write.
    # Keys are `(org_id, user_id)` tuples already "would-be" inserted in
    # this invocation.
    dry_seen: set[Tuple[str, str]] = set()
    async for row in cursor:
        if limit and seen >= limit:
            break
        seen += 1
        wid = row.get("workspace_id")
        uid = row.get("user_id")
        role = normalize_role(row.get("role"))
        # Manual override (e.g. Josias Mont → leader in default org).
        if uid in ROLE_OVERRIDES:
            role = ROLE_OVERRIDES[uid]

        org_id = ws_org.get(wid)
        if not org_id and FALLBACK_TO_DEFAULT_ORG and DEFAULT_ORG_ID and is_uuid(uid):
            # Option A consolidation — no per-workspace org exists yet, so
            # every real user ends up in the default org. Legacy test seeds
            # (non-UUID user_id) skip out via `bad_uuid` below.
            org_id = DEFAULT_ORG_ID
            # Note: intentionally NOT bumping a counter here — this is an
            # intermediate resolution, not a terminal status. The row will
            # still end up reported as `dry:would_insert`, `skip:duplicate`
            # or `skip:duplicate_in_run` below.
        if not org_id:
            print(f"  [skip:no_mapping] ws={wid} user={uid} (add it to workspaces.org_id or QUANTRO_DEFAULT_ORG_ID)")
            reporter.bump("members", "skip:no_mapping")
            continue
        if not is_uuid(uid):
            print(f"  [skip:bad_uuid] user_id={uid!r} is not a uuid (legacy account)")
            reporter.bump("members", "skip:bad_uuid")
            continue

        # Dedup — first against Supabase, then against this run's own plan.
        status, body = await sb.get(
            "/rest/v1/org_members",
            {"org_id": f"eq.{org_id}", "user_id": f"eq.{uid}", "select": "id", "limit": "1"},
        )
        if status == 200 and isinstance(body, list) and body:
            print(f"  [skip:duplicate] org={org_id} user={uid}")
            reporter.bump("members", "skip:duplicate")
            continue
        if (org_id, uid) in dry_seen:
            print(f"  [skip:duplicate_in_run] org={org_id} user={uid}")
            reporter.bump("members", "skip:duplicate_in_run")
            continue

        payload = {
            "org_id": org_id,
            "user_id": uid,
            "role": role,
        }
        joined_at = row.get("joined_at")
        if isinstance(joined_at, datetime):
            payload["joined_at"] = joined_at.astimezone(timezone.utc).isoformat()

        if not execute:
            print(f"  [dry] would insert org={org_id} user={uid} role={role}")
            reporter.bump("members", "dry:would_insert")
            dry_seen.add((org_id, uid))
            continue

        status, body = await sb.post("/rest/v1/org_members", payload)
        if status < 400:
            print(f"  [ok] inserted user={uid} role={role}")
            reporter.bump("members", "inserted")
            dry_seen.add((org_id, uid))
        else:
            print(f"  [error:{status}] user={uid} body={str(body)[:160]}")
            reporter.bump("members", f"error:{status}")
            reporter.error("members", f"{org_id}/{uid}", f"http {status}: {str(body)[:120]}")


async def migrate_invites(
    db, sb: SupabaseClient, ws_org: Dict[str, str], reporter: Reporter, *,
    execute: bool, limit: Optional[int],
) -> None:
    print("\n--- workspace_invites → invitations ---")
    cursor = db["workspace_invites"].find({}, {"_id": 0})
    seen = 0
    async for row in cursor:
        if limit and seen >= limit:
            break
        seen += 1
        wid = row.get("workspace_id")
        token = row.get("token")
        org_id = ws_org.get(wid)

        if not org_id:
            print(f"  [skip:no_mapping] ws={wid} token={token[:8] if token else '?'}")
            reporter.bump("invites", "skip:no_mapping")
            continue
        if not token:
            print(f"  [skip:no_token] invite_id={row.get('invite_id')}")
            reporter.bump("invites", "skip:no_token")
            continue

        # Supabase invitations.token is uuid; legacy Mongo tokens are
        # ``secrets.token_urlsafe(24)`` (~32 chars, NOT a uuid). When
        # the Mongo row lacks a paired Supabase token (it would have
        # been stored on ``supabase_token`` after Phase 7c shadow-write),
        # we generate a fresh uuid for the new Supabase row and store
        # it back on Mongo for cross-linking on the next run.
        sb_token = row.get("supabase_token") or (token if is_uuid(token) else str(uuid.uuid4()))

        # Dedup by token
        status, body = await sb.get(
            "/rest/v1/invitations",
            {"token": f"eq.{sb_token}", "select": "id", "limit": "1"},
        )
        if status == 200 and isinstance(body, list) and body:
            print(f"  [skip:duplicate] token={sb_token[:8]}…")
            reporter.bump("invites", "skip:duplicate")
            continue

        role = normalize_role(row.get("role"))
        email = (row.get("email") or "").strip().lower()
        if not email:
            email = f"pending+{org_id[:8]}@quantro.invite"

        payload: Dict[str, Any] = {
            "org_id": org_id,
            "email": email,
            "role": role,
            "token": sb_token,
            "invited_by": row.get("created_by") if is_uuid(row.get("created_by")) else None,
            "accepted": bool((row.get("used_count", 0) or 0) > 0 or row.get("revoked")),
        }
        if row.get("expires_at") and isinstance(row["expires_at"], datetime):
            payload["expires_at"] = row["expires_at"].astimezone(timezone.utc).isoformat()
        if row.get("full_name"):
            payload["full_name"] = row["full_name"]

        if not execute:
            print(f"  [dry] would insert email={email} role={role} token={sb_token[:8]}…")
            reporter.bump("invites", "dry:would_insert")
            continue

        status, body = await sb.post("/rest/v1/invitations", payload)
        if status < 400:
            print(f"  [ok] inserted token={sb_token[:8]}…")
            reporter.bump("invites", "inserted")
            # Cross-link Mongo row → Supabase id (so future shadow-writes
            # on revoke can find the right Supabase row).
            try:
                rows = body if isinstance(body, list) else [body] if body else []
                inserted_id = (rows[0] if rows else {}).get("id") if rows else None
                if inserted_id:
                    await db["workspace_invites"].update_one(
                        {"invite_id": row.get("invite_id")},
                        {"$set": {"supabase_invite_id": inserted_id, "supabase_token": sb_token}},
                    )
            except Exception:
                pass
        else:
            print(f"  [error:{status}] token={sb_token[:8]}… body={str(body)[:160]}")
            reporter.bump("invites", f"error:{status}")
            reporter.error("invites", sb_token[:12], f"http {status}: {str(body)[:120]}")


async def migrate_audit(
    db, sb: SupabaseClient, ws_org: Dict[str, str], reporter: Reporter, *,
    execute: bool, limit: Optional[int],
) -> None:
    print("\n--- audit_log → org_audit_logs ---")
    cursor = db["audit_log"].find({}, {"_id": 0}).sort("timestamp", 1)  # oldest first
    seen = 0
    async for row in cursor:
        if limit and seen >= limit:
            break
        seen += 1
        wid = row.get("workspace_id")
        target = row.get("target_member_id")
        actor = row.get("user_id")
        event_type = row.get("event_type")
        action = AUDIT_EVENT_MAP.get(event_type)
        org_id = ws_org.get(wid)

        if not org_id:
            reporter.bump("audit", "skip:no_mapping")
            continue
        if not action:
            # Event types outside the constrained vocabulary
            # (workspace.*, policy.*, integration.*) are intentionally
            # NOT migrated — there's no slot for them in
            # org_audit_logs.action and squeezing them as
            # "permissions_modified" would dilute the timeline.
            reporter.bump("audit", "skip:unmapped_action")
            continue
        if not is_uuid(target):
            reporter.bump("audit", "skip:no_target_uuid")
            continue

        ts = row.get("timestamp")
        ts_iso = (
            ts.astimezone(timezone.utc).isoformat()
            if isinstance(ts, datetime)
            else None
        )

        # Dedup: same (org_id, action, target_user_id, created_at).
        params = {
            "org_id": f"eq.{org_id}",
            "action": f"eq.{action}",
            "target_user_id": f"eq.{target}",
            "select": "id",
            "limit": "1",
        }
        if ts_iso:
            params["created_at"] = f"eq.{ts_iso}"
        status, body = await sb.get("/rest/v1/org_audit_logs", params)
        if status == 200 and isinstance(body, list) and body:
            reporter.bump("audit", "skip:duplicate")
            continue

        meta = dict(row.get("metadata") or {})
        meta.setdefault("event_type", event_type)
        meta.setdefault("description", row.get("description"))

        payload: Dict[str, Any] = {
            "org_id": org_id,
            "action": action,
            "target_user_id": target,
            "actor_user_id": actor if is_uuid(actor) else None,
            "metadata": meta,
        }
        old_role = meta.get("previous_role") or meta.get("old_role")
        new_role = meta.get("new_role")
        if old_role:
            payload["old_role"] = normalize_role(old_role)
        if new_role:
            payload["new_role"] = normalize_role(new_role)
        if ts_iso:
            payload["created_at"] = ts_iso

        if not execute:
            reporter.bump("audit", "dry:would_insert")
            continue

        status, body = await sb.post(
            "/rest/v1/org_audit_logs", payload, prefer="return=minimal"
        )
        if status < 400:
            reporter.bump("audit", "inserted")
        else:
            reporter.bump("audit", f"error:{status}")
            reporter.error(
                "audit",
                f"{action}/{target[:8]}/{ts_iso or '?'}",
                f"http {status}: {str(body)[:120]}",
            )


# ── Main ─────────────────────────────────────────────────────────────
async def main(args: argparse.Namespace) -> None:
    sb = SupabaseClient()
    print(f"[supabase] {SUPABASE_URL}  auth={'service-role' if sb.use_service else 'anon'}")
    if not sb.use_service:
        print(
            "[warn] No SUPABASE_SERVICE_ROLE_KEY found. Anon-key writes are "
            "subject to RLS and may fail for rows you don't own. Strongly "
            "recommend running with service-role for backfill."
        )

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    ws_org = await build_workspace_org_map(db)
    print(f"[mapping] {len(ws_org)} workspace(s) mapped to Supabase orgs:")
    for wid, oid in ws_org.items():
        print(f"   - {wid:30s} → {oid}")
    if DEFAULT_WORKSPACE_ID not in ws_org:
        print(
            f"[warn] '{DEFAULT_WORKSPACE_ID}' has no mapping. "
            "Set QUANTRO_DEFAULT_ORG_ID in /app/backend/.env to enable it."
        )

    if not args.execute:
        print("\n[mode] DRY-RUN — nothing will be written. Use --execute for the real run.")
    else:
        print("\n[mode] EXECUTE — rows will be written to Supabase.")
        if not args.yes:
            confirm = input("Type 'YES' to proceed: ").strip()
            if confirm != "YES":
                print("[abort] Confirmation not given.")
                client.close()
                return

    reporter = Reporter()
    table = args.table.lower()
    if table in ("members", "all"):
        await migrate_members(db, sb, ws_org, reporter, execute=args.execute, limit=args.limit)
    if table in ("invites", "all"):
        await migrate_invites(db, sb, ws_org, reporter, execute=args.execute, limit=args.limit)
    if table in ("audit", "all"):
        await migrate_audit(db, sb, ws_org, reporter, execute=args.execute, limit=args.limit)

    reporter.print_summary()

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump({"counts": reporter.counts, "errors": reporter.errors}, f, indent=2)
        print(f"\n[json] full report written to {args.json_out}")

    client.close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Backfill MongoDB → Supabase. DRY-RUN by default.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help="Actually write to Supabase. Default is dry-run.",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive 'YES' confirmation when --execute is used.",
    )
    p.add_argument(
        "--table",
        choices=["members", "invites", "audit", "all"],
        default="all",
        help="Restrict which collection to process (default: all).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after N rows per table (handy for spot-checks).",
    )
    p.add_argument(
        "--json-out",
        type=str,
        default=None,
        help="Write a machine-readable report to this path.",
    )
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
