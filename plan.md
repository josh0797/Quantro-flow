# plan.md (Updated)

## 1. Objectives
- Deliver a premium **dark-first**, OS-like SaaS web app: **Quantro Flow | Business OS**.
- Ship a connected, production-feeling workflow engine:
  **Smart Inbox → AI triage (single + batch) → automation policy evaluation → (auto-run OR review & control) → (simulated) Calendar/CRM updates → activity + execution trail**.
- Maintain **multi-industry adaptability** via configuration (Business Profile) — no industry-specific rewrites.
- Make Settings the **operational control center** where the system becomes real:
  - API keys (OpenAI/LLM)
  - Gmail / Google Calendar connections (OAuth-ready, simulated for now)
  - CRM connections (API-key based)
  - Webhooks/endpoints
  - Automation governance
- Keep integrations mocked/simulated for now, but ensure the UI/UX is **production-grade** and trust-building.
- **Expose the self-healing layer as a user-facing trust signal** (Apple/Stripe-style):
  - “System Status: Healthy / Auto‑Repaired / Degraded”
  - “Quantro Flow detects and fixes issues before you notice them.”
  - Surface integrity checks + repair explanations
- **Ship a robust multilingual system (i18n) as an OS-level capability**, not a simple UI translation layer:
  - UI text + dashboard labels
  - Settings and integrations control center
  - Self-healing surface copy
  - Decision system (Quantro Revenue / Action Center) via **keys**, not stored translated strings
  - AI-generated content language enforced via prompt injection
- **Ship Simulation Mode as a first-class product control (not demo data):**
  - Simulation Mode ON: realistic, industry-specific sample dataset drives the full app.
  - Live Mode: uses exclusively real workspace records (manual + integrated).
  - Mode switching is instant, safe, and **never destroys real data**.
- **Guarantee strict Simulation vs Live data isolation (critical trust requirement):**
  - Simulation Mode → sandbox dataset only
  - Live Mode → real workspace dataset only (`is_simulation != True`)
  - **Zero mixing** and **zero ambiguity** about which dataset is visible.
