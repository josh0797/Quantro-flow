# Phase 6.2–6.3 — activity / content / contacts / calendar → Supabase

## Tables
| Mongo collection | Supabase table | Flag (default `mongo`) |
|---|---|---|
| `activity_events` | `activity_events` | `QUANTRO_ACTIVITY_PRIMARY` |
| `content_items` | `content_items` | `QUANTRO_CONTENT_PRIMARY` |
| `content_templates` | `content_templates` | `QUANTRO_CONTENT_PRIMARY` |
| `contacts` | `contacts` | `QUANTRO_CONTACTS_PRIMARY` |
| `calendar_events` | `calendar_events` | `QUANTRO_CALENDAR_PRIMARY` |

Migration: `supabase/migrations/20260918210000_phase6_activity_content_crm.sql`  
Store: `backend/product_domain_store.py` (wired in `server.py`)

## Rollout
1. Apply SQL on Konta Supabase
2. Deploy/redeploy API (Fly) with dual-write (primary still mongo)
3. Backfill when ready (extend `scripts/backfill_mongo_to_supabase.py`)
4. Flip primaries one domain at a time after compare

## Notes
- Dual-write requires `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`
- Upsert conflict: `(workspace_id, <app_id>)`
- No automatic primary flip in this PR

## Backfill CLI

After dual-write is live, historical Mongo rows can be copied with:

```bash
python scripts/backfill_mongo_to_supabase.py --table activity_events
python scripts/backfill_mongo_to_supabase.py --table content_items
python scripts/backfill_mongo_to_supabase.py --table content_templates
python scripts/backfill_mongo_to_supabase.py --table contacts
python scripts/backfill_mongo_to_supabase.py --table calendar_events
# then --execute --yes once dry-run looks clean
```

Supported via `scripts/backfill_mongo_to_supabase.py` Phase 6.2–6.3 migrators (mirrors `product_domain_store.DomainConfig`).

## Calendar primary (hardening)

`QUANTRO_CALENDAR_PRIMARY` must remain **`mongo`** until the canonical
`external_event_id` / `external_provider` / `start_time` model + tests are green.
Do not recommend supabase as calendar primary in runbooks until then.
See `docs/flip-audit-report.md` and migration `20260919010000_calendar_events_canonical.sql`.

