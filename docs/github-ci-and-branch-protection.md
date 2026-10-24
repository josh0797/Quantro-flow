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
- `test_phase6_inbox_items.py`
- `backend/tests/` (product domains, calendar canonical, adapters, CORS helpers, Quantro OS invoicing, etc.)

Do not hide build errors with blanket `CI=false` on install.

## Security audits (#25 proposal updated 2026-10-23)

- Frontend runs build + regression tests, then **blocking** `npm audit --audit-level=high`.
- Backend resolves the exact pinned requirements, runs `pip check` + tests, then a separate pinned `pip-audit==2.10.1`
  audits that manifest (`--no-deps --disable-pip --strict`). The audit does not itself certify resolution; installation and
  `pip check` do. No ignored vulnerabilities and no `continue-on-error`.
- These are proposed on #25, NOT assertions about current `main`. Current findings block certification and merge.
- GitHub API checked 2026-10-23: Backend/Frontend/Vercel strict, enforce_admins, force-push/delete forbidden;
  **zero required approving reviews**. No protection setting was changed by this update.
- See `docs/security/FLOW_REVIEW_2026-10-23.md` for all 12 PRs, exact dependency failures and audit scope.
- Full ISP SoT: `josh0797/konta` → `docs/security/`.
