# QUANTRO_*_PRIMARY flip audit

Do **not** auto-flip unsafe primaries. Calendar must remain **mongo** until new
canonical calendar tests pass.

| Env var | Primary (intended/prod) | Mirror | Backfill status | safe_to_flip | Notes |
|---------|-------------------------|--------|-----------------|--------------|-------|
| `QUANTRO_SECRETS_PRIMARY` | supabase | ON (`QUANTRO_MONGO_MIRROR`) | known (phase 2) | yes (already) | Keep mirror until Mongo removal |
| `QUANTRO_ACTIONS_PRIMARY` | supabase (audited) | ON | known (phase 3) | yes if backfill verified | Confirm Fly secret matches |
| `QUANTRO_INBOX_PRIMARY` | supabase | ON | known (phase 6.1) | yes (already) | |
| `QUANTRO_ACTIVITY_PRIMARY` | supabase | ON | known (phase 6.2) | yes (already) | |
| `QUANTRO_CONTENT_PRIMARY` | supabase | ON | known (phase 6.2) | yes (already) | |
| `QUANTRO_CONTACTS_PRIMARY` | supabase | ON | known (phase 6.3) | yes (already) | |
| `QUANTRO_CALENDAR_PRIMARY` | **mongo** | N/A while primary=mongo | partial / field mismatch | **no** | Premature flip caused Google/MS `gcal_id`/`ms_id`/`start`/`end` vs SB `start_time` mismatch. Stay mongo until hardening tests green + backfill with canonical mapper. |
| `QUANTRO_DB_PRIMARY` | supabase | ON | identity | conditional | Workspace APIs still touch Mongo |

## Calendar policy

- Set `QUANTRO_CALENDAR_PRIMARY=mongo` on Fly (this PR / ops).
- Do **not** document supabase as recommended primary until:
  1. Additive migration `20260919010000_calendar_events_canonical.sql` applied
  2. Tests: Google sync→SB, MS sync→SB, internal→SB, legacy backfill shape, duplicate external no-dup
  3. Backfill re-run with `_normalize_calendar_mongo_row`


## Audit hardening (PR #20 remaining findings)

Implemented on branch (keep `QUANTRO_CALENDAR_PRIMARY=mongo`):

1. **Calendar Supabase upsert** — `calendar_on_conflict` + `_sb_upsert_doc` use
   `workspace_id,external_provider,external_event_id` when `external_event_id` is set;
   preserve existing `event_id` on subsequent external upserts.
2. **Legacy Mongo dedupe** — `upsert_calendar_external_event` / `find_calendar_event_for_external_sync`
   resolve canonical then legacy `gcal_id`/`ms_id`; update in place; do not delete legacy keys.
3. **MS incremental consent** — `requested_scopes` in OAuth state; callback passes scopes to
   token exchange; Connect Grant Permission for Microsoft with `return_to=/connect`.
4. **Atomic sync lease** — `sync_lock.acquire_sync_lock_lease` via `find_one_and_update` + insert.

**Still NOT READY to flip calendar to Supabase** without applied migration + verified backfill + real smoke.
