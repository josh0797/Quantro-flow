# Sentry en Quantro Flow

Documento maestro (proyectos, política de PII, alertas, rollout): `docs/observability/sentry.md`
en el repo **konta** (josh0797/konta PR #67). Org de Sentry: `quantro-tb`.

| Pieza | Proyecto Sentry | Código | Variable |
|---|---|---|---|
| API FastAPI (Fly `quantro-flow-api`) | `quantro-flow-api` | `backend/observability.py` (init en `server.py` antes de `FastAPI()`) | `SENTRY_DSN` (Fly secret) |
| Web CRA (Vercel) | `quantro-flow-web` | `frontend/src/lib/sentry.js` (init en `src/index.js`) | `REACT_APP_SENTRY_DSN` (Vercel) |

Sin la variable, ambos son no-op (el SDK web ni siquiera se descarga).

## Backend
- `sentry-sdk[fastapi]==2.70.0`; integraciones FastAPI/Starlette capturan excepciones y respuestas 5xx.
- `send_default_pii=False`, `include_local_variables=False`, `max_request_body_size="never"`.
- `before_send`/`before_breadcrumb` (`scrub_event`/`scrub_breadcrumb`) + `EventScrubber` con denylist ampliada:
  Authorization, cookies, API keys, tokens, secrets, passwords, JWT de Supabase, `Bearer`, llaves de
  proveedores, tokens Fernet, emails, RFC, CURP, CLABE, tarjetas; usuario reducido a `{id}`.
- `environment`: `SENTRY_ENVIRONMENT` → `ENVIRONMENT`/`ENV` → `production` si corre en Fly.
- `release`: `SENTRY_RELEASE` → `GIT_SHA` → `FLY_IMAGE_REF` (Fly lo define solo).
- `traces_sample_rate`: `SENTRY_TRACES_SAMPLE_RATE` (default 0.05).
- Tests: `backend/tests/test_observability.py`.

## Frontend
- Import dinámico de `@sentry/react`, `sendDefaultPii: false`, sin tracing ni replay,
  `ignoreErrors` para extensiones/wallets (`window.ethereum`) y ResizeObserver, mismo scrubbing.
- `environment`: `REACT_APP_SENTRY_ENVIRONMENT` → `REACT_APP_VERCEL_ENV` → `NODE_ENV`;
  `release`: `REACT_APP_VERCEL_GIT_COMMIT_SHA` (requiere "Automatically expose System Environment Variables" en Vercel).
- Sin lookbehind en regex (CRA no lo transpila; Safari < 16.4 fallaría al parsear el entry chunk).
- Source maps a Sentry: no incluidos (CRA). Mantener `GENERATE_SOURCEMAP=false` en builds públicos.

## Checklist (no configurado por este PR)
- [ ] Fly: `fly secrets set SENTRY_DSN=<dsn quantro-flow-api> -a quantro-flow-api`
- [ ] (opcional) Fly: `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE`
- [ ] Vercel (Flow web): `REACT_APP_SENTRY_DSN=<dsn quantro-flow-web>` → redeploy
- [ ] Sentry: Data Scrubber + Default Scrubbers + Prevent Storing of IP Addresses en ambos proyectos
