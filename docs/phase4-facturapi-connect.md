# Phase 4 — Facturapi Connect + webhook inbox + integrations_config

Moves **Facturapi secrets**, **webhook receipts**, and the **Connect UI catalog**
toward Supabase with dual-write, while **default reads stay on Mongo** (no
auto-flip). Reuses the Phase 2 `provider_connections` vault — does **not**
invent a parallel secrets table.

| Concern | Mongo (default read) | Supabase |
|---------|----------------------|----------|
| Facturapi secret + metadata | `facturapi_connections` | `provider_connections` (`provider=facturapi`) |
| Webhook receipts | `facturapi_webhook_events` | `webhook_events` |
| Connect UI status/config | `integrations_config` | `integrations_config` (non-secret) |
| Google / Microsoft OAuth | unchanged Phase 2 | unchanged Phase 2 |

## Design

Pattern: **dual-write → backfill → optional flip → stop Mongo write**.

- Facturapi ciphertext maps `secret_key_encrypted` → `api_key_enc`,
  `webhook_token_encrypted` → `webhook_token_enc`,
  `webhook_signing_secret_encrypted` → `webhook_secret_enc`.
- Google/Microsoft continue to use `access_token_enc` / `refresh_token_enc`.
- `integrations_config` on Supabase **strips known secret field names** from
  `config` (UI catalog only). Secrets for Facturapi live in
  `provider_connections`.
- Persistence helpers: `backend/provider_secrets_store.py` (extended) +
  `backend/connect_store.py` (webhooks + UI catalog + Facturapi wrappers).
- `FacturapiAdapter` calls store helpers; Mongo collections remain for the
  `primary=mongo` path.

## Migration

Apply in the **Konta** Supabase project (SQL editor or CLI):

```text
supabase/migrations/20260918190000_phase4_facturapi_connect.sql
```

### How to apply (Konta Supabase)

1. Open [Supabase Dashboard](https://supabase.com/dashboard) → project **Konta**.
2. **SQL Editor** → New query.
3. Paste the full contents of
   `supabase/migrations/20260918190000_phase4_facturapi_connect.sql`.
4. Run. The script is idempotent (`if not exists` / drop+recreate check).
5. Spot-check:
   - `\d provider_connections` (or Table Editor) shows `api_key_enc`,
     `connection_id`, `meta`, …
   - Tables `webhook_events` and `integrations_config` exist.
   - RLS on; no policies for `anon` / `authenticated`; `service_role` granted.

CLI alternative (if linked):

```bash
supabase db push
# or
psql "$DATABASE_URL" -f supabase/migrations/20260918190000_phase4_facturapi_connect.sql
```

## Env flags

```bash
# Facturapi secrets + webhooks (shared with Phase 2 OAuth vault)
QUANTRO_SECRETS_PRIMARY=mongo          # default — do not flip on Fly in this PR
QUANTRO_MONGO_MIRROR=1

# Connect UI catalog (independent soft flip)
QUANTRO_INTEGRATIONS_CONFIG_PRIMARY=mongo   # default

# Dual-write fires whenever these are set (automatic)
# SUPABASE_URL=...
# SUPABASE_SERVICE_ROLE_KEY=...
```

| Flag | Default | Reads | Notes |
|------|---------|-------|-------|
| `QUANTRO_SECRETS_PRIMARY` | `mongo` | Facturapi + webhooks | Same as Phase 2 |
| `QUANTRO_INTEGRATIONS_CONFIG_PRIMARY` | `mongo` | UI catalog only | Independent of secrets |
| `QUANTRO_MONGO_MIRROR` | `1` | — | Gates Mongo writes when primary=`supabase` |

**This PR does not flip Fly secrets.** Deploy with defaults.

## Backfill

```bash
# Dry-run (default)
python scripts/backfill_mongo_to_supabase.py --table facturapi_connections
python scripts/backfill_mongo_to_supabase.py --table webhook_events
python scripts/backfill_mongo_to_supabase.py --table integrations_config

# Execute
python scripts/backfill_mongo_to_supabase.py --table facturapi_connections --execute --yes
python scripts/backfill_mongo_to_supabase.py --table webhook_events --execute --yes
python scripts/backfill_mongo_to_supabase.py --table integrations_config --execute --yes
```

## Rollout

1. Apply SQL migration on Konta Supabase.
2. Deploy backend with defaults (`QUANTRO_SECRETS_PRIMARY=mongo`,
   `QUANTRO_INTEGRATIONS_CONFIG_PRIMARY=mongo`) → dual-write starts.
3. Backfill dry-run, then `--execute`.
4. Spot-check row counts vs Mongo.
5. **Optional** flip reads:
   - `QUANTRO_SECRETS_PRIMARY=supabase` (Facturapi + webhooks)
   - `QUANTRO_INTEGRATIONS_CONFIG_PRIMARY=supabase` (UI catalog)
6. After soak, optionally `QUANTRO_MONGO_MIRROR=0`.

## Rollback

1. Set primaries back to `mongo` and restart.
2. Dual-write can stay on (harmless) or unset Supabase service role temporarily.
3. Do **not** drop Supabase columns/tables until Mongo is confirmed SoT again.
4. SQL check constraint / new tables can remain; they are additive.

## Residual Mongo

Until a later cutover phase, Mongo still holds:

- Live Facturapi docs when `QUANTRO_SECRETS_PRIMARY=mongo`
- Live webhook receipts under the same flag
- Live `integrations_config` when `QUANTRO_INTEGRATIONS_CONFIG_PRIMARY=mongo`
- Seed / bootstrap inserts in `server.py` that write Mongo directly outside the
  Connect UI update path (dual-write on list/get/update routes only)
- Google / Microsoft paths unchanged (Phase 2)

## Security

- Never log plaintext or ciphertext API keys / webhook tokens.
- Supabase tables are **service_role only** (RLS on, no anon policies).
- `integrations_config.config` on Supabase must not contain secret fields.

## Tests

```bash
cd backend && python -m pytest tests/test_facturapi_adapter.py -q
cd .. && python -m pytest test_phase4_facturapi_connect.py test_phase2_oauth_secrets.py -q
```
