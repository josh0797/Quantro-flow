# GitHub CI and branch protection

## Required checks for `main`
Configure branch protection so these must pass before merge:

1. **Backend** — `.github/workflows/ci.yml` job `Backend`
2. **Frontend** — job `Frontend` (`npm ci` + `npm run build`)
3. **Vercel** — Vercel GitHub integration deployment/check for the frontend

## Coverage
Backend runs at least:
- `test_phase1_identity_sot.py`
- `test_phase2_oauth_secrets.py`
- `test_phase3_actions_postgres.py`
- `test_phase4_facturapi_connect.py`
- `test_phase6_inbox_items.py`
- `backend/tests/` (product domains, calendar canonical, adapters, CORS helpers, Facturapi, etc.)

Do not hide build errors with blanket `CI=false` on install.
