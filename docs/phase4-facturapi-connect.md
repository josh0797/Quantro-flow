# Phase 4 — Facturapi Connect (retired 2026-09-30)

**Status: retired.** Quantro Flow no longer connects customer-owned Facturapi
(PAC) accounts and no longer holds, stores or reads any Facturapi key.

## Decision (owner, 2026-09-30)

- **Quantro OS is the only fiscal system.** It stamps CFDI from Quantro's own
  Facturapi account; customers buy Quantro's stamps. Customers never connect
  their own Facturapi account.
- **Flow only reads invoices Quantro OS already processed**, through the
  `quantro_invoicing` provider
  (`backend/integrations/providers/quantro_invoicing.py`, service-to-service
  with `QUANTRO_OS_API_URL` / `QUANTRO_OS_SERVICE_TOKEN`). That lets Flow email
  an invoice a customer asks for, using the business's own Gmail/Outlook
  connection.

## What was removed

- `FacturapiAdapter` (`backend/integrations/providers/facturapi.py`) and the
  unregistered Facturapi action handlers (`backend/actions/handlers/facturapi.py`).
- `POST /api/connect/providers/facturapi/connect` (it already answered 410) and
  the webhook receiver `POST /api/webhooks/facturapi/{connection_id}/{webhook_token}`.
- The System Health "Facturapi connectivity" and webhook-signature checks.
- The Facturapi wrappers and webhook-receipt helpers in
  `backend/connect_store.py`, and `facturapi` as a provider of
  `backend/provider_secrets_store.py`.
- The `facturapi_connections` / `facturapi_webhook_events` datasets of both
  Mongo → Supabase backfills (the Mongo exit is done).
- The Connect UI dialog strings and the Facturapi tests.

## Data left in place

No migration was written and no data was deleted. Supabase still holds
`provider_connections` rows with `provider = 'facturapi'` and the
`webhook_events` table; nothing in Flow reads or writes them any more. A later,
owner-approved migration can purge them.

The original migration
`supabase/migrations/20260918190000_phase4_facturapi_connect.sql` is kept as
history. The `integrations_config` part of Phase 4 (Connect UI catalog,
`backend/connect_store.py`) is unaffected.
