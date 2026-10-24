# Flow security / open PR review — 2026-10-23

Scope: `josh0797/Quantro-flow` main `02bcc85718f5ed78040ff27232ed21fd3b367347`; all **12 open PRs**.
PR checks below refer to their exact reviewed heads, NOT rebased/integrated combinations. No blanket merge approval.
This report is part of #25, not evidence of deployment. No secret values read, provider/model changes, SQL apply or protection edits.

## Dependency certification: FAILED, not waived

- GitHub Dependabot **all pages**, open alerts: **186 = 12 critical + 81 high + 73 medium + 20 low**.
  Alerts include manifests/history tracked by GitHub, not a count of exploitable production paths.
- Current frontend lockfile: `npm audit --package-lock-only --json`, exit 1:
  **64 affected package records = 1 critical + 23 high + 29 moderate + 11 low**.
  `shell-quote` is critical; CRA/webpack/PostCSS and direct `zod` remain affected.
  CRA is a declared dependency: `--omit=dev` is not a justification to dismiss its whole toolchain.
- Backend exact pinned manifest: isolated **pip-audit 2.10.1**, `--no-deps --disable-pip --strict -r backend/requirements.txt`,
  exit 1: **143 packages audited, 23 affected packages, 220 returned vulnerability records** (some IDs are duplicated;
  **not** 220 unique CVEs). No dependency installed by the audit, no ignore list. This audits pinned records, not full
  resolver compatibility or runtime reachability. A fresh install + `pip check` + tests remains required.
- Existing local Python environment: `pip check` passes, but it is **not a clean requirements install**: the broad local
  adapter run found 3 missing-`msal` import failures and 31 passes. This cannot certify the backend build.
- Local checks after refreshing frontend exactly from the lockfile: **21 suites / 181 tests pass**; production build
  succeeds (main JS 395.2 kB gzip). No upload or deployment. Backend targeted: **9 invoice-adapter tests + 13 service-role
  credit tests pass**. The six new offline security-control contracts pass. These do not waive either dependency audit.
- #25 now proposes **blocking** audits in the existing Backend/Frontend jobs, regression tests and 25-minute limits.
  Tests run before audits; audit failure is never hidden. The current debt must be repaired before this PR can be green.

Affected pinned Python packages: aiohttp, anyio, black, certifi, cryptography, ecdsa, filelock, fsspec, h2, hpack,
httplib2, idna, litellm, multidict, oauthlib, pillow, pyasn1, PyJWT, pymongo, python-jose, python-multipart, starlette, urllib3.
Some advisory entries have no fixed version: replacing/removing the dependency or proving scoped non-reachability with a
formally approved, expiring exception is needed; not `continue-on-error`. No such exception was accepted here.

## All eleven other PRs

| PR | Head | Existing checks | Decision / required action |
|---|---|---|---|
| #49 black 26.10.1 | `9e20afda` | Backend/Frontend/Vercel green | Candidate for isolated merge after refreshed CI; fixes the bundled Action advisory; not whole-repo certification |
| #48 Pillow 13 | `d11dd059` | All green | Priority candidate, many critical/high image advisories; major version needs image-consumer regression on the integrated head |
| #47 aiohttp 3.14.4 | `a5b43d92` | **Backend failed** | Resolver: requires `yarl>=1.25.1,<2`, pinned yarl=1.23.0. Update/test as a compatible group, not override resolution |
| #45 urllib3 2.8 | `c08b2f80` | All green | Candidate after integration CI; TLS proxy behavior changed, verify proxy/client tests |
| #44 LiteLLM 1.93.2 | `6f1249cd` | **Backend failed** | Requires `openai>=2.20,<3`, pinned openai=1.99.9. **Blocked**; no provider/model or external endpoint change authorized |
| #41 PyJWT 2.15 | `6a62eeeb` | All green | Priority candidate; rerun JWT allowlist/algorithm, malformed-token and tenant tests on integrated head |
| #27 cryptography 50 | `cfeaa74e` | **Backend failed** | `msal==1.36.0` requires cryptography<49. Must review MSAL+crypto together and exercise OAuth + Fernet old-ciphertext decrypt |
| #26 hpack 4.2 | `551ff749` | All green | Candidate with HTTP/2 tests; removes sensitive-header DEBUG logging, Python target is 3.12 |
| #24 DB mirrors | `34c227c7` | All green | **DO NOT MERGE AS IS**: duplicates credits under another version, regrants `decrement_ai_credits` to authenticated; multi-org backfill can select an ambiguous org and suppress constraint errors |
| #23 invoice tenant scope | `cf0250df` | Old checks green, **conflicts** | Superseded by main's stricter UUID `org_resolver`, missing-link fail closed, no workspace_id as scope, cross-org/recipient tests. Close candidate with this evidence; do not merge the old adapter/server |
| #22 Product Hub help | `78baa3a1` | Old checks green, **conflicts** | Rebase against Settings/ConnectPanel/onboarding changes; schema-validate registry, constrain learn paths, add error/mobile/i18n regression. Do not restore deleted Connect.js |

#24 credits duplicate SHA-256: both PR `20260928000000` and main `20260425` have
`d0347eb48a791d67ca3e5caa0ad61535bf34477d29356156479451f4ca9440c6`.
The other #24 migration is **not** byte-identical to main's `20260426_people_onboarding_audit.sql`.
Do not reapply a mirror or repair production migration history to make it look merged.

Failure logs: aiohttp run **39365850478**, LiteLLM **36813608810**, crypto **36256399368**.
Main's CI lacks security audits and frontend regression execution; old green badges do not certify dependency security.

## #25 itself

Updated by merging main into its existing branch, preserving newer code and avoiding force-push. It adds `SECURITY.md`,
Dependabot config, honest security records, read-only CI permissions, offline control tests and blocking audits.
GitHub API: strict Backend/Frontend/Vercel, enforce_admins, no force-push/delete; **required approving reviews=0**.
Security updates, secret scanning and push protection enabled; validity/non-provider checks disabled. Settings unchanged.

## Safe integration order

1. Repair grouped resolver conflicts and vulnerable frontend toolchain in separate reviewed changes; keep audits blocking.
2. Refresh integrated-head checks for security update candidates (#49/#48/#45/#41/#26). No automatic merging here.
3. Validate #25 against the repaired chain, including clean installs, imports, all tests and build; only then merge security controls.
4. Retire superseded #23 / unsafe duplicate #24 with owner direction; rebase #22 as a focused frontend change.
5. Update the central Konta register only after actual merges/deployments; no inferred production certification.
