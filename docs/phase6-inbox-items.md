# Phase 6.1 — Inbox items (Supabase / Postgres)

Migrates the **inbox_items** product domain toward Supabase without flipping
reads in this PR. Contacts, calendar, and activity stay Mongo.

Cutover doc maps product “Phase 4” → inbox (+ activity later). This PR is
**inbox_items only**.

| Concern | Mongo (default read) | Supabase |
|---------|----------------------|----------|
| Inbox messages (seed + Gmail/Outlook sync + AI) | `inbox_items` | `inbox_items` |
| Activity events | `activity_events` | **Next** |
| Contacts / calendar | Mongo | **Later** |

## Design

Pattern: **dual-write → backfill → flip read → stop Mongo write**.

Persistence goes through `backend/inbox_store.py` (Motor-like facade).
`server.py` keeps the same `inbox_col.*` call sites; filters from
`get_mode_filter()` (including `hidden_by_real`) are unchanged.

### App id mapping

| Path | Mongo field | Postgres `inbox_id` |
|------|-------------|---------------------|
| Seed / AI routes | `inbox_id` | `inbox_id` |
| Google / Outlook sync `$setOnInsert` | `id` | `inbox_id` (= that `id`) |

Both `from_email` (seed) and `from_address` (sync) are stored.

### RLS

| Table | Posture |
|-------|---------|
| `inbox_items` | **service_role only** (bodies may be sensitive). Org-scoped `authenticated` reads deferred — same vault posture as Phase 2/3. |

Backend uses `SUPABASE_SERVICE_ROLE_KEY`. Missing tables / transport errors →
warning log + Mongo (graceful degrade). Error logs truncate / avoid bulk
email bodies.

## Migration

Apply in Supabase SQL editor (or CLI):

```text
supabase/migrations/20260918200000_phase6_inbox_items.sql
```

### SQL apply instructions

1. Open Supabase Dashboard → SQL → New query.
2. Paste the full contents of `20260918200000_phase6_inbox_items.sql`.
3. Run. Safe to re-run (idempotent `IF NOT EXISTS` / `CREATE OR REPLACE`).
4. Confirm: Table Editor shows `public.inbox_items` with RLS enabled;
   only `service_role` has grants.

Unique keys:

- `(workspace_id, inbox_id)`
- partial `(workspace_id, gmail_id) WHERE gmail_id IS NOT NULL`
- partial `(workspace_id, ms_id) WHERE ms_id IS NOT NULL` (Outlook)

## Env flags

```bash
# Default for this Phase 6.1 PR — safe without backfill / Fly secret flips
QUANTRO_INBOX_PRIMARY=mongo

# Dual-write to Supabase whenever URL + service role are set (automatic)
# SUPABASE_URL=...
# SUPABASE_SERVICE_ROLE_KEY=...

# After migration + backfill, flip reads to Supabase (Mongo fallback)
QUANTRO_INBOX_PRIMARY=supabase

# Mongo writes when primary=supabase (prefer dedicated flag; else shared)
QUANTRO_INBOX_MONGO_MIRROR=1
# or QUANTRO_MONGO_MIRROR=1

# Later: freeze Mongo inbox writes
QUANTRO_INBOX_MONGO_MIRROR=0
```

`QUANTRO_INBOX_PRIMARY` is **independent** of Phase 1 `QUANTRO_DB_PRIMARY`,
Phase 2 `QUANTRO_SECRETS_PRIMARY`, Phase 3 `QUANTRO_ACTIONS_PRIMARY`, and
Phase 4 Facturapi connect flags.

### Behaviour matrix

| `QUANTRO_INBOX_PRIMARY` | Reads | Mongo writes | Supabase writes |
|-------------------------|-------|--------------|-----------------|
| `mongo` (default) | Mongo | always | when SB configured (dual-write) |
| `supabase` | Supabase → Mongo fallback | if mirror on | when SB configured |

## Backfill

```bash
# Dry-run (default)
python scripts/backfill_mongo_to_supabase.py --table inbox_items

# Execute
python scripts/backfill_mongo_to_supabase.py --table inbox_items --execute --yes
```

Idempotent upsert on `(workspace_id, inbox_id)`. Sync docs that only have
Mongo `id` map that value into `inbox_id`.

## Rollout

1. Apply SQL migration in Supabase.
2. Deploy backend with defaults (`QUANTRO_INBOX_PRIMARY=mongo`) → dual-write.
   **Do not** flip Fly secrets in this PR.
3. Backfill dry-run, then `--execute`.
4. Spot-check row counts vs Mongo; sample `hidden_by_real` after a Google sync.
5. Set `QUANTRO_INBOX_PRIMARY=supabase`, restart, exercise list / analyze /
   approve / sync.
6. Optionally `QUANTRO_INBOX_MONGO_MIRROR=0` after soak.

## Rollback

```bash
QUANTRO_INBOX_PRIMARY=mongo
QUANTRO_INBOX_MONGO_MIRROR=1
```

Restart backend. Reads return to Mongo; Supabase dual-write continues when
configured.

## Next domains

1. **activity_events** — same dual-write pattern; tied to inbox AI/actions logging.
2. **contacts** then **calendar** — after inbox read path is stable on Supabase.

`escalation_rules` remain Mongo until a dedicated follow-up (still deferred
from Phase 3).

## Tests

```bash
cd backend && PYTHONPATH=. pytest tests/test_hidden_by_real_filter.py -q
PYTHONPATH=backend pytest test_phase6_inbox_items.py -q
```

## Code map

- Store: `backend/inbox_store.py`
- Wiring: `backend/server.py` (`wrap_inbox_col`)
- SQL: `supabase/migrations/20260918200000_phase6_inbox_items.sql`
- Backfill: `scripts/backfill_mongo_to_supabase.py --table inbox_items`
- Docs: this file