- **Ship SaaS foundation with strict tenant isolation**:
  - **Supabase Auth** (shared project with https://quantro.technology landing)
  - Multi-workspace per user (MongoDB-backed)
  - Workspace-scoped data model across all operational and configuration collections
  - Audit logging foundation for trust and compliance
- **Enforce AI cost controls (no free AI bleeding)**:
  - Replace Emergent LLM key usage with an internal **USD-based AI Credits** system
  - Block trial/coupon users from Quantro credits and require their own OpenAI key
  - Force **`gpt-4o-mini`** when using Quantro credits
  - Log per-request usage and debit credits after successful generations

**Current status (as of this update):**
- ✅ **Phases 1–5 complete** (Core app + workflow engine + policies/escalations + templates + auto-execution).
- ✅ Global rebrand + multi-industry UI adaptation implemented across all main pages.
- ✅ Simulation Layer (backend) implemented and wired to Business Profile.
- ✅ **Settings Operational Control Center** complete.
- ✅ Backend integrations config is **self-healing** (auto-seeded on startup; idempotent).
- ✅ **System Health surface layer shipped** (Settings banner + Dashboard card + repair toast + backend health endpoint/events).
- ✅ **Multilingual i18n system shipped** (ES + EN) with global Language Context, translation keys, persistence, and AI language enforcement.
- ✅ **Brand rename shipped:** **Quantro One → Quantro Flow**.
- ✅ **Simulation Mode UX shipped:** persistent toggle in Sidebar + Settings, localized, confirmation modal on Simulation→Live, localStorage mirroring.
- ✅ **Phase 6.10 complete:** Simulation/Live Data Wiring Hardening (**strict dataset isolation + E2E verification complete**).
- ✅ **Plan y Uso + Automation Policies CRUD shipped and frontend-tested (100% pass)** (`iteration_10.json`).
- ✅ **Phase 7a-sup complete:** Supabase Auth + Workspace scoping
  - Auth source of truth migrated from Emergent sessions → **Supabase sessions**.
  - Frontend uses `@supabase/supabase-js` and validates session via `supabase.auth.getSession()`.
  - Backend verifies Supabase JWTs locally using **dual path**:
    - JWKS-based verification for **current ECC (P-256) signing key**
    - HS256 shared-secret verification for **legacy tokens**
  - Backend upserts Mongo users keyed by **Supabase UUID** (`sub`) and ensures workspace membership/claiming.
  - **Plan y Uso** reads **real data** from Supabase (`profiles` + `ai_usage`) and no longer uses `/api/usage`.
- ✅ **Phase 7d-pre (new): AI Credits Wrapper landed (P0 complete)**
  - Implemented centralized `run_ai_request(...)` wrapper with USD-cost accounting.
  - Removed `EMERGENT_LLM_KEY` and `emergentintegrations.LlmChat` usage.
  - Migrated all backend AI endpoints to the wrapper (inbox analyze, batch analyze, content generate, template generate).
  - Fixed latent NameError bug: `build_intent_prompt`/`build_content_prompt` now accept `workspace_id`.
- ⏳ **Pending validation:** Sign-in with an existing Supabase user from the landing to confirm end-to-end in production.
- ⏳ **Pending validation:** End-to-end test that AI calls debit credits and/or log usage in Supabase in the deployed environment.
- ⏭️ Next: **Phase 7b** (RBAC + invitations + multi-workspace UX) and **Phase 7c** (audit logs UI + export).

---

## 2. Implementation Steps

### Phase 1 — Core AI POC (isolation; do not proceed until stable)
**Status: ✅ Completed**

**User stories (delivered)**
1. Intent detection returns structured JSON results.
2. Confidence + extracted entities included.
3. Consistently parseable JSON across runs.
4. Safe fallback behavior for ambiguous messages (`needs_review`).
5. Content generation produces social + email drafts.

**What was implemented (historical)**
- OpenAI GPT-4o integration using **Emergent LLM Key**.
- Robust prompts enforcing **JSON-only** outputs for:
  - Inbox intent detection + suggested action
  - Content generation
- POC test script:
  - `/app/tests/test_core_ai.py` (10/10 passed)

---

### Phase 2 — V1 App Development (build around proven core; no auth)
**Status: ✅ Completed**

**Delivered**
- Premium dark UI and full module set:
  - Dashboard, Smart Inbox, Schedule, CRM, Onboarding, Content Engine
- Backend seed data and endpoints for end-to-end demo workflows.

---

### Phase 3 — Workflow Engine Upgrade (Batch Triage + Manual Control Layer)
**Status: ✅ Completed**

**Delivered**
- Batch triage endpoints + UI multi-select.
- Review & Control manual override UI and endpoints.

---

### Phase 4 — Workflow Governance + Communication Layer (Automation Policies + Templates)
**Status: ✅ Completed**

**Delivered**
- Automation Policies (confidence tiers → actions).
- Escalation Rules CRUD.
- Content Templates CRUD + AI generation.

---

### Phase 5 — Automation Engine Upgrade (Auto-Execution + Advanced Escalations)
**Status: ✅ Completed**

**Delivered**
- Auto-execution pipeline:
  - `execute_action_for_item()` executes mocked actions.
  - Inbox items marked `status=auto_actioned` with `execution_results`.
- Advanced escalation evaluation:
  - `calendar_conflict`, `incomplete_entities`, `urgency`, `contact_type` (+ `intent`, `keyword`).
- UI updates:
  - Smart Inbox shows auto-executed badge + execution trail.
  - Escalation reasons rendered.
  - Automation rule editor supports advanced condition types.

---

### Phase 6 — Business OS Transformation (Rebrand + Configurability + Settings)
**Status: ✅ Completed (production-ready)**

**Primary goal (Phase 6)**
Transform the product from:
- “Quantro One | Realty OS” (real-estate specific)

into:
- **“Quantro Flow | Business OS”** (horizontal, configurable, multi-industry)

#### 6.1 Global Rebranding (Quantro Flow | Business OS)
**Status: ✅ Completed**

#### 6.2 Business Profile (Core System Layer)
**Status: ✅ Completed**

**Business Profile fields (delivered)**
- Industry, Use case, Entity labels
- `simulation_mode`
- `language` (`"es" | "en"`)

**Endpoints**
- `GET /api/business-profile`
- `PUT /api/business-profile`

#### 6.3 Settings Section (Operational Control Center)
**Status: ✅ Completed (production-grade + QA-validated)**

#### 6.4 System Health / Self-Healing Surface Layer (Trust Signal)
**Status: ✅ Completed**

#### 6.5 Multilingual System (i18n) — OS-level capability
**Status: ✅ Completed (ES + EN shipped)**

#### 6.6 Simulation Layer UX (First-class product control)
**Status: ✅ Completed**

#### 6.7 Data model: “Workspace-ready” scoping (single-tenant)
**Status: ✅ Completed via Phase 7a**

#### 6.8 UX Guidelines (apply throughout Phase 6)
**Status: ✅ Completed**

#### 6.9 Testing & verification (Phase 6)
**Status: ✅ Completed**

#### 6.10 Simulation/Live Data Wiring Hardening (Strict Isolation)
**Status: ✅ Completed (P0 / critical trust requirement satisfied)**

**Key implementation (delivered)**
- `backfill_simulation_flag()` startup backfill
- `get_mode_filter()` applied to all operational reads
- Writes tagged with `is_simulation`
- Non-destructive Simulation↔Live toggling
- Auto-seed simulation dataset on first Simulation entry
- Frontend re-fetch on mode change + Live empty-state guidance (`LiveEmptyState`)

**Testing (completed)**
- Backend: **100% pass** (`/app/test_reports/iteration_6.json`).
- Frontend: passed cross-module verification.

---

### Phase 7 — SaaS Foundation (Auth + Multi-tenant + RBAC + Audit Logs)

#### Phase 7a-sup — Supabase Auth + Workspace Creation + Strict Workspace Scoping
**Status: ✅ Completed (code shipped) / ⏳ pending end-to-end validation with real user session**

**User-approved configuration (implemented)**
- Auth provider: **Supabase Auth** (shared project with https://quantro.technology)
- Login method: **Email + Password** (matches landing)
- Tenancy model: **multi-workspace per user** (MongoDB)
- Operational data: **MongoDB remains** (inbox/CRM/etc)
- Billing/plan/usage/account data:
  - Supabase **`profiles`** = plan source of truth
  - Supabase **`ai_usage`** = monthly AI consumption source of truth

**What was implemented (delivered)**
1) **Frontend Supabase integration**
- Added `@supabase/supabase-js`.
- New singleton client: `/app/frontend/src/lib/supabaseClient.js` using:
  - `REACT_APP_SUPABASE_URL`
  - `REACT_APP_SUPABASE_ANON_KEY`
- Auth hydration:
  - `supabase.auth.getSession()` on boot
  - `supabase.auth.onAuthStateChange()` subscription
- Login UI:
  - `LoginPage.js` replaced Google/Emergent flow with email+password.
  - `AuthCallback.js` updated to handle Supabase redirect-based confirmation.
- Token propagation:
  - `authFetch.js` and axios interceptor attach Supabase `access_token` as Bearer.

2) **Backend JWT verification + identity mapping**
- Backend verifies Supabase JWTs locally:
  - JWKS verification for ECC (P-256) tokens
  - HS256 legacy secret verification fallback
