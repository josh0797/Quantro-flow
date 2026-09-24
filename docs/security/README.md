# Quantro Flow — Security docs (slim)

**Source of truth** for the Quantro Information Security Program:

→ **`josh0797/konta`** / `docs/security/` (Information Security Policy, Vulnerability Management, Access Control, Incident Response, Secure SDLC, full Control Register).

## Shared controls (Flow)

| Control | Status (2026-09-23) | Notes |
|---------|---------------------|-------|
| CI Backend / Frontend | Implemented | Required check names: `Backend`, `Frontend` |
| npm audit (frontend) | Implemented | In Frontend job |
| pip-audit (backend) | Partial / as wired | In Backend job; triage HIGH+ |
| Branch protection on `main` | Implemented when API applied | Require PR; block force-push/delete; checks above (+ `Vercel` if safe) |
| Dependabot config | Implemented | `.github/dependabot.yml` |
| Dependabot alerts | Planned if API disabled | Enable in GitHub settings |
| Fernet integration secrets | Implemented | `backend/integrations/secrets.py` |
| Org audit logging | Implemented | Mongo / Supabase paths as deployed |
| MFA | Planned | |
| Formal backup/DR | Planned | |

Vulnerability reports: see root `SECURITY.md`.
