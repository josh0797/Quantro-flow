# Quantro Flow — Slim Control Register

Last reviewed: **2026-09-23**. Full register: **konta** `docs/security/SECURITY_CONTROL_REGISTER.md`.

| Control | Status | Implementation | Evidence | Owner | Review frequency | Last reviewed |
|---------|--------|----------------|----------|-------|------------------|---------------|
| CI Backend + Frontend | Implemented | `.github/workflows/ci.yml` | Job names `Backend`, `Frontend` | Engineering | Per release | 2026-09-23 |
| Frontend npm audit | Implemented | `npm audit --audit-level=high` | Frontend job | Engineering | Per release | 2026-09-23 |
| Backend pip-audit | Partial | `pip-audit -r requirements.txt` in CI | Backend job / implementation report | Engineering | Per release | 2026-09-23 |
| Branch protection main | See SoT | Require Backend, Frontend, Vercel; no force-push | GitHub branch protection API | Josías Martín | Quarterly | 2026-09-23 |
| Dependabot.yml | Implemented | npm/frontend, pip/backend, actions, docker | `.github/dependabot.yml` | Engineering | Weekly | 2026-09-23 |
| Fernet secrets | Implemented | integrations secrets module | `backend/integrations/secrets.py` | Engineering | Semi-annual | 2026-09-23 |
| MFA | Planned | — | — | Josías Martín | Quarterly | 2026-09-23 |
| SECURITY.md | Implemented | Root reporting process | `SECURITY.md` | Engineering | Annual | 2026-09-23 |
