# Quantro Flow — Slim Control Register

Reviewed **2026-10-23** against `main` **02bcc857**, GitHub API and the #25 proposal. A file on #25 is NOT deployed.
Full source of truth: `josh0797/konta/docs/security/SECURITY_CONTROL_REGISTER.md`.

| Control | Main status | #25 proposal / verified evidence |
|---|---|---|
| CI Backend + Frontend | Implemented | Jobs preserved, tests expanded; required names unchanged |
| Dependency certification | **Failed / blocked** | Blocking audits added; no vulnerabilities ignored; see dated review |
| pip-audit / npm audit gates | Absent on main | Proposed on #25, blocking; not described as deployed |
| Branch protection | Implemented, independent review gap | API: strict Backend/Frontend/Vercel, enforce_admins, no force-push/delete; **required approvals = 0** |
| Dependabot version configuration | Absent on main | `.github/dependabot.yml` proposed on #25 |
| Dependabot security updates | Enabled | GitHub `security_and_analysis` API |
| Secret scanning / push protection | Enabled | GitHub API; non-provider patterns and validity checks disabled |
| SECURITY.md | Absent on main | Root reporting process proposed on #25 |
| Fernet secrets | Implemented in code | `backend/integrations/secrets.py`; no claim of production key rotation |
| MFA | Planned | No activation claimed |

See [the dated review](FLOW_REVIEW_2026-10-23.md). No repo protection, production secret, provider/model or deployment changed.
