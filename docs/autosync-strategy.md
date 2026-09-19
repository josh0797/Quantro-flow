# Autosync strategy

## Problem
Fly `auto_stop_machines` + `min_machines_running=0` stops the only process that
runs `_periodic_provider_sync_loop`, causing missed syncs and cold-start
`ERR_CONNECTION_CLOSED` on the API.

## Decision (now)
1. **`min_machines_running = 1`** in `fly.toml` — keep one HTTP machine warm.
2. Autosync stays on the **HTTP process** (same app).
3. **Sync lock / idempotency** per `provider + workspace_id` with a time window
   (`QUANTRO_SYNC_LOCK_WINDOW_SECONDS`, default 300s) via Mongo `sync_locks`
   (+ in-process fallback) so multi-instance does not double-sync.

## Later
Dedicated worker / Machines process group for sync only, separate from HTTP
scaling. Not required for this hardening PR.
