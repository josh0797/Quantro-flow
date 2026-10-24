# Quantro Flow — Security docs (slim)

**Source of truth** for the Quantro Information Security Program:

→ **`josh0797/konta`** / `docs/security/` (Information Security Policy, Vulnerability Management, Access Control, Incident Response, Secure SDLC, full Control Register).

## Shared controls (Flow)

| Control | Status (2026-10-23, main `02bcc857` vs #25) | Notes |
|---------|---------------------|-------|
| CI Backend / Frontend | Implemented | Required check names: `Backend`, `Frontend` |
| npm audit (frontend) | Proposed on #25, absent on main | Blocking high/critical; current certification FAILED |
| pip-audit (backend) | Proposed on #25, absent on main | Blocking exact pinned manifest; current certification FAILED |
| Branch protection on `main` | Partial | Strict Backend/Frontend/Vercel, no force-push/delete, but **0 approving reviews required** |
| Dependabot config | Proposed on #25, absent on main | `.github/dependabot.yml` |
| Dependabot security updates / alerts | Enabled | Read-only GitHub API check |
| Fernet integration secrets | Implemented | `backend/integrations/secrets.py` |
| Org audit logging | Implemented | Mongo / Supabase paths as deployed |
| MFA | Planned | |
| Formal backup/DR | Planned | |

Vulnerability reports: root `SECURITY.md` is **proposed on #25**, not present on main at the reviewed SHA.
See [the dated review](FLOW_REVIEW_2026-10-23.md) for all PRs and audit scopes. No production rollout or settings changed.