- `users` Mongo collection uses **Supabase UUID** as `user_id`.
- Automatic user upsert and workspace ensure-on-first-request.
- Legacy migration safety net:
  - If an Emergent-era Mongo user exists by email, memberships/ownership migrated to Supabase UUID.

3) **Workspace endpoints (still MongoDB-backed)**
- `/api/auth/me` returns:
  - user identity (from JWT)
  - workspace memberships from MongoDB
- `/api/auth/workspaces` create
- `/api/auth/workspaces/switch` switch active workspace

4) **Plan y Uso reads real Supabase data**
- `PlanAndUsage.js` queries Supabase directly:
  - `profiles` for plan fields
  - `ai_usage` filtered by `user_id` and current `month`, aggregated by `type`
- `/api/usage` no longer used by UI (kept only as legacy endpoint).

**Known constraints / open items**
- **Supabase sign-up fails** with: `Database error saving new user`.
  - Likely Supabase-side trigger/policy (e.g., auto-profile creation) in existing project.
  - Not a Quantro Flow code bug.
  - **Sign-in with existing landing accounts should work** and is the required validation step.

**Exit criteria**
- ✅ Quantro Flow connects directly to the existing Supabase project (no new DB).
- ✅ Session validated in Quantro Flow via Supabase.
- ✅ Plan y Uso reads plan + usage from Supabase (`profiles`, `ai_usage`).
- ⏳ Confirm end-to-end:
  - Sign in with an existing user from the landing
  - Verify `/api/auth/me` returns workspaces
  - Verify Smart Inbox/CRM/etc operate normally via Mongo (using Supabase identity)
  - Verify sign-out calls `supabase.auth.signOut()` and redirects to `/login`

---

#### Phase 7d-pre — AI Credits System + Backend Wrapper Enforcement (Cost Control)
**Status: ✅ Implemented / ⏳ pending deployed E2E verification**

**Goals (delivered)**
- Stop unmetered AI usage by enforcing a single AI request wrapper.
- Debit real USD costs (token-based) from `profiles.ai_credits_*`.
- Block coupon/trial users from Quantro credits.
- Force `gpt-4o-mini` whenever Quantro credits are used.
- Allow fallback to user-provided OpenAI API key (encryption/decryption pending).

