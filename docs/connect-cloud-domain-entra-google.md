# Connect — cloud domain, Google Cloud, Microsoft Entra

## Canonical frontend
- Production: `https://www.quantroflow.cloud` (`FRONTEND_PUBLIC_URL`)
- Also allowed via CORS: `https://quantroflow.cloud`, `https://quantro-flow.vercel.app`
- Apex `FRONTEND_PUBLIC_URL=https://quantroflow.cloud` is normalized to `https://www.quantroflow.cloud` on OAuth bounce

## Required env (backend)
```
FRONTEND_PUBLIC_URL=https://www.quantroflow.cloud
BACKEND_PUBLIC_URL=https://<api-host>
ALLOWED_FRONTEND_ORIGINS=https://www.quantroflow.cloud,https://quantroflow.cloud,https://quantro-flow.vercel.app
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_TOKENS_ENCRYPTION_KEY=...   # Fernet key (also used for MS tokens)
MS_CLIENT_ID=...
MS_CLIENT_SECRET=...
MS_TENANT_ID=common                 # or single-tenant GUID
MS_OAUTH_REDIRECT_URI=https://<api-host>/api/integrations/microsoft/callback
CALENDAR_BACKFILL_PAST_DAYS=90
CALENDAR_LOOKAHEAD_DAYS=180
QUANTRO_OS_API_URL=https://<quantro-os-host>
QUANTRO_OS_SERVICE_TOKEN=<server-only-service-token>
```

## Why Microsoft shows “Configuración pendiente”
Root cause is deploy config, not a workspace flag: `MicrosoftAdapter.get_status`
returns `configuration_missing` when `MS_CLIENT_ID` / `MS_CLIENT_SECRET` /
`GOOGLE_TOKENS_ENCRYPTION_KEY` are unset (`microsoft_oauth.is_oauth_configured()`).
Welcome modal mirrors `/api/integrations/microsoft/status` → `configured:false`.

## Microsoft Entra (manual)
1. App registration (Accounts in any org + personal Microsoft accounts if using `common`).
2. Web redirect URI: `https://<api-host>/api/integrations/microsoft/callback`.
3. Certificates & secrets → client secret → `MS_CLIENT_SECRET`.
4. API permissions (delegated): `User.Read`, `Mail.Read`, `Calendars.Read`,
   `offline_access` (OIDC). Incremental later: `Mail.Send`, `Calendars.ReadWrite`.
5. Set `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_TENANT_ID`, redirect URI env; redeploy.
6. Visible Connect name remains **Microsoft Outlook** (`provider_id=microsoft`).

## Google Cloud (manual)
1. OAuth client (Web) authorized JavaScript origins:
   - `https://www.quantroflow.cloud`
   - `https://quantroflow.cloud`
   - authorized Vercel origin(s)
2. Authorized redirect URIs:
   - `https://<api-host>/api/integrations/google/callback`
3. Ensure backend CORS includes the cloud origins (defaults now do).
4. Flow: `/welcome/inbox` → `/api/integrations/google/start?return_to=/welcome/inbox`
   → Google → callback → bounce to `FRONTEND_PUBLIC_URL` + return_to.

## Facturación (Quantro OS)
- Connect provider id `quantro_invoicing`, visible name **Facturación**.
- Service-to-service only; token never sent to the browser.
- Flow queries OS invoices and prepares Gmail/Outlook reply payloads; does not emit CFDI.
