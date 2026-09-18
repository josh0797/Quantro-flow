# Live inbox/calendar: hide demo seed after Google connects

## Problem

After Google OAuth + sync, simulation inbox/calendar rows were marked
`hidden_by_real: True`, but `GET /api/inbox` and calendar list endpoints only
applied `get_mode_filter` (workspace + `is_simulation`). Demo seed (e.g. Sarah
Chen) could still appear alongside DATOS REALES. OAuth callback also redirected
without kicking a background sync, so onboarding waited on a manual
"Sincronizar" click.

## Fix

1. **Live reads** — `get_mode_filter()` adds `hidden_by_real: {"$ne": True}` in
   Live mode (missing field = visible). Covers inbox, calendar, dashboard
   counters, and any other caller of the helper.
2. **OAuth callback** — on successful connect, `asyncio.create_task(
   _perform_google_sync_for_workspace(workspace_id))` before the redirect
   (same fire-and-forget pattern as auto-sync resume).
3. **Background sync** — `_perform_google_sync_for_workspace` now also marks
   simulation inbox/calendar rows `hidden_by_real: True` and flips
   `simulation_mode` off (mirrors `POST /api/integrations/google/sync`).
4. **Seed** — `seed_database()` stamps inbox + calendar rows with
   `is_simulation: True` and `workspace_id` so mode filter + hide flag work
   cleanly for new Atlas seeds.