**What was implemented (delivered)**
- `/app/backend/ai_billing.py`
  - Added httpx-based Supabase REST helpers:
    - `fetch_profile(...)` (reads via user JWT under RLS)
    - `rpc_decrement_credits(...)` (calls `decrement_ai_credits` RPC using user JWT)
    - `insert_credit_usage(...)` (prefers `SUPABASE_SERVICE_ROLE_KEY`, best-effort fallback)
  - Added `run_ai_request(...)` wrapper that:
    - resolves credit state (coupon/trial vs. paid vs. depleted)
    - forces model to `gpt-4o-mini` when using Quantro credits
    - calls OpenAI via `openai.AsyncOpenAI`
    - calculates USD cost from token usage
    - decrements credits (best-effort)
    - logs usage to `ai_credit_usage` (best-effort)
  - Note: `get_user_api_key(...)` is still a stub until encryption strategy is chosen.
- `/app/backend/server.py`
  - Removed `emergentintegrations.LlmChat` and all `EMERGENT_LLM_KEY` usage.
  - Extended `User` model to include `access_token`.
  - `get_current_user` now forwards the Supabase access token to downstream handlers.
  - Migrated all AI endpoints to `run_ai_request(...)`:
    - `POST /api/inbox/{id}/analyze`
    - `POST /api/inbox/batch-analyze` (re-raises HTTPException so UI sees a single 402)
    - `POST /api/content/generate`
    - `POST /api/templates/{id}/generate`
  - Fixed latent NameError: `build_intent_prompt` and `build_content_prompt` now accept `workspace_id`.

**Schema dependencies**
- Supabase migration: `/app/supabase/migrations/20260425_ai_credits_schema.sql`
  - Adds `profiles` credit columns
  - Creates `ai_credit_usage`
  - Adds `decrement_ai_credits` RPC
- If migration is not applied: wrapper still functions, but debiting/logging becomes best-effort and may no-op.

**Testing (completed locally)**
- Smoke-tested credit-state branches:
  - pro user w/ credits
  - coupon user w/o key (blocked)
  - coupon user w/ key (allowed, user_api)
  - depleted credits (blocked)
  - test user (20 credits)
- Verified real OpenAI call returns tokens and cost; decrement/logging mocks called once.
- Verified blocked paths return HTTP 402 with reasons:
  - `coupon_no_user_key`
  - `no_credits_no_user_key`

**Exit criteria (pending)**
- Confirm deployed environment:
  1) Credits decrement updates `profiles.ai_credits_used/remaining`
  2) Usage logs appear in `ai_credit_usage` (requires service-role key for inserts)
  3) Coupon/trial users receive 402 and UI renders the Spanish message

---

#### Phase 7b — Multi-workspace UX + Invitations + RBAC Enforcement
**Status: ⏭️ Ready (requires explicit user approval to start)**

**Goals**
- Workspace switching UI (workspace selector in sidebar/settings)
- Workspace member management UI
- Invitation links (token-based, email-free)
- RBAC enforcement (Owner/Admin/Manager/Operator/Agent) across backend + UI

**Deliverables (planned)**
- Backend:
  - Invite token endpoints
  - Membership CRUD + role assignments
  - RBAC dependency (`require_role`) and permission matrix for endpoints
- Frontend:
  - Workspace switcher
  - Members screen + role editor
  - Invite link generation + revoke

**Testing**
- Verify strict workspace isolation under multi-workspace switching.
- Verify permissions matrix for each role.

---

#### Phase 7c — Audit Logs UI + Export (CSV/JSON) + Deep Trust Events
**Status: ⏭️ Ready (requires explicit user approval to start)**

**Goals**
- Make audit logs user-visible and exportable.
- Capture critical trust events:
  - Simulation↔Live toggles
  - integrations connect/disconnect
  - automation actions executed
  - self-healing repair events
  - (new) AI billing/credit block events (optional)

**Deliverables (planned)**
- Backend:
  - `/api/audit` list endpoint (filter by date/event_type/user)
  - `/api/audit/export` (CSV + JSON)
  - Expand audit coverage for automation + simulation toggles + system health repairs
- Frontend:
  - Audit Logs screen (filters, search, pagination)
  - Export actions

---

## 3. Next Actions

**Immediate (P0): Validate Supabase auth end-to-end**
1) Sign in to Quantro Flow with an existing account from https://quantro.technology.
2) Confirm `/api/auth/me` returns a workspace list.
3) Confirm core app screens load (Dashboard, Smart Inbox, CRM, Schedule).
4) Confirm **Plan y Uso** shows:
   - profile plan (from `profiles.plan`)
   - monthly usage aggregate (from `ai_usage`)
