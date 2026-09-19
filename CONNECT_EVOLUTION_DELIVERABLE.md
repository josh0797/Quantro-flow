# Quantro Connect cleanup/evolution — deliverable

**Repo:** josh0797/Quantro-flow only (konta untouched)
**Branch:** `feat/connect-outlook-os-invoicing-cloud-domain` @ `4a81aa3` (+ chore commit)
**Box path:** `/workspace/Quantro-flow`
**Patch for Mac:** `/workspace/Quantro-flow-connect-evolution.patch`
**Mac helper:** `/workspace/push-connect-pr-from-mac.sh`
**PR URL:** _not created_ — box has no `gh` auth / no git credentials; Mac must push + `gh pr create` (do not merge).

## 1. Files modified
- `backend/server.py` — CORS cloud defaults, FRONTEND_PUBLIC_URL apex→www, MS calendar metrics sync, register `quantro_invoicing`, deprecate Facturapi connect 410
- `backend/microsoft_oauth.py` — calendar window env + Graph pagination + ical/lastModified/isCancelled
- `backend/product_domain_store.py` — `ical_uid`, `external_updated_at`, upsert outcomes
- `backend/integrations/providers/microsoft.py` — visible name **Microsoft Outlook**
- `backend/integrations/providers/quantro_invoicing.py` — new Facturación adapter (OS S2S)
- `backend/actions/handlers/quantro_invoicing.py` — query + prepare_reply
- `backend/actions/bootstrap.py` — replace Facturapi CFDI actions with OS invoicing actions
- `backend/actions/policy_engine.py` — provider id update
- `frontend/src/pages/Connect.js` — remove Coming Soon five + Facturapi dialog; return_to `/connect`
- `frontend/src/lib/api.js`, `i18n/translations.js`, `welcome/OnboardingShell.js`
- `supabase/migrations/20260919140000_calendar_events_ical_uid.sql`
- `docs/connect-cloud-domain-entra-google.md`, `docs/vercel-deploy.md`
- Tests: `backend/tests/test_connect_evolution.py`, updated CORS + calendar tests

## 2. Required env vars
```
FRONTEND_PUBLIC_URL=https://www.quantroflow.cloud
BACKEND_PUBLIC_URL=https://<api>
ALLOWED_FRONTEND_ORIGINS=https://www.quantroflow.cloud,https://quantroflow.cloud,https://quantro-flow.vercel.app
GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_TOKENS_ENCRYPTION_KEY
MS_CLIENT_ID / MS_CLIENT_SECRET / MS_TENANT_ID=common
MS_OAUTH_REDIRECT_URI=https://<api>/api/integrations/microsoft/callback
CALENDAR_BACKFILL_PAST_DAYS=90   # optional
CALENDAR_LOOKAHEAD_DAYS=180      # optional
QUANTRO_OS_API_URL=https://<os>
QUANTRO_OS_SERVICE_TOKEN=<server-only>
```
`QUANTRO_CALENDAR_PRIMARY` left unchanged (mongo unless unrelated).

## 3. Tests
- `backend/tests/` → **102 passed**
- Includes `test_connect_evolution.py` (Outlook fetch/pagination/metrics, CORS cloud, Facturación mocked query+reply, Connect.js grep assertions, bootstrap without facturapi.invoice.create)

## 4. Manual steps (Google / Entra)
See `docs/connect-cloud-domain-entra-google.md`.
- **MS “Configuración pendiente” root cause:** missing `MS_CLIENT_ID`/`MS_CLIENT_SECRET`/`GOOGLE_TOKENS_ENCRYPTION_KEY` on deploy (`is_oauth_configured()` → `configuration_missing`). Not a false workspace flag. Set Entra app + secrets to unlock.
- **Google on www:** add JS origins + ensure CORS/FRONTEND_PUBLIC_URL (code defaults fixed).

## 5. PR
Mac:
```bash
# copy patch from box /workspace/Quantro-flow-connect-evolution.patch to Mac
cd /Users/josh/Desktop/Quantro-flow
git fetch origin && git checkout -B feat/connect-outlook-os-invoicing-cloud-domain origin/main
git am /path/to/Quantro-flow-connect-evolution.patch
# or: bash /workspace/push-connect-pr-from-mac.sh
git push -u origin HEAD
gh pr create --base main --title "feat(connect): Outlook, cloud CORS, Quantro OS Facturación" --body "..."
# DO NOT MERGE
```

## 6. Remaining risks
- Production still blocked for Outlook until Entra secrets set.
- Quantro OS `/service-invoices` contract assumed; adjust path if OS API differs.
- Facturapi webhook route + vault code kept for compatibility; Connect UI no longer uses them; 410 on old connect endpoint.
- Historical migrations retaining “Facturapi” name intentionally retained.
- First-time calendar sync metrics include `possible_duplicates` by repeated `ical_uid` in one Graph page set (informational; no auto-merge across Google/MS).
