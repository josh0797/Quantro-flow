# GitHub CI and branch protection

## What CI runs

Workflow: `.github/workflows/ci.yml`  
Triggers: `pull_request` (all branches) and `push` to `main`.

| Job name (status check) | What it does |
|-------------------------|--------------|
| **Backend** | Python **3.12** (matches `backend/Dockerfile`). Installs `backend/requirements.txt` plus `pytest`, `pytest-asyncio`, `httpx`. Runs root phase tests (`test_phase1_identity_sot.py`, `test_phase2_oauth_secrets.py`, `test_phase3_actions_postgres.py`), then `backend/tests/` (hardening, `hidden_by_real`, policy gate, etc.). Ends with a light import smoke of `google_oauth`, `provider_secrets_store`, and `actions.store` (full `server.py` import is skipped — it needs runtime env). Pip is cached via `actions/setup-python`. |
| **Frontend** | Node **20**. `cd frontend && npm ci` (respects `frontend/.npmrc` `legacy-peer-deps=true`), then `npm run build` with `CI=false` and `DISABLE_ESLINT_PLUGIN=true`. npm is cached via `actions/setup-node`. |

Either job failing fails the workflow. Use the exact job names **Backend** and **Frontend** when configuring required status checks.

## Require checks on `main`

1. GitHub repo → **Settings** → **Branches**.
2. Add or edit a branch protection rule for `main`.
3. Enable **Require status checks to pass before merging**.
4. Search and select the checks named exactly:
   - `Backend`
   - `Frontend`
5. Optionally enable **Require branches to be up to date before merging**.

Status check names come from the workflow `jobs.<id>.name` fields. If you rename jobs in `ci.yml`, update the required checks to match.

## Vercel and GitHub Actions

Vercel already posts its own deployment / preview checks on PRs. Keep those as needed for preview deploys.

When Backend / Frontend CI is stable on a few PRs, add **Backend** and **Frontend** as required checks alongside (or instead of relying only on) Vercel. Do not block merges on flaky new checks until they look consistently green.

## Phase 0 note

Before this workflow, the repo had **zero** GitHub Actions workflows (see Phase 0 / emergent-exit scope: no Actions). This file documents the first CI pipeline (Fase 3).