5) Confirm logout fully signs out via Supabase and redirects to `/login`.

**Immediate (P0): Validate AI Credits wrapper end-to-end on Supabase**
6) Ensure migration is applied: `20260425_ai_credits_schema.sql`.
7) (Recommended) Set `SUPABASE_SERVICE_ROLE_KEY` in backend environment so `ai_credit_usage` inserts succeed under RLS.
8) Use the app or curl to trigger:
   - `POST /api/inbox/{id}/analyze`
   - `POST /api/inbox/batch-analyze`
   - `POST /api/content/generate`
   - `POST /api/templates/{id}/generate`
9) Verify in Supabase:
   - `profiles.ai_credits_used` increments
   - `profiles.ai_credits_remaining` decrements
   - `ai_credit_usage` rows are inserted with `source` correct
10) Verify coupon user gets HTTP 402 and no Quantro credits are consumed.

**Immediate (P0): If sign-up must work in Quantro Flow**
11) Investigate Supabase-side error `Database error saving new user`:
   - Check landing’s signup trigger/function (profiles insert) and RLS.
   - Ensure required `profiles` columns have defaults / nullable.
   - Ensure `profiles` auto-insert trigger handles missing metadata.

**Next (P1): Choose Phase 7b vs 7c**
12) Start **Phase 7b** (RBAC + invitations + multi-workspace UX) OR
13) Start **Phase 7c** (audit logs UI + export)

**Secondary (P2 hardening)**
14) Refactor oversized modules:
  - Backend: `server.py`
  - Frontend: `SmartInbox.js`, `ContentEngine.js`, `Dashboard.js`, `PlanAndUsage.js`

---

## 4. Success Criteria

**Achieved (Phases 1–5):**
- Workflow engine: Inbox → AI triage → policies → auto-run or manual control → mocked downstream actions → transparent execution trail.
- Premium dark UI across modules.
- Advanced escalation safety net.

**Phase 6 Success Criteria (Business OS Transformation): ✅ ACHIEVED**
- ✅ App fully rebranded to **Quantro Flow | Business OS**.
- ✅ Terminology industry-agnostic and configurable.
- ✅ Business Profile drives:
  - dynamic UI labels
  - AI context for classification + generation
  - i18n language enforcement
- ✅ Settings provides a SaaS-grade control surface.
- ✅ Integrations seeding is idempotent and self-healing; Integrations UI never blanks.
- ✅ Self-healing is user-visible as a trust signal.
- ✅ i18n shipped with full ES/EN coverage + persistence.
- ✅ Simulation Mode UX shipped as a first-class control.

**Phase 6.10 Success Criteria (Data Layer Isolation): ✅ ACHIEVED**
- ✅ Simulation Mode is a **true sandbox**: only `is_simulation: True` data is visible and writable.
- ✅ Live Mode is a **true workspace view**: only `is_simulation != True` data is visible and writable.
- ✅ Switching modes never deletes real data and never causes data leakage.
- ✅ Dashboard metrics + AI suggestions respect the current mode.
- ✅ Live empty state is intentional, clean, and guides the user to connect integrations or create first records.

**Phase 7a-sup Success Criteria (Supabase Auth + Workspace + Scoping):**
- ✅ Quantro Flow uses the same Supabase project as the landing (no new DB).
- ✅ Frontend validates session via `supabase.auth.getSession()`.
- ✅ Backend verifies Supabase JWTs locally (JWKS + legacy secret).
- ✅ MongoDB operational data remains workspace-scoped.
- ✅ Plan y Uso reads plan + usage from Supabase (`profiles`, `ai_usage`).
- ⏳ End-to-end user validation pending: existing landing user can sign in and operate normally.

**Phase 7d-pre Success Criteria (AI Credits enforcement):**
- ✅ All backend AI endpoints are routed through `run_ai_request`.
- ✅ Quantro-credit usage forces `gpt-4o-mini`.
- ✅ Trial/coupon users cannot consume Quantro credits.
- ⏳ Credits are decremented in Supabase after each successful AI request (requires schema + RPC).
- ⏳ Per-request usage logs are written to `ai_credit_usage` (requires service-role key for inserts).

**Phase 7 Success Criteria (SaaS Foundation):**
- Phase 7b:
  - Multi-workspace UX + invitation links
  - RBAC enforced across API + UI
- Phase 7c:
  - Audit logs user-visible, filterable, and exportable (CSV + JSON)
  - Audit coverage includes Simulation toggles, integrations connect/disconnect, automation executions, self-healing events, and (optional) AI credit block events
