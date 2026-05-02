# plan.md (Updated)

## 1. Objectives
- Deliver a modern, premium **dark-first**, OS-like SaaS web app: **Quantro Flow | Business OS**.
- Ship a connected, production-feeling workflow engine:
  **Smart Inbox → AI triage (single + batch) → automation policy evaluation → (auto-run OR review & control) → Calendar/CRM updates → activity + execution trail**.
- Maintain **multi-industry adaptability** via configuration (Business Profile) — no industry-specific rewrites.
- Make Settings the **operational control center** where the system becomes real:
  - API keys (OpenAI/LLM)
  - Email + Calendar integrations (Google + Microsoft OAuth)
  - CRM connections (future)
  - Webhooks/endpoints (future)
  - Automation governance
- Keep previews honest and trust-building:
  - **Preview → Connect** onboarding pattern (never claim real data unless connected)
  - Clear “Modo demo / Datos reales” labeling everywhere it matters
- **Guarantee strict Simulation vs Live data isolation (critical trust requirement)**:
  - Demo/Simulation Mode → sandbox dataset only
  - Live Mode → real workspace dataset only (`is_simulation != True`)
  - **Zero mixing** and **zero ambiguity** about which dataset is visible
- **Ship SaaS foundation with strict tenant isolation**:
  - **Supabase Auth** (shared project with https://quantro.technology landing)
  - Multi-workspace per user
  - Workspace-scoped operational model
  - Billing/plan truth in Supabase (`profiles`)
  - Audit logging foundation for trust and compliance
- **Enforce AI cost controls (no free AI bleeding)**:
  - Internal **USD-based AI Credits** system
  - Block coupon/trial users from Quantro credits; require their own OpenAI key
  - Force **`gpt-4o-mini`** when using Quantro credits
  - Debit credits after successful generations and log per-request usage

**Current status (as of this update):**
- ✅ **Phases 1–6 complete** (core app + workflow engine + policies/escalations + templates + auto-execution + Business OS transformation).
- ✅ **Phase 7a-sup complete:** Supabase Auth + workspace scoping
  - Frontend uses Supabase Auth (email/password)
  - Backend verifies Supabase JWTs (JWKS ES256 + HS256 fallback)
  - Mongo operational data stays workspace-scoped
  - Plan & Usage reads real data from Supabase (`profiles`, `ai_usage`)
- ✅ **Phase 7d-pre complete (P0): AI Credits wrapper enforcement**
- ✅ **Phase 7b complete:** RBAC + invitations + multi-workspace UX (pending live multi-user matrix verification)
- ✅ **Phase 7c complete:** MongoDB → Supabase backfill executed + cleanup + workspace rename + audit export
- ✅ **Phase 7e complete (P0): Real OAuth integrations (Google + Microsoft) + background sync**
  - Backend + frontend integrated, dual-provider UX in onboarding
  - Tokens encrypted at rest, refresh supported
  - 15-minute background sync scheduler implemented
  - Backend tests: **17/17 PASS** (`iteration_16.json`)
- ✅ **Phase 7e.3 complete (P1): Persistent “Modo demo / Datos reales” banner**
  - Smart Inbox + Schedule show clear mode and allow manual sync

---

## Phase 7e — Real OAuth Integrations (Google + Microsoft) + Sync

### ✅ Implementado (Backend)
- **`/app/backend/google_oauth.py`**
  - Fernet encryption for access/refresh tokens at rest
  - `build_authorization_url`, `exchange_code_for_tokens`, `credentials_from_tokens`, `maybe_refresh`
  - Fetch helpers: Gmail + Calendar, revoke token
  - `is_oauth_configured()` + `resolve_redirect_uri()` to fail cleanly when credentials are missing
- **`/app/backend/microsoft_oauth.py`**
  - MSAL-based auth code flow for Microsoft Graph
  - Encryption + refresh + revoke support mirroring Google
- **REST endpoints** (both providers):
  - `GET /api/integrations/{provider}/status`
  - `GET /api/integrations/{provider}/start?return_to=`
  - `GET /api/integrations/{provider}/callback?code&state`
  - `POST /api/integrations/{provider}/sync`
  - `POST /api/integrations/{provider}/auto-sync` with `{ paused: true|false }`
  - `DELETE /api/integrations/{provider}/disconnect`
- **Background scheduler**
  - 15-minute sync loop created in FastAPI lifespan
  - Provider-aware sync

### ✅ Implementado (Frontend onboarding)
- **Preview → Connect UX** in `/welcome/*`:
  - Primary CTA opens a **modal provider picker** (Google / Microsoft)
  - Full-page redirect to provider consent screen (Safari/mobile-safe)
- **`ProviderConnectModal`** (new)
  - One modal, two providers, consistent error toasts
- **Onboarding callback handler** updated to be provider-aware:
  - Handles `?google_connected=...` and `?microsoft_connected=...`
  - Triggers provider-specific `/sync`
  - Marks inbox + calendar steps as real-connected
  - Clears query params to avoid repeat sync on refresh

### ✅ Phase 7e.3 — Persistent “Modo demo / Datos reales” banner
- New component: **`/app/frontend/src/components/DataModeBanner.js`**
  - Polls integration status every 60s
  - Shows DEMO state with CTA to connect (routes to `/welcome/inbox` or `/welcome/calendar`)
  - Shows REAL state with:
    - provider label + account email
    - last sync relative time
    - manual “Sync now” action
    - surfaces last sync error + paused badge
- Integrated in:
  - `/app/frontend/src/pages/SmartInbox.js`
  - `/app/frontend/src/pages/Schedule.js`
- i18n: ES + EN keys added (`data_mode_banner.*`, `welcome.connect_modal.*`, plus provider-parameterized toasts)

### ✅ Testing
- Backend test suite report: `/app/test_reports/iteration_16.json`
  - **17/17 PASS**
  - Correct behaviors verified:
    - OAuth endpoints require auth (401 without token)
    - Missing credentials returns 503 with helpful detail
    - Sync without connection returns 400 (informative, not 500)
    - Disconnect idempotent
    - Auto-sync endpoint exists and behaves correctly

### ⚠️ Pendiente del lado del usuario (one-off)
To activate real OAuth in production, credentials must be provided in `/app/backend/.env`:
- Google:
  - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
  - Redirect URI: `https://<host>/api/integrations/google/callback`
- Microsoft:
  - `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`
  - Redirect URI: `https://<host>/api/integrations/microsoft/callback`

---

## 2. Implementation Steps

### Phase 1 — Core AI POC (isolation; do not proceed until stable)
**Status: ✅ Completed**

---

### Phase 2 — V1 App Development (build around proven core; no auth)
**Status: ✅ Completed**

---

### Phase 3 — Workflow Engine Upgrade (Batch Triage + Manual Control Layer)
**Status: ✅ Completed**

---

### Phase 4 — Workflow Governance + Communication Layer (Automation Policies + Templates)
**Status: ✅ Completed**

---

### Phase 5 — Automation Engine Upgrade (Auto-Execution + Advanced Escalations)
**Status: ✅ Completed**

---

### Phase 6 — Business OS Transformation (Rebrand + Configurability + Settings)
**Status: ✅ Completed (production-ready)**

---

### Phase 7 — SaaS Foundation (Auth + Multi-tenant + RBAC + Audit Logs)

#### Phase 7a-sup — Supabase Auth + Workspace Creation + Strict Workspace Scoping
**Status: ✅ Completed / ⏳ pending production E2E validation**

---

#### Phase 7d-pre — AI Credits System + Backend Wrapper Enforcement (Cost Control)
**Status: ✅ Implemented / ⏳ pending deployed E2E verification**

---

#### Phase 7b — RBAC + Invitations + Multi-workspace UX
**Status: ✅ Completed (backend verified) / ⏳ pending live multi-user matrix verification**

---

#### Phase 7c — Migration + Cleanup + Export
**Status: ✅ Completed**

---

#### Phase 7e — OAuth real (Google + Microsoft) + background sync
**Status: ✅ Completed**

---

#### Phase 7e.3 — Persistent “Modo demo / Datos reales” banner
**Status: ✅ Completed**

---

## 3. Next Actions

**Immediate (P0): Validate OAuth end-to-end with real credentials**
1) Add Google OAuth credentials in `/app/backend/.env`.
2) Add Microsoft OAuth credentials in `/app/backend/.env`.
3) Restart backend.
4) Login, go to `/welcome/inbox` and connect each provider.
5) Verify:
   - Sync occurs (emails/events counts in toast)
   - Smart Inbox + Schedule banner flips to “Datos reales”
   - Manual sync button works

