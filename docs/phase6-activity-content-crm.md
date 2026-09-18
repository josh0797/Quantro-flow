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
