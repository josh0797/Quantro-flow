# Phase 1 — Identity / tenancy Source of Truth (Supabase)

Finishes the Phase 7c dual-write cutover for **membership, invites, and audit**.

Supabase tables are the SoT:

| Concern | Supabase (SoT) | Mongo (optional mirror / rollback) |
|---------|----------------|-------------------------------------|
| Members | `org_members` | `workspace_members` |
| Invites | `invitations` | `workspace_invites` |
| Audit | `org_audit_logs` | `audit_log` |
| Workspaces / users | projections (`organizations`, Auth users) | `workspaces`, `users` (still used for profile + workspace mapping) |

No new parallel tables. Extends Phase 7c (`people_onboarding_steps` + existing org schema).

## Prerequisites

1. Phase 7c SQL applied (`supabase/migrations/20260426_people_onboarding_audit.sql`).
2. Backfill run (dry-run then execute): `scripts/backfill_mongo_to_supabase.py`.
3. Env:
   - `SUPABASE_URL`, `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY` (required for reliable RBAC lookups + invite accept)
   - `QUANTRO_DEFAULT_ORG_ID` (maps legacy `default` workspace)

## Flip `DB_PRIMARY`

```bash
# SoT (Phase 1 default)
QUANTRO_DB_PRIMARY=supabase

# Optional Mongo mirror while validating (default)
QUANTRO_MONGO_MIRROR=1

# After confidence: freeze Mongo identity writes
QUANTRO_MONGO_MIRROR=0
```

Restart the backend after changing env.

### Rollback

```bash
QUANTRO_DB_PRIMARY=mongo
# Keep mirror on so Mongo has recent rows, or re-run backfill the other way if needed
QUANTRO_MONGO_MIRROR=1
```

Reads fall back to Mongo; Supabase shadow-writes continue when configured.

## What changed vs Phase 7c

Phase 7c already dual-wrote and supported `QUANTRO_DB_PRIMARY=supabase` **reads** for list members/invites/audit, but:

- Default primary was still `mongo`.
- RBAC (`_membership_for`) always required a Mongo `workspace_members` doc.
- Invite peek/accept were Mongo-only.
- Writes always hit Mongo first; Supabase was best-effort shadow.

Phase 1:

- Default `QUANTRO_DB_PRIMARY=supabase`.
- Membership / invite / role / audit paths treat Supabase as SoT.
- Mongo identity writes are gated by `QUANTRO_MONGO_MIRROR` (default on).
- Invite accept works without Mongo member/invite docs.
- `user_sessions` is **frozen** (unused — auth is Supabase JWT only).

## Frozen: `user_sessions`

The Mongo `user_sessions` collection is bound in `server.py` only so legacy scripts do not crash. **Do not read or write it.** Session authority is the Supabase access token validated by `get_current_user`.

## Residual Mongo reads (known)

Even with `DB_PRIMARY=supabase`, these still touch Mongo (out of scope for this PR / needed for UX):

- `users` projection (email, name, picture on Members roster)
- `workspaces` docs for `org_id` mapping and display names
- Login / workspace claim paths that still upsert `workspace_members` for legacy single-tenant
- Onboarding aggregation still merges Mongo when listing steps
- Rollback path (`QUANTRO_DB_PRIMARY=mongo`)

## Tests

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -q httpx pytest pytest-asyncio
PYTHONPATH=backend pytest test_phase1_identity_sot.py -q
```

## Cutover checklist

1. Backfill complete; spot-check `org_members` / `invitations` / `org_audit_logs` counts.
2. Deploy with `QUANTRO_DB_PRIMARY=supabase` + `QUANTRO_MONGO_MIRROR=1`.
3. Exercise Members UI: invite → accept → role change → audit.
4. Set `QUANTRO_MONGO_MIRROR=0` when ready to stop Mongo identity writes.
5. Later phase: drop Mongo identity collections after a soak period.
