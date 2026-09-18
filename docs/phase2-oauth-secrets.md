# Phase 2 — OAuth secrets & Connect cutover (Supabase)

Moves **encrypted** Google / Microsoft OAuth tokens and short-lived OAuth CSRF
state toward Supabase as source of truth, without breaking deploys that have
not yet applied the migration or backfill.

| Concern | Mongo (default read) | Supabase |
|---------|----------------------|----------|
| Google tokens + metadata | `google_integrations` | `provider_connections` (`provider=google`) |
| Microsoft tokens + metadata | `microsoft_integrations` | `provider_connections` (`provider=microsoft`) |
| Google OAuth CSRF | `google_oauth_state` | `oauth_states` (`provider=google`) |
| Microsoft OAuth CSRF | `microsoft_oauth_state` | `oauth_states` (`provider=microsoft`) |

Out of scope: Facturapi, Actions / PolicyEngine, inbox/contacts/calendar sync
payloads, `integrations_config` UI rows.

## Encryption (do not rotate casually)

- Tokens are Fernet-encrypted **before** persistence (same as today).
- Key env name is unchanged: **`GOOGLE_TOKENS_ENCRYPTION_KEY`** (shared by Microsoft).
- Postgres stores **ciphertext only** (`access_token_enc` / `refresh_token_enc`).
- **Never log** access/refresh tokens (plaintext or ciphertext dumps).
- Rotating the Fernet key without a re-encrypt path invalidates every saved refresh token.

## Migration

Apply:

```text
supabase/migrations/20260918000000_provider_oauth_secrets.sql
```

Tables are **service_role only**: RLS enabled, no policies for `anon` /
`authenticated` (Konta vault posture). The FastAPI backend talks via
`SUPABASE_SERVICE_ROLE_KEY` in `backend/provider_secrets_store.py`.

## Env flags

```bash
# Default for this Phase 2 PR — safe without backfill
QUANTRO_SECRETS_PRIMARY=mongo

# Dual-write to Supabase whenever URL + service role are set (automatic)
# SUPABASE_URL=...
# SUPABASE_SERVICE_ROLE_KEY=...

# After migration + backfill, flip reads to Supabase (Mongo fallback)
QUANTRO_SECRETS_PRIMARY=supabase

# When primary=supabase, Mongo writes follow QUANTRO_MONGO_MIRROR (default on)
QUANTRO_MONGO_MIRROR=1

# Later: freeze Mongo secret writes
QUANTRO_MONGO_MIRROR=0
```

`QUANTRO_SECRETS_PRIMARY` is **independent** of Phase 1 `QUANTRO_DB_PRIMARY`
(identity). Identity can stay on Supabase while secrets remain Mongo until
you flip.

### Behaviour matrix

| `QUANTRO_SECRETS_PRIMARY` | Reads | Mongo writes | Supabase writes |
|---------------------------|-------|--------------|-----------------|
| `mongo` (default) | Mongo | always | when SB configured (dual-write) |
| `supabase` | Supabase → Mongo fallback | if `QUANTRO_MONGO_MIRROR=1` | when SB configured |

If Supabase tables are missing / unreachable, the store logs a warning and
keeps serving Mongo (graceful degrade).

OAuth **state** is dual-written when SB is configured; **consume** tries the
primary store then the other so mid-flip callbacks still succeed.

## Backfill

```bash
# Dry-run (default)
python scripts/backfill_mongo_to_supabase.py --table provider_connections

# Execute
python scripts/backfill_mongo_to_supabase.py --table provider_connections --execute --yes
```

Copies Fernet ciphertext as-is. Idempotent upsert on `(workspace_id, provider)`.

## Rollout

1. Apply SQL migration in Supabase.
2. Deploy backend with defaults (`QUANTRO_SECRETS_PRIMARY=mongo`) → dual-write starts.
3. Run backfill dry-run, then `--execute`.
4. Spot-check `provider_connections` row counts vs Mongo.
5. Set `QUANTRO_SECRETS_PRIMARY=supabase`, restart, exercise connect / refresh / disconnect.
6. Optionally `QUANTRO_MONGO_MIRROR=0` after soak.

## Rollback

```bash
QUANTRO_SECRETS_PRIMARY=mongo
QUANTRO_MONGO_MIRROR=1
```

Restart backend. Reads return to Mongo; Supabase dual-write continues when configured.

## Residual Mongo reads (known)

Even with `QUANTRO_SECRETS_PRIMARY=supabase`:

- Fallback path when Supabase miss / error
- Autosync listing falls back to Mongo if SB query fails
- `integrations_config` (non-secret UI status) remains Mongo-only
- Inbox / calendar / contacts collections unchanged

## Tests

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -q httpx pytest pytest-asyncio
PYTHONPATH=backend pytest test_phase2_oauth_secrets.py -q
```

## Code map

- Store: `backend/provider_secrets_store.py`
- Routes: `backend/server.py` (google/microsoft status, start, callback, sync, disconnect, auto-sync)
- Crypto: `backend/google_oauth.py`, `backend/microsoft_oauth.py` (unchanged key names)