**Immediate (P0): Validate Phase 7b end-to-end with real Supabase users (still pending)**
6) Members + invites + role matrix + ownership transfer

**Immediate (P0): Validate AI Credits wrapper end-to-end on Supabase (still pending)**
7) Ensure migration `20260425_ai_credits_schema.sql` is applied.
8) Confirm credits decrement + usage logging.

**Next (P2 hardening): Refactor complexity + split monoliths**
9) Backend:
   - Refactor `server.py` high cyclomatic functions (`evaluate_advanced_escalation`, `_verify_supabase_jwt`).
10) Frontend:
   - Split monolithic pages (`SmartInbox.js`, `Dashboard.js`, `ContentEngine.js`).

---

## 4. Success Criteria

**Achieved (Phases 1–6):**
- Workflow engine: Inbox → AI triage → policies → auto-run or manual control → downstream actions → transparent execution trail.
- Premium dark UI across modules.

**Phase 7a-sup (Auth + workspace scoping):**
- ✅ Shared Supabase project (no new DB)
- ✅ Frontend auth via Supabase
- ✅ Backend verifies Supabase JWTs
- ✅ Mongo operational data remains workspace-scoped
- ⏳ Production E2E validation with real landing accounts

**Phase 7d-pre (AI Credits enforcement):**
- ✅ All backend AI endpoints routed through `run_ai_request`
- ✅ Quantro-credit usage forces `gpt-4o-mini`
- ✅ Coupon/trial users cannot consume Quantro credits
- ⏳ Credits decremented + usage logged in live Supabase (schema + optional service-role key)

**Phase 7b (RBAC + invitations + multi-workspace UX):**
- ✅ Role hierarchy implemented
- ✅ Member CRUD + invite token flow implemented
- ✅ RBAC enforced on governance/admin endpoints
- ✅ Frontend workspace switcher + Members page + join page shipped
- ⏳ Live multi-user verification completed

**Phase 7c (migration + export):**
- ✅ Mongo → Supabase core relationships migrated
- ✅ Legacy Mongo workspaces cleaned
- ✅ Audit export shipped

**Phase 7e (OAuth + sync):**
- ✅ Google OAuth implemented end-to-end (tokens encrypted + refresh)
- ✅ Microsoft OAuth implemented end-to-end (tokens encrypted + refresh)
- ✅ Provider picker modal in onboarding
- ✅ Provider-aware callback handler and sync
- ✅ 15-minute scheduler for background sync
- ✅ Backend test suite passes (17/17)

**Phase 7e.3 (mode banner):**
- ✅ Smart Inbox + Schedule clearly label “Modo demo / Datos reales”
- ✅ Manual sync available when connected
- ✅ Status polling keeps UI honest
